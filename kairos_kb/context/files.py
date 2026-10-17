"""Governed reads of Unity Catalog Volume files, for when a file itself matters.

Most files have a table built from them, and the table is the better source:
it is described, verified and masked. But some files carry what no table
does — an upload not yet loaded, a config or mapping file a pipeline reads,
the raw feed behind a failure. These tools read them under the same rules as
everything else:

  scope        Volume paths only (/Volumes/catalog/schema/volume/…), in
               catalogs the map knows and the agent may see; the "files"
               permission is required
  bounded      only the start of a file is read (an HTTP range request), with
               row, line and character caps; binary formats are refused
  personal     delimited files: columns whose header names identifying data are
  data         masked; every value is also scanned for e-mail addresses and
               phone numbers, which are redacted
  context      each read says which pipeline tasks read the file (or its
               folder) and which tables they load, so an agent can move to the
               governed table when that answers the question
"""

from __future__ import annotations

import csv
import io
import json
import re
from typing import Any, Dict, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.config import get_settings
from kairos_kb.connectors.databricks import DatabricksConnector
from kairos_kb.context.access import AgentIdentity
from kairos_kb.context.documents import load_profile
from kairos_kb.context.query import MASK, _allowed_catalogs, is_personal
from kairos_kb.enrichment.pipeline import canonical_relation
from kairos_kb.models.catalog import Catalog
from kairos_kb.models.discovered import DiscoveredRelation
from kairos_kb.models.entity_profile import EntityProfile

STAGE_PATH = re.compile(r"^@([A-Za-z0-9_$]+)\.([A-Za-z0-9_$]+)\.([A-Za-z0-9_$]+)(/[^\s'\"]*)?$")
VOLUME_PATH = re.compile(r"^/Volumes/([A-Za-z0-9_\-]+)/([A-Za-z0-9_\-]+)/([A-Za-z0-9_\-]+)(/.*)?$")
TEXT_EXTENSIONS = {"csv", "tsv", "txt", "json", "jsonl", "ndjson", "log", "md", "xml", "yaml", "yml", "sql",
                   "py", "ini", "cfg", "conf", "properties", "psv", "dat"}
BINARY_EXTENSIONS = {"parquet", "orc", "avro", "zip", "gz", "tgz", "tar", "bz2", "7z", "xlsx", "xls", "pdf",
                     "png", "jpg", "jpeg", "gif", "bmp", "docx", "pptx", "delta", "snappy", "bin", "pkl", "whl"}
