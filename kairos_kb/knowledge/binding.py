"""Bind warehouse entities to industry concepts — as proposals, with evidence.

Two kinds of binding:

  instance_of     a table is an instance of a dataset type ("silver.fct_ics_867
                  is a 3PL 867 feed"). Scored from the dataset type's signature —
                  its key and typical fields, prefix patterns such as CUST_*, and
                  name hints (867, DDD, Xponent, …) — against the table's columns
                  and name, with meaning similarity as supporting evidence.
  identified_by   a column holds an identifier (NPI, NDC, DEA, HIN, Veeva VID, …),
                  recognised from its name.

Every binding records what it was based on and how confident Kairos is, and is
"proposed" until a person confirms or rejects it. A rejected binding is never
proposed again; a confirmed one is never overwritten.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.db.engine import async_session_factory
from kairos_kb.models.column import Column
from kairos_kb.models.context import ContextDocument
from kairos_kb.models.knowledge import KnowledgeBinding, KnowledgeConcept
from kairos_kb.models.table import Table

PROPOSE_AT = 0.45          # dataset-type score needed to propose a binding
SECOND_WITHIN = 0.08       # also propose the runner-up when it is this close

# Column-name patterns for identifiers. A concept can carry its own in a
# `column_patterns` frontmatter key, which takes precedence over these defaults.
IDENTIFIER_PATTERNS: Dict[str, str] = {
    "/identifiers/product/ndc": r"(^|_)ndc(_?(code|11|10|9|id|nbr|num|norm))?$",
    # _vod: Veeva CRM's own field suffix (NPI_VOD).
    "/identifiers/provider/npi": r"(^|_)npi(_?(id|num|nbr|number|no|vod))?$",
    "/identifiers/provider/dea-number": r"(^|_)dea(_?(num|nbr|number|no|id))?$",
    "/identifiers/provider/hin": r"(^|_)hin(_?(num|nbr|number|no|id))?$",
    "/identifiers/provider/veeva-vid": r"(^|_)(org|sys|hco|hcp|acct|account|parent)?_?vid$",
    "/identifiers/provider/ama-me-number": r"(^|_)me_?(num|nbr|number|no)$|ama_?me",
    "/identifiers/provider/ims-prescriber-id": r"ims_?prescriber_?id",
    "/identifiers/provider/onekey-id": r"onekey",
    "/identifiers/provider/ccn": r"(^|_)ccn$|cms_?certification",
    "/identifiers/provider/ncpdp-provider-id": r"ncpdp",
    "/identifiers/provider/340b-id": r"340b_?(id|entity)",
    "/identifiers/provider/ddd-outlet": r"outlet_?(id|number|nbr|num)",
    "/identifiers/provider/nucc-taxonomy": r"taxonomy(_?code)?$",
    "/identifiers/payer/bin-pcn-group": r"(^|_)(bin|pcn)(_|$)|rx_?group",
    "/identifiers/payer/plan-id": r"(^|_)(payer_?)?plan_?id$",
    "/identifiers/payer/cms-contract-pbp": r"(^|_)pbp(_|$)|contract_?pbp",
    "/identifiers/product/rxnorm-rxcui": r"rxcui|rxnorm",
    "/identifiers/product/gpi": r"(^|_)gpi(_|$)",
    "/identifiers/product/gcn": r"(^|_)gcn(_|$)",
    "/identifiers/product/hcpcs": r"hcpcs|(^|_)j_?code",
    "/identifiers/product/atc": r"(^|_)atc(_|$)",
    "/identifiers/product/usc": r"(^|_)usc(_|$)",
    "/identifiers/product/cmf": r"(^|_)cmf(_|$)",
    "/identifiers/patient/patient-token": r"patient_?token|(^|_)token_?id$",
}

_FIELD = re.compile(r"`([^`]+)`")
_GENERIC_FIELDS = {"id", "name", "date", "type", "code", "source", "amount", "status", "description",
                   "data_date", "week", "month", "year", "quantity"}
# Words in a dataset type's ID or title that make good name hints.
_HINT_STOP = {"data", "dataset", "file", "files", "feed", "the", "and", "for", "of", "by", "to", "a", "an",
              "sales", "claims", "reference", "provider", "patient", "level", "us", "type", "via", "vs", "or"}


def signature(concept: KnowledgeConcept) -> Dict[str, Any]:
    """What a dataset type's tables tend to look like: exact fields, prefix patterns, key fields, name hints."""
    fields = concept.fields or {}
    exact: Set[str] = set()
    prefixes: Set[str] = set()
    keys: Set[str] = set()

    def add(token: str, key: bool = False) -> None:
        for part in re.split(r"[,/]| or ", token):
            part = part.strip().strip("`").split(" (")[0].split("(")[0].strip()
            if not part or " " in part or part.startswith("<"):
                continue
            low = part.lower()
            if low.endswith("_*") or low.endswith("*"):
                prefixes.add(low.rstrip("*"))
            elif low not in _GENERIC_FIELDS and len(low) > 2:
                exact.add(low)
                if key:
                    keys.add(low)

    for k in fields.get("primary_key") or []:
        add(str(k), key=True)
    for k in fields.get("join_keys") or []:
        add(str(k), key=True)
    schema = (concept.sections or {}).get("Schema") or ""
    for row in schema.splitlines():
        if row.startswith("|") and "`" in row:
            first_cell = row.split("|")[1]
            for f in _FIELD.findall(first_cell):
                add(f)
    words = re.split(r"[^a-z0-9]+", (concept.concept_id.rsplit("/", 1)[-1] + " " + concept.title).lower())
    hints = {w for w in words if w and w not in _HINT_STOP and (w.isdigit() and len(w) == 3 or len(w) >= 3)}
    # A hint that is part of a field name ("npi", "hcp") says the table mentions the
    # identifier, not that it is this dataset — every table with an NPI column would match.
    hints = {h for h in hints if not any(h in f for f in exact | prefixes)}
    return {"exact": exact, "prefixes": prefixes, "keys": keys, "hints": hints}


