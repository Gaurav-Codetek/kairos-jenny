"""Jev-guided RCA — an experimental path that runs beside the standard agent.

Strict flow:
  1. Code gathers the cheap evidence: run details, error traces, task code.
  2. Jev classifies it: COLUMN_RENAME, EXTRA_COLUMN, COLUMN_ORDER_SWAP or
     NOT_SCHEMA_RELATED.
  3. For a confident schema class, Jev then picks — among the variants filed
     under THAT class only (:mod:`kairos_kb.agent.playbooks`) — the one whose
     mechanism fits, or none.
       - FAST: a variant fits. Agent B (:mod:`kairos_kb.agent.plan_executor`)
         runs its compiled plan as a LangGraph: fixed nodes, no agent loop.
         If any node or verification fails, fall through to LEARN.
       - LEARN: no variant fits. Agent A investigates fully, verifying Jev's
         hypothesis, then compiles what it did into a general node plan. The
         plan is validated, dry-run by Agent B on this same incident, and only
         saved as a new variant if it reproduces the diagnosis.
     A missing or unconfident class runs Agent A open-ended, learning nothing.
  4. Every run is logged to ``<storage>/logs/jev_rca.jsonl``.

Nothing here modifies the standard agent: it builds its own graph on the same
LLM and tools, plus the Delta history and structured tools.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import START, StateGraph
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field

from kairos_kb.agent import playbooks
from kairos_kb.agent.graph import SYSTEM_PROMPT, llm
from kairos_kb.agent.plan_executor import run_plan, validate_plan
from kairos_kb.agent.scope import bind_incident, rca_connector
from kairos_kb.agent.plan_library import LIBRARY_DOC, STRUCTURED_TOOLS
from kairos_kb.agent.state import AgentState
from kairos_kb.agent.tools import (
    DATA_ENGINEER_TOOLS,
    get_failed_run_details,
    get_task_context,
    get_task_error_trace,
)
from kairos_kb.config import get_settings
from kairos_kb.connectors.databricks import DatabricksConnector

logger = logging.getLogger(__name__)

LABELS = ["COLUMN_RENAME", "EXTRA_COLUMN", "COLUMN_ORDER_SWAP", "NOT_SCHEMA_RELATED"]
SCHEMA_LABELS = LABELS[:3]

# Bounds on what goes into Jev's state. Accuracy falls as state fills with
# material the question does not need, and the hard limit is 32k tokens for
# state plus the longest question.
MAX_FAILED_TASKS = 3
MAX_TRACE_CHARS = 6000
MAX_CODE_CHARS = 8000

# LangGraph counts one super-step per supervisor turn and per tool round.
LEARN_RECURSION_LIMIT = 80
# Fallback LLM-compile attempts, used only when recording Agent A's trace fails.
COMPILE_ATTEMPTS = 2

GENERIC_HINTS = {
    "COLUMN_RENAME": """\
- Find the column name the error says cannot be resolved, and where the task code references it.
- Identify where the expected columns come from and where the actual columns come from; compare them.
- For Delta tables, get_delta_table_history shows RENAME COLUMN (oldColumnPath / newColumnPath).
- Distinguish a rename from a dropped column: a drop has no replacement column.""",
    "EXTRA_COLUMN": """\
- Find where the column set is checked or enforced: a Delta write (schema mismatch error), or a check in the
  task code itself (e.g. comparing a file header against an expected column list / mapping file).
- Get the expected column list and the actual incoming columns and name exactly which column(s) are extra.
- For Delta tables, get_delta_table_history shows ADD COLUMNS or schema-changing writes.""",
    "COLUMN_ORDER_SWAP": """\
- An order swap only breaks code that works by POSITION: INSERT INTO ... SELECT *, insertInto(), union/unionAll
  (instead of unionByName), CSV/text reads without a header. Find that construct in the task code first.
