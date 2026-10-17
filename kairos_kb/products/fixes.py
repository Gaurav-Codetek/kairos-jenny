"""What agents can't find becomes part of the data product: checked, applied and proven.

Agents report gaps in a data product: a dimension it lacks (restaurant names), a metric nobody defined (cancelled
items), data that went missing (a stream that stopped). Each report about a product goes through:

  1. triage    Jev reads what would fix it: a product change, a data problem, a description, a new product, or
               nothing actionable; and whether it repeats a report already open (then the two are merged).
  2. proposal  for a product change, the smallest addition to the product's semantic model: new dimensions or
               metrics, nothing existing redefined, proposed by the model from the enriched map…
  3. checks    …and kept only where it holds: columns exist and joins have keys (validate_model), it compiles on
               the platform without reading data (verify_on_platform), and the product can query it.
  4. apply     additions go live at once, since nothing existing changes (PRODUCT_FIXES_AUTO_APPLY=never makes
               every proposal wait for a person's approval).
  5. proof     the new dimensions and metrics are queried for real and the agent's failed lookup is replayed; the
               report is resolved only then. If the proof fails, the change is rolled back.
  6. tell      agents learn what's new: Jenny mentions it when it's relevant.

Other kinds of report:
  description  the data is fine but the product's meanings mislead: a caveat, a rule for agents or a glossary term
               is added (additions only), the same way.
  new product  the report needs an area no product covers: Kairos drafts the product's concept, and a person builds
               it with one click (the product builder; it starts as a draft).
  data problem the data itself is wrong or missing: listed on Incidents with its evidence for whoever runs the
               pipeline; one whose lookup now returns data resolves itself.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field
from sqlalchemy import select

from kairos_kb.db.engine import async_session_factory
from kairos_kb.models.context import ContextFeedback
from kairos_kb.models.data_product import DataProduct
from kairos_kb.models.living import AgentNote
from kairos_kb.models.workspace import Workspace
from kairos_kb.products.designer import (
    DIALECTS, Dimension, Metric, SemanticModel, Term, model_brief, validate_model, verify_on_platform,
)
from kairos_kb.products.semantic import QueryError, compile_query

logger = logging.getLogger(__name__)

AUTO_APPLY = os.getenv("PRODUCT_FIXES_AUTO_APPLY", "additions").strip().lower()  # additions | never
INTERVAL_S = 600                 # how often open reports are looked at again
MAX_TABLES = 14                  # tables shown to the model when proposing
SAME_NEED = 0.75                 # Jev: two reports ask for the same thing
CATEGORIES = ("product_change", "data_issue", "description", "new_product", "not_actionable")
LIVE_STAGES = ("new", "triaged")  # still being worked on by the loop
ANSWERS = 0.6                    # Jev: the addition answers what the report asked for (else a person decides)
RESERVED = {"event_time"}        # names Kairos gives meaning to itself (the live event clock)

_lock = asyncio.Lock()
_task: Optional[asyncio.Task] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _step(f: ContextFeedback, stage: str, note: str, **extra: Any) -> None:
    """Move the report to `stage`, recording why."""
    loop = dict(f.loop or {})
    history = list(loop.get("history") or []) + [{"at": _now(), "stage": stage, "note": note}]
    loop.update(extra)
    loop["history"] = history[-20:]
    f.loop = loop
    f.stage = stage


async def product_of(db, entity_id: str) -> Optional[DataProduct]:
    """The product a report is about: entity ids look like product:<connection>:<slug>."""
    parts = (entity_id or "").split(":")
    if len(parts) < 3 or parts[0] != "product":
        return None
    ws = (await db.execute(select(Workspace).where(Workspace.name == ":".join(parts[1:-1])))).scalars().first()
    if ws is None:
        return None
    return (await db.execute(select(DataProduct).where(DataProduct.workspace_id == ws.id,
                                                       DataProduct.slug == parts[-1]))).scalars().first()


def product_brief(model: Dict[str, Any]) -> str:
    """The product as it stands, for the model: every dimension and metric, and where each lives."""
    lines = ["Dimensions:"]
    for d in model.get("dimensions") or []:
        via = "; ".join(f"{j['from_table']}.{j['from_column']} = {j['to_column']}" for j in d.get("joins") or [])
        lines.append(f"- {d['name']} ({d.get('type')}): {d['table']}.{d['column']}" + (f" joined by {via}" if via else ""))
    lines.append("Metrics:")
    for m in model.get("metrics") or []:
        lines.append(f"- {m['name']}: {m['expression']} on {m['base_table']}" + (" (adds up)" if m.get("additive") else ""))
    return "\n".join(lines)


# ── 1. triage ─────────────────────────────────────────────────────────


def triage_questions() -> Dict[str, Any]:
    from typesafe_sdk import Choice

    return {
        "category": Choice(
            instructions=("An agent reported that a data product couldn't give it what it needed (report). What would "
                          "fix it?"),
            criteria={
                "product_change": {"what": "The product lacks a dimension, metric or join the warehouse likely has.",
                                   "examples": ["only restaurant IDs, no names", "can't break it down by city",
                                                "no metric for cancelled items"]},
                "data_issue": {"what": "The data itself is wrong, late or missing: a stream stopped, a pipeline failed, "
                                       "zeros where there should be orders.",
                               "examples": ["zero orders between 5 and 6 a.m.", "numbers stopped updating"]},
                "description": {"what": "The product's description or meanings are wrong or confusing; the data is fine."},
                "new_product": {"what": "Needs an area of the business this product doesn't cover at all."},
                "not_actionable": {"what": "Too vague to act on, or not about the data."},
            }),
    }


def answers_questions() -> Dict[str, Any]:
    from typesafe_sdk import Noul

    return {"answers": Noul(
        instructions="Would the proposed additions let an agent give what the report asked for?",
        criteria={"true": "The addition is what was asked, or plainly lets it be answered (a city dimension for "
                          "'can't break it down by city').",
                  "false": "It adds something else, or only part of it, or something merely related."})}


async def answers(f: ContextFeedback, adds: List[Dict[str, str]]) -> Optional[float]:
    r = await _jev({"report": f.message, "suggestion": f.suggestion or "",
                    "proposed_additions": [f"{a['kind']} {a['name']}: {a['definition']}" for a in adds]},
                   answers_questions())
    return None if r is None else r.get("answers")


def same_need_questions() -> Dict[str, Any]:
    from typesafe_sdk import Noul

    return {"same_need": Noul(instructions="Do report_a and report_b ask for the same thing to be added or fixed?")}


async def _jev(state: Dict[str, Any], questions: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    from kairos_kb.companion.brain import ask_jev

    return await ask_jev(state, questions)


async def triage(f: ContextFeedback, p: DataProduct) -> Dict[str, Any]:
    r = await _jev({"report": f.message, "suggestion": f.suggestion or "", "product": p.name,
                    "question_asked": (f.evidence or {}).get("question") or ""}, triage_questions())
    c = (r or {}).get("category") or {}
    if c.get("choice") in CATEGORIES and c.get("confidence", 0) >= 0.5:
        return {"category": c["choice"], "confidence": c["confidence"]}
    # Without a confident read: the kind of report decides.
    by_kind = {"missing": "product_change", "stale": "data_issue", "incorrect": "description", "confusing": "description"}
    return {"category": by_kind.get(f.kind, "not_actionable"), "confidence": None}


async def same_need(a: str, b: str) -> bool:
    r = await _jev({"report_a": a, "report_b": b}, same_need_questions())
    return bool(r) and (r.get("same_need") or 0) >= SAME_NEED


# ── 2–3. proposal and checks ──────────────────────────────────────────


class Patch(BaseModel):
    possible: bool = Field(description="False when nothing in the listed tables answers the report.")
    reason: str = Field(description="One or two sentences: what you add and why, or why it isn't possible.")
    dimensions: List[Dimension] = Field(default_factory=list)
    metrics: List[Metric] = Field(default_factory=list)


FIX_SYSTEM = """You extend a data product's semantic model so it answers what an agent could not get from it.
- Propose the SMALLEST addition that answers the report: new dimensions and/or new metrics. Never redefine, rename
  or remove anything the product already has; every name you add is new (snake_case).
