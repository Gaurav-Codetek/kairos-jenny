"""Load an Open Knowledge Format (OKF) bundle as an industry knowledge pack.

An OKF bundle is a folder of Markdown files, one concept per file, each with
YAML frontmatter (type, title, description, tags, sources, and producer keys
such as grain or identifier_format) and a body of "# Heading" sections. The
concept ID is the file path without ".md". index.md and log.md files are
navigation, not concepts.

Folders named in `exclude` are skipped — a pack holds industry knowledge only;
anything about one client's warehouse belongs to that client, not the pack.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml
from sqlalchemy import delete, select, text as sql_text

from kairos_kb.db.engine import async_session_factory
from kairos_kb.models.knowledge import KnowledgeConcept, KnowledgePack, KnowledgeRelation

logger = logging.getLogger(__name__)

STANDARD_KEYS = {"type", "title", "description", "tags", "sources", "relations", "generated"}
_HEADING = re.compile(r"^# (.+?)\s*$", re.M)
_FOOTNOTE = re.compile(r"\[\^[^\]]+\]")


def concept_id_for(root: Path, path: Path) -> str:
    return "/" + path.relative_to(root).with_suffix("").as_posix()


def normalise_target(target: str) -> str:
    """A relation target ('/actors/x.md') as a concept ID ('/actors/x')."""
    t = (target or "").strip()
    if not t.startswith("/"):
        t = "/" + t
    return t[:-3] if t.endswith(".md") else t


def parse_concept(text: str) -> Optional[Tuple[Dict[str, Any], Dict[str, str]]]:
    """(frontmatter, sections) from one concept file, or None if it has no frontmatter."""
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        front = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(front, dict) or not front.get("type"):
        return None
    body = parts[2]
    sections: Dict[str, str] = {}
    matches = list(_HEADING.finditer(body))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        content = body[m.end():end].strip()
        # Footnote definitions ([^id]: …) belong to the sources, not the text.
        content = "\n".join(l for l in content.splitlines() if not l.startswith("[^"))
        sections[m.group(1).strip()] = _FOOTNOTE.sub("", content).strip()
    return front, sections


def search_text(concept: Dict[str, Any]) -> str:
    """What a concept is searched and embedded by."""
    fields = concept.get("fields") or {}
    parts = [concept["title"], concept.get("description") or "", concept["type"],
             " ".join(concept.get("tags") or [])]
    for key in ("grain", "measures", "identifier_format", "dataset_category", "phi_status"):
        if fields.get(key):
            parts.append(f"{key}: {fields[key]}")
    for key in ("primary_key", "join_keys"):
        if fields.get(key):
            parts.append(f"{key}: {', '.join(map(str, fields[key]))}")
    sections = concept.get("sections") or {}
    for name in ("Definition", "Grain & keys", "Schema", "Typical uses", "Pitfalls"):
        if sections.get(name):
            parts.append(sections[name])
    return "\n".join(p for p in parts if p)[:12000]


def read_bundle(root: Path, exclude: Iterable[str] = ()) -> Tuple[List[Dict[str, Any]], List[Tuple[str, str, str]], Dict[str, Any]]:
    """Concepts, relations (source, predicate, target) and bundle metadata from a folder."""
    excluded = {e.strip("/").lower() for e in exclude}
    concepts, relations = [], []
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root)
        if rel.parts and rel.parts[0].lower() in excluded:
            continue
        if path.name in ("index.md", "log.md"):
            continue
        parsed = parse_concept(path.read_text(encoding="utf-8"))
        if not parsed:
            continue
        front, sections = parsed
        cid = concept_id_for(root, path)
        concept = {
            "concept_id": cid,
            "type": str(front.get("type")),
            "title": str(front.get("title") or path.stem),
            "description": front.get("description"),
            "tags": [str(t) for t in front.get("tags") or []],
            "fields": {k: v for k, v in front.items() if k not in STANDARD_KEYS} or None,
            "sections": sections or None,
            "sources": front.get("sources"),
        }
        digest_src = yaml.safe_dump({k: concept[k] for k in ("type", "title", "description", "tags", "fields", "sections")},
                                    sort_keys=True, allow_unicode=True)
        concept["content_hash"] = hashlib.sha256(digest_src.encode("utf-8")).hexdigest()
        concepts.append(concept)
        for r in front.get("relations") or []:
            if isinstance(r, dict) and r.get("predicate") and r.get("target"):
                relations.append((cid, str(r["predicate"]), normalise_target(str(r["target"]))))
    meta: Dict[str, Any] = {}
    index = root / "index.md"
    if index.exists():
        text = index.read_text(encoding="utf-8")
        m = re.search(r"okf_version:\s*\"?([\w.]+)", text)
        meta["okf_version"] = m.group(1) if m else None
        t = re.search(r"^# (.+)$", text, re.M)
        meta["title"] = t.group(1).strip() if t else None
    version = hashlib.sha256("".join(sorted(c["content_hash"] for c in concepts)).encode()).hexdigest()[:16]
    meta["version"] = version
    return concepts, relations, meta


async def load_pack(path: str, name: str, *, exclude: Iterable[str] = ("warehouse",), embed: bool = True) -> Dict[str, Any]:
    """Load (or refresh) a pack. Unchanged concepts keep their embeddings; removed ones are deleted."""
    root = Path(path)
    if not root.is_dir():
        raise FileNotFoundError(f"No knowledge bundle at {path}")
    concepts, relations, meta = read_bundle(root, exclude)
    now = datetime.now(timezone.utc)

    async with async_session_factory() as db:
        pack = (await db.execute(select(KnowledgePack).where(KnowledgePack.name == name))).scalars().first()
        if pack is None:
            pack = KnowledgePack(name=name, version=meta["version"], source_path=str(root), loaded_at=now)
            db.add(pack)
            await db.flush()
        unchanged_pack = pack.version == meta["version"] and pack.concept_count == len(concepts)
        pack.title, pack.okf_version = meta.get("title"), meta.get("okf_version")
        pack.version, pack.source_path, pack.loaded_at, pack.concept_count = meta["version"], str(root), now, len(concepts)

        existing = {c.concept_id: c for c in (await db.execute(
            select(KnowledgeConcept).where(KnowledgeConcept.pack_id == pack.id)
        )).scalars()}
        to_embed: List[KnowledgeConcept] = []
        seen = set()
        for c in concepts:
            seen.add(c["concept_id"])
            row = existing.get(c["concept_id"])
            if row is not None and row.content_hash == c["content_hash"] and row.embedding is not None:
                continue
            if row is None:
                row = KnowledgeConcept(pack_id=pack.id, concept_id=c["concept_id"])
                db.add(row)
            for key in ("type", "title", "description", "tags", "fields", "sections", "sources", "content_hash"):
                setattr(row, key, c[key])
            row.embedding = None
            to_embed.append(row)
        removed = [cid for cid in existing if cid not in seen]
        if removed:
            await db.execute(delete(KnowledgeConcept).where(
                KnowledgeConcept.pack_id == pack.id, KnowledgeConcept.concept_id.in_(removed)))
        await db.execute(delete(KnowledgeRelation).where(KnowledgeRelation.pack_id == pack.id))
        for s, p, t in relations:
            db.add(KnowledgeRelation(pack_id=pack.id, source_concept=s, predicate=p, target_concept=t))
        await db.flush()

        embedded = 0
        if embed and to_embed:
            from kairos_kb.context.embeddings import embed_texts

            by_id = {c["concept_id"]: c for c in concepts}
            for start in range(0, len(to_embed), 32):
                batch = to_embed[start:start + 32]
                vectors = await embed_texts([search_text(by_id[r.concept_id]) for r in batch])
                if vectors:
                    for r, v in zip(batch, vectors):
                        r.embedding = v
                    embedded += len(batch)
        await db.flush()
        await db.execute(sql_text("""
            UPDATE knowledge_concepts SET search_vector =
                setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
                setweight(to_tsvector('english', coalesce(description, '')), 'B') ||
                setweight(to_tsvector('english', coalesce(sections::text, '') || ' ' || coalesce(fields::text, '')), 'C')
            WHERE pack_id = :pack
        """), {"pack": pack.id})
        await db.commit()
    result = {"pack": name, "version": meta["version"], "concepts": len(concepts), "relations": len(relations),
              "updated": len(to_embed), "embedded": embedded, "removed": len(removed),
              "unchanged": unchanged_pack and not to_embed}
    logger.info("Knowledge pack %s loaded: %s", name, result)
    return result
