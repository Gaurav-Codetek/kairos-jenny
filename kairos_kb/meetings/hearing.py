"""Hearing a meeting through its captions.

Meet shows live captions in blocks, one per speaker turn, each carrying the speaker's name. A block keeps changing
while the person talks — the last few words are rewritten as recognition settles — and the same block grows again if
they pick up after a short pause. So a block's words count as said only once it has been still for FINAL_S, and only
the words beyond what was already taken from that block become a new utterance.

Her own speech is captioned too (as "You", or her name): never treated as someone else talking.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

FINAL_S = 1.2           # a block still for this long: its words are settled
BARGE_WORDS = 3         # someone else saying this many new words while she speaks: they're talking over her
SELF = {"you", "jenny", "jenny (kairos)", "jenny kairos"}


def words(text: str) -> List[str]:
    return [w for w in re.split(r"\s+", (text or "").strip()) if w]


@dataclass
class Utterance:
    speaker: str
    text: str
    at: float


@dataclass
class _Block:
    speaker: str
    text: str = ""
    changed: float = 0.0
    taken: int = 0              # words of this block already turned into utterances
    live_from: int = 0          # words already present when she started speaking (for talking over her)


@dataclass
class Hearing:
    me: set = field(default_factory=lambda: set(SELF))
    blocks: Dict[str, _Block] = field(default_factory=dict)

    def mine(self, speaker: str) -> bool:
        return (speaker or "").strip().lower() in self.me

    def caption(self, block_id: str, speaker: str, text: str, now: float) -> None:
        """A caption block as it now reads."""
        if self.mine(speaker):
            return
        b = self.blocks.get(block_id)
        if b is None:
            b = self.blocks[block_id] = _Block(speaker=speaker.strip(), changed=now)
        if text != b.text:
            b.text, b.changed = text, now
            if len(words(text)) < b.taken:  # rewritten shorter than what was taken: keep the count honest
                b.taken = len(words(text))

    def due(self, now: float) -> List[Utterance]:
        """The words that have settled since the last call, as utterances (oldest first)."""
        out: List[Tuple[float, Utterance]] = []
        for bid, b in list(self.blocks.items()):
            ws = words(b.text)
            if now - b.changed >= FINAL_S and len(ws) > b.taken:
                out.append((b.changed, Utterance(b.speaker, " ".join(ws[b.taken:]), b.changed)))
                b.taken = len(ws)
            if now - b.changed > 120:  # long gone from the screen
                self.blocks.pop(bid, None)
        return [u for _, u in sorted(out, key=lambda x: x[0])]

    def she_starts_speaking(self) -> None:
        """Mark what's already been said, so only new words count as talking over her."""
        for b in self.blocks.values():
            b.live_from = len(words(b.text))

    def talking_over(self, now: float, window: float = 2.0) -> Optional[Utterance]:
        """Someone else saying BARGE_WORDS or more new words while she speaks."""
        for b in self.blocks.values():
            new = words(b.text)[b.live_from:]
            if len(new) >= BARGE_WORDS and now - b.changed <= window:
                return Utterance(b.speaker, " ".join(new), b.changed)
        return None


NAME = re.compile(r"\b(jenny|jenni|jennie|jeni|genny|jenny's)\b", re.I)


def mentions_jenny(text: str) -> bool:
    """Her name in the words, as captions write it (they often get it slightly wrong)."""
    return bool(NAME.search(text or ""))


def split_at_name(text: str) -> Tuple[str, str]:
    """(what came before, the question to her): the question starts at the sentence where she's addressed — the last
    mention of her name, so "as Jenny said earlier…" stays context. Meet can put minutes of talk in one caption
    block; only the part from her name on is the request. No name: it's all the question (a follow-up)."""
    text = (text or "").strip()
    hits = list(NAME.finditer(text))
    if not hits:
        return "", text
    at = hits[-1].start()
    start = max(text.rfind(c, 0, at) for c in ".?!")  # the sentence her name is in
    start = 0 if start < 0 else start + 1
    ask = text[start:]
    # Her name tagged on at the end ("Jenny?", "right, Jenny?", "I'm asking you, Jenny"): the question is the sentence
    # before it.
    tagged = not ask[hits[-1].end() - start:].strip(" ,.?!")  # nothing but punctuation after her name
    if tagged and len(words(NAME.sub("", ask).strip(" ,.?!"))) <= 4 and start > 0:
        prev = max(text.rfind(c, 0, start - 1) for c in ".?!")
        start = 0 if prev < 0 else prev + 1
    return text[:start].strip(), text[start:].strip()


TO_HER = re.compile(r"\byou\s+(just\s+)?(said|mentioned|told|showed|meant)\b|\byour\s+(number|answer|figure)s?\b", re.I)


def refers_to_her(text: str) -> bool:
    """Words that point back at what she said ("the volume you mentioned, correct?"): maybe for her, without her name."""
    return bool(TO_HER.search(text or ""))