- Get the expected and actual column order and name which columns moved.
- For Delta tables, get_delta_table_history shows CHANGE COLUMN ... FIRST/AFTER or a replace with new order.""",
}


# ── Extra tool: Delta table history ──────────────────────────────────

_IDENT = re.compile(r"^[A-Za-z0-9_\-]+$")


@tool
async def get_delta_table_history(table: str, limit: int = 20) -> Dict[str, Any]:
    """Get the Delta transaction history of a table: every schema and data operation with its timestamp.

    This is the authoritative record of schema changes. Look for operations such as
    RENAME COLUMN (operationParameters has oldColumnPath/newColumnPath), ADD COLUMNS,
    CHANGE COLUMN (a FIRST/AFTER position means a reorder), CREATE OR REPLACE TABLE,
    and WRITE/MERGE that changed the schema.

    Args:
        table: The table's full name 'catalog.schema.table', or its table entity_id.
        limit: How many most-recent versions to return.
    """
    full_name = table.rsplit(":", 1)[-1] if table.startswith("table:") else table
    parts = full_name.strip("`").split(".")
    if len(parts) != 3 or not all(_IDENT.match(p) for p in parts):
        return {"error": f"Expected 'catalog.schema.table', got {table!r}."}
    quoted = ".".join(f"`{p}`" for p in parts)
    limit = max(1, min(int(limit), 50))

    connector = rca_connector()
    try:
        result = await connector.execute_query(f"DESCRIBE HISTORY {quoted} LIMIT {limit}")
        rows = DatabricksConnector._rows_from_statement_result(result)
    except Exception as exc:  # noqa: BLE001 — surface the failure to the agent
        return {"error": f"Could not read Delta history for {full_name}: {exc}"}

    keep = ("version", "timestamp", "userName", "operation", "operationParameters", "operationMetrics")
    return {"table": full_name, "history": [{k: r.get(k) for k in keep if k in r} for r in rows]}


JEV_RCA_TOOLS = [*DATA_ENGINEER_TOOLS, get_delta_table_history, *STRUCTURED_TOOLS]


# ── Evidence gathering (plain code, no LLM) ──────────────────────────


_ERROR_LIST = r"{label}\s*:?\s*(\[[^\[\]]*\])"


def compare_columns_in_error(text: Optional[str]) -> Optional[Dict[str, Any]]:
    """If an error prints both an expected and an actual column list, compare them in code.

    Custom schema checks often print both lists, and their wording can mislead
    (one notebook reports any same-length difference as an "order mismatch").
    Comparing two long lists is exactly what Jev is bad at, so the comparison
    is done here and handed to Jev as plain-language facts.
    """
    import ast

    from kairos_kb.agent.plan_library import column_diff

    if not text:
        return None
    found = {}
    for key, label in (("expected", "Expected"), ("actual", "Actual")):
        match = re.search(_ERROR_LIST.format(label=label), text, re.IGNORECASE)
        if not match:
            return None
        try:
            value = ast.literal_eval(match.group(1))
        except (ValueError, SyntaxError):
            return None
        if not isinstance(value, list) or not value:
            return None
        found[key] = [str(v) for v in value]

    d = column_diff(found["expected"], found["actual"])
    delta = d["actual_count"] - d["expected_count"]
    renames = [f"{r['expected']} → {r['actual']} (position {r['position']})" for r in d["rename_candidates"]]
    renamed = {r["actual"] for r in d["rename_candidates"]} | {r["expected"] for r in d["rename_candidates"]}
    return {
        "column_count": (
            "same number of columns in expected and actual" if delta == 0
            else f"actual has {abs(delta)} {'more' if delta > 0 else 'fewer'} column(s) than expected"
        ),
        "names_replaced_in_place": renames or "none",
        "names_only_in_actual": [c for c in d["extra"] if c not in renamed] or "none",
        "names_only_in_expected": [c for c in d["missing"] if c not in renamed] or "none",
        "same_names_in_different_order": (
            "yes" if d["order_changed"] and not d["extra"] and not d["missing"] else "no"
        ),
        "columns_that_changed_position": [m["column"] for m in d["moved"]] or "none",
    }


def _clip(text: Any, limit: int) -> Optional[str]:
    if text is None:
        return None
    text = str(text)
    return text if len(text) <= limit else text[:limit] + f"\n...[truncated, {len(text) - limit} more chars]"


async def gather_evidence(run_id: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Collect what Jev judges from. Returns (state for Jev, metadata that never goes to Jev)."""
    await bind_incident(run_id)
    details = await get_failed_run_details.ainvoke({"run_id": run_id})
    if "error" in details:
        raise ValueError(details["error"])

    connector = rca_connector()
    tasks: List[Dict[str, Any]] = []
    task_keys: List[str] = []
    for ft in details.get("failed_tasks", [])[:MAX_FAILED_TASKS]:
        entry: Dict[str, Any] = {"task_key": ft["task_key"], "error_message": _clip(ft.get("error_message"), 2000)}
        task_keys.append(ft["task_key"])

        if ft.get("source_native_id"):
            trace = await get_task_error_trace.ainvoke({"source_native_id": ft["source_native_id"]})
            # Compare before clipping: the lists are often longer than the clip.
            comparison = compare_columns_in_error(trace.get("error")) or compare_columns_in_error(ft.get("error_message"))
            if comparison:
                entry["column_comparison_computed_from_error"] = comparison
            entry["error"] = _clip(trace.get("error"), 2000)
            entry["error_trace"] = _clip(trace.get("error_trace"), MAX_TRACE_CHARS)

        ctx = await get_task_context.ainvoke({"entity_id": ft["taskrun_entity_id"]})
        if "error" not in ctx:
            code = None
            if ctx.get("sql_query"):
                code = ctx["sql_query"]
            elif ctx.get("notebook_path"):
                try:
                    code = await connector.read_workspace_file(ctx["notebook_path"])
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Could not read %s: %s", ctx["notebook_path"], exc)
            if code:
                entry["code"] = _clip(code, MAX_CODE_CHARS)
        tasks.append(entry)

    state = {
        "job_name": details.get("job_name"),
        "run_error_message": _clip(details.get("error_message"), 2000),
        "failed_tasks": tasks,
    }
    return state, {"job_name": details.get("job_name"), "task_keys": task_keys}