CELL_CHARS = 300
TEXT_CHARS = 20000

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?<![\w.])(?:\+?\d{1,3}[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]\d{3}[\s.-]\d{4}(?![\w.])")


def redact_values(text: str) -> str:
    return _PHONE.sub("<phone>", _EMAIL.sub("<email>", text))


def check_path(path: str) -> Optional[str]:
    """Why this path may not be read, or None."""
    if not path or not path.startswith("/Volumes/"):
        return "Only Unity Catalog Volume paths can be read: /Volumes/<catalog>/<schema>/<volume>/…"
    if "/../" in path + "/" or "\\" in path or "//" in path[1:]:
        return "Path must be a plain Volume path (no '..', backslashes or empty segments)."
    if not VOLUME_PATH.match(path.rstrip("/")):
        return "Give at least /Volumes/<catalog>/<schema>/<volume>."
    return None


def extension(path: str) -> str:
    name = path.rstrip("/").rsplit("/", 1)[-1].lower()
    return name.rsplit(".", 1)[-1] if "." in name else ""


async def _authorise(db: AsyncSession, identity: AgentIdentity, path: str) -> Optional[str]:
    if not identity.can("files"):
        return "This agent may not read files: it needs the 'files' permission."
    problem = check_path(path)
    if problem:
        return problem
    catalog = VOLUME_PATH.match(path.rstrip("/")).group(1).lower()
    known = (await db.execute(select(Catalog.entity_id).where(Catalog.name.ilike(catalog)))).scalars().all()
    if not known and not get_settings().sql_allow_unmapped:
        return f"Catalog '{catalog}' is not in the map; sync it first."
    if known and not any(identity.sees_entity(e) for e in known):
        return f"Catalog '{catalog}' is not visible to this agent."
    allowed = _allowed_catalogs(identity)
    if allowed is not None and catalog not in allowed:
        return f"Outside the catalogs this agent may read ({', '.join(sorted(allowed))})."
    return None


async def _connector_holding(db: AsyncSession, identity: AgentIdentity, name: str, platform: str):
    """The connector of the connection that holds this catalog (Databricks) or database (Snowflake).

    The same name can exist in several connections; the first one this agent may see wins.
    None when no connection of that platform holds it.
    """
    from kairos_kb.connectors.factory import connector_for_entity, platform_of

    known = (await db.execute(select(Catalog.entity_id).where(Catalog.name.ilike(name)))).scalars().all()
    for entity_id in known:
        if identity.sees_entity(entity_id) and await platform_of(db, entity_id) == platform:
            return await connector_for_entity(db, entity_id)
    return None


async def _volume_connector(db: AsyncSession, identity: AgentIdentity, path: str):
    catalog = VOLUME_PATH.match(path.rstrip("/")).group(1)
    connector = await _connector_holding(db, identity, catalog, "databricks")
    # An unmapped catalog (only with SQL_ALLOW_UNMAPPED) has no connection to go by: the default workspace.
    return connector or DatabricksConnector()


async def file_context(db: AsyncSession, path: str) -> Dict[str, Any]:
    """What the map knows about a file: the tasks that read it or its folder, and what they load."""
    path = path.rstrip("/")
    readers: Dict[str, str] = {}
    rels = (await db.execute(select(DiscoveredRelation).where(
        DiscoveredRelation.status != "contradicted", DiscoveredRelation.target_entity_id.like("file:%")
    ))).scalars().all()
    for r in rels:
        canonical, _, _ = canonical_relation(r.relation_type)
        file_path = r.target_entity_id.split(":", 2)[-1].rstrip("/")
        if canonical == "READS_FILE" and (path == file_path or path.startswith(file_path + "/")
                                          or file_path.startswith(path + "/")):
            readers.setdefault(r.source_entity_id, f"reads {file_path}")
    # Volume paths named in task code (Stage 0 facts in each task profile).
    for (task_id,) in (await db.execute(select(EntityProfile.entity_id).where(EntityProfile.kind == "task"))).all():
        facts = (await load_profile(db, task_id) or {}).get("facts") or {}
        for vp in facts.get("volume_paths_in_code") or []:
            vp = vp.rstrip("/")
            if path == vp or path.startswith(vp + "/") or vp.startswith(path + "/") or \
                    path.rsplit("/", 1)[0] == vp.rsplit("/", 1)[0]:
                readers.setdefault(task_id, f"code names {vp}")
    loads: Dict[str, str] = {}
    if readers:
        writes = (await db.execute(select(DiscoveredRelation).where(
            DiscoveredRelation.status != "contradicted",
            or_(DiscoveredRelation.source_entity_id.in_(list(readers)),
                DiscoveredRelation.target_entity_id.in_(list(readers))),
        ))).scalars().all()
        for w in writes:
            canonical, flip, _ = canonical_relation(w.relation_type)
            src, dst = (w.target_entity_id, w.source_entity_id) if flip else (w.source_entity_id, w.target_entity_id)
            if canonical == "WRITES_TABLE" and src in readers and dst.startswith("table:"):
                loads.setdefault(dst, src.split(":")[-1])
    out: Dict[str, Any] = {}
    if readers:
        out["read_by"] = [{"entity_id": k, "name": k.split(":")[-1], "evidence": v} for k, v in readers.items()]
    if loads:
        out["loads_into"] = [{"entity_id": k, "name": k.split(":")[-1], "via": v} for k, v in loads.items()]
        out["note"] = ("These tables are built from this file's pipeline: they are described, verified and "
                       "masked — query them with run_sql when they hold what you need.")
    return out


async def list_volume_files(db: AsyncSession, identity: AgentIdentity, path: str) -> Dict[str, Any]:
    problem = await _authorise(db, identity, path)
    if problem:
        return {"error": problem}
    try:
        entries = await (await _volume_connector(db, identity, path)).list_directory(path)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Could not list {path}: {str(exc)[:300]}"}
    from datetime import datetime, timezone

    items = []
    for e in entries[:200]:
        modified = e.get("last_modified")
        items.append({
            "name": e.get("name"),
            "path": e.get("path"),
            "type": "folder" if e.get("is_directory") else (extension(e.get("name") or "") or "file"),
            "bytes": e.get("file_size"),
            "modified": datetime.fromtimestamp(modified / 1000, tz=timezone.utc).isoformat() if modified else None,
        })
    return {"path": path, "entries": items, "count": len(items), **({"truncated": True} if len(entries) > 200 else {})}


def _parse_delimited(text: str, delimiter: str, max_rows: int, geography: bool, complete: bool) -> Dict[str, Any]:
    lines = text.splitlines()
    if not complete and lines:
        lines = lines[:-1]  # the last line may be cut mid-row
    rows = list(csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter))
    if not rows:
        return {"columns": [], "rows": []}
    first = rows[0]
    has_header = all(c and not re.fullmatch(r"[-+\d.,/: ]+", c) for c in first) and len(set(first)) == len(first)
    header = first if has_header else [f"_c{i}" for i in range(len(first))]
    body = rows[1:] if has_header else rows
    masked = [i for i, h in enumerate(header) if has_header and is_personal(h, geography=geography)]
    shaped = []
    for r in body[:max_rows]:
        row = []
        for i, v in enumerate(r):
            if i in masked and v != "":
                row.append(MASK)
            else:
                v = redact_values(v)
                row.append(v if len(v) <= CELL_CHARS else v[:CELL_CHARS] + "…")
        shaped.append(row)
    out = {"columns": header, "rows": shaped, "rows_read": len(shaped),
           "masked_columns": [header[i] for i in masked], "has_header": has_header}
    if not has_header:
        out["note"] = ("No header row: personal-data columns cannot be identified by name. E-mail addresses and "
                       "phone numbers are redacted; treat other values with care.")
    return out


