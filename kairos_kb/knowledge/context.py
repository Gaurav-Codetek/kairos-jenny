"""What the industry knowledge says about one warehouse table.

A table's card gains an "industry" section when the table is bound to a
dataset type: what kind of data it is, the grain and measures such data
usually has, its known pitfalls, which of its columns hold industry
identifiers, and which governance and data-quality rules apply to it.

Proposed bindings are shown with their confidence and marked as proposed —
an agent should treat them as Kairos's best reading, not as settled fact.
Rejected bindings are never shown.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.models.knowledge import KnowledgeBinding, KnowledgeConcept

RULE_CONCEPTS = ("/_meta/data-quality-rules", "/_meta/data-governance-policy")
_RULE = re.compile(r"^\s*[*-]\s+\*\*(.+?)\*\*:?\s*(.*)$")
SECTION_CHARS = 900


def parse_rules(concept: KnowledgeConcept) -> List[Dict[str, str]]:
    """Each "* **Label** text" bullet of a rule concept's Definition."""
    rules = []
    for line in ((concept.sections or {}).get("Definition") or "").splitlines():
        m = _RULE.match(line)
        if m:
            label = m.group(1).strip().rstrip(":.")
            rules.append({"rule": label, "text": f"{label}: {m.group(2).strip()}".strip(), "source": concept.concept_id})
    return rules


def _words(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) >= 3}


def topics_for(dataset_types: List[KnowledgeConcept], identifier_ids: List[str], columns: List[str]) -> set:
    """Words that describe what a table holds, for matching rules to it."""
    topics = set()
    for c in dataset_types:
        f = c.fields or {}
        topics |= _words(c.concept_id.rsplit("/", 1)[-1]) | _words(c.title) | _words(" ".join(map(str, c.tags or [])))
        topics |= _words(str(f.get("dataset_category") or "")) | _words(str(f.get("projection") or ""))
        phi = str(f.get("phi_status") or "").lower()
        if "phi" in phi or "de-identified" in phi or "patient" in phi:
            topics |= {"patient", "phi", "reidentify"}
        if "prescriber" in phi or "pdrp" in phi:
            topics |= {"pdrp", "prescriber"}
        if "licen" in phi or "licen" in str(f).lower():
            topics.add("licence")
        if "projected" in str(f.get("projection") or "").lower() or f.get("measures"):
            topics.add("measure")
    for cid in identifier_ids:
        topics |= _words(cid.rsplit("/", 1)[-1])
    if any(re.search(r"(^|_)zip", c, re.I) for c in columns):
        topics.add("zip")
    return topics


# What each rule is about, beyond the words of its label.
_RULE_TOPICS = {
    "never re-identify": {"patient", "phi"},
    "respect licence scope": {"iqvia", "komodo", "symphony", "licence"},
    "ama pdrp": {"pdrp", "prescriber"},
    "do not add across measure families": {"867", "ddd", "xponent", "measure", "projected"},
    "small-cell suppression": {"patient", "claims"},
    "pharmacy claims": {"pharmacy", "apld", "claims"},
    "medical claims": {"medical"},
    "wide weekly files": {"ddd", "weekly"},
}


def applicable_rules(rules: List[Dict[str, str]], topics: set) -> List[Dict[str, str]]:
    out = []
    for r in rules:
        about = _RULE_TOPICS.get(r["rule"].lower()) or (_words(r["rule"]) - {"off", "label", "opdp"})
        if r["rule"].lower().startswith("off-label"):
            continue  # about promotional content, not data
        if about & topics:
            out.append(r)
    return out


def concept_brief(c: KnowledgeConcept, *, full: bool = False) -> Dict[str, Any]:
    f = c.fields or {}
    s = c.sections or {}
    cut = (lambda t: t) if full else (lambda t: t if not t or len(t) <= SECTION_CHARS else t[:SECTION_CHARS].rstrip() + "…")
    out: Dict[str, Any] = {"concept_id": c.concept_id, "type": c.type, "title": c.title, "description": c.description}
    for key in ("dataset_category", "grain", "primary_key", "join_keys", "measures", "phi_status",
                "projection", "refresh_cadence", "identifier_format", "issuer"):
        if f.get(key):
            out[key] = f[key]
    for name, key in (("Pitfalls", "pitfalls"), ("Typical uses", "typical_uses")):
        if s.get(name):
            out[key] = cut(s[name])
    return out


async def table_knowledge(db: AsyncSession, entity_id: str, columns: List[str]) -> Optional[Dict[str, Any]]:
    """The "industry" section of a table's card, or None when the pack says nothing about it."""
    rest = entity_id.split(":", 1)[1] if ":" in entity_id else entity_id
    bindings = (await db.execute(select(KnowledgeBinding).where(
        KnowledgeBinding.status != "rejected",
        (KnowledgeBinding.entity_id == entity_id) | KnowledgeBinding.entity_id.like(f"column:{rest}.%"),
    ))).scalars().all()
    bindings = [b for b in bindings if b.entity_id == entity_id or "." not in b.entity_id[len(f"column:{rest}."):]]
    if not bindings:
        return None
    ids = {b.concept_id for b in bindings} | set(RULE_CONCEPTS)
    concepts = {c.concept_id: c for c in (await db.execute(
        select(KnowledgeConcept).where(KnowledgeConcept.concept_id.in_(ids))
    )).scalars()}

    types = sorted((b for b in bindings if b.predicate == "instance_of" and b.concept_id in concepts),
                   key=lambda b: (b.status != "confirmed", -b.confidence))
    idents = [b for b in bindings if b.predicate == "identified_by" and b.concept_id in concepts]

    dataset_types = [{**concept_brief(concepts[b.concept_id]), "status": b.status,
                      "confidence": b.confidence, "why": _why(b.evidence)} for b in types[:2]]
    identifier_columns = [{"column": b.entity_id.rsplit(".", 1)[-1], "identifier": concepts[b.concept_id].title,
                           "concept_id": b.concept_id, "status": b.status,
                           "format": (concepts[b.concept_id].fields or {}).get("identifier_format")}
                          for b in sorted(idents, key=lambda b: b.entity_id)]
    rules: List[Dict[str, str]] = []
    for rid in RULE_CONCEPTS:
        if rid in concepts:
            rules += parse_rules(concepts[rid])
    topics = topics_for([concepts[b.concept_id] for b in types[:2]], [b.concept_id for b in idents], columns)
    out: Dict[str, Any] = {
        "dataset_type": dataset_types,
        "identifier_columns": identifier_columns,
        "rules": [r["text"] for r in applicable_rules(rules, topics)],
        "note": ("From Kairos's industry knowledge. 'proposed' means Kairos matched this table to the "
                 "dataset type from its columns and name and no person has confirmed it yet; the "
                 "expected grain and pitfalls describe such data in general, not this table — this "
                 "table's own grain and checks are under trust and shape. get_concept(concept_id) "
                 "gives the full concept."),
    }
    return out


def _why(evidence: Optional[Dict[str, Any]]) -> Optional[str]:
    if not evidence:
        return None
    parts = []
    if evidence.get("matched_keys"):
        parts.append("key columns " + ", ".join(evidence["matched_keys"][:6]))
    if evidence.get("matched_patterns"):
        parts.append("column patterns " + ", ".join(evidence["matched_patterns"][:4]))
    if evidence.get("name_hints"):
        parts.append("name mentions " + ", ".join(evidence["name_hints"]))
    if evidence.get("meaning_similarity") is not None:
        parts.append(f"meaning similarity {evidence['meaning_similarity']}")
    return "; ".join(parts) or None
