"""Jenny never says she'll do, or did, what nothing backs — enforced by the system, not asked of the model.

Every sentence of hers passes a gate before the owner hears or reads it. Jev reads the sentence against what backs
her claims (brain.check_claim):

  backing   what she set up on her desk (desk.py), the lookups she ran this turn, what she found when she looked into
            something by herself, and her standing duties (desk.STANDING).

A sentence that only repeats what she already said (the watch she confirmed a turn ago, again, after a thank-you)
is trimmed to what's new — or to the few words the moment needs.

A sentence that commits her to something later ("I'll ping you if cancellations top eight percent") or claims she
did something ("I checked the zones") with nothing behind it is held back, and repaired before anything after it is
released — commit or retract:

  commit    if her desk can do what it promises, she sets it up there and then (a watch, a check for later), and the
            sentence is said as it now truly is;
  retract   otherwise (email, SMS, a check she never ran) the sentence is rewritten honestly: what she can do instead,
            or without the claim.

Streaming (a call speaks each sentence as it's released): sentences are checked as they complete, in parallel, and
released in order, so the owner hears the first sentence a Jev read (~0.2 s) later and the rest without delay.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional

from kairos_kb.companion import brain, desk

logger = logging.getLogger(__name__)

_END = re.compile(r"[.!?…](?=\s)")
_TAG = re.compile(r"^\s*(\[[a-z]+\]\s*)", re.I)

REPAIR = """You are Jenny, the business companion. You were about to say a sentence that promises or claims something
nothing backs. Make it true, or make it honest:
- If what it promises is something your desk can do — a watch on a metric against a threshold, or a check at a set
  time — set it up now with the tool, exactly as promised. Then write the sentence again so it matches what you set
  up (or what the tool told you, e.g. that it's already above that).
- If it's something you can't do (email, a text message, any channel but this one; an action outside your tools),
  or it claims you did something you didn't, write it again honestly: what you can do instead, or without the claim.
- If the sentence isn't needed at all, reply with nothing.
Reply with the one sentence only, in the same voice and style as the rest of your reply{voice}."""


def sentences(text: str) -> List[str]:
    """The text cut after each sentence end that's followed by a space (the last piece is whatever remains)."""
    out, start = [], 0
    for m in _END.finditer(text):
        out.append(text[start:m.end()])
        start = m.end()
    if text[start:].strip():
        out.append(text[start:])
    return out


def backing(desk_lines: List[str], lookups: Optional[List[Dict[str, Any]]] = None,
            found: Optional[str] = None) -> List[str]:
    out = [f"standing duty: {d}" for d in desk.STANDING]
    out += [f"on the desk: {x}" for x in desk_lines]
    for lk in lookups or []:
        args = ", ".join(f"{k}={v}" for k, v in (lk.get("args") or {}).items() if k != "filters")
        out.append(f"looked up this turn: {lk.get('tool')}({args})" + ("" if lk.get("ok", True) else " — failed"))
    if found:
        out.append(f"what I found looking into it myself: {found[:600]}")
    return out


async def repair(workspace_id, sentence: str, check: Dict[str, Any], said_before: str, backed_by: List[str],
                 voice: bool, origin: Optional[Dict[str, Any]] = None) -> str:
    """Commit or retract: the sentence as it can truly be said ('' to drop it)."""
    from kairos_kb.companion import chat
    from kairos_kb.evals.connector_eval import _client, _record_calls, _record_result, default_model

    tag = (_TAG.match(sentence).group(1) if _TAG.match(sentence) else "")
    if check.get("claim") == "repeat":
        if said_before.strip():
            return ""  # something came before it: the repeat is simply not said
        return await _trim_repeat(sentence, said_before, voice)
    tools = [t for t in desk.TOOLS if t["function"]["name"] in ("keep_watch", "check_later")] if check.get("claim") == "later" else []
    if tools:  # what she can watch: the products and metrics
        products = await chat.call_tool(workspace_id, "list_products", {})
        catalog = "; ".join(f"{p['product']}: {', '.join(m['name'] for m in p['metrics'])}"
                            for p in (products.get("products") or []) if p.get("live"))[:1500]
    else:
        catalog = ""
    system = REPAIR.format(voice=" (spoken aloud: plain words, numbers in words)" if voice else "")
    history: List[Dict[str, Any]] = [{"role": "user", "content": (
        f"About to say: \"{sentence.strip()}\"\nJust before it: \"{said_before[-300:].strip() or '(start of reply)'}\"\n"
        f"What backs my claims now: {json.dumps(backed_by[:20])}\n"
        + (f"Live products and metrics I can watch: {catalog}\n" if catalog else "")
        + ("This sentence commits me to something later that nothing above backs." if check.get("claim") == "later"
           else "This sentence claims I did something that nothing above backs."))}]

    async def quiet(_t: str) -> None:
        return None

    client, model = _client(), default_model()
    try:
        out = await chat._stream_turn(client, model, system, history, tools, not tools, quiet, "minimal")
        if out.get("calls"):
            _record_calls(history, out["text"], out["calls"])
            for c in out["calls"]:
                try:
                    args = json.loads(c["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                res = await desk.call(workspace_id, c["name"], args, origin)
                logger.info("Jenny's claim gate: committed (%s) -> %s", c["name"], "ok" if res.get("ok") else res.get("error"))
                _record_result(history, c["id"], json.dumps(res, default=str))
            out = await chat._stream_turn(client, model, system, history, tools, True, quiet, "minimal")
        text = (out.get("text") or "").strip().strip('"')
    except Exception:  # noqa: BLE001 — unrepaired, the claim isn't said
        logger.exception("Claim repair failed")
        text = ""
    if text and tag and not _TAG.match(text):
        text = tag + text
    lead = sentence[:len(sentence) - len(sentence.lstrip())]
    return (lead + text) if text else ""


TRIM = """You are Jenny, the business companion. The sentence you were about to say only repeats what you already said
earlier in the conversation. Keep only what's new in it. If nothing is new: when it's the start of your reply, give
just the few natural words the moment needs ("Anytime."); otherwise reply with nothing. Reply with the sentence only{voice}."""


async def _trim_repeat(sentence: str, said_before: str, voice: bool) -> str:
    from kairos_kb.companion import chat
    from kairos_kb.evals.connector_eval import _client, default_model

    async def quiet(_t: str) -> None:
        return None

    tag = (_TAG.match(sentence).group(1) if _TAG.match(sentence) else "")
    try:
        out = await chat._stream_turn(_client(), default_model(), TRIM.format(voice=" (spoken aloud)" if voice else ""),
                                      [{"role": "user", "content": f"About to say: \"{sentence.strip()}\"\nJust before "
                                        f"it in this reply: \"{said_before.strip() or '(nothing: this is the start)'}\""}],
                                      [], True, quiet, "minimal")
        text = (out.get("text") or "").strip().strip('"')
    except Exception:  # noqa: BLE001 — keep what she meant to say
        return sentence
    if text and tag and not _TAG.match(text):
        text = tag + text
    lead = sentence[:len(sentence) - len(sentence.lstrip())]
    return (lead + text) if text else ""


class Gate:
    """Releases a streamed reply sentence by sentence, each only once it passes the claim check (or is repaired)."""

    def __init__(self, workspace_id, backing_fn: Callable[[], List[str]], on_release: Callable[[str], Awaitable[None]],
                 voice: bool, origin: Optional[Dict[str, Any]] = None, earlier: Optional[List[str]] = None) -> None:
        self.workspace_id, self.backing_fn, self.on_release = workspace_id, backing_fn, on_release
        self.voice, self.origin, self.earlier = voice, origin, earlier or []
        self.log: List[Dict[str, Any]] = []
        self.reset()

    def reset(self) -> None:
        if getattr(self, "_pump", None) and not self._pump.done():
            self._pump.cancel()
        self.raw, self.cut, self.out = "", 0, ""
        self.queue: List[Dict[str, Any]] = []
        self.done_upto = 0
        self._pump: Optional[asyncio.Task] = None

    def _add(self, seg: str) -> None:
        context = self.raw[:self.cut]
        self.queue.append({"seg": seg, "task": asyncio.create_task(
            brain.check_claim(seg.strip(), self.backing_fn(), context, self.earlier,
                              (self.origin or {}).get("question", "")))})

    def feed(self, so_far: str) -> None:
        if not so_far.startswith(self.raw[:len(so_far)]) or len(so_far) < self.cut:
            self.reset()  # a new stream for this step: start again
        self.raw = so_far
        for m in _END.finditer(so_far, self.cut):
            seg = so_far[self.cut:m.end()]
            self.cut = m.end()
            if seg.strip():
                self._add(seg)
        self._kick()

    def _kick(self) -> None:
        if self._pump is None or self._pump.done():
            self._pump = asyncio.create_task(self._release())

    async def _release(self) -> None:
        while self.done_upto < len(self.queue):
            item = self.queue[self.done_upto]
            seg = item["seg"]
            try:
                r = await item["task"]
            except Exception:  # noqa: BLE001 — a check that failed lets the sentence through
                r = {"ok": True, "checked": False}
            if r.get("ok"):
                self.out += seg
            else:
                fixed = await repair(self.workspace_id, seg, r, self.out, self.backing_fn(), self.voice, self.origin)
                self.log.append({"sentence": seg.strip(), "check": r, "said_instead": fixed.strip()})
                logger.info("Jenny's claim gate held back: %r -> %r", seg.strip(), fixed.strip())
                self.out += fixed
            self.done_upto += 1
            await self.on_release(self.out)

    async def finish(self, text: str) -> str:
        """The whole reply is written: check what's left, release everything in order, return the reply as said."""
        self.feed(text)
        rest = text[self.cut:]
        if rest.strip():
            self.cut = len(text)
            self._add(rest)
            self._kick()
        while self._pump is not None and not self._pump.done():
            await self._pump
            if self.done_upto < len(self.queue):
                self._kick()
        return self.out


async def vet(workspace_id, text: str, backed_by: List[str], voice: bool) -> str:
    """A whole text she's about to say (a voice note, a raise, a welcome): every sentence checked, unbacked ones
    repaired. Jev unavailable: unchanged."""
    parts = sentences(text)
    if not parts:
        return text
    checks = await asyncio.gather(*(brain.check_claim(p.strip(), backed_by, "".join(parts[:i]))
                                    for i, p in enumerate(parts)), return_exceptions=True)
    out = ""
    for p, r in zip(parts, checks):
        if isinstance(r, BaseException) or r.get("ok", True):
            out += p
        else:
            fixed = await repair(workspace_id, p, r, out, backed_by, voice)
            logger.info("Jenny's claim gate held back: %r -> %r", p.strip(), fixed.strip())
            out += fixed
    return out.strip() or text
