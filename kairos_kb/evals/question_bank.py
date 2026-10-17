"""Generate evaluation questions from what the map knows, with references taken from the same facts.

    python -m kairos_kb.evals.question_bank        # writes questions/generated.yaml

Each family asks something a real agent would, about a real entity, and its
reference is what Kairos holds about it — so a failed question means the agent
could not get to (or misread) something the map has, through that connector.
Hand-written questions (traps, business and governance) live in
questions/curated.yaml and are never overwritten.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from collections import defaultdict
from datetime import date
from typing import Any, Dict, List

import yaml
from sqlalchemy import func, select

from kairos_kb.db.engine import async_session_factory
from kairos_kb.evals.connector_eval import QUESTIONS_DIR, slug

PER_FAMILY = {"jobs": 15, "failures": 12, "dataset_types": 10, "concepts": 16, "columns": 12, "unprofiled": 8}


def _short(full: str) -> str:
    return (full or "").split(".")[-1]


def _first_line(text: Any, n: int = 220) -> str:
    line = str(text or "").strip().splitlines()[0] if str(text or "").strip() else ""
    return line if len(line) <= n else line[: n - 1] + "…"


def _case(cid: str, category: str, question: str, reference: str, must: List[List[str]]) -> Dict[str, Any]:
    return {"id": cid, "category": category, "question": question, "reference": reference.strip(),
            "must_mention": [[str(p) for p in g if p] for g in must if any(g)]}


def _ordered(tasks: List[Dict[str, Any]]) -> List[str]:
    """Task keys in dependency order (ties by name)."""
    deps = {t["task_key"]: set(t.get("depends_on") or []) for t in tasks}
    order: List[str] = []
    while deps:
        ready = sorted(k for k, d in deps.items() if not (d & set(deps)))
        if not ready:
            order += sorted(deps)
            break
        order += ready
        for k in ready:
            deps.pop(k)
    return order


async def generate() -> List[Dict[str, Any]]:
    from kairos_kb.context.cards import entity_card
    from kairos_kb.mcp_server import server as v1
    from kairos_kb.models.context import ContextDocument
    from kairos_kb.models.entity_profile import EntityProfile
    from kairos_kb.models.job import Job
    from kairos_kb.models.knowledge import KnowledgeBinding, KnowledgeConcept
    from kairos_kb.models.table import Table

    cases: List[Dict[str, Any]] = []
    async with async_session_factory() as db:
        # ── Profiled tables: meaning, writers, sources, keys, impact, columns ──
        profiled = [e for (e,) in (await db.execute(
            select(EntityProfile.entity_id).where(EntityProfile.kind == "table").order_by(EntityProfile.entity_id)
        )).all()]
        column_cases: List[Dict[str, Any]] = []
        for eid in profiled:
            card = await entity_card(db, eid)
            if not card:
                continue
            full, short = card.get("full_name") or card["name"], _short(card.get("full_name") or card["name"])
            shape, flow = card.get("shape") or {}, card.get("flow") or {}
            trust = (card.get("trust") or {}).get("level")
            cases.append(_case(
                f"table-meaning-{slug(short)}", "table-meaning",
                f"What does the table {short} hold, and what does one row represent?",
                f"{full}: {_first_line(card.get('summary'), 400)} Grain: {shape.get('grain') or 'not stated'}. "
                f"Trust level: {trust}.",
                [[short]]))
            writers = [w for w in flow.get("produced_by") or [] if w["entity_id"].startswith(("task:", "job:"))]
            if writers:
                names = [w.get("name") or w["entity_id"].split(":")[-1] for w in writers]
                cases.append(_case(
                    f"table-writer-{slug(short)}", "lineage",
                    f"Which pipeline and which task write {full}?",
                    f"Written by: {', '.join(dict.fromkeys(names))} (evidence: "
                    f"{', '.join(dict.fromkeys(w.get('evidence', '')[:40] for w in writers))}).",
                    [names]))
            ups = [u["entity_id"].split(":")[-1] for u in flow.get("upstream_tables") or []]
            if ups:
                cases.append(_case(
                    f"table-sources-{slug(short)}", "lineage",
                    f"What is {short} built from? Name the upstream tables.",
                    f"Upstream of {full}: {', '.join(ups)}.", [[_short(u) for u in ups]]))
            downs = [d["entity_id"].split(":")[-1] for d in flow.get("downstream_tables") or []]
            if downs:
                cases.append(_case(
                    f"table-impact-{slug(short)}", "impact",
                    f"If the data in {short} is wrong, which downstream tables would be affected?",
                    f"Downstream of {full}: {', '.join(downs)}.", [[_short(d) for d in downs]]))
            keys = shape.get("grain_key") or []
            if keys:
                unique = shape.get("grain_key_unique")
                cases.append(_case(
                    f"table-key-{slug(short)}", "grain-and-keys",
                    f"I want to deduplicate {short}. Which columns uniquely identify a row, and has that been checked?",
                    f"Grain key {', '.join(keys)}; {shape.get('grain') or ''} "
                    f"Uniqueness check: {'holds' if unique else 'does NOT hold' if unique is False else 'not run'}.",
                    [keys]))
            for col in (shape.get("columns") or []):
                if col.get("meaning") and len(column_cases) < PER_FAMILY["columns"] * 3:
                    column_cases.append(_case(
                        f"column-{slug(short)}-{slug(col['name'])}", "columns",
                        f"In {short}, what does the column {col['name']} mean, and what is its data type?",
                        f"{full}.{col['name']} ({col.get('type')}): {_first_line(col['meaning'], 300)}",
                        [[col["name"]]]))
        # Spread column questions across tables.
        by_table = defaultdict(list)
        for c in column_cases:
            by_table[c["id"].split("-")[1]].append(c)
        picked = []
        while len(picked) < PER_FAMILY["columns"] and any(by_table.values()):
            for k in list(by_table):
                if by_table[k] and len(picked) < PER_FAMILY["columns"]:
                    picked.append(by_table[k].pop(0))
        cases += picked

        # ── Pipelines: structure ──
        jobs = (await db.execute(select(Job).order_by(Job.name))).scalars().all()
        n = 0
        for j in jobs:
            if n >= PER_FAMILY["jobs"]:
                break
            card = await entity_card(db, j.entity_id)
            tasks = (card or {}).get("tasks") or []
            if len(tasks) < 3 or not any(t.get("depends_on") for t in tasks):
                continue
            order = _ordered(tasks)
            cases.append(_case(
                f"pipeline-steps-{slug(j.name)}-{j.source_native_id}", "pipelines",
                f"What steps does the pipeline '{j.name}' run, and in what order?",
                f"{j.name} ({j.source_native_id}) runs {len(order)} tasks in dependency order: {' → '.join(order)}.",
                [[order[0]], [order[-1]]]))
            n += 1

    # ── Pipelines: last failure (facts as recorded at the last sync) ──
    incidents = (await v1._raw(v1.list_incidents)("", 100)).get("incidents", []) if hasattr(v1, "_raw") else \
        (await v1.list_incidents.__wrapped__("", 100)).get("incidents", [])
    seen = set()
    for inc in incidents:
        if inc["pipeline"] in seen or len(seen) >= PER_FAMILY["failures"]:
            continue
        seen.add(inc["pipeline"])
        failed = inc.get("failed_tasks") or []
        first = failed[0] if failed else {}
        error = _first_line(first.get("error") or inc.get("status_message") or "not recorded", 200)
        cases.append(_case(
            f"pipeline-failure-{slug(inc['pipeline'])}", "operations",
            f"Did the pipeline '{inc['pipeline']}' fail recently? Which task failed, and with what error?",
            f"Most recent failed run started {inc.get('run_started_at')}; result {inc.get('result')}"
            + (f"; failed task {first.get('task_key')}" if first else "") + f"; error: {error}"
            + (" (later attempt succeeded)" if first.get("later_attempt_succeeded") else "") + ".",
            [[first.get("task_key")] if first else [inc["pipeline"]]]))

    async with async_session_factory() as db:
        # ── Industry dataset types found in the warehouse ──
        rows = (await db.execute(
            select(KnowledgeBinding.concept_id, KnowledgeConcept.title, KnowledgeBinding.entity_id, KnowledgeBinding.confidence)
            .join(KnowledgeConcept, KnowledgeConcept.concept_id == KnowledgeBinding.concept_id)
            .where(KnowledgeBinding.predicate == "instance_of", KnowledgeBinding.status != "rejected",
                   KnowledgeBinding.confidence >= 0.7)
            .order_by(KnowledgeBinding.confidence.desc())
        )).all()
        grouped: Dict[str, Dict[str, Any]] = {}
        for cid, title, eid, conf in rows:
            grouped.setdefault(cid, {"title": title, "tables": []})["tables"].append(eid.split(":")[-1])
        for cid, g in list(grouped.items())[: PER_FAMILY["dataset_types"]]:
            cases.append(_case(
                f"dataset-type-{slug(cid.rsplit('/', 1)[-1])}", "industry-in-warehouse",
                f"Which tables in our warehouse contain {g['title']} data?",
                f"Kairos binds these tables to {g['title']} ({cid}), as proposals: {', '.join(g['tables'][:10])}.",
                [[_short(t) for t in g["tables"]]]))

        # ── Identifier columns ──
        for cid in ("/identifiers/provider/npi", "/identifiers/product/ndc", "/identifiers/provider/dea-number",
                    "/identifiers/provider/hin", "/identifiers/provider/veeva-vid",
                    "/identifiers/provider/ims-prescriber-id", "/identifiers/payer/plan-id"):
            concept = (await db.execute(select(KnowledgeConcept).where(KnowledgeConcept.concept_id == cid))).scalars().first()
            cols = [e for (e,) in (await db.execute(select(KnowledgeBinding.entity_id).where(
                KnowledgeBinding.concept_id == cid, KnowledgeBinding.predicate == "identified_by",
                KnowledgeBinding.status != "rejected"))).all()]
            if not concept or not cols:
                continue
            names = sorted({c.rsplit(".", 1)[-1] for c in cols})
            fmt = (concept.fields or {}).get("identifier_format")
            cases.append(_case(
                f"identifier-columns-{slug(cid.rsplit('/', 1)[-1])}", "industry-in-warehouse",
                f"Which columns in our warehouse hold {concept.title} values, and what format should they have?",
                f"{len(cols)} columns are bound to {concept.title}, named {', '.join(names)}. Format: {fmt or 'see concept'}.",
                [names]))

        # ── Industry concepts on their own ──
        concepts = (await db.execute(select(KnowledgeConcept).where(
            KnowledgeConcept.type.in_(["Metric", "Identifier", "Dataset Type", "Program", "Regulation", "Pricing Concept"])
        ).order_by(KnowledgeConcept.type, KnowledgeConcept.concept_id))).scalars().all()
        by_type = defaultdict(list)
        for c in concepts:
            by_type[c.type].append(c)
        picked_concepts = []
        while len(picked_concepts) < PER_FAMILY["concepts"] and any(by_type.values()):
            for t in list(by_type):
                if by_type[t] and len(picked_concepts) < PER_FAMILY["concepts"]:
                    # Every third concept of a type, for spread across the pack.
                    picked_concepts.append(by_type[t].pop(0))
                    del by_type[t][:2]
        for c in picked_concepts:
            f = c.fields or {}
            extra = "; ".join(f"{k}: {f[k]}" for k in ("grain", "identifier_format", "measures", "phi_status") if f.get(k))
            pitfalls = _first_line((c.sections or {}).get("Pitfalls"), 200)
            cases.append(_case(
                f"concept-{slug(c.concept_id.rsplit('/', 1)[-1])}", "industry-knowledge",
                f"In US pharma commercial data, what is {c.title}, and what should I watch out for when using it?",
                f"{c.title} ({c.type}): {c.description or ''} {extra}. {('Pitfall: ' + pitfalls) if pitfalls else ''}",
                [[c.title.split(" (")[0]]]))

        # ── Tables Kairos only synced: does the agent say so? ──
        unprofiled = (await db.execute(
            select(Table.full_name, func.count())
            .join(ContextDocument, ContextDocument.entity_id == Table.entity_id)
            .where(Table.entity_id.not_in(select(EntityProfile.entity_id)))
            .group_by(Table.full_name).order_by(Table.full_name)
        )).all()
        step = max(1, len(unprofiled) // PER_FAMILY["unprofiled"])
        for full, _ in unprofiled[::step][: PER_FAMILY["unprofiled"]]:
            cases.append(_case(
                f"unprofiled-{slug(full)}", "trust",
                f"What is in the table {full}, and how far can I rely on what you know about it?",
                f"{full} is only synced (platform metadata: names, types, comments); Kairos has not profiled or "
                f"verified it, so meaning, grain and quality are unknown. A good answer describes its columns and "
                f"says plainly that it is unverified.",
                [[_short(full)], ["synced", "not profiled", "unverified", "not been profiled", "not verified", "metadata only"]]))
    return cases


async def main() -> int:
    logging.disable(logging.WARNING)
    cases = await generate()
    QUESTIONS_DIR.mkdir(exist_ok=True)
    out = QUESTIONS_DIR / "generated.yaml"
    header = (f"# Generated {date.today().isoformat()} by `python -m kairos_kb.evals.question_bank` from the map.\n"
              "# References are what Kairos holds about each entity. Regenerating replaces this file;\n"
              "# put hand-written questions in curated.yaml.\n")
    out.write_text(header + yaml.safe_dump({"cases": cases}, sort_keys=False, allow_unicode=True, width=110),
                   encoding="utf-8")
    counts = defaultdict(int)
    for c in cases:
        counts[c["category"]] += 1
    print(f"{len(cases)} questions → {out}")
    for k, v in sorted(counts.items()):
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
