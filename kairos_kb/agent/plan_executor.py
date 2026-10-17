"""Agent B — runs a compiled RCA plan as a LangGraph, with no agent loop.

A plan (learned by Agent A, see :mod:`kairos_kb.agent.jev_rca`) is an ordered
list of nodes from :mod:`kairos_kb.agent.plan_library`. This module checks a
plan statically, then builds one graph node per plan node and runs them in
order. An LLM is only called inside ``extract`` nodes (single-shot, schema
bound, values checked verbatim against their source) and the final
``report`` node (which sees only the computed facts). Any failing node —
a tool error, an unfound value, a verify returning ok=false — stops the
graph, and the caller falls back to Agent A.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict, List, Literal, Optional, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import Field, create_model

from kairos_kb.agent.graph import llm
from kairos_kb.agent.plan_library import COMPUTE_OPS, VERIFY_OPS

logger = logging.getLogger(__name__)

NODE_TYPES = ("tool", "extract", "compute", "verify", "report")
MAX_EXTRACT_SOURCE_CHARS = 60000
MAX_FACT_CHARS = 6000

_ID = re.compile(r"^[a-z_][a-z0-9_]*$")
_PATH = r"((?:\.[A-Za-z0-9_]+|\[\d+\])*)"
_WHOLE_REF = re.compile(rf"^\$([a-z_][a-z0-9_]*){_PATH}$")
_TEMPLATE = re.compile(rf"\{{\{{\s*\$?([a-z_][a-z0-9_]*){_PATH}\s*\}}\}}")
_STEP = re.compile(r"\.([A-Za-z0-9_]+)|\[(\d+)\]")


def _tool_registry() -> Dict[str, Any]:
    # Imported lazily: jev_rca imports this module.
    from kairos_kb.agent.jev_rca import JEV_RCA_TOOLS

    return {t.name: t for t in JEV_RCA_TOOLS}


# ── References ───────────────────────────────────────────────────────


def _walk(value: Any, path: str, ref: str) -> Any:
    for key, index in _STEP.findall(path):
        if index:
            if not isinstance(value, list) or int(index) >= len(value):
                raise KeyError(f"{ref}: no item [{index}]")
            value = value[int(index)]
        else:
            if not isinstance(value, dict) or key not in value:
                raise KeyError(f"{ref}: no field '{key}'")
            value = value[key]
    return value


def _resolve(arg: Any, results: Dict[str, Any]) -> Any:
    if isinstance(arg, dict):
        return {k: _resolve(v, results) for k, v in arg.items()}
    if isinstance(arg, list):
        return [_resolve(v, results) for v in arg]
    if not isinstance(arg, str):
        return arg

    whole = _WHOLE_REF.match(arg)
    if whole:
        node, path = whole.groups()
        if node not in results:
            raise KeyError(f"${node}: no such result")
        return _walk(results[node], path, arg)

    def sub(match: re.Match) -> str:
        node, path = match.groups()
        if node not in results:
            raise KeyError(f"{{{{{node}}}}}: no such result")
        value = _walk(results[node], path, match.group(0))
        # Interpolated values mostly land in SQL string literals.
        return str(value).replace("'", "''")

    return _TEMPLATE.sub(sub, arg)


def _refs_in(arg: Any) -> List[str]:
    if isinstance(arg, dict):
        return [r for v in arg.values() for r in _refs_in(v)]
    if isinstance(arg, list):
        return [r for v in arg for r in _refs_in(v)]
    if not isinstance(arg, str):
        return []
    whole = _WHOLE_REF.match(arg)
    if whole:
        return [whole.group(1)]
    return [m.group(1) for m in _TEMPLATE.finditer(arg)]


def _literals_in(arg: Any) -> List[str]:
    """Plain strings in args, with every reference removed."""
    if isinstance(arg, dict):
        return [s for v in arg.values() for s in _literals_in(v)]
    if isinstance(arg, list):
        return [s for v in arg for s in _literals_in(v)]
    if not isinstance(arg, str) or _WHOLE_REF.match(arg):
        return []
    return [_TEMPLATE.sub("", arg)]


# ── Static validation ────────────────────────────────────────────────

_INSTANCE_PATH = re.compile(r"/(Volumes|Workspace|Users|Repos|Shared)/")


def validate_plan(nodes: List[Dict[str, Any]], forbidden_literals: Optional[List[str]] = None) -> List[str]:
    """Return a list of problems; empty means the plan is well-formed and general."""
    errors: List[str] = []
    tools = _tool_registry()
    seen = {"input"}
    forbidden = [f for f in (forbidden_literals or []) if len(f) >= 8]

    if not nodes:
        return ["Plan has no nodes."]
    for i, node in enumerate(nodes):
        nid, ntype, name, args = node.get("id"), node.get("type"), node.get("name"), node.get("args", {})
        where = f"node {i} ({nid})"
        if not isinstance(nid, str) or not _ID.match(nid) or nid in seen:
            errors.append(f"{where}: id must be unique snake_case and not 'input'.")
        if ntype not in NODE_TYPES:
            errors.append(f"{where}: unknown type {ntype!r}.")
        if not isinstance(args, dict):
            errors.append(f"{where}: args must be an object.")
            args = {}
        if ntype == "tool" and name not in tools:
            errors.append(f"{where}: unknown tool {name!r}.")
        if ntype == "compute" and name not in COMPUTE_OPS:
            errors.append(f"{where}: unknown compute op {name!r}.")
        if ntype == "verify" and name not in VERIFY_OPS:
            errors.append(f"{where}: unknown verify op {name!r}.")
        if ntype == "extract" and not (args.get("from") and isinstance(args.get("fields"), dict) and args["fields"]):
            errors.append(f"{where}: extract needs 'from' and a non-empty 'fields' object.")
        if ntype == "report" and i != len(nodes) - 1:
            errors.append(f"{where}: report must be the last node.")
        for ref in _refs_in(args):
            if ref not in seen:
                errors.append(f"{where}: references '{ref}' before it exists.")
        # An extract's field descriptions are instructions to the extractor,
        # not values the plan uses, so only its other args are checked.
        checked = {k: v for k, v in args.items() if k != "fields"} if ntype == "extract" else args
        for lit in _literals_in(checked):
            if _INSTANCE_PATH.search(lit):
                errors.append(f"{where}: hardcoded path in {lit[:80]!r} — take it from a reference or an extract.")
            for f in forbidden:
                if f in lit:
                    errors.append(f"{where}: hardcoded instance value {f[:60]!r} — take it from a reference or an extract.")
        if isinstance(nid, str):
            seen.add(nid)

    types = [n.get("type") for n in nodes]
    if nodes[-1].get("type") != "report":
        errors.append("The last node must be a report.")
    if "compute" not in types:
        errors.append("A plan needs at least one compute node.")
    if "verify" not in types:
        errors.append("A plan needs at least one verify node.")
    return errors


# ── Node execution ───────────────────────────────────────────────────


class _Failure(Exception):
    pass


def _short(value: Any, limit: int = 160) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= limit else text[:limit] + "…"


def _as_text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, default=str, indent=1)


async def _run_tool(name: str, args: Dict[str, Any]) -> Any:
    try:
        result = await _tool_registry()[name].ainvoke(args)
    except Exception as exc:  # noqa: BLE001
        raise _Failure(f"tool {name} raised: {exc}") from exc
    # Tools report their own failure as {"error": ...} and nothing else. An
    # "error" key alongside other fields is data (e.g. the task's error text).
    if isinstance(result, dict) and set(result) == {"error"}:
        raise _Failure(f"tool {name}: {result['error']}")
    if isinstance(result, str) and result.lower().startswith("error"):
        raise _Failure(f"tool {name}: {result[:300]}")
    # In a diagnosis plan an empty column source always means the plan is
    # wrong (bad filter, wrong file) — fail here, not three nodes later.
    if isinstance(result, dict) and (result.get("row_count") == 0 or result.get("count") == 0):
        raise _Failure(f"tool {name} returned nothing for args {json.dumps(args, default=str)[:300]}")
    return result


async def _run_extract(args: Dict[str, Any]) -> Dict[str, Any]:
    sources = args["from"] if isinstance(args["from"], list) else [args["from"]]
    text = "\n\n---\n\n".join(_as_text(s) for s in sources)[:MAX_EXTRACT_SOURCE_CHARS]
    fields: Dict[str, str] = args["fields"]

    model = create_model(
        "Extracted",
        **{name: (Optional[str], Field(default=None, description=desc)) for name, desc in fields.items()},
    )
    try:
        out = await llm.with_structured_output(model).ainvoke([
            SystemMessage(content=(
                "Copy each requested value exactly as it is written in the source text, without surrounding "
                "quotes. Do not infer, reformat or complete values. If a value is not written in the text, "
                "return null."
            )),
            HumanMessage(content=f"Source text:\n{text}"),
        ])
    except Exception as exc:  # noqa: BLE001
        raise _Failure(f"extract failed: {exc}") from exc

    values = {}
    for name, value in out.model_dump().items():
        # Models often copy a string literal together with its quotes.
        if isinstance(value, str):
            value = value.strip()
            while len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'`":
                value = value[1:-1].strip()
        values[name] = value
    for name, value in values.items():
        if not value:
            raise _Failure(f"extract: '{name}' not found in the source")
        if value not in text:
            raise _Failure(f"extract: '{name}'={value!r} does not appear verbatim in the source")
    return values


def _without_agent_hints(value: Any) -> Any:
    """Drop fields that are instructions to an agent (e.g. next_step), not facts."""
    if isinstance(value, dict):
        return {k: _without_agent_hints(v) for k, v in value.items() if k != "next_step"}
    if isinstance(value, list):
        return [_without_agent_hints(v) for v in value]
    return value


async def _run_report(args: Dict[str, Any], failure_class: str) -> str:
    facts = {
        label: _short(_without_agent_hints(value), MAX_FACT_CHARS)
        for label, value in (args.get("facts") or {}).items()
    }
    response = await llm.ainvoke([
        SystemMessage(content=(
            "You write a Root Cause Analysis for a failed Databricks pipeline run, using ONLY the facts "
            "given. Do not add anything the facts do not show; if something is unknown, say so. Use exactly "
            "these markdown headers: ### 🚨 Incident Summary, ### 🔍 Root Cause Analysis, "
            "### ⛓️ Lineage & Impact, ### 🛠️ Recommended Fix. Name the exact columns involved, and report "
            "every difference in the diff (extra, missing, renamed, moved), not only the first."
        )),
        HumanMessage(content=f"Diagnosed class: {failure_class}\n\nFacts:\n{json.dumps(facts, indent=1)}"),
    ])
    return response.text


# ── Graph ────────────────────────────────────────────────────────────


class PlanState(TypedDict):
    results: Dict[str, Any]
    steps: List[Dict[str, Any]]
    failed: Optional[str]


def _make_node(node: Dict[str, Any], failure_class: str):
    nid, ntype, name = node["id"], node["type"], node.get("name")

    async def run(state: PlanState) -> dict:
        started = time.perf_counter()
        results = dict(state["results"])
        step = {"id": nid, "type": ntype, "name": name}
        try:
            args = _resolve(node.get("args", {}), results)
            if ntype == "tool":
                output = await _run_tool(name, args)
            elif ntype == "extract":
                output = await _run_extract(args)
            elif ntype == "compute":
                try:
                    output = COMPUTE_OPS[name](**args)
                except Exception as exc:  # noqa: BLE001
                    raise _Failure(f"compute {name}: {exc}") from exc
            elif ntype == "verify":
                output = VERIFY_OPS[name](**args)
                if not output.get("ok"):
                    raise _Failure(f"verify {name}: {output.get('detail')}")
            else:
                output = await _run_report(args, failure_class)
            results[nid] = output
            step.update(ok=True, summary=_short(output))
            failed = None
        except (_Failure, KeyError) as exc:
            step.update(ok=False, summary=str(exc))
            failed = f"{nid}: {exc}"
        step["ms"] = round((time.perf_counter() - started) * 1000)
        return {"results": results, "steps": state["steps"] + [step], "failed": failed}

    return run


def _build(nodes: List[Dict[str, Any]], failure_class: str):
    graph = StateGraph(PlanState)
    ids = [n["id"] for n in nodes]
    for node in nodes:
        graph.add_node(node["id"], _make_node(node, failure_class))
    graph.add_edge(START, ids[0])
    for current, nxt in zip(ids, ids[1:] + [END]):
        def route(state: PlanState, _next=nxt) -> str:
            return END if state["failed"] else _next
        graph.add_conditional_edges(current, route)
    return graph.compile()


async def run_plan(
    nodes: List[Dict[str, Any]], run_id: str, failure_class: str, *, return_results: bool = False
) -> Dict[str, Any]:
    """Execute a plan. Returns success, the report, per-node steps and the failure reason.

    ``return_results`` adds every node's full output (evaluations check the
    computed diff against known answers).
    """
    started = time.perf_counter()
    problems = validate_plan(nodes)
    if problems:
        return {"success": False, "failure": "invalid plan: " + "; ".join(problems), "steps": [], "report": None,
                "ms": 0, "tool_calls": 0, **({"results": {}} if return_results else {})}

    final = await _build(nodes, failure_class).ainvoke(
        {"results": {"input": {"run_id": run_id, "failure_class": failure_class}}, "steps": [], "failed": None},
        config={"recursion_limit": len(nodes) + 5},
    )
    report_id = nodes[-1]["id"]
    success = not final["failed"] and report_id in final["results"]
    report = final["results"].get(report_id) if success else None
    if report:
        report += f"\n\n### 🏷️ Schema Classification\nFINAL_CLASSIFICATION: {failure_class}\n"
    out = {
        "success": success,
        "failure": final["failed"],
        "steps": final["steps"],
        "report": report,
        "ms": round((time.perf_counter() - started) * 1000),
        "tool_calls": sum(1 for s in final["steps"] if s["type"] == "tool"),
    }
    if return_results:
        out["results"] = final["results"]
    return out
