"""Evidence, change events and sync states in words instead of ids.

An evidence row is a raw platform response (a table's metadata, a job's
definition) or a file the agent read; a change event is a field that moved.
On the map they used to be shown by their UUID. These helpers say what each
one actually is — "Table metadata: zomato.raw.orders — MANAGED, DELTA, 12
columns" — and hand back a readable excerpt with e-mail addresses masked,
since these payloads carry creator and owner names.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

SOURCE_LABELS = {
    "API_RESPONSE": "Platform metadata",
    "FILE_CONTENT": "File content",
    "SQL_QUERY": "Query result",
    "TABLE_HISTORY": "Table history",
    "SCHEMA_CHANGE": "Schema change",
    "SYSTEM_TABLE": "System table",
}


def mask_emails(text: str) -> str:
    return _EMAIL.sub("<email>", text)


def source_label(source_type: Optional[str]) -> str:
    if not source_type:
        return "Evidence"
    return SOURCE_LABELS.get(source_type.upper(), source_type.replace("_", " ").lower().capitalize())


def _clip(text: Any, n: int) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _dotted(*parts: Any) -> str:
    return ".".join(str(p) for p in parts if p)


def _describe_payload(d: Dict[str, Any]) -> Tuple[str, List[str]]:
    """A title and a few plain facts for a platform API response."""
    facts: List[str] = []
    if isinstance(d.get("settings"), dict) or ("job_id" in d and "run_id" not in d):
        s = d.get("settings") or {}
        tasks = s.get("tasks") or d.get("tasks") or []
        facts.append(f"{len(tasks)} task{'s' if len(tasks) != 1 else ''}")
        cron = (s.get("schedule") or {}).get("quartz_cron_expression")
        if cron:
            facts.append(f"schedule {cron}")
        if s.get("max_concurrent_runs"):
            facts.append(f"max {s['max_concurrent_runs']} concurrent runs")
        return f"Job definition: {s.get('name') or d.get('job_id')}", facts
    if "run_id" in d:
        state = d.get("state") or {}
        result = state.get("result_state") or state.get("life_cycle_state")
        if result:
            facts.append(str(result))
        if state.get("state_message"):
            facts.append(_clip(state["state_message"], 160))
        return f"Run: {d.get('run_name') or d['run_id']}", facts
    if isinstance(d.get("columns"), list) and d.get("name"):
        for key in ("table_type", "data_source_format"):
            if d.get(key):
                facts.append(str(d[key]))
        facts.append(f"{len(d['columns'])} columns")
        if d.get("comment"):
            facts.append(_clip(d["comment"], 160))
        return f"Table metadata: {d.get('full_name') or _dotted(d.get('catalog_name'), d.get('schema_name'), d['name'])}", facts
    if d.get("catalog_name") and d.get("name"):
        if d.get("comment"):
            facts.append(_clip(d["comment"], 160))
        return f"Schema metadata: {d.get('full_name') or _dotted(d['catalog_name'], d['name'])}", facts
    if d.get("catalog_type") or (d.get("name") and "owner" in d):
        if d.get("catalog_type"):
            facts.append(str(d["catalog_type"]))
        if d.get("comment"):
            facts.append(_clip(d["comment"], 160))
        return f"Catalog metadata: {d.get('name')}", facts
    keys = [k for k in d if not isinstance(d[k], (dict, list))][:6]
    facts.extend(f"{k}: {_clip(d[k], 60)}" for k in keys)
    return "Platform response", facts


def evidence_digest(row: Any, *, excerpt_chars: int = 0) -> Dict[str, Any]:
    """What one evidence row says, in words; with excerpt_chars, a masked excerpt of the payload itself."""
    text = row.content or ""
    parsed: Any = None
    if text[:1] in "{[":
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None

    if isinstance(parsed, dict):
        title, facts = _describe_payload(parsed)
    elif isinstance(parsed, list):
        title, facts = "Platform response", [f"{len(parsed)} items"]
    else:
        meta = row.metadata_extra if isinstance(row.metadata_extra, dict) else {}
        where = row.source_id or meta.get("path")
        title = f"File read: {where}" if where else source_label(row.source_type)
        first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
        facts = [_clip(first, 160)] if first else []
    if (row.source_type or "").upper() not in ("API_RESPONSE", "") and not title.startswith("File read"):
        title = f"{source_label(row.source_type)}: {title}"

    out: Dict[str, Any] = {
        "id": f"evidence:{row.id}",
        "title": mask_emails(title),
        "summary": mask_emails(" · ".join(f for f in facts if f)) or None,
        "source_type": row.source_type,
        "source_label": source_label(row.source_type),
        "source": row.source_id,
        "about": row.entity_id,
        "observed_at": row.observed_at.isoformat() if row.observed_at else None,
        "size_chars": len(text),
    }
    if excerpt_chars:
        body = json.dumps(parsed, indent=2, default=str) if parsed is not None else text
        out["excerpt"] = mask_emails(body[:excerpt_chars])
        out["truncated"] = len(body) > excerpt_chars
    return out


def change_label(row: Any) -> str:
    """'Created table', 'Updated column (data_type)'."""
    verb = (row.change_type or "changed").replace("_", " ").lower().capitalize()
    noun = (row.entity_type or "").replace("_", " ").lower()
    label = f"{verb} {noun}".strip()
    return f"{label} ({row.field_name})" if row.field_name else label


def change_summary(row: Any) -> str:
    subject = (row.entity_id or "").split(":")[-1]
    parts = [f"{change_label(row)} {subject}".strip()]
    if row.old_value is not None or row.new_value is not None:
        parts.append(f"{_clip(row.old_value, 80) or '∅'} → {_clip(row.new_value, 80) or '∅'}")
    if row.detected_at:
        parts.append(row.detected_at.date().isoformat())
    return mask_emails(" · ".join(parts))