- A dimension on another table needs joins from each of the product's base fact tables that should reach it
  (from_table = that fact table, from_column on it, to_column on the dimension's table). Prefer a join path the
  product already uses.
- A metric is one SQL aggregate over its base fact table, columns prefixed 'f.', with no subqueries.
- When the asked-for metric can't be one aggregate over a base table, a dimension that lets an EXISTING metric
  answer it is the smallest addition (e.g. an order status joined from the orders table, so units sold can be
  filtered to cancelled orders); say in reason how it answers the report.
- Use table and column names exactly as listed; never invent a column. If nothing listed answers the report, set
  possible to false and say why.
- Personal data (people's names, emails, phone numbers) is never a dimension."""


def _evidence_brief(f: ContextFeedback) -> str:
    ev = f.evidence or {}
    out = []
    if ev.get("question"):
        out.append(f"The owner asked: {ev['question']}")
    for lk in ev.get("lookups") or []:
        if not lk.get("ok"):
            out.append(f"A lookup that failed: {lk.get('tool')} {json.dumps(lk.get('args'), default=str)[:300]} "
                       f"→ {str(lk.get('error'))[:200]}")
    return "\n".join(out)


async def propose(db, f: ContextFeedback, p: DataProduct, ws: Workspace) -> Dict[str, Any]:
    """The smallest addition that answers the report, with only what passes every check kept."""
    from kairos_kb.connectors.factory import connector_for, sql_dialect
    from kairos_kb.llm.provider import chat_model
    from kairos_kb.products.service import _shortlist, enriched_tables

    model = (p.spec or {}).get("model") or {}
    tables = await enriched_tables(db, ws)
    own = [i["entity_id"] for i in (p.spec or {}).get("inputs") or []]
    shortlist = await _shortlist(db, ws, tables, f"{f.message} {f.suggestion or ''}", "", own)
    inputs = [t for t in tables if t["entity_id"] in own]
    inputs += [t for t in shortlist if t["entity_id"] not in own][:max(0, MAX_TABLES - len(inputs))]
    connector = connector_for(ws)
    dialect = sql_dialect(connector)
    llm = chat_model()
    if llm is None:
        return {"possible": False, "reason": "No language model is configured to propose a change."}
    brief = (f"# The product: {p.name}\n{product_brief(model)}\n\n# What the agent could not get\n{f.message}\n"
             + (f"Suggested: {f.suggestion}\n" if f.suggestion else "") + _evidence_brief(f)
             + "\n\n# Tables you may use\n" + model_brief(p.name, p.intent or "", inputs, dialect))
    patch: Patch = await llm.with_structured_output(Patch).ainvoke(
        [("system", FIX_SYSTEM + "\n" + DIALECTS.get(dialect, "")), ("human", brief)])
    if not patch.possible or not (patch.dimensions or patch.metrics):
        return {"possible": False, "reason": patch.reason or "Nothing in the warehouse answers it."}
    from kairos_kb.products.designer import _snake, repair_metrics

    reserved = [x.name for x in [*patch.dimensions, *patch.metrics] if _snake(x.name) in RESERVED]
    patch.dimensions = [d for d in patch.dimensions if _snake(d.name) not in RESERVED]
    patch.metrics = [m for m in patch.metrics if _snake(m.name) not in RESERVED]
    designed = SemanticModel(description="", purpose="", dimensions=patch.dimensions, metrics=patch.metrics)
    checked, dropped = validate_model(designed, inputs)
    dropped += [{"kind": "name", "item": n, "reason": "a name Kairos reserves for itself"} for n in reserved]
    have_d = {d["name"] for d in model.get("dimensions") or []}
    have_m = {m["name"] for m in model.get("metrics") or []}
    clashes = [x["name"] for x in checked["dimensions"] if x["name"] in have_d] + \
              [x["name"] for x in checked["metrics"] if x["name"] in have_m]
    probe = {"dimensions": [d for d in checked["dimensions"] if d["name"] not in have_d],
             "metrics": [m for m in checked["metrics"] if m["name"] not in have_m], "tools": []}
    dropped += await verify_on_platform(probe, connector)
    failures = [d for d in dropped if d["kind"] == "metric" and "does not compile" in d["reason"]]
    if failures:  # one more pass with the platform's own error, as the product builder does
        fixed = await repair_metrics(designed, failures, inputs, dialect)
        if fixed:
            again, more = validate_model(SemanticModel(description="", purpose="", dimensions=[], metrics=fixed), inputs)
            extra = {"dimensions": [], "metrics": [m for m in again["metrics"] if m["name"] not in have_m], "tools": []}
            more += await verify_on_platform(extra, connector)
            if extra["metrics"]:
                names = {m["name"] for m in extra["metrics"]}
                dropped = [d for d in dropped if not (d["kind"] == "metric" and d["item"] in names)] + more
                probe["metrics"] += extra["metrics"]
    merged = merge(model, probe["dimensions"], probe["metrics"])
    dims = []
    for d in probe["dimensions"]:
        if reaching_metric(merged, d["name"]):
            dims.append(d)
        else:
            dropped.append({"kind": "dimension", "item": d["name"], "reason": "no metric of the product can reach it"})
    merged = merge(model, dims, probe["metrics"])
    used = {d["entity_id"] for d in dims if d.get("entity_id")} | {m["base_entity_id"] for m in probe["metrics"]}
    new_inputs = [{"entity_id": t["entity_id"], "table": t["full_name"], "role": "dimension" if t["lane"] != "mart" else "aggregate",
                   "why": f"Added to answer a report: {f.message[:120]}", "lane": t["lane"], "grain": t.get("grain"),
                   "trust": t.get("trust")} for t in inputs if t["entity_id"] in used and t["entity_id"] not in own]
    return {"possible": bool(dims or probe["metrics"]), "reason": patch.reason, "dimensions": dims,
            "metrics": probe["metrics"], "dropped": dropped, "clashes": clashes, "additive": not clashes,
            "model": merged, "new_inputs": new_inputs}


def merge(model: Dict[str, Any], dims: List[Dict[str, Any]], metrics: List[Dict[str, Any]]) -> Dict[str, Any]:
    out = copy.deepcopy(model)
    out["dimensions"] = list(out.get("dimensions") or []) + copy.deepcopy(dims)
    out["metrics"] = list(out.get("metrics") or []) + copy.deepcopy(metrics)
    return out


def reaching_metric(model: Dict[str, Any], dim: str) -> Optional[str]:
    """A metric of the product that can be broken down by this dimension (the query compiles)."""
    for m in model.get("metrics") or []:
        try:
            compile_query(model, [m["name"]], [dim])
            return m["name"]
        except QueryError:
            continue
    return None


def describe(prop: Dict[str, Any]) -> List[Dict[str, str]]:
    """What the proposal adds, in words a person can check."""
    out = []
    for d in prop.get("dimensions") or []:
        via = "; ".join(f"{j['from_table'].split('.')[-1]}.{j['from_column']} = {j['to_column']}" for j in d.get("joins") or [])
        out.append({"kind": "dimension", "name": d["name"], "label": d.get("label") or d["name"],
                    "definition": f"{d['table']}.{d['column']}" + (f" (joined on {via})" if via else "")})
    for m in prop.get("metrics") or []:
        out.append({"kind": "metric", "name": m["name"], "label": m.get("label") or m["name"],
                    "definition": f"{m['expression']} on {m['base_table']}"})
    for kind, key in (("caveat", "caveats"), ("rule", "agent_guidance")):
        for text in prop.get(key) or []:
            out.append({"kind": kind, "name": kind, "label": text[:60], "definition": text})
    for t in prop.get("glossary") or []:
        out.append({"kind": "term", "name": t["term"], "label": t["term"], "definition": t["meaning"]})
    return out


class GuidanceFix(BaseModel):
    possible: bool = Field(description="False when the report isn't about what the product's meanings say.")
    reason: str
    caveats: List[str] = Field(default_factory=list, description="Facts about the data agents must keep in mind.")
    agent_guidance: List[str] = Field(default_factory=list, description="Concrete rules for answering from it.")
    glossary: List[Term] = Field(default_factory=list, description="Terms people use and what they mean here.")


GUIDANCE_SYSTEM = """An agent found a data product's meanings wrong or confusing; the data itself is fine. Add the
smallest correction to what agents read about the product: a caveat (a fact about the data), a rule for answering,
or a glossary term. Add only; never restate what's already there. One sentence each, concrete, naming the metric or
dimension it concerns. If the report isn't about what the product says, set possible to false."""


async def fix_guidance(f: ContextFeedback, p: DataProduct) -> Dict[str, Any]:
    from kairos_kb.llm.provider import chat_model

    model = (p.spec or {}).get("model") or {}
    llm = chat_model()
    if llm is None:
        return {"possible": False, "reason": "No language model is configured."}
    said = {"caveats": model.get("caveats") or [], "agent_guidance": model.get("agent_guidance") or [],
            "glossary": model.get("glossary") or []}
    fix: GuidanceFix = await llm.with_structured_output(GuidanceFix).ainvoke([("system", GUIDANCE_SYSTEM), (
        "human", f"# {p.name}\n{product_brief(model)}\nWhat agents read now: {json.dumps(said, default=str)[:3000]}\n\n"
                 f"# The report\n{f.message}\n" + (f"Suggested: {f.suggestion}\n" if f.suggestion else "") + _evidence_brief(f))])
    have = set(said["caveats"]) | set(said["agent_guidance"]) | {t.get("term") for t in said["glossary"]}
    out = {"possible": fix.possible, "reason": fix.reason,
           "caveats": [c for c in fix.caveats if c not in have], "agent_guidance": [g for g in fix.agent_guidance if g not in have],
           "glossary": [t.model_dump() for t in fix.glossary if t.term not in have], "dimensions": [], "metrics": []}
    out["possible"] = fix.possible and bool(out["caveats"] or out["agent_guidance"] or out["glossary"])
    return out


class NewProduct(BaseModel):
    concept: str = Field(description="The business concept to build a data product for, in two or three words.")
    intent: str = Field(description="What it should let people answer, in one sentence, drawn from the report.")
    why: str = Field(description="Why the existing product can't hold it, in one sentence.")


async def plan_product(f: ContextFeedback, p: DataProduct) -> Optional[Dict[str, Any]]:
    from kairos_kb.llm.provider import chat_model

    llm = chat_model()
    if llm is None:
        return None
    plan: NewProduct = await llm.with_structured_output(NewProduct).ainvoke([(
        "system", "An agent needs an area of the business the data product it used doesn't cover. Name the new data "
                  "product to build for it."), (
        "human", f"Existing product: {p.name}: {p.description or ''}\nThe report: {f.message}\n"
                 + (f"Suggested: {f.suggestion}\n" if f.suggestion else "") + _evidence_brief(f))])
    return plan.model_dump()


# ── 4–6. apply, prove, tell ──────────────────────────────────────────


def apply(p: DataProduct, prop: Dict[str, Any], f: ContextFeedback) -> Dict[str, Any]:
    """The product with the additions: model, inputs and a revision record. Returns what it was before."""
    spec = copy.deepcopy(p.spec or {})
    before = copy.deepcopy(spec.get("model") or {})
    spec["model"] = merge(before, prop.get("dimensions") or [], prop.get("metrics") or [])
    for key in ("caveats", "agent_guidance"):
        spec["model"][key] = list(spec["model"].get(key) or []) + [x for x in prop.get(key) or []]
    spec["model"]["glossary"] = list(spec["model"].get("glossary") or []) + list(prop.get("glossary") or [])
    have = {i["entity_id"] for i in spec.get("inputs") or []}
    spec["inputs"] = list(spec.get("inputs") or []) + [i for i in prop.get("new_inputs") or [] if i["entity_id"] not in have]
    added = [x["name"] for x in describe(prop)]
    spec["revisions"] = list(spec.get("revisions") or []) + [{"at": _now(), "report": str(f.id), "added": added,
                                                              "by": "report loop"}]
    p.spec = spec
    p.seeds = list(dict.fromkeys([*(p.seeds or []), *[i["entity_id"] for i in prop.get("new_inputs") or []]]))
    return before


def take_back(p: DataProduct, added: List[str]) -> None:
    """Remove these additions again (leaving anything added since)."""
    spec = copy.deepcopy(p.spec or {})
    model = spec.get("model") or {}
    model["dimensions"] = [d for d in model.get("dimensions") or [] if d["name"] not in added]
    model["metrics"] = [m for m in model.get("metrics") or [] if m["name"] not in added]
    for key in ("caveats", "agent_guidance"):
        model[key] = [x for x in model.get(key) or [] if x not in added]
    model["glossary"] = [t for t in model.get("glossary") or [] if t.get("term") not in added]
    spec["model"] = model
    p.spec = spec


def _numbers(rows: List[Any]) -> List[float]:
    out = []
    for r in rows or []:
        for v in (r if isinstance(r, (list, tuple)) else [r]):
            try:
                out.append(float(v))
            except (TypeError, ValueError):
                continue
    return out


async def prove(db, f: ContextFeedback, p: DataProduct, prop: Dict[str, Any]) -> Tuple[bool, List[Dict[str, Any]]]:
    """Query each addition for real, and replay the agent's failed lookups. Additions must return rows."""
    from kairos_kb.companion.vitals import event_column, live_model, run

    ev = await event_column(db, p)
    model = live_model(p, {"table": ev[0], "column": ev[1]} if ev else None)
    checks: List[Dict[str, Any]] = []
    for d in prop.get("dimensions") or []:
        metric = reaching_metric(model, d["name"]) or ""
        r = await run(db, model, [metric], [d["name"]], None, "", 5) if metric else {"error": "no metric reaches it"}
        checks.append({"what": f"{metric} by {d['name']}", "ok": not r.get("error") and bool(r.get("rows")),
                       "sample": [list(map(str, x)) for x in (r.get("rows") or [])[:3]], "error": r.get("error")})
    for m in prop.get("metrics") or []:
        r = await run(db, model, [m["name"]], None, None, "", 5)
        checks.append({"what": m["name"], "ok": not r.get("error") and bool(r.get("rows")),
                       "sample": [list(map(str, x)) for x in (r.get("rows") or [])[:3]], "error": r.get("error")})
    for lk in (f.evidence or {}).get("lookups") or []:
        if lk.get("ok") or lk.get("tool") != "query":
            continue
        a = lk.get("args") or {}
        r = await run(db, model, list(a.get("metrics") or []), list(a.get("by") or []), a.get("filters") or None,
                      str(a.get("order") or ""), 5)
        checks.append({"what": "the lookup that failed, replayed", "replay": True, "ok": not r.get("error"),
                       "sample": [list(map(str, x)) for x in (r.get("rows") or [])[:3]], "error": r.get("error")})
    own = [c for c in checks if not c.get("replay")]
    return bool(own) and all(c["ok"] for c in own), checks


async def _apply_and_prove(db, f: ContextFeedback, p: DataProduct, prop: Dict[str, Any], by: str) -> None:
    public = {"adds": describe(prop), "reason": prop.get("reason"), "dropped": prop.get("dropped") or []}
    apply(p, prop, f)
    await db.flush()
    if prop.get("dimensions") or prop.get("metrics"):
        ok, checks = await prove(db, f, p, prop)
    else:  # words for agents, not data: nothing to query
        ok, checks = True, []
    # What was added, as take_back finds it again: names for dimensions, metrics and terms; the text of a caveat or rule.
    added = [x["definition"] if x["kind"] in ("caveat", "rule") else x["name"] for x in public["adds"]]
    if not ok:
        take_back(p, added)
        _step(f, "needs_person", "The change didn't hold up when queried for real, so it was taken back.",
              proposal=public, checks=checks)
        return
    data = [x for x in public["adds"] if x["kind"] in ("dimension", "metric")]
    f.status = "applied"
    f.resolution = (f"Added to {p.name}: {', '.join(x['name'] for x in data)} ({by}); checked against live data." if data
                    else f"{p.name}'s guidance for agents corrected ({by}): {len(public['adds'])} addition(s).")
    _step(f, "verified", f"Live in {p.name} ({by})" + (" and checked against live data." if checks else "."),
          proposal=public, checks=checks, added=added)
    title = (f"{p.name} can now give {', '.join(x['label'] for x in data)}" if data
             else f"{p.name}: corrected guidance on {f.message[:80]}")
    db.add(AgentNote(workspace_id=p.workspace_id, product_id=p.id, kind="capability", mode="live", importance=6,
                     confidence=0.9, status="open", title=title[:500],
                     body=(f"Added after an agent couldn't get it ({f.message[:200]}). New in {p.name}: "
                           + "; ".join(f"{x['name']} = {x['definition']}" for x in public["adds"])),
                     facts={"report": str(f.id), "added": added}))


async def process(feedback_id: Any) -> Optional[Dict[str, Any]]:
    """Take one report as far as it can go without a person."""
    async with _lock:
        async with async_session_factory() as db:
            f = await db.get(ContextFeedback, uuid.UUID(str(feedback_id)))
            if f is None or f.status != "open" or not f.entity_id.startswith("product:"):
                return None
            p = await product_of(db, f.entity_id)
            if p is None:
                _step(f, "needs_person", "The data product it names doesn't exist any more.")
                await db.commit()
                return payload(f)
            ws = await db.get(Workspace, p.workspace_id)
            stage = f.stage or "new"
            try:
                if stage == "new":
                    stage = await _triage_step(db, f, p)
                if stage == "triaged":
                    await _act(db, f, p, ws)
            except Exception as exc:  # noqa: BLE001 — the report stays open, for a person or the next pass
                logger.exception("Report loop failed on %s", f.id)
                _step(f, "needs_person", f"Couldn't work this one out automatically: {str(exc)[:200]}")
            await db.commit()
            return payload(f)


async def _triage_step(db, f: ContextFeedback, p: DataProduct) -> str:
    others = (await db.execute(select(ContextFeedback).where(
        ContextFeedback.entity_id == f.entity_id, ContextFeedback.id != f.id, ContextFeedback.status == "open",
        ContextFeedback.created_at < f.created_at))).scalars().all()
    for o in others:
        if await same_need(o.message, f.message):
            ev = dict(o.evidence or {})
            ev["also_reported"] = list(ev.get("also_reported") or []) + [{"message": f.message, "evidence": f.evidence}]
            o.evidence = ev
            f.status = "applied"
            f.resolution = "Merged into an earlier report asking for the same thing."
            _step(f, "merged", "Asks for the same thing as an earlier report; merged into it.", merged_into=str(o.id))
            return "merged"
    t = await triage(f, p)
    _step(f, "triaged", f"Read as a {t['category'].replace('_', ' ')}.", category=t["category"], triage=t)
    return "triaged"


async def _act(db, f: ContextFeedback, p: DataProduct, ws: Workspace) -> None:
    cat = (f.loop or {}).get("category")
    if cat == "product_change":
        prop = await propose(db, f, p, ws)
        if not prop.get("possible"):
            # Can't be added here: offer the product that would hold it, for a person to build with one click.
            plan = await plan_product(f, p)
            _step(f, "needs_person", (prop.get("reason") or "Nothing in this product can answer it.")
                  + (f" Kairos can build a {plan['concept']} data product for it instead." if plan else ""),
                  proposal={"adds": [], "reason": prop.get("reason"), "dropped": prop.get("dropped") or []},
                  **({"new_product": plan} if plan else {}))
        else:
            fit = await answers(f, describe(prop))
            prop["answers"] = fit
            if AUTO_APPLY == "additions" and prop["additive"] and (fit is None or fit >= ANSWERS):
                await _apply_and_prove(db, f, p, prop, "added automatically")
            else:
                partial = fit is not None and fit < ANSWERS
                # Only part of it fits here: the product that would hold all of it is the other option.
                plan = await plan_product(f, p) if partial else None
                why = ("It doesn't fully give what was asked, so a person should decide"
                       + (f": add this, or build a {plan['concept']} data product for the whole of it." if plan else ".")
                       if partial else "Waiting for approval.")
                _step(f, "proposed", why, pending=prop,
                      proposal={"adds": describe(prop), "reason": prop.get("reason"), "dropped": prop.get("dropped") or [],
                                "answers": fit}, **({"new_product": plan} if plan else {}))
    elif cat == "data_issue":
        _step(f, "needs_person", "The data itself looks wrong or missing: a pipeline or ingestion problem for whoever "
                                 "runs it. It resolves itself once the lookup returns data again.")
    elif cat == "new_product":
        plan = await plan_product(f, p)
        if plan:
            _step(f, "needs_person", f"Needs an area {p.name} doesn't cover. Kairos can build a {plan['concept']} data "
                                     f"product for it: {plan['why']}", new_product=plan)
        else:
            _step(f, "needs_person", f"Needs an area of the business {p.name} doesn't cover: a new data product.")
    elif cat == "description":
        fix = await fix_guidance(f, p)
        if not fix.get("possible"):
            _step(f, "needs_person", fix.get("reason") or f"{p.name}'s meanings need a person to correct them.")
        elif AUTO_APPLY == "additions":
            await _apply_and_prove(db, f, p, fix, "added automatically")
        else:
            _step(f, "proposed", "Waiting for approval.", pending=fix,
                  proposal={"adds": describe(fix), "reason": fix.get("reason"), "dropped": []})
    else:
        f.status = "dismissed"
        _step(f, "dismissed", "Not something a change to the data can fix.")


async def approve(feedback_id: Any) -> Optional[Dict[str, Any]]:
    async with _lock, async_session_factory() as db:
        f = await db.get(ContextFeedback, uuid.UUID(str(feedback_id)))
        if f is None or f.stage != "proposed":
            return payload(f) if f else None
        p = await product_of(db, f.entity_id)
        prop = (f.loop or {}).get("pending")
        if p is None or not prop:
            _step(f, "needs_person", "The proposal or its product is gone.")
        else:
            await _apply_and_prove(db, f, p, prop, "approved")
        await db.commit()
        return payload(f)


async def build_product(feedback_id: Any) -> Optional[Dict[str, Any]]:
    """Build the data product a report asked for (the product builder), then resolve the report. Starts it in the
    background and returns at once; the report shows "building" meanwhile."""
    async with async_session_factory() as db:
        f = await db.get(ContextFeedback, uuid.UUID(str(feedback_id)))
        plan = ((f.loop or {}).get("new_product") if f else None)
        if f is None or not plan or f.stage == "building":
            return payload(f) if f else None
        _step(f, "building", f"Building a {plan['concept']} data product.")
        await db.commit()
        out = payload(f)
    asyncio.create_task(_build(str(feedback_id), plan))
    return out


async def _build(feedback_id: str, plan: Dict[str, Any]) -> None:
    from kairos_kb.products.service import build

    async with async_session_factory() as db:
        f = await db.get(ContextFeedback, uuid.UUID(feedback_id))
        old = await product_of(db, f.entity_id)
        ws = await db.get(Workspace, old.workspace_id) if old else None
        try:
            if ws is None:
                raise ValueError("The connection behind the report is gone.")
            made = await build(db, ws, concept=plan["concept"], intent=plan["intent"], origin="report")
            f.status = "applied"
            f.resolution = f"Built a new data product, {made.name} (a draft: review it under Data products)."
            _step(f, "verified", f"Built {made.name} for this report.", built_product={"id": str(made.id), "name": made.name,
                                                                                     "slug": made.slug})
            metrics = [m["label"] or m["name"] for m in ((made.spec or {}).get("model") or {}).get("metrics") or []][:6]
            db.add(AgentNote(workspace_id=ws.id, product_id=made.id, kind="capability", mode="live", importance=6,
                             confidence=0.8, status="open", title=f"New data product: {made.name} ({', '.join(metrics)})"[:500],
                             body=f"Built after an agent couldn't get it ({f.message[:200]}).", facts={"report": feedback_id}))
        except Exception as exc:  # noqa: BLE001 — shown on the report
            logger.exception("Building a product for report %s failed", feedback_id)
            await db.rollback()
            f = await db.get(ContextFeedback, uuid.UUID(feedback_id))
            _step(f, "needs_person", f"Building {plan['concept']} didn't work: {str(exc)[:200]}", new_product=plan)
        await db.commit()


async def reject(feedback_id: Any) -> Optional[Dict[str, Any]]:
    async with _lock, async_session_factory() as db:
        f = await db.get(ContextFeedback, uuid.UUID(str(feedback_id)))
        if f is None:
            return None
        f.status = "dismissed"
        _step(f, "dismissed", "Rejected by a person.")
        await db.commit()
        return payload(f)


async def roll_back(feedback_id: Any) -> Optional[Dict[str, Any]]:
    async with _lock, async_session_factory() as db:
        f = await db.get(ContextFeedback, uuid.UUID(str(feedback_id)))
        if f is None or f.stage != "verified":
            return payload(f) if f else None
        p = await product_of(db, f.entity_id)
        added = list((f.loop or {}).get("added") or [])
        if p is not None and added:
            take_back(p, added)
            notes = (await db.execute(select(AgentNote).where(AgentNote.product_id == p.id,
                                                              AgentNote.kind == "capability"))).scalars().all()
            for n in notes:
                if (n.facts or {}).get("report") == str(f.id):
                    n.status = "withdrawn"
        f.status = "dismissed"
        f.resolution = f"Rolled back: {', '.join(added)} removed again."
        _step(f, "rolled_back", "Rolled back by a person.")
        await db.commit()
        return payload(f)


async def recheck_data(f: ContextFeedback, db) -> bool:
    """A data problem resolves itself when the lookup that came back empty now returns numbers."""
    from kairos_kb.companion.vitals import event_column, live_model, run

    p = await product_of(db, f.entity_id)
    lookups = [lk for lk in (f.evidence or {}).get("lookups") or [] if lk.get("tool") == "query" and lk.get("ok")]
    if p is None or not lookups:
        return False
    ev = await event_column(db, p)
    model = live_model(p, {"table": ev[0], "column": ev[1]} if ev else None)
    for lk in lookups:
        a = lk.get("args") or {}
        r = await run(db, model, list(a.get("metrics") or []), list(a.get("by") or []), a.get("filters") or None, "", 50)
        if any(v for v in _numbers(r.get("rows") or [])) and not any(v for v in _numbers(lk.get("rows") or [])):
            f.status = "applied"
            f.resolution = "The data is there now: the lookup that came back empty returns numbers."
            _step(f, "verified", "Resolved itself: the missing data has arrived.")
            return True
    return False


def payload(f: ContextFeedback) -> Dict[str, Any]:
    loop = f.loop or {}
    return {"id": str(f.id), "stage": f.stage or ("new" if f.entity_id.startswith("product:") else None),
            "category": loop.get("category"), "proposal": loop.get("proposal"), "checks": loop.get("checks"),
            "history": loop.get("history") or [], "question": (f.evidence or {}).get("question"),
            "also_reported": len((f.evidence or {}).get("also_reported") or []),
            "new_product": loop.get("new_product"), "built_product": loop.get("built_product")}


# ── the background pass ──────────────────────────────────────────────


async def sweep() -> int:
    """Every open product report, as far as each can go; and data problems that may have resolved themselves."""
    async with async_session_factory() as db:
        rows = (await db.execute(select(ContextFeedback.id, ContextFeedback.stage, ContextFeedback.loop).where(
            ContextFeedback.status == "open", ContextFeedback.entity_id.like("product:%"))
            .order_by(ContextFeedback.created_at))).all()
    done = 0
    for fid, stage, loop in rows:
        if (stage or "new") in LIVE_STAGES:
            await process(fid)
            done += 1
        elif stage == "needs_person" and (loop or {}).get("category") == "data_issue":
            async with _lock, async_session_factory() as db:
                f = await db.get(ContextFeedback, fid)
                if f is not None and await recheck_data(f, db):
                    done += 1
                await db.commit()
    return done


async def _loop() -> None:
    await asyncio.sleep(30)
    while True:
        try:
            n = await sweep()
            if n:
                logger.info("Report loop: worked on %d report(s)", n)
        except Exception:  # noqa: BLE001 — never stops the loop
            logger.exception("Report loop pass failed")
        await asyncio.sleep(INTERVAL_S)


def start() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())