def _mask_json(value: Any, geography: bool) -> Any:
    if isinstance(value, dict):
        return {k: (MASK if is_personal(str(k), geography=geography) and v not in (None, "") else _mask_json(v, geography))
                for k, v in value.items()}
    if isinstance(value, list):
        return [_mask_json(v, geography) for v in value[:50]]
    if isinstance(value, str):
        v = redact_values(value)
        return v if len(v) <= CELL_CHARS else v[:CELL_CHARS] + "…"
    return value


def shape_file(path: str, raw: bytes, total: Optional[int], modified: Any, max_rows: int) -> Dict[str, Any]:
    """The start of a text file as an agent should see it: parsed where the format allows, personal
    columns masked, e-mail addresses and phone numbers redacted. Shared by Volume and stage reads."""
    settings = get_settings()
    ext = extension(path)
    text = raw.decode("utf-8", errors="replace")
    complete = total is not None and len(raw) >= total
    result: Dict[str, Any] = {
        "path": path,
        "format": ext or "text",
        "file_bytes": total,
        "bytes_read": len(raw),
        "complete": complete,
        "modified": modified,
    }
    geography = settings.sql_mask_geography
    if ext in ("csv", "tsv", "psv", "dat") or (not ext and text.count(",") > text.count("\n") * 2):
        delimiter = {"tsv": "\t", "psv": "|"}.get(ext, ",")
        if ext == "dat" and text and "|" in text.splitlines()[0]:
            delimiter = "|"
        result.update(_parse_delimited(text, delimiter, max_rows, geography, complete))
    elif ext in ("jsonl", "ndjson"):
        lines = text.splitlines()[: max_rows + (0 if complete else 1)]
        if not complete and lines:
            lines = lines[:-1]
        records = []
        for line in lines:
            try:
                records.append(_mask_json(json.loads(line), geography))
            except ValueError:
                continue
        result.update({"records": records, "rows_read": len(records)})
    elif ext == "json" and complete:
        try:
            result["json"] = _mask_json(json.loads(text), geography)
        except ValueError:
            result["text"] = redact_values(text[:TEXT_CHARS])
    else:
        lines = text.splitlines()
        if not complete and lines:
            lines = lines[:-1]
        result["text"] = redact_values("\n".join(lines[: max_rows * 4])[:TEXT_CHARS])
        result["lines_read"] = min(len(lines), max_rows * 4)
    if not complete:
        result["note_size"] = (f"Only the first {len(raw):,} of {total:,} bytes were read." if total
                               else f"Only the first {len(raw):,} bytes were read.")
    return result


async def read_volume_file(db: AsyncSession, identity: AgentIdentity, path: str, max_rows: int = 50) -> Dict[str, Any]:
    settings = get_settings()
    problem = await _authorise(db, identity, path)
    if problem:
        return {"error": problem}
    ext = extension(path)
    if ext in BINARY_EXTENSIONS:
        return {"error": f"'.{ext}' is a binary format and is not read as text. If it backs a table, query the "
                         "table with run_sql.", "context": await file_context(db, path)}
    max_rows = max(1, min(int(max_rows or 50), 500))
    try:
        head = await (await _volume_connector(db, identity, path)).read_file_head(path, settings.file_read_max_bytes)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Could not read {path}: {str(exc)[:300]}"}
    raw = head["content"]
    if b"\x00" in raw[:2048]:
        return {"error": "This file looks binary and is not read as text.", "context": await file_context(db, path)}
    result = shape_file(path, raw, head.get("total_bytes"), head.get("last_modified"), max_rows)
    context = await file_context(db, path)
    if context:
        result["context"] = context
    return result


# ── Snowflake stages ─────────────────────────────────────────────────


