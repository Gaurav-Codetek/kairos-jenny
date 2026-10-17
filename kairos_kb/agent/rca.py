"""Structured RCA: investigate a failed run, then emit a machine-readable report.

The agent produces the structure itself via ``submit_rca`` rather than us
parsing English back out of a narrative afterwards. Parsing prose would be
guesswork; a tool call is a contract.

Kairos explains and never remediates. ``remediation`` here is a *proposal*
for a downstream consumer to evaluate — nothing in this module writes to
Databricks.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from sqlalchemy import select

from kairos_kb.agent.scope import bind_incident
from kairos_kb.agent.tools import DATA_ENGINEER_TOOLS
from kairos_kb.db.engine import async_session_factory
from kairos_kb.models.incident import Incident, RcaReport
from kairos_kb.models.job import Job
from kairos_kb.models.run import Run
from kairos_kb.models.task_run import TaskRun

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 26
# Turns held back purely for submitting. An investigation that runs out of
# budget mid-thought must still hand back a report.
SUBMIT_RESERVE = 3

ROOT_CAUSE_CATEGORIES = [
    "SCHEMA_DRIFT",
    "MISSING_DATA",
    "PERMISSION",
    "CONFIG_ERROR",
    "CODE_DEFECT",
    "UPSTREAM_FAILURE",
    "INFRASTRUCTURE",
    "RESOURCE_LIMIT",
    "UNKNOWN",
]

REMEDIATION_TYPES = ["CODE_CHANGE", "CONFIG_CHANGE", "SOURCE_FIX", "INFRA_CHANGE", "NO_ACTION"]


@dataclass
class RcaContext:
    """Collects the structured report the agent submits."""

    run_id: uuid.UUID
    report: Dict[str, Any] = field(default_factory=dict)
    tools_used: List[str] = field(default_factory=list)


def _build_submit_tool(ctx: RcaContext):
    @tool
    async def submit_rca(
        root_cause_category: str,
        root_cause_summary: str,
        confidence: float,
        narrative: str,
        root_cause_entity_id: str = "",
        evidence: str = "",
        timeline: str = "",
        affected_assets: str = "",
        open_questions: str = "",
        remediation_type: str = "",
        remediation_detail: str = "",
        remediation_risk: str = "MEDIUM",
    ) -> str:
        """Submit your finished root cause analysis. Call this exactly once, last.

        Args:
            root_cause_category: One of SCHEMA_DRIFT, MISSING_DATA, PERMISSION,
                CONFIG_ERROR, CODE_DEFECT, UPSTREAM_FAILURE, INFRASTRUCTURE,
                RESOURCE_LIMIT, UNKNOWN.
            root_cause_summary: One or two sentences stating the cause precisely.
            confidence: 0.0-1.0. Be honest — a low number is more useful than
                a confident guess.
            narrative: The full markdown report, using the four required headers.
            root_cause_entity_id: The entity_id most responsible, if identifiable.
            evidence: One finding per line. Each line should name where it came
                from, e.g. 'error trace: ValueError Column Count Mismatch'.
            timeline: One event per line, earliest first.
            affected_assets: One entity_id or asset name per line.
            open_questions: One per line — anything you could not determine.
            remediation_type: CODE_CHANGE, CONFIG_CHANGE, SOURCE_FIX,
                INFRA_CHANGE or NO_ACTION.
            remediation_detail: What a downstream system would need to do. Kairos
                does not apply this.
            remediation_risk: LOW, MEDIUM or HIGH.
        """

        def lines(raw: str) -> List[str]:
            return [ln.strip("-• ").strip() for ln in (raw or "").splitlines() if ln.strip()]

        category = (root_cause_category or "UNKNOWN").strip().upper()
        if category not in ROOT_CAUSE_CATEGORIES:
            category = "UNKNOWN"

        ctx.report = {
            "root_cause_category": category,
            "root_cause_entity_id": (root_cause_entity_id or "").strip() or None,
            "root_cause_summary": root_cause_summary.strip(),
            "confidence": max(0.0, min(1.0, float(confidence))),
            "evidence": lines(evidence),
            "timeline": lines(timeline),
            "affected_assets": lines(affected_assets),
            "open_questions": lines(open_questions),
            "narrative": narrative.strip(),
            "remediation": {
                "type": (remediation_type or "NO_ACTION").strip().upper(),
                "detail": (remediation_detail or "").strip(),
                "risk": (remediation_risk or "MEDIUM").strip().upper(),
                "applied_by_kairos": False,
            },
        }
        return "RCA submitted."

    return submit_rca


SYSTEM_PROMPT = """You are Kairos, investigating a failed Databricks job run.