_ANY_IDENTIFIER = re.compile("|".join(f"(?:{p})" for p in IDENTIFIER_PATTERNS.values()), re.I)


def identifier_like(column: str) -> bool:
    """Columns any table may carry to join elsewhere: they show a link to a dataset, not membership."""
    return bool(_ANY_IDENTIFIER.search(column) or re.search(r"(^|_)(id|key|code)$|[a-z]id$", column, re.I))


def score_table(sig: Dict[str, Any], table_name: str, columns: List[str]) -> Tuple[float, Dict[str, Any]]:
    """How well a table matches a dataset type's signature, 0..1, with the matches as evidence.

    Identifier columns are weak evidence on their own, so a table needs either two
    distinctive matches (fields that are not identifiers, or column patterns such as
    CUST_*), or one with a name hint (867, DDD, Xponent…). Otherwise it scores 0.
    """
    cols = {c.lower() for c in columns}
    if not cols:
        return 0.0, {}
    exact_hits = sorted(sig["exact"] & cols)
    key_hits = sorted(sig["keys"] & cols)
    prefix_hits = sorted(p for p in sig["prefixes"] if any(c.startswith(p) for c in cols))
    name = table_name.lower()
    name_hits = sorted(h for h in sig["hints"] if re.search(rf"(^|[^a-z0-9]){re.escape(h)}([^a-z0-9]|$)", name))
    signature_size = len(sig["exact"]) + len(sig["prefixes"])
    if signature_size == 0:
        return 0.0, {}
    distinctive = len([f for f in exact_hits if not identifier_like(f)]) + len(prefix_hits)
    if not (distinctive >= 2 or (distinctive >= 1 and name_hits)):
        return 0.0, {}
    coverage = (len(exact_hits) + len(prefix_hits)) / signature_size
    key_cover = len(key_hits) / len(sig["keys"]) if sig["keys"] else 0.0
    score = 0.55 * coverage + 0.25 * key_cover + (0.25 if name_hits else 0.0)
    evidence = {"matched_fields": exact_hits[:12], "matched_patterns": [p + "*" for p in prefix_hits],
                "matched_keys": key_hits, "name_hints": name_hits,
                "distinctive_matches": distinctive,
                "coverage": round(coverage, 2), "key_coverage": round(key_cover, 2)}
    return min(1.0, score), evidence


def identifier_patterns(concepts: List[KnowledgeConcept]) -> Dict[str, re.Pattern]:
    out = {}
    for c in concepts:
        if c.type not in ("Identifier", "Code System", "Code"):
            continue
        pattern = (c.fields or {}).get("column_patterns") or IDENTIFIER_PATTERNS.get(c.concept_id)
        if pattern:
            if isinstance(pattern, list):
                pattern = "|".join(f"(?:{p})" for p in pattern)
            out[c.concept_id] = re.compile(pattern, re.I)
    return out


# Columns about an identifier rather than holding one: counts and distinct counts
# (UNIQ_DRUGS_WITH_NPI), descriptions and names (USC_DESCRIPTION), flags.
_NOT_AN_IDENTIFIER = re.compile(
    r"^(uniq|unique|distinct|cnt|count|num_of|n|total|sum|avg|pct|share)_|_with_|"
    r"_(count|cnt|desc|description|name|label|flag|ind|pct)$",
    re.I,
)


def identify_columns(columns: List[str], patterns: Dict[str, re.Pattern]) -> List[Tuple[str, str]]:
    """(column, identifier concept) pairs, from column names."""
    hits = []
    for col in columns:
        if _NOT_AN_IDENTIFIER.search(col):
            continue
        for concept_id, rx in patterns.items():
            if rx.search(col):
                hits.append((col, concept_id))
                break
    return hits


