"""Jenny's brain: how she reads a turn before she answers it.

A person in a conversation doesn't turn every remark into a report. They first take in what kind of
turn it was (a question, a passing reaction, a correction, a goodbye), how the other person feels, and
what's called for — a quick answer, a question back, a word of reassurance, or something worth raising —
and only then speak. Jenny does the same, in two layers answered together in one fast call to Jev
(TypeSafe's System One model, which returns calibrated choices rather than text):

  perception   what kind of turn this is · the owner's mood · urgency · confusion · whether it could mean
               two things · whether they want detail · whether the topic changed
  the thread   where the conversation stands: is the matter settled, and has she already said what she'd say now
               (her own recent replies are in what Jev sees, so she notices herself repeating)
  decision     her move (answer briefly or in depth, ask back, empathise first, just acknowledge, raise
               something, small talk, wrap up) · her tone · how long to be · whether live data is needed

Before she speaks, the read becomes a short private note to herself (inner_note): where we are, how they seem,
what she has already said and promised. She speaks from that, the way a person does, rather than from rules.

The read becomes guidance for the model that words her reply; a judgment Jev isn't confident about is
left out, and the model decides that part itself. When no data is needed she answers without tools,
which is quicker. Every read is logged (data/logs/jenny_brain.jsonl) with what happened next, so the
criteria can be refined from real conversations — and, later, a model trained on them.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

CONFIDENT = 0.55          # below this, a choice is left to the model
SELF_CONTAINED = 0.6      # at or above: the turn stands on its own (may be answered again from memory)
AMBIGUOUS = 0.6           # at or above this (and when asking is fair), she asks which one is meant
TIMEOUT_S = 4.0
LOG = Path("data/logs/jenny_brain.jsonl")


def questions() -> Dict[str, Any]:
    from typesafe_sdk import Choice, Noul, NoulCriteria, Score

    return {
        # ── layer 2 · perception ──
        "turn_kind": Choice(
            instructions=("What kind of turn is the owner's latest message, given the conversation so far? Judge the "
                          "latest message (owner_said) in its context, not the whole conversation."),
            criteria={
                "question": {"what": "Asks for information Jenny hasn't given yet.",
                             "examples": ["How are we doing today?", "Which city is behind?", "What's GMV so far?"]},
                "follow_up": {"what": "Builds on Jenny's last answer: asks for more, a breakdown, a why, or the same "
                                      "for something else.",
                              "examples": ["Why?", "And Pune?", "Break that down by city", "What about yesterday?"]},
                "reaction": {"what": "A comment or feeling about what Jenny just said, with no request in it.",
                             "not_for": "Statements that really ask something, like 'I wonder why Pune is down'.",
                             "examples": ["Hmm, interesting", "Oh wow", "That makes sense", "Okay good"]},
                "correction": {"what": "Says Jenny misunderstood, misheard, or answered the wrong thing.",
                               "not_for": "A new question asked in frustration, unless it says Jenny got something wrong.",
                               "examples": ["No, I meant Patna", "Not orders, GMV", "That's not what I asked"]},
                "instruction": {"what": "Asks Jenny to do something rather than tell something: flag, report, keep "
                                        "an eye on, remember, change how she talks.",
                                "examples": ["Flag this to the data team", "Keep it shorter", "Remember I care about Pune"]},
                "small_talk": {"what": "Social talk not about the numbers: greetings, how are you, jokes, thanks "
                                       "mid-conversation.",
                               "examples": ["Hey Jenny", "How's your day?", "You're funny", "Thanks, that helps"]},
                "closing": {"what": "Ends the conversation.",
                            "examples": ["That's all for now", "Bye", "Thanks, talk later"]},
                "unclear": {"what": "Too garbled, cut off or fragmentary to tell what is meant.",
                            "examples": ["Uh what about the", "Can you the", "Hmm so"]},
            }),
        "emotion": Choice(
            instructions="How does the owner seem to feel right now, from their words and how they spoke?",
            criteria={
                "neutral": "Matter-of-fact, no particular feeling.",
                "curious": "Interested, exploring, wants to understand.",
                "worried": "Concerned something is wrong or might go wrong.",
                "frustrated": "Annoyed — with the numbers, the business, or with Jenny's answers.",
                "pleased": "Happy or relieved about something.",
                "impatient": "Wants it faster or shorter; cut Jenny off or pushed for the point.",
                "playful": "Joking or teasing, light-hearted.",
            }),
        "urgency": Noul(instructions="Does the owner need this right now — something seems to be going wrong, or "
                                     "they need to act soon?"),
        "confused": Noul(instructions="Is the owner confused by something Jenny said, or unsure what it means?"),
        "ambiguous": Noul(
            instructions=("Could the latest message reasonably mean two quite different things, with the conversation "
                          "not settling which?"),
            criteria=NoulCriteria(true="e.g. 'what about that city' when two cities were just discussed; a name that "
                                       "could be a city or a restaurant.",
                                  false="The meaning is clear from the words or the conversation.")),
        "wants_detail": Noul(instructions="Does the owner want depth and specifics rather than the headline?"),
        "new_topic": Noul(instructions="Does the latest message move to a different subject from Jenny's last answer?"),

        # ── the thread: where the conversation stands ──
        "thread_settled": Noul(
            instructions=("Is the matter Jenny and the owner were just discussing settled — answered, agreed or decided, "
                          "with nothing left open — so that the owner's latest words close it off rather than ask for "
                          "anything more?"),
            criteria=NoulCriteria(true="Jenny proposed a plan and the owner said 'yeah thanks'; she answered and they "
                                       "said 'great, thank you'; they said 'okay, that's all'.",
                                  false="A question is still unanswered, the owner asks for more, or brings something new.")),
        "jenny_already_said": Noul(
            instructions=("Look at Jenny's recent replies in the conversation. Has she already said what a reply to the "
                          "owner's latest words would naturally say — the same confirmation, plan, promise or summary?"),
            criteria=NoulCriteria(true="She confirmed the watch plan in her last reply and the owner is just thanking "
                                       "her; she gave today's numbers and they say 'okay'.",
                                  false="The owner asks something she hasn't covered, or a new fact matters now.")),

        # ── layer 3 · decision ──
        "move": Choice(
            instructions=("Given the turn and the owner's mood, what should Jenny do next, the way a sharp, warm chief "
                          "of staff would?"),
            criteria={
                "answer_brief": "Give the answer in a sentence or two; let the owner steer from there.",
                "answer_deep": "Give a fuller answer with the key specifics — the owner wants depth or it's complex.",
                "ask_back": {"what": "Ask one short clarifying question before answering.",
                             "not_for": "Anything the conversation already makes clear."},
                "empathise_then_answer": "Acknowledge how the owner feels in a few words, then answer.",
                        "acknowledge": {"what": "Respond briefly and naturally to a reaction, a comment or thanks; add "
                                        "nothing she has already said; no report.",
                                "examples": ["after 'Hmm, interesting'", "after 'Okay good'", "after 'yeah, thank you' "
                                             "once a plan is agreed"]},
                "raise_something": {"what": "Answer, then bring up one thing from today's live picture the owner "
                                            "hasn't heard yet and would want to know.",
                                    "not_for": "A thank-you, a goodbye, or a matter that's settled; anything Jenny "
                                               "already said."},
                "small_talk": "Reply socially, warmly and briefly; no numbers unless asked.",
                "wrap_up": "Close the conversation gracefully in a sentence.",
            }),
        "tone": Choice(
            instructions="What tone should Jenny take in her reply?",
            criteria={"calm": "Steady and even.", "warm": "Friendly and personal.", "upbeat": "Positive, energetic.",
                      "concerned": "Serious and caring — something is wrong.", "playful": "Light, a touch of wit."}),
        "length": Score(
            instructions="How long should Jenny's reply be, spoken or written?",
            criteria=["A few words.", "A sentence or two.", "A short paragraph.", "A detailed answer."]),
        "sets_preference": Noul(
            instructions=("Is the owner telling Jenny how to speak to them from now on: how to address them, a word or "
                          "name to use or avoid, or how to say something?"),
            criteria=NoulCriteria(true="'Call me partner.' / 'Say gross merchandise value, not GMV.' / 'No need to "
                                       "greet me every time.'",
                                  false="A question about the business, a reaction, or a request about this answer only.")),
        "sets_focus": Noul(
            instructions=("Is the owner telling Jenny something to keep watching, a decision they've made, or a plan to "
                          "come back to later?"),
            criteria=NoulCriteria(true="'Keep an eye on Bangalore.' / 'We're pausing the Pune promo.' / 'Let's look at "
                                       "delivery times again on Friday.'",
                                  false="A question, a reaction, or how they'd like to be spoken to.")),
        "beyond_abilities": Noul(
            instructions="Does the owner ask Jenny to do something that isn't among what she can do (jenny_can)?",
            criteria=NoulCriteria(true="'Email me the summary.' / 'Text me if it drops.' / 'Change the order status.'",
                                  false="Anything jenny_can covers: a question about the numbers, keeping an eye on "
                                        "a metric, checking something later, filing a data report.")),
        "visual_helps": Noul(
            instructions=("Would a chart on screen make Jenny's answer to the owner's latest words clearer — a "
                          "breakdown by city or restaurant, today against normal, particular hours, or a key figure?"),
            criteria=NoulCriteria(true="'Which cities are driving cancellations?' / 'How's today tracking against "
                                       "normal?' / 'Show me the morning hours' / 'Compare GMV and orders'.",
                                  false="Thanks, greetings, small talk, a yes or no, how to speak, keeping an eye on "
                                        "something, or a one-number answer that's clear in words.")),
        "needs_data": Noul(
            instructions=("Does answering well need Jenny to look up live data or her notes now, beyond what is already "
                          "in this conversation or in the business_now summary?"),
            criteria=NoulCriteria(true="New numbers, a breakdown, a comparison, or anything not already stated.",
                                  false="Small talk, reactions, thanks, goodbyes, or something already answered.")),
    }


def alone_questions() -> Dict[str, Any]:
    """Asked of the message alone — no conversation shown — because that's exactly the question: would it make sense to
    someone who hadn't heard what came before? (Shown the conversation, Jev marks a repeated question as leaning on it.)"""
    from typesafe_sdk import Noul, NoulCriteria

    return {
        "self_contained": Noul(
            instructions="Could this message be understood and answered on its own, with no conversation before it?",
            criteria=NoulCriteria(true="A full question that names what it's about: 'How many orders were delivered "
                                       "today?', 'GMV today?', 'How are cancellations in Mumbai this afternoon?'",
                                  false="It leans on something said before ('And Pune?', 'what about that city', "
                                        "'why?', 'the second one'), or it isn't a question (thanks, a reaction, small "
                                        "talk).")),
    }