Kairos is a knowledge layer. You EXPLAIN failures with evidence; you never apply
fixes. Any remediation you give is a proposal for a downstream system to evaluate.

You have the entity map — a knowledge graph over workspaces, catalogs, schemas,
tables, columns, jobs, tasks, runs and task runs, plus relationships an enrichment
agent discovered by reading real task code. Navigate it rather than guessing names.

A typical investigation:
1. get_failed_run_details(run_id) — what failed, and which tasks were blocked.
2. get_task_context(taskrun_entity_id) — resolves to the task definition and its
   notebook_path. Do not guess paths.
3. get_task_error_trace(source_native_id) — the real trace.
4. read_databricks_text_file(notebook_path) — the code that ran.
5. list_databricks_directory / query_databricks_data_file — inspect volume files
   and config the code depends on.
6. get_data_dependencies / get_blast_radius — which tables are involved and who
   consumes them.
7. explore_entity / get_entity_details — reach any other part of the graph,
   including a table's columns.

Rules:
- Every claim in evidence must name where it came from.
- A relationship marked 'discovered' was inferred by an agent reading code; it
  carries a confidence and a rationale. Cite it as inference, not fact.
- If a tool returns nothing, say so. Absence of data is not absence of a cause.
- Set confidence honestly. A 0.4 with clear open questions is more useful to a
  downstream agent than a false 0.95.

