"""Cold-agent evaluation: can an agent that has never seen this warehouse use it through Kairos alone?

This is Kairos's north-star test. A generic tool-calling agent is given only
what any MCP client gets — the server's instructions and its tools — and a
set of questions from different roles (analyst, pipeline ops, governance,
impact analysis, incident response). Each answer is scored two ways:

  mentions  deterministic: the answer names what it must (tables, tasks, facts)
  judge     an LLM compares the answer with a reference and, when it falls
            short, names the context the agent was missing

The "missing context" notes are the point: every failure is a specific gap in
the map, not a vague score. Run with --toolset legacy to measure the same
agent on the pre-context-layer tools and see what the context layer adds.

    python -m kairos_kb.evals.cold_agent [--toolset full|legacy] [--case ID ...]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from kairos_kb.config import get_settings

CASES_FILE = Path(__file__).with_name("cold_agent.yaml")
MAX_STEPS = 12
TOOL_RESULT_CHARS = 14000

# The surface an agent had before the context layer, for comparison.
LEGACY_TOOLS = {"get_entity_map", "list_workspaces", "search_entities", "get_entity", "explore_entity",
                "get_entity_profile", "get_data_dependencies", "get_blast_radius"}
LEGACY_INSTRUCTIONS = (
    "Kairos is a synthetic knowledge layer over a connected data platform. It maintains an entity map "
    "and semantic profiles. Use get_entity_map() to see the terrain, search_entities() to find things by "
    "name, explore_entity() to walk relationships."
)
# Never called during an evaluation: they write or spend budget.
EXCLUDED = {"report_context_issue"}

AGENT_SYSTEM = """You are a capable data assistant working for this company. You have just been connected
to a context server for the company's data platform. You know nothing about the platform beyond what the
server's tools tell you. Use the tools to answer the user's question accurately.

In your answer: name the exact tables, pipelines and tasks you rely on (full names), state facts only when
the tools support them, say how confident you are, and say plainly when the tools do not tell you something.

Server instructions:
{instructions}"""

JUDGE_PROMPT = """You grade answers given by an AI agent that used a data-platform context server.

Question: {question}
Reference (what a correct answer contains): {reference}

Agent's answer:
---
{answer}
---

Grade how well the answer matches the reference in substance (not wording). Penalise invented tables,
wrong claims and missing key facts. Partial credit is allowed.