def check_stage_path(path: str) -> Optional[str]:
    if not path or not path.startswith("@"):
        return "Give a stage path: @<database>.<schema>.<stage>/<folder or file>."
    if "/../" in path + "/" or "\\" in path or "//" in path:
        return "Path must be a plain stage path (no '..', backslashes or empty segments)."
    if not STAGE_PATH.match(path.rstrip("/")):
        return "Give the fully qualified stage: @<database>.<schema>.<stage>, then /folder/file."
    return None


async def _authorise_stage(db: AsyncSession, identity: AgentIdentity, path: str) -> Optional[str]:
    if not identity.can("files"):
        return "This agent may not read files: it needs the 'files' permission."
    problem = check_stage_path(path)
    if problem:
        return problem
    database = STAGE_PATH.match(path.rstrip("/")).group(1)
    known = (await db.execute(select(Catalog.entity_id).where(Catalog.name.ilike(database)))).scalars().all()
    if not known:
        return f"Database '{database}' is not in the map; sync it first."
    if not any(identity.sees_entity(e) for e in known):
        return f"Database '{database}' is not visible to this agent."
    allowed = _allowed_catalogs(identity)
    if allowed is not None and database.lower() not in allowed:
        return f"Outside the databases this agent may read ({', '.join(sorted(allowed))})."
    return None


def _split_stage(path: str):
    m = STAGE_PATH.match(path.rstrip("/"))
    stage = f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
    return stage, (m.group(4) or "").lstrip("/")


async def _stage_connector(db: AsyncSession, identity: AgentIdentity, path: str):
    database = STAGE_PATH.match(path.rstrip("/")).group(1)
    return await _connector_holding(db, identity, database, "snowflake")


async def list_stage_files(db: AsyncSession, identity: AgentIdentity, path: str) -> Dict[str, Any]:
    problem = await _authorise_stage(db, identity, path)
    if problem:
        return {"error": problem}
    connector = await _stage_connector(db, identity, path)
    if connector is None:
        return {"error": "No Snowflake connection holds this stage's database."}
    stage, rel = _split_stage(path)
    try:
        entries = await connector.list_stage(stage, rel)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Could not list {path}: {str(exc)[:300]}"}
    items = [{"name": e["name"], "path": f"@{stage}/{e['name']}", "type": extension(e["name"]) or "file",
              "bytes": e.get("size"), "modified": e.get("last_modified")} for e in entries[:200]]
    return {"path": path, "entries": items, "count": len(items), **({"truncated": True} if len(entries) > 200 else {})}


async def read_stage_file(db: AsyncSession, identity: AgentIdentity, path: str, max_rows: int = 50) -> Dict[str, Any]:
    """The start of a staged file, governed like a Volume read: parsed, masked, redacted."""
    settings = get_settings()
    problem = await _authorise_stage(db, identity, path)
    if problem:
        return {"error": problem}
    stage, rel = _split_stage(path)
    if not rel or rel.endswith("/"):
        return {"error": "Give a file, not a folder: list it first with action='list'."}
    ext = extension(rel)
    if ext in BINARY_EXTENSIONS:
        return {"error": f"'.{ext}' is a binary format and is not read as text. If it backs a table, query the "
                         "table with run_sql."}
    max_rows = max(1, min(int(max_rows or 50), 500))
    connector = await _stage_connector(db, identity, path)
    if connector is None:
        return {"error": "No Snowflake connection holds this stage's database."}
    try:
        head = await connector.read_stage_head(stage, rel, settings.file_read_max_bytes)
        raw = head["content"]
    except Exception as exc:  # noqa: BLE001
        head, raw = None, b""
        first_error = str(exc)[:200]
    if head is not None and b"\x00" not in raw[:2048]:
        return shape_file(path, raw, head.get("total_bytes"), head.get("last_modified"), max_rows)
    # Client-side encrypted stage (or no presigned access): read delimited rows with SQL instead.
    if ext not in ("csv", "tsv", "psv", "dat", "txt", ""):
        return {"error": f"Could not read {path} directly" + (f": {first_error}" if head is None else
                         " (the stage encrypts files client-side and only delimited files can be read with SQL).")}
    try:
        rows = await connector.read_stage_rows(stage, rel, max_rows + 1)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Could not read {path}: {str(exc)[:300]}"}
    buf = io.StringIO()
    csv.writer(buf).writerows([[v if v is not None else "" for v in r] for r in rows])
    result = shape_file(path if ext in ("csv", "") else path + ".csv", buf.getvalue().encode("utf-8"),
                        None, None, max_rows)
    result.update({"path": path, "read_with": "SQL (default CSV parsing: comma-separated, first row included)"})
    return result