# ── Jev ──────────────────────────────────────────────────────────────


def _classification_questions():
    from typesafe_sdk import Choice, Noul

    return {
        "schema_issue": Choice(
            instructions=(
                "Classify the root cause of this Databricks pipeline failure. When a "
                "column_comparison_computed_from_error is present, it is an exact comparison of the expected "
                "and actual columns and outweighs the wording of the error message, which can be misleading. "
                "Otherwise judge from the error messages, error traces and the task code."
            ),
            criteria={
                "COLUMN_RENAME": (
                    "The number of columns is unchanged, but one or more expected column names were replaced by a "
                    "different name in the same place (a rename); or the code references a column that no longer "
                    "exists under that name, with errors like UNRESOLVED_COLUMN / cannot resolve a column name."
                ),
                "EXTRA_COLUMN": (
                    "The actual data has MORE columns than expected: a new, additional column appeared that the "
                    "target table or the code does not expect (even if some other column was also renamed); "
                    "errors like a column count mismatch or a Delta schema mismatch listing extra fields."
                ),
                "COLUMN_ORDER_SWAP": (
                    "Exactly the same column names exist, only in a different order — never when any column name "
                    "differs. It breaks code that maps columns by position (INSERT INTO ... SELECT *, insertInto, "
                    "union/unionAll, headerless CSV), causing type cast errors or values in the wrong columns."
                ),
                "NOT_SCHEMA_RELATED": (
                    "None of the above: permissions, missing data or files, configuration, resource or cluster "
                    "problems, code bugs unrelated to column changes, or not enough information to tell."
                ),
            },
        ),
        "error_names_missing_column": Noul(
            instructions="An error message states that a specific column cannot be found or resolved."
        ),
        "error_reports_schema_mismatch": Noul(
            instructions="An error message reports that the schema of the data being written does not match the table schema."
        ),
        "code_uses_positional_columns": Noul(
            instructions=(
                "The task code maps columns by position rather than by name, for example INSERT INTO ... SELECT *, "
                "insertInto(), union or unionAll instead of unionByName, or reading CSV without a header."
            )
        ),
    }


def _jev_client():
    """(client, error_dict). Exactly one is None."""
    settings = get_settings()
    if not settings.typesafe_api_key:
        return None, {"status": "not_configured", "reason": "TYPESAFE_API_KEY is not set."}
    try:
        from typesafe_sdk import AsyncTypeSafeClient
    except ImportError:
        return None, {"status": "not_configured", "reason": "typesafe-sdk is not installed; rebuild the API image."}
    client = AsyncTypeSafeClient(
        api_key=settings.typesafe_api_key, model=settings.typesafe_model or None, timeout=20.0
    )
    return client, None