Return only JSON:
{{"score": <0.0-1.0>, "verdict": "<one sentence>", "missing_context": "<if score < 1: what information the
agent apparently could not get from the server that it needed; else empty>"}}"""


def _llm():
    from kairos_kb.llm.provider import chat_model

    return chat_model()


def load_cases(ids: Optional[List[str]] = None) -> Dict[str, Any]:
    data = yaml.safe_load(CASES_FILE.read_text(encoding="utf-8"))
    if ids:
        data["cases"] = [c for c in data["cases"] if c["id"] in ids]
    return data


def mention_score(answer: str, groups: List[List[str]]) -> Dict[str, Any]:
    """Each group needs at least one of its phrases in the answer (case-insensitive)."""
    low = (answer or "").lower()
    hits, missing = [], []
    for group in groups or []:
        found = next((p for p in group if p.lower() in low), None)
        (hits if found else missing).append(found or " | ".join(group))
    total = len(groups or [])
    return {"score": (len(hits) / total) if total else 1.0, "hits": hits, "missing": missing}


def _parse_json(text: str) -> Dict[str, Any]:
    start, end = text.find("{"), text.rfind("}")
    try:
        return json.loads(text[start:end + 1]) if start >= 0 else {}
    except json.JSONDecodeError:
        return {}


async def _tool_specs(toolset: str) -> List[Dict[str, Any]]:
    from kairos_kb.mcp_server.server import server

    specs = []
    for t in await server.list_tools():
        if t.name in EXCLUDED or (toolset == "legacy" and t.name not in LEGACY_TOOLS):
            continue
        specs.append({"type": "function", "function": {
            "name": t.name, "description": (t.description or "")[:1500], "parameters": t.input_schema}})
    return specs


async def _call_tool(name: str, args: Dict[str, Any]) -> str:
    from kairos_kb.mcp_server.server import server

    try:
        result = await server.call_tool(name, args)
        text = "\n".join(getattr(c, "text", "") for c in result.content)
    except Exception as exc:  # noqa: BLE001 — the agent sees the error, as a real client would
        text = json.dumps({"error": str(exc)[:500]})
    return text if len(text) <= TOOL_RESULT_CHARS else text[:TOOL_RESULT_CHARS] + "\n…[truncated]"


async def ask(question: str, toolset: str = "full") -> Dict[str, Any]:
    """One question, one fresh conversation. Returns the answer and how it was reached."""
    from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

    from kairos_kb.mcp_server.server import INSTRUCTIONS

    specs = await _tool_specs(toolset)
    llm = _llm().bind_tools(specs)
    messages: List[Any] = [
        SystemMessage(AGENT_SYSTEM.format(instructions=INSTRUCTIONS if toolset == "full" else LEGACY_INSTRUCTIONS)),
        HumanMessage(question),
    ]
    calls: List[Dict[str, Any]] = []
    tokens = 0
    for _ in range(MAX_STEPS):
        reply = await llm.ainvoke(messages)
        usage = getattr(reply, "usage_metadata", None) or {}
        tokens += int(usage.get("total_tokens") or 0)
        messages.append(reply)
        if not reply.tool_calls:
            return {"answer": reply.text or "", "tool_calls": calls, "tokens": tokens}
        for tc in reply.tool_calls:
            output = await _call_tool(tc["name"], tc.get("args") or {})
            calls.append({"tool": tc["name"], "args": tc.get("args") or {}, "result_chars": len(output)})
            messages.append(ToolMessage(content=output, tool_call_id=tc["id"]))
    final = await _llm().ainvoke(messages + [HumanMessage("Answer now with what you have found.")])
    return {"answer": final.text or "", "tool_calls": calls, "tokens": tokens, "step_limit_hit": True}


async def judge(question: str, reference: str, answer: str) -> Dict[str, Any]:
    reply = await _llm().ainvoke(JUDGE_PROMPT.format(question=question, reference=reference, answer=answer))
    parsed = _parse_json(reply.text or "")
    try:
        parsed["score"] = max(0.0, min(1.0, float(parsed.get("score", 0))))
    except (TypeError, ValueError):
        parsed["score"] = 0.0
    return parsed


async def run(toolset: str = "full", case_ids: Optional[List[str]] = None, concurrency: int = 3) -> Dict[str, Any]:
    from kairos_kb.context.access import AgentIdentity, set_current_agent

    # Audited like any other agent, under its own name.
    set_current_agent(AgentIdentity(agent_id=None, name=f"cold-agent-eval ({toolset})", channel="eval"))
    data = load_cases(case_ids)
    pass_mark = float(data.get("pass_mark", 0.7))
    sem = asyncio.Semaphore(concurrency)

    async def one(case: Dict[str, Any]) -> Dict[str, Any]:
        async with sem:
            started = time.perf_counter()
            try:
                outcome = await ask(case["question"], toolset)
            except Exception as exc:  # noqa: BLE001
                outcome = {"answer": "", "tool_calls": [], "tokens": 0, "error": str(exc)[:300]}
            mentions = mention_score(outcome["answer"], case.get("must_mention") or [])
            graded = await judge(case["question"], case.get("reference", ""), outcome["answer"]) if outcome["answer"] else \
                {"score": 0.0, "verdict": "No answer.", "missing_context": outcome.get("error", "")}
            passed = mentions["score"] == 1.0 and graded["score"] >= pass_mark
            return {
                "id": case["id"], "role": case.get("role"), "question": case["question"], "passed": passed,
                "mention_score": round(mentions["score"], 2), "mentions_missing": mentions["missing"],
                "judge_score": round(graded["score"], 2), "verdict": graded.get("verdict"),
                "missing_context": graded.get("missing_context") or None,
                "tools_used": [c["tool"] for c in outcome["tool_calls"]],
                "tool_calls": len(outcome["tool_calls"]), "tokens": outcome["tokens"],
                "seconds": round(time.perf_counter() - started, 1),
                "answer": outcome["answer"], "error": outcome.get("error"),
            }

    results = await asyncio.gather(*(one(c) for c in data["cases"]))
    passed = sum(1 for r in results if r["passed"])
    by_role: Dict[str, List[bool]] = {}
    for r in results:
        by_role.setdefault(r["role"] or "other", []).append(r["passed"])
    report = {
        "toolset": toolset,
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "cases": len(results),
        "passed": passed,
        "readiness": round(passed / len(results), 3) if results else 0.0,
        "mean_judge_score": round(sum(r["judge_score"] for r in results) / len(results), 3) if results else 0.0,
        "by_role": {k: f"{sum(v)}/{len(v)}" for k, v in sorted(by_role.items())},
        "tool_calls": sum(r["tool_calls"] for r in results),
        "tokens": sum(r["tokens"] for r in results),
        "context_gaps": [{"case": r["id"], "gap": r["missing_context"]} for r in results
                         if not r["passed"] and r["missing_context"]],
        "results": results,
    }
    save(report)
    return report


def results_dir() -> Path:
    path = Path(get_settings().storage_base_path) / "evals" / "cold_agent"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save(report: Dict[str, Any]) -> Path:
    stamp = report["ran_at"].replace(":", "").replace("-", "")[:15]
    path = results_dir() / f"{stamp}_{report['toolset']}.json"
    path.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    return path


def list_reports(limit: int = 20) -> List[Dict[str, Any]]:
    out = []
    for path in sorted(results_dir().glob("*.json"), reverse=True)[:limit]:
        try:
            r = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        out.append({k: r.get(k) for k in ("toolset", "ran_at", "cases", "passed", "readiness",
                                          "mean_judge_score", "by_role", "tool_calls", "tokens")}
                   | {"file": path.name})
    return out


def format_report(report: Dict[str, Any]) -> str:
    lines = [f"Cold-agent evaluation ({report['toolset']} tools): {report['passed']}/{report['cases']} passed "
             f"· readiness {report['readiness']:.0%} · mean judge {report['mean_judge_score']:.2f} "
             f"· {report['tool_calls']} tool calls · {report['tokens']:,} tokens", ""]
    for r in report["results"]:
        mark = "PASS" if r["passed"] else "FAIL"
        lines.append(f"{mark}  {r['id']:<28} judge {r['judge_score']:.2f}  mentions {r['mention_score']:.2f}  "
                     f"{r['tool_calls']} calls  {r['seconds']}s")
        if not r["passed"]:
            if r["mentions_missing"]:
                lines.append(f"      missing: {', '.join(r['mentions_missing'])}")
            if r["verdict"]:
                lines.append(f"      judge: {r['verdict']}")
    if report["context_gaps"]:
        lines += ["", "Context gaps found:"]
        lines += [f"  - [{g['case']}] {g['gap']}" for g in report["context_gaps"]]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m kairos_kb.evals.cold_agent", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--toolset", choices=["full", "legacy"], default="full")
    parser.add_argument("--case", nargs="*", help="only these case ids")
    parser.add_argument("--concurrency", type=int, default=3)
    args = parser.parse_args()
    logging.disable(logging.WARNING)
    report = asyncio.run(run(args.toolset, args.case, args.concurrency))
    print(format_report(report))
    return 0 if report["passed"] == report["cases"] else 1


if __name__ == "__main__":
    sys.exit(main())