FINISH by calling submit_rca exactly once. The narrative field must use these
four headers:
### 🚨 Incident Summary
### 🔍 Root Cause Analysis
### ⛓️ Lineage & Impact
### 🛠️ Recommended Fix
"""


def _build_llm():
    from kairos_kb.llm.provider import chat_model, model_name

    llm = chat_model()
    return (llm, model_name()) if llm else (None, None)


async def _fingerprint(run_id: uuid.UUID) -> str:
    """Hash the run state an analysis was derived from.

    A finding is true against the state that produced it. Storing this lets a
    consumer detect that the world moved on since the report was written.
    """
    async with async_session_factory() as db:
        run = await db.get(Run, run_id)
        task_runs = (
            await db.execute(select(TaskRun).where(TaskRun.run_id == run_id).order_by(TaskRun.task_key))
        ).scalars().all()
        payload = {
            "run": [run.entity_id, run.result_state, run.error_message] if run else [],
            "tasks": [[t.task_key, t.result_state, t.error_message] for t in task_runs],
        }
    return hashlib.sha256(json.dumps(payload, default=str).encode()).hexdigest()


async def investigate(run_id: uuid.UUID, *, max_iterations: int = MAX_ITERATIONS) -> Dict[str, Any]:
    """Investigate a failed run and persist a structured RCA report."""
    llm, model_name = _build_llm()
    if llm is None:
        raise RuntimeError("Azure OpenAI is not configured; cannot run RCA.")

    await bind_incident(run_id)
    ctx = RcaContext(run_id=run_id)
    submit_tool = _build_submit_tool(ctx)
    tools = list(DATA_ENGINEER_TOOLS) + [submit_tool]
    tools_by_name = {t.name: t for t in tools}
    llm_with_tools = llm.bind_tools(tools)
    llm_submit_only = llm.bind_tools([submit_tool])

    messages: List[BaseMessage] = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(
            content=(
                f"Investigate the failed run with warehouse run_id: {run_id}.\n"
                "Start with get_failed_run_details, then follow the entity map to the "
                "code and data involved. Finish with submit_rca."
            )
        ),
    ]

    forced = False
    iterations = 0

    for iteration in range(max_iterations):
        iterations = iteration + 1
        remaining = max_iterations - iteration
        force = remaining <= SUBMIT_RESERVE and not ctx.report

        if force and not forced:
            forced = True
            messages.append(
                HumanMessage(
                    content=(
                        "You are out of investigation budget. Call submit_rca NOW with what "
                        "you have established. Lower your confidence accordingly and record "
                        "what remains unknown in open_questions."
                    )
                )
            )

        response: AIMessage = await (llm_submit_only if force else llm_with_tools).ainvoke(messages)
        messages.append(response)

        calls = getattr(response, "tool_calls", None) or []
        if not calls:
            if ctx.report or iteration >= max_iterations - 1:
                break
            messages.append(HumanMessage(content="Call submit_rca now."))
            continue

        for call in calls:
            name = call.get("name", "")
            ctx.tools_used.append(name)
            selected = tools_by_name.get(name)
            if selected is None:
                result: Any = f"ERROR: unknown tool '{name}'."
            else:
                try:
                    result = await selected.ainvoke(call.get("args", {}) or {})
                except Exception as exc:  # noqa: BLE001 — surfaced back to the model
                    logger.warning("RCA tool %s failed: %s", name, exc)
                    result = f"ERROR calling {name}: {exc}"
            messages.append(
                ToolMessage(content=str(result)[:60_000], tool_call_id=call.get("id", name))
            )

        if ctx.report:
            break

    if not ctx.report:
        raise RuntimeError(
            f"RCA finished without submitting a report for run {run_id} after {iterations} turns."
        )

    return await _persist(run_id, ctx, model_name, iterations)


async def _persist(
    run_id: uuid.UUID, ctx: RcaContext, model_name: Optional[str], iterations: int
) -> Dict[str, Any]:
    """Upsert the incident and append a new report to it."""
    fingerprint = await _fingerprint(run_id)
    now = datetime.now(timezone.utc)

    async with async_session_factory() as db:
        run = await db.get(Run, run_id)
        if run is None:
            raise RuntimeError(f"Run {run_id} not found.")
        job = (await db.execute(select(Job).where(Job.id == run.job_id))).scalars().first()

        blocked = [
            {"task_key": t.task_key, "result_state": t.result_state}
            for t in (
                await db.execute(select(TaskRun).where(TaskRun.run_id == run_id))
            ).scalars().all()
            if t.result_state in ("UPSTREAM_FAILED", "SKIPPED", "CANCELED")
        ]

        incident = (
            await db.execute(select(Incident).where(Incident.run_id == run_id))
        ).scalars().first()

        confidence = ctx.report["confidence"]
        title = f"{job.name if job else 'Job'} — {ctx.report['root_cause_category']}"

        if incident is None:
            incident = Incident(
                workspace_id=run.workspace_id,
                run_id=run_id,
                entity_id=run.entity_id,
                title=title[:512],
                status="explained",
                severity="high" if not blocked else "critical",
                detected_at=run.start_time or now,
            )
            db.add(incident)
            await db.flush()
        else:
            incident.title = title[:512]
            incident.status = "explained"

        report = RcaReport(
            incident_id=incident.id,
            workspace_id=run.workspace_id,
            run_id=run_id,
            root_cause_category=ctx.report["root_cause_category"],
            root_cause_entity_id=ctx.report["root_cause_entity_id"],
            root_cause_summary=ctx.report["root_cause_summary"],
            confidence=confidence,
            evidence=ctx.report["evidence"],
            timeline=ctx.report["timeline"],
            affected_assets=ctx.report["affected_assets"],
            blocked_tasks=blocked,
            open_questions=ctx.report["open_questions"],
            remediation=ctx.report["remediation"],
            narrative=ctx.report["narrative"],
            source_fingerprint=fingerprint,
            tools_used=sorted(set(ctx.tools_used)),
            model=model_name,
            iterations=iterations,
            status="final",
            generated_at=now,
        )
        db.add(report)
        await db.commit()
        await db.refresh(report)
        report_id = report.id
        incident_id = incident.id

    return {
        "incident_id": str(incident_id),
        "report_id": str(report_id),
        "run_id": str(run_id),
        **ctx.report,
        "blocked_tasks": blocked,
        "source_fingerprint": fingerprint,
        "tools_used": sorted(set(ctx.tools_used)),
        "iterations": iterations,
        "generated_at": now.isoformat(),
    }