async def _upsert(db: AsyncSession, workspace_id, entity_id: str, concept_id: str, predicate: str,
                  confidence: float, evidence: Dict[str, Any]) -> bool:
    row = (await db.execute(select(KnowledgeBinding).where(
        KnowledgeBinding.entity_id == entity_id, KnowledgeBinding.concept_id == concept_id,
        KnowledgeBinding.predicate == predicate,
    ))).scalars().first()
    if row is not None and row.status in ("confirmed", "rejected"):
        return False  # a person decided; Kairos does not overrule them
    if row is None:
        row = KnowledgeBinding(workspace_id=workspace_id, entity_id=entity_id, concept_id=concept_id,
                               predicate=predicate, method="auto", status="proposed")
        db.add(row)
    row.confidence = round(confidence, 3)
    row.evidence = evidence
    return True


async def classify_workspace(workspace_id, pack_id=None) -> Dict[str, int]:
    """Propose dataset types for every table and identifiers for every column in a workspace."""
    async with async_session_factory() as db:
        q = select(KnowledgeConcept)
        if pack_id:
            q = q.where(KnowledgeConcept.pack_id == pack_id)
        concepts = list((await db.execute(q)).scalars())
        dataset_types = [c for c in concepts if c.type == "Dataset Type"]
        sigs = {c.concept_id: signature(c) for c in dataset_types}
        patterns = identifier_patterns(concepts)
        tables = (await db.execute(select(Table).where(Table.workspace_id == workspace_id))).scalars().all()
        counts = {"tables": len(tables), "dataset_types_proposed": 0, "identifier_columns_proposed": 0,
                  "withdrawn": 0}
        kept: Set[Tuple[str, str, str]] = set()

        for t in tables:
            columns = [n for (n,) in (await db.execute(select(Column.name).where(Column.table_id == t.id))).all()]
            scored = []
            for cid, sig in sigs.items():
                s, ev = score_table(sig, t.full_name, columns)
                if s > 0:
                    scored.append((s, cid, ev))
            # Meaning similarity between the table's document and each candidate type.
            doc = (await db.execute(select(ContextDocument).where(ContextDocument.entity_id == t.entity_id))).scalars().first()
            if doc is not None and doc.embedding is not None and scored:
                top_ids = [cid for _, cid, _ in sorted(scored, reverse=True)[:8]]
                sims = dict((await db.execute(
                    select(KnowledgeConcept.concept_id, 1 - KnowledgeConcept.embedding.cosine_distance(doc.embedding))
                    .where(KnowledgeConcept.concept_id.in_(top_ids))
                )).all())
                scored = [(min(1.0, s + 0.25 * max(0.0, float(sims.get(cid, 0)) - 0.3)), cid,
                           {**ev, "meaning_similarity": round(float(sims.get(cid, 0)), 2)}) for s, cid, ev in scored]
            scored.sort(reverse=True)
            if scored and scored[0][0] >= PROPOSE_AT:
                chosen = [scored[0]] + [x for x in scored[1:2] if scored[0][0] - x[0] <= SECOND_WITHIN and x[0] >= PROPOSE_AT]
                for s, cid, ev in chosen:
                    kept.add((t.entity_id, cid, "instance_of"))
                    if await _upsert(db, workspace_id, t.entity_id, cid, "instance_of", s, ev):
                        counts["dataset_types_proposed"] += 1

            for col, cid in identify_columns(columns, patterns):
                col_entity = f"column:{t.entity_id.split(':', 1)[1]}.{col}"
                kept.add((col_entity, cid, "identified_by"))
                if await _upsert(db, workspace_id, col_entity, cid, "identified_by", 0.8,
                                 {"column_name": col, "rule": "column name pattern"}):
                    counts["identifier_columns_proposed"] += 1
        # Kairos's own earlier proposals that no longer hold are withdrawn; a person's decisions stay.
        stale = [b.id for b in (await db.execute(select(KnowledgeBinding).where(
            KnowledgeBinding.workspace_id == workspace_id, KnowledgeBinding.status == "proposed",
            KnowledgeBinding.method == "auto",
        ))).scalars() if (b.entity_id, b.concept_id, b.predicate) not in kept]
        if stale:
            await db.execute(delete(KnowledgeBinding).where(KnowledgeBinding.id.in_(stale)))
        counts["withdrawn"] = len(stale)
        await db.commit()
    return counts


async def review_binding(binding_id, status: str, reviewer: str, note: Optional[str] = None) -> Optional[KnowledgeBinding]:
    if status not in ("confirmed", "rejected", "proposed"):
        raise ValueError("status must be confirmed, rejected or proposed")
    async with async_session_factory() as db:
        row = await db.get(KnowledgeBinding, binding_id)
        if row is None:
            return None
        row.status = status
        row.method = "person" if status != "proposed" else row.method
        row.reviewed_by, row.reviewed_at, row.note = reviewer, datetime.now(timezone.utc), note
        await db.commit()
        return row
