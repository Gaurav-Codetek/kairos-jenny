"""Live progress of a workspace sync, for the Connections screen.

A sync writes everything in one transaction, so nothing it produces is
visible to another session until it commits. Progress is therefore kept in
process memory: the sync reports what it is doing, and the API hands out a
snapshot. It is lost if the API restarts — the sync itself is too, since it
runs in this process.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, Optional

PHASES = ("catalog", "jobs", "objects", "lineage", "index")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


class SyncProgress:
    """What one sync is doing right now, and what it has done so far."""

    def __init__(self, workspace_id: uuid.UUID, options: Dict[str, Any]) -> None:
        self.id = uuid.uuid4()
        self.workspace_id = workspace_id
        self.options = options
        self.status = "running"  # running | completed | failed
        self.started_at = _now()
        self.finished_at: Optional[datetime] = None
        self.phase: Optional[str] = None
        self.step = "Starting"
        self.step_at = self.started_at
        # Position within the current phase, when the total is known: "job 4 of 12".
        self.position: Optional[Dict[str, Any]] = None
        self.phases: Dict[str, Dict[str, Any]] = {
            p: {"status": "pending", "started_at": None, "finished_at": None, "items": 0, "error": None}
            for p in PHASES
        }
        self.counts: Dict[str, int] = {}
        self.log: Deque[Dict[str, Any]] = deque(maxlen=80)
        self.error: Optional[str] = None
        self.results: Optional[Dict[str, Any]] = None
        self.task: Optional[asyncio.Task] = None

    # ── reporting, called by the sync ──

    def phase_start(self, phase: str, message: str) -> None:
        self.phase = phase
        self.phases[phase].update(status="running", started_at=_now())
        self.position = None
        self.set_step(message)
        self.note(message)

    def phase_end(self, phase: str, items: int = 0, error: Optional[str] = None) -> None:
        self.phases[phase].update(
            status="failed" if error else "completed", finished_at=_now(), items=items, error=error
        )
        self.position = None
        self.note(f"{phase.capitalize()} {'failed: ' + error[:200] if error else f'done — {items:,} item(s)'}",
                  level="error" if error else "info")

    def phase_skip(self, phase: str, reason: str) -> None:
        self.phases[phase].update(status="skipped")
        self.note(f"{phase.capitalize()} skipped — {reason}")

    def set_step(self, message: str, *, index: Optional[int] = None, total: Optional[int] = None,
                 unit: Optional[str] = None) -> None:
        self.step = message[:300]
        self.step_at = _now()
        if total:
            self.position = {"index": index, "total": total, "unit": unit}

    def note(self, message: str, level: str = "info") -> None:
        self.log.append({"at": _now().isoformat(), "message": message[:400], "level": level})

    def bump(self, key: str, n: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + n

    def finish(self, results: Dict[str, Any]) -> None:
        self.results = results
        self.status = "completed"
        self.finished_at = _now()
        self.phase = None
        self.set_step("Sync complete")
        self.note("Sync complete — committed to the Synthetic Warehouse")

    def fail(self, error: str) -> None:
        self.error = error[:2000]
        self.status = "failed"
        self.finished_at = _now()
        self.set_step("Sync failed")
        self.note(f"Sync failed: {error[:300]}", level="error")

    # ── reading, called by the API ──

    def snapshot(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "workspace_id": str(self.workspace_id),
            "status": self.status,
            "options": self.options,
            "started_at": _iso(self.started_at),
            "finished_at": _iso(self.finished_at),
            "phase": self.phase,
            "step": self.step,
            "step_at": _iso(self.step_at),
            "position": self.position,
            "phases": {
                p: {**v, "started_at": _iso(v["started_at"]), "finished_at": _iso(v["finished_at"])}
                for p, v in self.phases.items()
            },
            "counts": dict(self.counts),
            "log": list(self.log)[::-1],  # newest first
            "error": self.error,
            "results": self.results,
            # Timers in the browser count from the server's clock.
            "server_now": _now().isoformat(),
        }


class NullProgress(SyncProgress):
    """For a sync nobody is watching: every report is a no-op."""

    def __init__(self) -> None:  # noqa: D107 — deliberately skips the real state
        pass

    def phase_start(self, *a, **k) -> None: ...
    def phase_end(self, *a, **k) -> None: ...
    def phase_skip(self, *a, **k) -> None: ...
    def set_step(self, *a, **k) -> None: ...
    def note(self, *a, **k) -> None: ...
    def bump(self, *a, **k) -> None: ...


# The latest sync per workspace, running or finished.
_LATEST: Dict[uuid.UUID, SyncProgress] = {}


def latest(workspace_id: uuid.UUID) -> Optional[SyncProgress]:
    return _LATEST.get(workspace_id)


def is_running(workspace_id: uuid.UUID) -> bool:
    p = _LATEST.get(workspace_id)
    return bool(p and p.status == "running" and p.task and not p.task.done())


def forget(workspace_id: uuid.UUID) -> None:
    """Drop the last sync's progress, for a workspace that no longer exists."""
    _LATEST.pop(workspace_id, None)


def begin(workspace_id: uuid.UUID, options: Dict[str, Any]) -> SyncProgress:
    progress = SyncProgress(workspace_id, options)
    _LATEST[workspace_id] = progress
    return progress