async def classify_with_jev(state: Dict[str, Any]) -> Dict[str, Any]:
    """Ask Jev for a schema-drift hypothesis. Never raises; failures are reported in the result."""
    client, err = _jev_client()
    if err:
        return err
    started = time.perf_counter()
    try:
        response = await client.system_one(state=state, questions=_classification_questions())
    except Exception as exc:  # noqa: BLE001
        logger.warning("Jev classification failed: %s", exc)
        return {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}
    finally:
        await client.aclose()
    latency_ms = round((time.perf_counter() - started) * 1000)

    answer = response.answers["schema_issue"]
    signals = {k: round(response.answers[k].noul, 3) for k in (
        "error_names_missing_column", "error_reports_schema_mismatch", "code_uses_positional_columns",
    )}
    threshold = get_settings().jev_rca_confidence_threshold
    return {
        "status": "ok",
        "hypothesis": answer.choice,
        "confidence": round(answer.confidence, 3),
        "probabilities": {k: round(v, 3) for k, v in answer.probabilities.items()},
        "signals": signals,
        "model": response.model,
        "latency_ms": latency_ms,
        "input_tokens": getattr(response.usage, "input_tokens", None),
        "threshold": threshold,
        # Only a confident schema hypothesis steers the investigation.
        "used_as_hint": answer.choice in SCHEMA_LABELS and answer.confidence >= threshold,
    }


