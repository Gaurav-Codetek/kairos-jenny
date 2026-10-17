"""Learned diagnosis variants — compiled RCA plans, keyed by class then variant.

Strict lookup order: Jev picks the class; then Jev picks, among the variants
filed under that class only, the one whose mechanism fits (or none). A
variant is the general diagnosis for one way that class of failure arises —
e.g. EXTRA_COLUMN / "notebook compares a CSV header to a mapping file" —
compiled by Agent A into a node plan that Agent B runs as a LangGraph.

Stored as one YAML file each under ``<storage>/playbooks/<CLASS>/<id>.yaml``
so they can be read and corrected by hand. ``trusted: true`` marks a
hand-checked variant as proven.

Lifecycle:
  draft    — compiled from one investigation and verified by a dry run on it
  proven   — succeeded PROMOTE_AFTER times on later runs
  retired  — failed RETIRE_AFTER times in a row; no longer offered to Jev
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from kairos_kb.config import get_settings

logger = logging.getLogger(__name__)

PROMOTE_AFTER = 2
RETIRE_AFTER = 3


def _root() -> Path:
    return Path(get_settings().storage_base_path) / "playbooks"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path(v: Dict[str, Any]) -> Path:
    return _root() / v["class"] / f"{v['id']}.yaml"


def load_all(failure_class: Optional[str] = None, *, include_retired: bool = True) -> List[Dict[str, Any]]:
    base = _root() / failure_class if failure_class else _root()
    if not base.exists():
        return []
    out = []
    for file in sorted(base.rglob("*.yaml")):
        try:
            v = yaml.safe_load(file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — one bad file must not hide the rest
            logger.exception("Could not read variant %s", file)
            continue
        # Only compiled variants; anything else (older formats) is ignored.
        if not (isinstance(v, dict) and v.get("id") and v.get("class") and isinstance(v.get("plan"), list)):
            continue
        if include_retired or v.get("status") != "retired" or v.get("trusted"):
            out.append(v)
    return out


def variants_for(failure_class: str) -> List[Dict[str, Any]]:
    """The variants Jev may choose from for this class."""
    return load_all(failure_class, include_retired=False)


def save(v: Dict[str, Any]) -> None:
    v["updated_at"] = _now()
    path = _path(v)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(v, sort_keys=False, allow_unicode=True, width=110), encoding="utf-8")


def create(
    *,
    failure_class: str,
    variant: str,
    plan: List[Dict[str, Any]],
    learned_from_run: str,
    dry_run: Dict[str, Any],
) -> Dict[str, Any]:
    slug = re.sub(r"[^a-z0-9]+", "-", variant.lower()).strip("-")[:60] or "variant"
    digest = hashlib.sha256(f"{failure_class}{variant}{_now()}".encode()).hexdigest()[:6]
    v = {
        "id": f"{slug}-{digest}",
        "class": failure_class,
        "variant": variant,
        "status": "draft",
        "trusted": False,
        "created_at": _now(),
        "learned_from_run": learned_from_run,
        "dry_run": {"ms": dry_run.get("ms"), "tool_calls": dry_run.get("tool_calls")},
        "stats": {"successes": 0, "failures": 0, "consecutive_failures": 0},
        "plan": plan,
    }
    save(v)
    return v


def record_outcome(v: Dict[str, Any], *, success: bool, ms: int, failure: Optional[str] = None) -> Dict[str, Any]:
    stats = v.setdefault("stats", {"successes": 0, "failures": 0, "consecutive_failures": 0})
    stats["last_used"] = _now()
    stats["last_ms"] = ms
    if success:
        stats["successes"] = int(stats.get("successes", 0)) + 1
        stats["consecutive_failures"] = 0
        stats.pop("last_failure", None)
        if v.get("status") == "draft" and stats["successes"] >= PROMOTE_AFTER:
            v["status"] = "proven"
    else:
        stats["failures"] = int(stats.get("failures", 0)) + 1
        stats["consecutive_failures"] = int(stats.get("consecutive_failures", 0)) + 1
        stats["last_failure"] = failure
        if stats["consecutive_failures"] >= RETIRE_AFTER and not v.get("trusted"):
            v["status"] = "retired"
    save(v)
    return v


def summary(v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not v:
        return None
    return {
        "id": v["id"],
        "class": v["class"],
        "variant": v.get("variant"),
        "status": v.get("status"),
        "trusted": v.get("trusted", False),
        "stats": v.get("stats"),
        "plan": [
            {"id": n.get("id"), "type": n.get("type"), "name": n.get("name")} for n in v.get("plan", [])
        ],
    }
