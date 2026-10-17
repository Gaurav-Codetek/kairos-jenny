"""The companion's heartbeat: it looks by itself, without anyone asking.

Every half minute the scheduler checks each connection that has data products: a connection
gets a companion the first time it is seen (on by default), and a pulse when it is due — every
few minutes while its data is live, every half hour when it is not. A person can switch it off,
change the interval, or ask for a pulse now; one pulse runs at a time per connection.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional, Set

from sqlalchemy import select

from kairos_kb.db.engine import async_session_factory
from kairos_kb.models.companion import CompanionState
from kairos_kb.models.data_product import DataProduct
from kairos_kb.models.workspace import Workspace

logger = logging.getLogger(__name__)

TICK_SECONDS = 30
RUNNING: Set[str] = set()
_TASK: Optional[asyncio.Task] = None
_PULSES: Dict[str, asyncio.Task] = {}


async def state_for(db, workspace_id: uuid.UUID) -> CompanionState:
    st = (await db.execute(select(CompanionState).where(CompanionState.workspace_id == workspace_id))).scalars().first()
    if st is None:
        st = CompanionState(workspace_id=workspace_id, enabled=True, interval_seconds=300, live=False, status="idle")
        db.add(st)
        await db.flush()
    return st


async def run_pulse(workspace_id: uuid.UUID, *, force: bool = False) -> None:
    """One pulse for one connection, in its own session."""
    from kairos_kb.companion.pulse import pulse

    key = str(workspace_id)
    if key in RUNNING:
        return
    RUNNING.add(key)
    try:
        async with async_session_factory() as db:
            ws = await db.get(Workspace, workspace_id)
            st = await state_for(db, workspace_id)
            st.status = "running"
            await db.commit()
            try:
                await pulse(db, ws, st, force=force)
                st.status = "idle"
                await db.commit()
                await _speak_first(workspace_id)
            except Exception as exc:  # noqa: BLE001 — shown on the screen; the next tick tries again
                logger.exception("Companion pulse failed for %s", ws.name if ws else key)
                await db.rollback()
                st = await state_for(db, workspace_id)
                st.status, st.error, st.last_pulse_at = "idle", str(exc)[:1000], datetime.now(timezone.utc)
                await db.commit()
    finally:
        RUNNING.discard(key)


async def _speak_first(workspace_id: uuid.UUID) -> None:
    """After a pulse: keep her desk alive (watches checked, checks run), look into what's new and material, then
    don't wait to be asked (a voice note when no call is open; a call raises it live)."""
    from kairos_kb.companion import desk, initiative

    try:
        await desk.review(workspace_id)
        await initiative.look_into_new(workspace_id)
        await initiative.after_pulse(workspace_id)
    except Exception:  # noqa: BLE001 — never stops the heartbeat
        logger.exception("Companion: couldn't speak first")


def start_pulse(workspace_id: uuid.UUID, *, force: bool = False) -> bool:
    if str(workspace_id) in RUNNING:
        return False
    _PULSES[str(workspace_id)] = asyncio.create_task(run_pulse(workspace_id, force=force))
    return True


async def tick() -> None:
    from kairos_kb.companion.pulse import interval_for

    now = datetime.now(timezone.utc)
    async with async_session_factory() as db:
        with_products = {r[0] for r in (await db.execute(select(DataProduct.workspace_id).distinct())).all()}
        states = {s.workspace_id: s for s in (await db.execute(select(CompanionState))).scalars()}
        for wid in with_products - set(states):
            states[wid] = await state_for(db, wid)
        await db.commit()
        due = [wid for wid, s in states.items()
               if s.enabled and wid in with_products and str(wid) not in RUNNING
               and (s.last_pulse_at is None or (now - s.last_pulse_at).total_seconds() >= interval_for(s))]
    for wid in due:
        start_pulse(wid)


async def _loop() -> None:
    await asyncio.sleep(15)  # let the API finish starting
    try:  # a pulse cut off by a restart is not still running
        async with async_session_factory() as db:
            for s in (await db.execute(select(CompanionState).where(CompanionState.status == "running"))).scalars():
                s.status = "idle"
            await db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("Could not reset interrupted companion pulses")
    while True:
        try:
            await tick()
        except Exception:  # noqa: BLE001 — the heartbeat never stops
            logger.exception("Companion scheduler tick failed")
        await asyncio.sleep(TICK_SECONDS)


def start() -> asyncio.Task:
    global _TASK
    if _TASK is None or _TASK.done():
        _TASK = asyncio.create_task(_loop())
        logger.info("Companion heartbeat started")
    return _TASK


def stop() -> None:
    if _TASK and not _TASK.done():
        _TASK.cancel()