async def match_variant_with_jev(state: Dict[str, Any], variants: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Among one class's variants, let Jev pick the one whose mechanism fits — or none."""
    from typesafe_sdk import Choice

    client, err = _jev_client()
    if err or not variants:
        return {"variant": None, "reason": (err or {}).get("reason", "no variants for this class yet")}
    criteria = {f"V{i}": v["variant"] for i, v in enumerate(variants)}
    criteria["NONE"] = "None of these mechanisms describes how this failure arises in this task's code."
    started = time.perf_counter()
    try:
        response = await client.system_one(
            state=state,
            questions={
                "mechanism": Choice(
                    instructions=(
                        "Which of these failure mechanisms describes how this pipeline failure arises, "
                        "given its error and task code?"
                    ),
                    criteria=criteria,
                )
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Jev variant match failed: %s", exc)
        return {"variant": None, "reason": f"{type(exc).__name__}: {exc}"}
    finally:
        await client.aclose()

    answer = response.answers["mechanism"]
    result = {
        "choice": answer.choice,
        "confidence": round(answer.confidence, 3),
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "variant": None,
    }
    if answer.choice != "NONE" and answer.confidence >= get_settings().jev_rca_confidence_threshold:
        result["variant"] = variants[int(answer.choice[1:])]
    return result


# ── Agent A (investigates; own graph, the standard agent is untouched) ──

JEV_SYSTEM_ADDENDUM = """

You also have get_delta_table_history (the authoritative record of schema operations on a table) and
structured tools that return data rather than prose: get_file_columns, get_table_columns,
run_select_query and read_code_file. Prefer them whenever you need column lists or rows, so the
comparison you make can be reproduced exactly.

At the very end of your report add this section, with exactly one label on the line:
### 🏷️ Schema Classification
FINAL_CLASSIFICATION: <COLUMN_RENAME | EXTRA_COLUMN | COLUMN_ORDER_SWAP | NOT_SCHEMA_RELATED>
Choose from the evidence you gathered, regardless of any hypothesis you were given.
"""

_llm_with_tools = llm.bind_tools(JEV_RCA_TOOLS) if llm else None


async def _supervisor(state: AgentState) -> dict:
    messages = state.get("messages", [])
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=SYSTEM_PROMPT + JEV_SYSTEM_ADDENDUM)] + messages
    return {"messages": [await _llm_with_tools.ainvoke(messages)]}


def _route(state: AgentState) -> Literal["tools", "__end__"]:
    last = state["messages"][-1]
    return "tools" if getattr(last, "tool_calls", None) else "__end__"


def _build_agent_a():
    workflow = StateGraph(AgentState)
    workflow.add_node("supervisor", _supervisor)
    workflow.add_node("tools", ToolNode(JEV_RCA_TOOLS))
    workflow.add_edge(START, "supervisor")
    workflow.add_conditional_edges("supervisor", _route)
    workflow.add_edge("tools", "supervisor")
    return workflow.compile()


agent_a_graph = _build_agent_a() if _llm_with_tools else None


def _learn_prompt(run_id: str, jev: Dict[str, Any]) -> str:
    prompt = f"Investigate the failed Databricks job run with ID: {run_id} and write a Root Cause Analysis.\n\n"
    if jev.get("used_as_hint"):
        label = jev["hypothesis"]
        prompt += (
            f"A fast classifier read the error traces and task code and suggests the root cause is "
            f"**{label}** (confidence {jev['confidence']:.2f}). Treat this as a HYPOTHESIS TO VERIFY, not a fact. "
            f"If the evidence contradicts it, say so plainly and classify the failure correctly.\n\n"
            f"Common shapes of {label} (generic — this pipeline may work differently, follow the evidence):\n"
            f"{GENERIC_HINTS[label]}\n\n"
            "Find exactly WHAT changed: which table or file, which column(s), the expected versus actual "
            "state — with the tool output that proves it. Establish the expected column list and the actual "
            "column list as data (structured tools), because this investigation will be turned into a "
            "reusable plan for future failures of this class.\n"
        )
    else:
        prompt += (
            "Start with get_failed_run_details, then get_task_error_trace for each failed task, then follow "
            "the evidence. If a schema change is involved, use get_delta_table_history to pin down exactly "
            "what changed and when.\n"
        )
    return prompt


_FINAL = re.compile(r"FINAL_CLASSIFICATION:\s*\**\s*([A-Z_]+)")


async def _run_agent_a(prompt: str, run_id: str) -> Dict[str, Any]:
    started = time.perf_counter()
    final_state = await agent_a_graph.ainvoke(
        {"messages": [HumanMessage(content=prompt)], "run_id": run_id, "intent": "rca_jev"},
        config={"recursion_limit": LEARN_RECURSION_LIMIT},
    )
    messages = final_state["messages"]
    report = messages[-1].text
    match = _FINAL.search(report)
    return {
        "messages": messages,
        "report": report,
        "tools_used": [t["name"] for m in messages if getattr(m, "tool_calls", None) for t in m.tool_calls],
        "label": match.group(1) if match and match.group(1) in LABELS else None,
        "ms": round((time.perf_counter() - started) * 1000),
    }


# ── Compile: Agent A's investigation → a general node plan ───────────


class PlanNode(BaseModel):
    id: str = Field(description="Unique snake_case id; later nodes reference this node's output as $id.")
    type: Literal["tool", "extract", "compute", "verify", "report"]
    name: str = Field(description="Tool name, compute/verify op name, or 'extract' / 'report'.")
    args_json: str = Field(description="The node's args as a JSON object string, using $id / {{id}} references.")


class CompiledPlan(BaseModel):
    variant: str = Field(description=(
        "One sentence naming the MECHANISM by which this class of failure arises in this kind of pipeline, "
        "general enough to recognise it in other pipelines built the same way, e.g. 'Notebook compares the "
        "incoming CSV header against an expected column list read from a mapping file and raises on mismatch'."
    ))
    nodes: List[PlanNode]


COMPILE_SYSTEM = f"""You compile a completed root cause investigation into a reusable diagnosis plan.

The plan will be run by an executor — not an agent — for FUTURE failures of the same class that arise
through the same mechanism, in this pipeline or any other pipeline built the same way. So it must be
GENERAL: every instance-specific value (run ids, task keys, notebook paths, file paths, table names,
subject areas, job names) must come from a reference to an earlier node's output or from an extract
node that reads it out of code, parameters or query results. Never write such values as literals.

The plan must:
  1. locate the failure from $input.run_id (run details → task context → error trace → code),
  2. obtain the EXPECTED column list and the ACTUAL column list as data,
  3. compute column_diff(expected, actual),
  4. verify with diff_explains_class(diff, "$input.failure_class") and, when the error states
     counts, counts_match_error(diff, <error text>),
  5. end with a report whose facts include the error, the diff and the located sources.
Use the fewest nodes that achieve this; omit everything that did not contribute to the diagnosis.

{LIBRARY_DOC}"""


def _compact_trace(messages) -> str:
    results = {m.tool_call_id: str(m.content) for m in messages if isinstance(m, ToolMessage)}
    lines, n = [], 0
    for m in messages:
        if isinstance(m, AIMessage) and m.tool_calls:
            for call in m.tool_calls:
                n += 1
                args = json.dumps(call.get("args", {}), default=str)[:400]
                result = (results.get(call.get("id"), "") or "").replace("\n", " ")[:700]
                lines.append(f"[{n}] {call['name']}({args})\n    → {result}")
    return "\n".join(lines)


def _instance_literals(run_id: str, meta: Dict[str, Any], messages) -> List[str]:
    """Values specific to this incident that a general plan must not hardcode."""
    values = {run_id, meta.get("job_name") or "", *meta.get("task_keys", [])}
    three_part = re.compile(r"^[A-Za-z0-9_]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+$")
    for m in messages:
        if isinstance(m, AIMessage) and m.tool_calls:
            for call in m.tool_calls:
                for v in (call.get("args") or {}).values():
                    if not isinstance(v, str) or len(v) >= 300:
                        continue
                    # Paths, entity ids, table names — and native run ids, which
                    # hardcoded would fetch THIS incident's evidence every time.
                    if "/" in v or ":" in v or three_part.match(v) or (v.isdigit() and len(v) >= 8):
                        values.add(v)
    return sorted(v for v in values if v and len(v) >= 8)


RECORD_NUDGE = (
    "Before finishing: confirm your finding with the structured tools. Obtain the EXPECTED column list and "
    "the ACTUAL column list as data — get_file_columns, get_table_columns, or run_select_query on the "
    "sources you identified — so the comparison can be reproduced exactly. Then restate your conclusion "
    "in one short paragraph."
)


_TRANSIENT = re.compile(r"connection error|name resolution|timed out|timeout|temporarily unavailable|429", re.IGNORECASE)


def is_transient(failure: Optional[str]) -> bool:
    """A network or rate-limit failure says nothing about whether a plan is right."""
    return bool(failure and _TRANSIENT.search(failure))


async def _run_plan_retrying(nodes: List[Dict[str, Any]], run_id: str, failure_class: str) -> Dict[str, Any]:
    result = await run_plan(nodes, run_id, failure_class)
    if not result["success"] and is_transient(result["failure"]):
        await asyncio.sleep(5)
        result = await run_plan(nodes, run_id, failure_class)
    return result


async def _try_plan(nodes: List[Dict[str, Any]], forbidden: List[str], run_id: str, failure_class: str):
    """Validate, then dry-run on this incident. Returns (dry_run or None, problem or None)."""
    problems = validate_plan(nodes, forbidden)
    if problems:
        return None, {"problem": "validation", "details": problems}
    dry = await _run_plan_retrying(nodes, run_id, failure_class)
    if not dry["success"]:
        return None, {"problem": "dry run failed", "details": [dry["failure"]], "steps": dry["steps"]}
    return dry, None


async def compile_variant(failure_class: str, run: Dict[str, Any], run_id: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    """Record (or, failing that, compile) → validate → dry-run on this incident → save."""
    from kairos_kb.agent.plan_recorder import record_plan

    attempts: List[Dict[str, Any]] = []
    messages = run["messages"]

    # ── Primary: record Agent A's real calls, references resolved in code ──
    nodes, reason = await record_plan(messages, run_id, failure_class)
    if nodes is None and reason.startswith("no pair"):
        attempts.append({"attempt": "record", "problem": reason, "details": ["asked Agent A to confirm with structured tools"]})
        final = await agent_a_graph.ainvoke(
            {"messages": messages + [HumanMessage(content=RECORD_NUDGE)], "run_id": run_id, "intent": "rca_jev"},
            config={"recursion_limit": LEARN_RECURSION_LIMIT},
        )
        messages = final["messages"]
        nodes, reason = await record_plan(messages, run_id, failure_class)

    forbidden = _instance_literals(run_id, meta, messages)
    if nodes is not None:
        dry, problem = await _try_plan(nodes, forbidden, run_id, failure_class)
        if dry:
            variant = playbooks.create(
                failure_class=failure_class, variant=await _describe_variant(nodes, run, failure_class),
                plan=nodes, learned_from_run=run_id, dry_run=dry,
            )
            attempts.append({"attempt": "record", "problem": None})
            return {"saved": True, "variant": variant, "attempts": attempts, "dry_run": dry, "method": "recorded"}
        attempts.append({"attempt": "record", **problem})
    else:
        attempts.append({"attempt": "record", "problem": reason})

    # ── Fallback: LLM compile, given working plans as examples ──
    examples = [
        {"class": v["class"], "variant": v["variant"], "nodes": v["plan"]}
        for v in playbooks.load_all(include_retired=False)[:2]
    ]
    structured = llm.with_structured_output(CompiledPlan)
    conversation = [
        SystemMessage(content=COMPILE_SYSTEM),
        HumanMessage(content=(
            f"Failure class: {failure_class}\n\n"
            + (f"Working plans already learned (follow their structure and reference style):\n"
               f"{json.dumps(examples, indent=1)[:8000]}\n\n" if examples else "")
            + f"Investigation tool trace ({len(run['tools_used'])} calls):\n{_compact_trace(messages)}\n\n"
            f"Final report:\n{run['report'][:6000]}"
        )),
    ]

    for attempt in range(1, COMPILE_ATTEMPTS + 1):
        try:
            compiled: CompiledPlan = await structured.ainvoke(conversation)
            nodes = [
                {"id": n.id, "type": n.type, "name": n.name, "args": json.loads(n.args_json or "{}")}
                for n in compiled.nodes
            ]
        except Exception as exc:  # noqa: BLE001
            attempts.append({"attempt": attempt, "problem": f"could not produce a plan: {exc}"})
            continue

        dry, problem = await _try_plan(nodes, forbidden, run_id, failure_class)
        if dry:
            variant = playbooks.create(
                failure_class=failure_class, variant=compiled.variant, plan=nodes,
                learned_from_run=run_id, dry_run=dry,
            )
            attempts.append({"attempt": f"compile {attempt}", "problem": None})
            return {"saved": True, "variant": variant, "attempts": attempts, "dry_run": dry, "method": "compiled"}
        attempts.append({"attempt": f"compile {attempt}", **problem})
        if problem["problem"] == "validation":
            feedback = "The plan was rejected:\n- " + "\n- ".join(problem["details"])
        else:
            feedback = (
                f"The plan was executed on this same incident and failed at: {problem['details'][0]}\n"
                f"Executed steps:\n{json.dumps(problem['steps'], indent=1, default=str)[:4000]}"
            )
        conversation += [
            AIMessage(content=compiled.model_dump_json()),
            HumanMessage(content=feedback + "\n\nReturn a corrected plan."),
        ]

    return {"saved": False, "variant": None, "attempts": attempts, "dry_run": None, "method": None}


class _VariantName(BaseModel):
    variant: str = Field(description=CompiledPlan.model_fields["variant"].description)


async def _describe_variant(nodes: List[Dict[str, Any]], run: Dict[str, Any], failure_class: str) -> str:
    """One sentence naming the mechanism — what Jev matches future failures against."""
    try:
        out = await llm.with_structured_output(_VariantName).ainvoke([
            SystemMessage(content=(
                "Name the MECHANISM by which this failure arises, in one general sentence that would also "
                "describe other pipelines built the same way. Do not include file names, paths or ids."
            )),
            HumanMessage(content=(
                f"Class: {failure_class}\nDiagnosis plan steps: "
                f"{[(n['id'], n['name']) for n in nodes]}\n\nInvestigation report:\n{run['report'][:4000]}"
            )),
        ])
        return out.variant
    except Exception:  # noqa: BLE001
        logger.exception("Could not name variant")
        return f"{failure_class}: diagnosed by comparing expected and actual column lists"


# ── Orchestration ────────────────────────────────────────────────────


def _log_run(record: Dict[str, Any]) -> None:
    try:
        path = Path(get_settings().storage_base_path) / "logs" / "jev_rca.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
    except Exception:  # noqa: BLE001 — logging must never fail the request
        logger.exception("Could not write Jev RCA log")


async def run_jev_rca(run_id: str) -> Dict[str, Any]:
    """Jev class → Jev variant → Agent B; otherwise Agent A learns a new variant."""
    if not agent_a_graph:
        return {"response": "Agent is not configured (missing LLM credentials).", "tools_used": [], "jev": None}

    started = time.perf_counter()
    meta: Dict[str, Any] = {}
    await bind_incident(run_id)
    try:
        state, meta = await gather_evidence(run_id)
        jev = await classify_with_jev(state)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Jev evidence gathering failed")
        state, jev = {}, {"status": "error", "reason": f"Evidence gathering failed: {exc}"}

    failure_class = jev.get("hypothesis") if jev.get("used_as_hint") else None
    variant_match: Optional[Dict[str, Any]] = None
    agent_b: Optional[Dict[str, Any]] = None
    variant = None

    # ── Strict: class first, then a variant under that class only ──
    if failure_class:
        variant_match = await match_variant_with_jev(state, playbooks.variants_for(failure_class))
        variant = variant_match.get("variant")
        if variant:
            agent_b = await _run_plan_retrying(variant["plan"], run_id, failure_class)
            # A network failure is not evidence against the variant; don't count it.
            if agent_b["success"] or not is_transient(agent_b["failure"]):
                variant = playbooks.record_outcome(
                    variant, success=agent_b["success"], ms=agent_b["ms"], failure=agent_b["failure"]
                )

    compile_result: Optional[Dict[str, Any]] = None
    if agent_b and agent_b["success"]:
        mode = "fast"
        report, label, tools_used = agent_b["report"], failure_class, [
            s["name"] for s in agent_b["steps"] if s["type"] == "tool"
        ]
        agent_a_run = None
    else:
        mode = "fast_fallback_learn" if agent_b else ("learn" if failure_class else "open")
        agent_a_run = await _run_agent_a(_learn_prompt(run_id, jev), run_id)
        report, label, tools_used = agent_a_run["report"], agent_a_run["label"], agent_a_run["tools_used"]
        # Learn under the class Agent A verified. When it disagrees with Jev,
        # the dry run's diff_explains_class still has to confirm that class on
        # real data before anything is saved — and without this, a persistent
        # disagreement would loop in LEARN mode forever.
        if failure_class and label in SCHEMA_LABELS:
            try:
                compile_result = await compile_variant(label, agent_a_run, run_id, meta)
            except Exception as exc:  # noqa: BLE001 — learning must never fail the RCA
                logger.exception("Variant compilation failed")
                compile_result = {"saved": False, "variant": None, "attempts": [{"problem": str(exc)}]}

    agreement = jev.get("hypothesis") == label if jev.get("status") == "ok" and label else None
    total_ms = round((time.perf_counter() - started) * 1000)
    learned = (compile_result or {}).get("variant")

    _log_run({
        "at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "mode": mode,
        "jev": jev,
        "variant_match": {k: v for k, v in (variant_match or {}).items() if k != "variant"},
        "variant_used": (variant or {}).get("id"),
        "agent_b": {k: agent_b[k] for k in ("success", "failure", "ms", "tool_calls")} if agent_b else None,
        "agent_a": {"tool_calls": len(agent_a_run["tools_used"]), "ms": agent_a_run["ms"]} if agent_a_run else None,
        "classification": label,
        "agreement": agreement,
        "variant_learned": (learned or {}).get("id"),
        "compile_attempts": len((compile_result or {}).get("attempts", [])) or None,
        "total_ms": total_ms,
    })

    return {
        "response": report,
        "tools_used": tools_used,
        "jev": jev,
        "agent_classification": label,
        "agreement": agreement,
        "total_ms": total_ms,
        "mode": mode,
        "variant_match": {k: v for k, v in (variant_match or {}).items() if k != "variant"} or None,
        "variant_used": playbooks.summary(variant),
        "agent_b": (
            {k: agent_b[k] for k in ("success", "failure", "steps", "ms", "tool_calls")} if agent_b else None
        ),
        "agent_a": {"tool_calls": len(agent_a_run["tools_used"]), "ms": agent_a_run["ms"]} if agent_a_run else None,
        "variant_learned": playbooks.summary(learned),
        "compile": (
            {
                "saved": compile_result["saved"],
                "attempts": compile_result["attempts"],
                "dry_run_steps": (compile_result.get("dry_run") or {}).get("steps"),
            }
            if compile_result else None
        ),
    }