def state_for(owner_said: str, history: List[Dict[str, Any]], *, voice: bool, cut_in: Optional[str],
              business_now: Dict[str, Any], desk: Optional[List[str]] = None,
              abilities: Optional[List[str]] = None) -> Dict[str, Any]:
    """What Jev sees: the owner's latest words, the conversation, how they spoke, the live picture, and what's on
    Jenny's desk (the watches and checks she has committed to)."""
    turns = []
    for item in history[-12:]:
        role, content = item.get("role"), item.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            turns.append({"who": "owner" if role == "user" else "jenny", "said": content.strip()[:400]})
    return {
        "owner_said": owner_said,
        "channel": "voice call" if voice else "typed chat",
        "conversation": turns[-6:],
        "how_they_spoke": ({"cut_jenny_off": True, "jenny_had_said": cut_in[-300:]} if cut_in is not None
                           else {"cut_jenny_off": False}),
        "business_now": business_now,
        "on_jennys_desk": desk or ["(nothing)"],
        "jenny_can": abilities or [],
    }


async def read(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Jenny's read of the turn, or None when Jev isn't available (she then answers on the model's judgment)."""
    from kairos_kb.config import get_settings

    settings = get_settings()
    if not settings.typesafe_api_key:
        return None
    try:
        from typesafe_sdk import AsyncTypeSafeClient
    except ImportError:
        return None
    client = AsyncTypeSafeClient(api_key=settings.typesafe_api_key, model=settings.typesafe_model or None,
                                 timeout=TIMEOUT_S)
    started = time.perf_counter()
    try:
        response, alone = await asyncio.gather(
            client.system_one(state=state, questions=questions(), timeout=TIMEOUT_S),
            client.system_one(state={"message": state.get("owner_said", "")}, questions=alone_questions(),
                              timeout=TIMEOUT_S),
            return_exceptions=True)
        if isinstance(response, BaseException):
            raise response
    except Exception as exc:  # noqa: BLE001 — the conversation never waits on this
        logger.warning("Jenny's read failed: %s", exc)
        return None
    finally:
        await client.aclose()
    out: Dict[str, Any] = {"latency_ms": round((time.perf_counter() - started) * 1000), "model": response.model}
    answers = dict(response.answers)
    if not isinstance(alone, BaseException):
        answers.update(alone.answers)
    for name, a in answers.items():
        if a.type == "choice":
            out[name] = {"choice": a.choice, "confidence": round(a.confidence, 3),
                         "probabilities": {k: round(v, 3) for k, v in a.probabilities.items()}}
        elif a.type == "noul":
            out[name] = round(a.noul, 3)
        else:
            out[name] = {"score": round(a.score, 2), "confidence": round(a.confidence, 3),
                         "first_level": min(a.legend) if a.legend else 0}
    return out


def _confident(r: Dict[str, Any], key: str) -> Optional[str]:
    a = r.get(key) or {}
    return a.get("choice") if isinstance(a, dict) and a.get("confidence", 0) >= CONFIDENT else None


MOVES = {
    "answer_brief": "Answer in a sentence or two, then stop and let them steer. No offer of more unless it really helps.",
    "answer_deep": "Give a fuller answer with the key specifics; still lead with the point.",
    "ask_back": "Ask ONE short clarifying question instead of answering; don't guess. Name the two readings briefly.",
    "empathise_then_answer": "Start with a few human words that meet how they feel (not 'I understand your concern'), "
                             "then answer.",
    "acknowledge": "This was a reaction, not a request: respond naturally in a few words, maybe add one small thing. "
                   "No report, no list of numbers, and don't offer anything.",
    "raise_something": "Answer, then add the one thing from today's picture they'd want to know.",
    "small_talk": "Reply like a person — warm, brief, a light touch is fine. No numbers unless they ask, and no "
                  "offers or either-or questions.",
    "wrap_up": "Close warmly in ONE sentence. No recap, no numbers, no new information.",
}
TONES = {"calm": "thoughtful", "warm": "warm", "upbeat": "upbeat", "concerned": "concerned", "playful": "upbeat"}
LENGTH = ["a few words", "a sentence or two", "a short paragraph", "a detailed answer"]


FEELINGS = {
    "frustrated": "Open with a few honest words that meet their frustration — e.g. \"Fair enough —\", \"I hear you —\" — "
                  "never \"I understand your concern\" — once, at the very start, not again later. Then get straight to it.",
    "worried": "Open by steadying them in a few words (what's fine, or that you'll find out), then answer.",
    "impatient": "Skip any preamble: the answer first, in as few words as it takes.",
    "pleased": "Share their good mood briefly before anything else.",
    "playful": "Match their lightness for a moment; a dry touch of wit is welcome.",
}


SETTLED = 0.6  # thread_settled / jenny_already_said at or above: the matter is closed, or she's said it already
REQUESTS = ("question", "follow_up", "instruction", "correction")
ASKS = 0.5    # at or above: the turn more likely asks for something than not


def asks(r: Dict[str, Any]) -> float:
    """How likely the turn asks for something, summed over Jev's turn kinds — so a request it can't place with
    confidence still counts: "okay up the tell me whether the field has started again" (a misheard "feed") read as
    question .27 + instruction .22 + follow-up .03, with no single kind confident."""
    kind = r.get("turn_kind")
    p = (kind.get("probabilities") or {}) if isinstance(kind, dict) else {}
    return sum(p.get(k) or 0.0 for k in REQUESTS)


def decide(r: Dict[str, Any], last_reply: str = "") -> Dict[str, Optional[str]]:
    """Her move for this turn, from the read: Jev's confident judgments, settled by how people actually talk."""
    kind, mood, move, tone = (_confident(r, k) for k in ("turn_kind", "emotion", "move", "tone"))
    settled, said = r.get("thread_settled") or 0.0, r.get("jenny_already_said") or 0.0
    if kind == "closing":
        move = "wrap_up"
    elif kind in SOCIAL and (settled >= SETTLED or said >= SETTLED):
        move = "acknowledge"  # a thank-you once it's all agreed: a few words, not the plan again
    elif move == "raise_something" and (said >= SETTLED or kind in SOCIAL):
        move = "acknowledge" if kind in SOCIAL else "answer_brief"
    elif not move:  # the kind of turn, read confidently, settles the move for these
        move = {"small_talk": "small_talk", "reaction": "acknowledge", "unclear": "ask_back"}.get(kind or "")
    # A request is answered, never just acknowledged — even one Jev couldn't place (garbled speech).
    if move in ("acknowledge", "small_talk") and kind not in SOCIAL and asks(r) >= ASKS:
        move = "answer_brief"
    # Ask back only when it's fair: a real question that could mean two things, from someone who isn't already
    # annoyed, and not straight after she asked something herself. A correction has just made things clearer.
    fair = kind in ("question", "follow_up") and mood not in ("frustrated", "impatient") and         not last_reply.rstrip().endswith("?")
    if (r.get("ambiguous") or 0) >= AMBIGUOUS and fair:
        move = "ask_back"
    elif move == "ask_back" and not fair and kind != "unclear":
        move = "answer_brief"
    return {"kind": kind, "mood": mood, "move": move, "tone": tone}


_LEAD = re.compile(r"^\s*(?:\[[a-z]+\]\s*)?([^.,;:!?—–-]{1,40}?)\s*[—–,.:;!?-]")


def openers(replies: List[str]) -> List[str]:
    """How her recent replies began ("Understood", "Fair enough"): a person notices saying the same thing each time."""
    out = []
    for t in replies:
        m = _LEAD.match(t or "")
        if m and len(m.group(1).split()) <= 4:
            out.append(m.group(1).strip())
    return out


def inner_note(r: Optional[Dict[str, Any]], recent_replies: List[str], desk: List[str]) -> str:
    """What she knows about this moment before she speaks, in her own words: where the conversation stands, how they
    seem, what she's already said and promised. Built from Jev's read; she speaks from it."""
    if not r:
        return ""
    d = decide(r, recent_replies[-1] if recent_replies else "")
    kind, mood = d["kind"], d["mood"]
    notes = []
    if (r.get("thread_settled") or 0) >= SETTLED:
        notes.append("What we were discussing is settled; nothing is left open.")
    if (r.get("jenny_already_said") or 0) >= SETTLED:
        notes.append("I've already said what I'd say now — saying it again would be repeating myself.")
    if kind in SOCIAL:
        notes.append({"small_talk": "They're being social, not asking for anything.",
                      "reaction": "They're reacting, not asking for anything.",
                      "closing": "They're wrapping up."}[kind])
    if mood and mood != "neutral":
        notes.append(f"They sound {mood}.")
    seen = openers(recent_replies[-3:])
    repeated = sorted({o for o in seen if seen.count(o) >= 2})
    if repeated:
        notes.append("My last replies kept opening with \"" + "\", \"".join(repeated) + "\" — I'll start differently.")
    if desk:
        notes.append("Already on my desk: " + "; ".join(desk[:4]) + ". No need to promise those again.")
    if not notes:
        return ""
    return "\n\n# Where we are (my own note before I speak)\n" + " ".join(notes)


def aware(r: Optional[Dict[str, Any]]) -> str:
    """What she's aware of about this turn, said beside the owner's words (where a model pays most attention): that
    the matter is settled and she's said it all, or that they've asked for something beyond her. Empty when neither."""
    if not r:
        return ""
    out = []
    if (r.get("beyond_abilities") or 0) >= 0.6:
        out.append("what they ask for, as asked, is beyond what I can do: I'll say so plainly first, then what I can "
                   "do instead")
    d = decide(r)
    if d["move"] in ("acknowledge", "wrap_up") and ((r.get("thread_settled") or 0) >= SETTLED
                                                    or (r.get("jenny_already_said") or 0) >= SETTLED):
        out.append("this is settled and I've already said everything on it: a few words back, nothing I've said "
                   "before, no question")
    return f"\n\n(My own awareness, not the owner's words: {'; '.join(out)}.)" if out else ""


def guidance(r: Optional[Dict[str, Any]], voice: bool, last_reply: str = "") -> str:
    """Her read, as instructions for the model wording the reply. Only confident judgments are passed on."""
    if not r:
        return ""
    lines = []
    d = decide(r, last_reply)
    kind, mood, move, tone = d["kind"], d["mood"], d["move"], d["tone"]
    if kind:
        lines.append(f"- The owner's turn is a {kind.replace('_', ' ')}.")
    if mood and mood != "neutral" and move != "wrap_up":
        lines.append(f"- They seem {mood}. " + FEELINGS.get(mood, "Let that shape how you say it."))
    if (r.get("ambiguous") or 0) >= AMBIGUOUS and move != "ask_back" and kind in ("question", "follow_up", "correction"):
        lines.append("- It could mean more than one thing: answer the most likely reading and say in a few words "
                     "which one you took.")
    if (r.get("urgency") or 0) >= 0.6:
        lines.append("- It feels urgent to them: get to the point first.")
    if sets_focus(r):
        lines.append("- They're telling you something to watch, a decision, or a plan. Something to watch goes on your "
                     "desk (keep_watch, or check_later for a later look) before you say you'll do it; a decision you "
                     "simply remember. If a decision has a real downside, name it once.")
    if sets_preference(r):
        lines.append("- They're telling you how to speak to them from now on: say in a few words that you will, and do "
                     "it from this answer on.")
    if (r.get("beyond_abilities") or 0) >= 0.6:
        lines.append("- They asked for something you can't do as asked: say so plainly in a few words (\"I can't send "
                     "email\"), then what you can do instead — don't quietly do something else.")
    if (r.get("confused") or 0) >= 0.6:
        lines.append("- They seem confused by something you said: clear it up simply, without repeating yourself.")
    if move:
        lines.append(f"- Your move: {MOVES[move]}")
    length = r.get("length") or {}
    if length.get("confidence", 0) >= CONFIDENT:
        idx = max(0, min(3, round(length["score"]) - int(length.get("first_level", 0))))
        lines.append(f"- Length: {LENGTH[idx]}.")
    if tone:
        lines.append(f"- Tone: {tone}" + (f" (use the [{TONES[tone]}] cue)." if voice else "."))
    # People don't end every turn by offering more: a habit like that is what sounds like a machine.
    if ended_with_offer(last_reply) and move != "ask_back":
        lines.append("- Your last reply ended with an offer or a question. This time, end on a statement — no offer, "
                     "no question.")
    if not lines:
        return ""
    return ("\n\n# How to handle this turn\nYou read the owner's last message before answering. Follow this read "
            "unless the facts make it wrong:\n" + "\n".join(lines))


_OFFER = re.compile(r"(if you (want|like|'d like)|want me to|shall i|should i|i can (pull|show|check|break|look|dig))", re.I)


_LOOKING = re.compile(r"\b(let me|let's|i'?ll|i will|i'?m going to)\s+(just\s+|quickly\s+|now\s+)?"
                      r"(check|pull|look|see|find|fetch|get|dig|read|(take|have)\s+a\s+(quick\s+)?look)\b", re.I)


def announces_lookup(text: str) -> bool:
    """She says she's about to look something up ("Let me pull the latest feed status") — a promise only a lookup in
    the same turn keeps."""
    return bool(_LOOKING.search(text or ""))


def ended_with_offer(reply: str) -> bool:
    """Her last reply closed with an offer or a question ("Want me to…?", "If you like, I can…")."""
    tail = re.split(r"(?<=[.!?])\s+", reply.strip())[-1] if reply.strip() else ""
    return tail.endswith("?") or bool(_OFFER.search(tail))


# Turns that never need a lookup — a thank-you, a reaction, a goodbye — when read with confidence.
SOCIAL = ("small_talk", "reaction", "closing")


def stands_alone(r: Optional[Dict[str, Any]]) -> Optional[bool]:
    """A self-contained question — not a follow-up ("and Pune?"), a reaction or small talk: the only kind of turn an
    answer from a few minutes ago can answer again. Jev's own read of exactly that (a repeat of an earlier question
    counts, which "is it a new question" would hesitate over). Unsure means no: memory is only a shortcut. None when
    there's no read at all."""
    if not r:
        return None
    if _confident(r, "turn_kind") in SOCIAL:
        return False  # "Hmm, interesting." is understood on its own, but it isn't a question
    alone = r.get("self_contained")
    if alone is None:  # a read without this judgment
        return _confident(r, "turn_kind") == "question"
    return alone >= SELF_CONTAINED


def quick(r: Optional[Dict[str, Any]], last_reply: str = "") -> bool:
    """No live data needed and a move that never needs it: answer without tools (faster). The kind of turn decides
    first — Jev reads it reliably ("Okay thank you" is small talk at 0.8), while its sense of whether live data is
    needed is the weaker signal (it put a thank-you and a data question both near 0.4)."""
    if not r:
        return False
    if _confident(r, "turn_kind") in SOCIAL:
        return True
    move = decide(r, last_reply)["move"]
    if move in ("ask_back", "wrap_up"):
        return True
    if asks(r) >= ASKS:
        return False  # it asks for something: she may need to look, whatever needs_data says (it said .15 to "has
                      # the feed started again?")
    if move == "small_talk":
        return (r.get("needs_data") or 1) < 0.5
    return (r.get("needs_data") or 1) < 0.35 and move in ("acknowledge", "small_talk", "wrap_up", "empathise_then_answer",
                                                          "ask_back")


def summary(r: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The read in brief, for the screen and the record."""
    if not r:
        return None
    pick = lambda k: (r.get(k) or {}).get("choice") if isinstance(r.get(k), dict) else None  # noqa: E731
    conf = lambda k: (r.get(k) or {}).get("confidence") if isinstance(r.get(k), dict) else None  # noqa: E731
    return {"turn": pick("turn_kind"), "turn_confidence": conf("turn_kind"), "emotion": pick("emotion"),
            "move": pick("move"), "move_confidence": conf("move"), "tone": pick("tone"),
            "needs_data": r.get("needs_data"), "ambiguous": r.get("ambiguous"), "latency_ms": r.get("latency_ms")}


def log(record: Dict[str, Any]) -> None:
    """One line per read, for refining the criteria later (and, one day, training a model on them)."""
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(), **record}, default=str) + "\n")
    except OSError:
        logger.debug("Could not write the brain log", exc_info=True)


_OPENER = re.compile(r"^\s*(?:\[[a-z]+\]\s*)?([A-Za-z' ]{2,30}?)\s*[—–-]\s+")


def drop_repeated_opener(first_line: str, answer: str) -> str:
    """"Fair enough — I'll check…" then "Fair enough — they aren't high": a person says it once."""
    m = _OPENER.match(first_line or "")
    if not m:
        return answer
    again = re.match(r"^(\s*(?:\[[a-z]+\]\s*)?)" + re.escape(m.group(1)) + r"\s*[—–-]\s+", answer or "", re.I)
    return (again.group(1) + answer[again.end():]) if again else answer


# ── thinking out loud: what to say while working, and when there's enough ────

def narration_questions() -> Dict[str, Any]:
    from typesafe_sdk import Choice, Noul, NoulCriteria

    return {
        "line_kind": Choice(
            instructions=("Jenny is working on the owner's question and is about to say candidate_line aloud before her "
                          "next lookup. What kind of line is it, given what she has already said aloud this turn?"),
            criteria={
                "plan": {"what": "Says what she's going to look at — the first time she says it this turn."},
                "restating": {"what": "Says again, in other words, a plan or step she has already said this turn.",
                              "examples": ["'I'll pull today's GMV for five a.m.' after 'Let me get the five a.m. GMV.'"]},
                "change_of_route": {"what": "Says the last try didn't give what was needed, and what she'll try instead."},
                "reaction": {"what": "Reacts to what a result showed, in a few words, before looking further."},
            }),
        "new_to_owner": Noul(
            instructions="Does candidate_line tell the owner anything they haven't already heard from Jenny this turn?",
            criteria=NoulCriteria(true="A first plan, a change of route, or something a result showed.",
                                  false="The same plan or step again, however it's worded.")),
        "owner_cares": Noul(
            instructions=("Would the owner care to hear candidate_line? They care about their business, and about "
                          "anything that stands between them and what they asked for (it isn't available, it hasn't "
                          "happened yet, she has to go another way). They don't care about Jenny fixing a slip in how "
                          "she asked — a misspelt name, a wrong label, a retry with the right parameter."),
            criteria=NoulCriteria(true="'That gave me IDs, not the names you asked for — let me try another way.' / "
                                       "'Lucknow's the one slipping.' / 'The two o'clock hour hasn't happened yet.'",
                                  false="'The metric label failed; I'll request gmv instead.' / 'Retrying with the "
                                        "correct field name.'")),
    }


SAY_NEW = 0.5  # new_to_owner at or above: worth saying


async def narrate(question: str, said: List[str], line: str, last_lookup: str) -> Dict[str, Any]:
    """Should Jenny say this line aloud while she works? A person says their plan once, then speaks again only when
    something changes — a try that didn't work and the new route, or what a result showed. Without a read, a line
    is said only after a lookup that failed (a change of route is worth hearing)."""
    state = {"owner_question": question, "said_aloud_this_turn": said or ["(nothing yet)"], "candidate_line": line,
             "last_lookup": last_lookup}
    r = await _one(state, narration_questions())
    if r is None:
        return {"say": not said or last_lookup.startswith("failed"), "read": None}
    kind = _confident(r, "line_kind")
    new, cares = r.get("new_to_owner") or 0.0, r.get("owner_cares")
    say = (new >= SAY_NEW and kind != "restating" and not (kind == "plan" and said)
           and (cares is None or cares >= SAY_NEW))  # a slip she's quietly fixing isn't worth saying
    return {"say": say, "kind": kind, "new": new, "cares": cares, "latency_ms": r.get("latency_ms")}


def enough_questions() -> Dict[str, Any]:
    from typesafe_sdk import Noul, NoulCriteria

    return {
        "enough": Noul(
            instructions="Do the lookup results so far contain what's needed to answer the owner's question?",
            criteria=NoulCriteria(true="The numbers or facts the question asks for are in the results — even if the "
                                       "answer is 'nothing unusual'.",
                                  false="Something the question needs is missing, or the lookups failed or came back "
                                        "about something else.")),
    }


ENOUGH = 0.8  # at or above: answer now rather than look further


async def enough(question: str, results: List[str]) -> Optional[float]:
    """How likely the results so far already answer the question (None without a read)."""
    r = await _one({"owner_question": question, "results": results or ["(none)"]}, enough_questions())
    return None if r is None else r.get("enough")


async def _one(state: Dict[str, Any], qs: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """One quick Jev read with these questions, parsed; None when Jev isn't available."""
    from kairos_kb.config import get_settings

    settings = get_settings()
    if not settings.typesafe_api_key:
        return None
    try:
        from typesafe_sdk import AsyncTypeSafeClient
    except ImportError:
        return None
    client = AsyncTypeSafeClient(api_key=settings.typesafe_api_key, model=settings.typesafe_model or None, timeout=TIMEOUT_S)
    started = time.perf_counter()
    try:
        response = await client.system_one(state=state, questions=qs, timeout=TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 — never holds anything up
        logger.debug("Jev read failed: %s", exc)
        return None
    finally:
        await client.aclose()
    out: Dict[str, Any] = {"latency_ms": round((time.perf_counter() - started) * 1000)}
    for name, a in response.answers.items():
        if a.type == "choice":
            out[name] = {"choice": a.choice, "confidence": round(a.confidence, 3)}
        elif a.type == "noul":
            out[name] = round(a.noul, 3)
    return out


# ── an interruption: does it add to the request in progress, correct it, or replace it? ──

def relation_questions() -> Dict[str, Any]:
    from typesafe_sdk import Choice

    return {
        "relation": Choice(
            instructions=("Jenny was working on the owner's earlier request (earlier_request) when the owner spoke again "
                          "(new_words). How do the new words relate to the earlier request?"),
            criteria={
                "adds_to": {"what": "Adds to the same request: another measure, place, period or angle to cover as well.",
                            "examples": ["also by cancellation rate", "and for Pune too", "include last week as well"]},
                "corrects": {"what": "Changes part of the earlier request: it was misheard, or they meant something else.",
                             "examples": ["no, delivered orders not GMV", "I meant yesterday", "sorry, Mumbai not Pune"]},
                "replaces": {"what": "A different request; the earlier one no longer matters.",
                             "examples": ["forget that, how's GMV today?", "actually, what's our best city right now?"]},
                "aside": {"what": "A remark that needs no change to the work.",
                          "examples": ["take your time", "okay, go on", "sure"]},
            }),
    }


ADDS = re.compile(r"^\s*(also|and|plus|as well|too|include|along with)\b", re.I)


async def relation(earlier: str, heard: str, new: str) -> Dict[str, Any]:
    """How an interruption relates to the request she was working on (Jev). Without a read, words that open like an
    addition ("also…", "and…") add to it; anything else replaces it."""
    r = await _one({"earlier_request": earlier, "jenny_had_said": heard or "(nothing yet)", "new_words": new},
                   relation_questions())
    kind = _confident(r, "relation") if r else None
    if kind is None:
        return {"relation": "adds_to" if ADDS.search(new) else "replaces", "read": None}
    return {"relation": kind, "confidence": r["relation"]["confidence"], "latency_ms": r.get("latency_ms")}


ask_jev = _one  # for other parts of Kairos that need a quick typed judgment (the report loop)


# ── in a meeting: words someone said, read the way a person in the room would ─────────

def meeting_questions() -> Dict[str, Any]:
    from typesafe_sdk import Noul, NoulCriteria

    return {
        "addressed": Noul(
            instructions=("In a meeting with several people, are `words` (said by `speaker`) spoken to Jenny — the AI "
                          "assistant in the call — asking her something, asking her to do something, checking "
                          "something with her, or thanking her?"),
            criteria=NoulCriteria(true="'Jenny, how did Pune do?' / 'Hey Jenny, how are you?' / 'Can you tell me about "
                                       "cancellations?' right after someone said 'Hey, Jenny' / 'And Delhi?' from the "
                                       "person she just answered / 'that's what you mentioned, correct?' right after "
                                       "she answered / 'Thanks, Jenny.'",
                                  false="People talking to each other; mentioning her ('as Jenny said earlier'); "
                                        "reading out a number.")),
        "finished": Noul(
            instructions="Has the speaker finished what they want to say, or did they stop mid-thought?",
            criteria=NoulCriteria(true="A complete question, request, remark or thanks.",
                                  false="'Jenny, listen, actually I wanted…' / 'And what about?' / 'Jenny, can you'")),
        "bears": Noul(
            instructions=("Does what the speaker said just before (`before`) bear on their words to Jenny — explaining "
                          "which thing they mean, what the problem is, or why they're asking?"),
            criteria=NoulCriteria(true="before: 'we see data loss on weekend mornings, we have to fix it' / words: "
                                       "'Jenny, what was the exact timing on Saturday and Sunday?'",
                                  false="before: talk about lunch or another topic, or nothing / words: 'Jenny, how "
                                        "is GMV today?'")),
        "agreement": Noul(
            instructions=("Is the speaker asking Jenny to confirm or agree with something — a point they made, or "
                          "their understanding of what she said?"),
            criteria=NoulCriteria(true="'Kochi's rate is higher because of fewer orders, right Jenny?' / 'so that was "
                                       "the order volume you mentioned, correct?' / 'you agree?'",
                                  false="A new question; a request to look something up; thanks.")),
        "dismisses": Noul(
            instructions=("Is the speaker telling Jenny their earlier words weren't meant for her, or asking her to "
                          "stop or stay out of it?"),
            criteria=NoulCriteria(true="'Not you, Jenny.' / 'Jenny, we're talking among ourselves.' / 'Jenny, stop.' / "
                                       "'No no, I wasn't asking you.'",
                                  false="A question for her; a correction of her numbers; thanks.")),
        "needs_look": Noul(
            instructions=("To answer `words`, would Jenny have to look something up — numbers, a breakdown, a "
                          "comparison — rather than reply straight away?"),
            criteria=NoulCriteria(true="'Jenny, how did Pune do?' / 'And which items sell most in the north?' / 'What's "
                                       "the cancellation rate there?'",
                                  false="'Hi Jenny, how are you?' / 'Thanks, Jenny.' / 'Right, Jenny?' / 'Jenny, stop.'")),
    }


ADDRESSED = 0.6  # at or above: the words are for her, and she answers
BEARS = 0.6      # what came before bears on the question: she uses it, and may link back to it
AGREES = 0.6     # they're checking something with her: she confirms or corrects, plainly first
DISMISSES = 0.6  # "not you" / "stop": she stops, says a word or two and goes quiet — unless it's more a request
FINISHED = 0.45  # below: they stopped mid-thought — she waits for the rest
LOOKS = 0.5      # at or above: answering needs a lookup — she says "mm-hm, one sec" the moment they finish


async def meeting_read(speaker: str, words: str, before: str, recent: List[str],
                       jenny_last: str = "") -> Optional[Dict[str, float]]:
    """How words said in a meeting land on Jenny: for her? finished? does what came before matter? checking something
    with her? telling her it wasn't for her? One Jev read (None without Jev)."""
    r = await _one({"speaker": speaker, "words": words, "before": (before or "(nothing)")[-1500:],
                    "said_just_before": recent[-6:] or ["(nothing yet)"],
                    "jenny_last_said": jenny_last[-300:] or "(nothing yet)"}, meeting_questions())
    if r is None:
        return None
    return {k: float(r.get(k) or 0.0) for k in ("addressed", "finished", "bears", "agreement", "dismisses", "needs_look")}


def dismissed(r: Dict[str, float]) -> bool:
    """Told to stop, or that it wasn't for her — and that more than it's a request. 'So Jenny, North Indian cities: I
    want to know what people order most', right after a 'no no, stop', read addressed .86 and dismisses .61: a
    question, not a dismissal."""
    return r.get("dismisses", 0.0) >= DISMISSES and r.get("dismisses", 0.0) > r.get("addressed", 0.0)


_OPENS_LOOKING = re.compile(r"^\s*(\[[a-z]+\]\s*)?((okay|ok|sure|alright|right|so)[,.]?\s+)?" + _LOOKING.pattern, re.I)


def opens_with_lookup(sentence: str) -> bool:
    """A sentence that only announces a lookup ("Let me check cancellation rates for Bikaner…")."""
    return bool(_OPENS_LOOKING.match(sentence or ""))


# ── an offer at the end: something the owner can answer yes or no ──────

def offer_questions() -> Dict[str, Any]:
    from typesafe_sdk import Noul, NoulCriteria

    return {
        "offers": Noul(
            instructions=("Does `last_sentence` (the end of Jenny's reply) ask the owner a yes-or-no question about "
                          "whether Jenny should do something next?"),
            criteria=NoulCriteria(true="'Shall I pull a breakdown by city?' / 'Want me to keep an eye on Chennai?' / "
                                       "'Should I check the restaurants next?'",
                                  false="A statement; an open question ('What would you like to look at?'); asking "
                                        "which of two things they meant; asking how they are.")),
    }


OFFERS = 0.6  # at or above: the reply ends with an offer the owner can answer yes or no


async def offer(reply: str) -> Optional[str]:
    """The offer her reply ends with ("Shall I pull a breakdown by city?"), or None."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", re.sub(r"\[[a-z]+\]\s*", "", reply or "").strip()) if p.strip()]
    if not parts or not parts[-1].endswith("?"):
        return None  # a yes-or-no question is a question
    r = await _one({"last_sentence": parts[-1], "reply": reply[-600:]}, offer_questions())
    return parts[-1] if r and (r.get("offers") or 0) >= OFFERS else None


# ── claims: she never says she'll do, or did, what nothing backs ────────

def claim_questions() -> Dict[str, Any]:
    from typesafe_sdk import Noul, NoulCriteria

    return {
        "commits_later": Noul(
            instructions=("Does `sentence` commit Jenny to do something AFTER this reply — keep watching something, "
                          "alert or tell the owner when something happens, check back later, remind, send or report?"),
            criteria=NoulCriteria(true="'I'll ping you if cancellations top eight percent.' / 'I'll check the zones "
                                       "again at eleven.' / 'I'll email you the summary.' / 'I'll keep an eye on Pune.'",
                                  false="'Let me check the zones.' (now, this turn) / 'Want me to watch it?' (an offer) "
                                        "/ 'Cancellations are up.' / 'I can break it down by city.'")),
        "claims_done": Noul(
            instructions="Does `sentence` say Jenny has already looked at, checked or done something specific?",
            criteria=NoulCriteria(true="'I checked the zones and it's two restaurants.' / 'I've set an alert.' / "
                                       "'I looked at last week too.'",
                                  false="Stating a number or fact; a plan; an offer.")),
        "repeats": Noul(
            instructions=("Does `sentence` only say again something Jenny already said in her_earlier_replies — the same "
                          "promise, confirmation or fact — adding nothing new, when the owner (owner_said) didn't ask "
                          "to hear it again?"),
            criteria=NoulCriteria(true="She confirmed the cancellations watch earlier; the owner says 'thanks'; the "
                                       "sentence says she's still watching cancellations and will ping them.",
                                  false="A new fact or promise; anything the owner asked for again ('what was it "
                                        "again?'); a few words of courtesy ('Anytime.').")),
        "backed": Noul(
            instructions=("Is what `sentence` commits to or claims actually backed by `backing` — something Jenny "
                          "set up on her desk, a lookup she ran this turn, or one of her standing duties?"),
            criteria=NoulCriteria(true="'I'll alert you if cancellations top eight percent' with a desk watch "
                                       "'cancellation rate above 8%'; 'I'll keep watching the live numbers' (a standing "
                                       "duty); 'I checked by zone' with a lookup broken down by zone.",
                                  false="A promise or claim nothing in backing covers: a different threshold or "
                                        "metric, a time with no check set, a channel she doesn't have (email, SMS).")),
    }


CLAIM = 0.6    # commits_later / claims_done at or above: the sentence makes a claim that needs backing
BACKED = 0.5   # backed below this: nothing makes the claim true


REPEATS = 0.7  # repeats at or above: the sentence only says again what she already said


async def check_claim(sentence: str, backing: List[str], context: str = "", earlier: Optional[List[str]] = None,
                      owner_said: str = "") -> Dict[str, Any]:
    """Whether a sentence she's about to say promises or claims something nothing backs, or only repeats what she
    already said. Jev unavailable: let it through (the conversation never waits on this), marked unchecked."""
    r = await _one({"sentence": sentence, "said_just_before": context[-300:] or "(start of her reply)",
                    "owner_said": owner_said or "(not known)", "her_earlier_replies": (earlier or [])[-3:] or ["(none)"],
                    "backing": backing or ["(nothing)"]}, claim_questions())
    if r is None:
        return {"ok": True, "checked": False}
    later, done, backed = r.get("commits_later") or 0.0, r.get("claims_done") or 0.0, r.get("backed") or 0.0
    repeats = r.get("repeats") or 0.0
    claim = "later" if later >= CLAIM else "done" if done >= CLAIM else None
    if claim is not None and backed < BACKED:
        ok = False
    elif earlier and repeats >= REPEATS:
        ok, claim = False, "repeat"
    else:
        ok = True
    return {"ok": ok, "claim": claim, "later": later, "done": done, "backed": backed, "repeats": repeats,
            "checked": True, "latency_ms": r.get("latency_ms")}

PREFERENCE = 0.7  # sets_preference at or above: the owner set how she should speak to them, for good


FOCUS = 0.7  # sets_focus at or above: something to watch, a decision, or a plan to revisit


def sets_focus(r: Optional[Dict[str, Any]]) -> bool:
    return bool(r) and (r.get("sets_focus") or 0) >= FOCUS


def sets_preference(r: Optional[Dict[str, Any]]) -> bool:
    return bool(r) and (r.get("sets_preference") or 0) >= PREFERENCE


# ── turn-taking: has the owner finished? ─────────────────────────────

async def finished(so_far: str, jenny_last: str = "") -> Optional[float]:
    """How likely the owner has finished their turn (0–1), judged from their words so far — so Jenny neither
    jumps in mid-thought nor sits in silence after a complete question. None when Jev isn't available."""
    from kairos_kb.config import get_settings

    settings = get_settings()
    if not settings.typesafe_api_key or not so_far.strip():
        return None
    try:
        from typesafe_sdk import AsyncTypeSafeClient, Noul, NoulCriteria
    except ImportError:
        return None
    client = AsyncTypeSafeClient(api_key=settings.typesafe_api_key, model=settings.typesafe_model or None, timeout=1.5)
    try:
        r = await client.system_one(
            state={"owner_so_far": so_far.strip()[-400:], "jenny_said_before": (jenny_last or "")[-300:]},
            questions={"done": Noul(
                instructions=("The owner is speaking to Jenny on a call and has just paused. Has the owner finished "
                              "their turn — said a complete thought and is now waiting for Jenny to respond?"),
                criteria=NoulCriteria(
                    true="A complete question, request or remark: 'How are we doing today?', 'Which city is behind?', "
                         "'Thanks, that's all', 'Pune?' as a follow-up.",
                    false="Cut off mid-thought: ends on 'and', 'but', 'so', 'the', 'what about', 'I was wondering if', "
                          "or a clause that needs more words."))},
            timeout=1.5)
        return round(r.answers["done"].noul, 3)
    except Exception:  # noqa: BLE001 — the call falls back to timing alone
        return None
    finally:
        await client.aclose()
