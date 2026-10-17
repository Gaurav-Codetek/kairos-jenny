---
name: jev-typesafe
description: Build with Jev, TypeSafe AI's "System One" decision model, which returns typed probabilistic decisions (Choice / Score / Noul) instead of generated text, in roughly 70-500ms at ~$0.042 per million input tokens with free output. Use this skill whenever the user mentions Jev, TypeSafe AI, System One models, the typesafe-sdk or @typesafe-ai/sdk packages, or a TYPESAFE_API_KEY. Also use it proactively whenever the user is building classification, routing, triage, moderation, relevance filtering, guardrails, confidence-gated branching, or any real-time agent loop where an LLM call per decision is too slow or too expensive — even if they never say the word "Jev". If the user is about to call a frontier LLM in a hot loop just to get back a label, a category, a score, or a yes/no, consult this skill first.
---

# Jev (TypeSafe AI System One model)

## Status of this document

Jev launched on 15 September 2026. This file was assembled from launch-week
reporting and community guides, so treat concrete numbers, SDK signatures and
limits as *probably right but verify*. The authoritative source is
**https://docs.typesafe.ai**. When something here conflicts with the official
docs, the docs win — and update this file.

TypeSafe also publishes an official agent skill, which may be newer than this one:

```bash
claude plugin marketplace add typesafe-ai/skills
claude plugin install typesafe@typesafe-ai
# other agents:
npx skills add typesafe-ai/skills --skill typesafe-ai
```

---

## 1. What Jev is

Jev is a frontier model from TypeSafe AI (San Francisco; out of stealth
15 Sept 2026 with $40M seed led by DCVC; founded by Diogo Almeida, a former
OpenAI researcher and co-inventor of RLHF / InstructGPT).

The one-line version: **Jev does not generate text. It returns typed,
probabilistic decisions.**

You hand it a `state` (your context) plus a set of typed `questions`. It answers
all of them in one parallel pass and gives you back values that conform to a
schema *you* defined in advance, each with probabilities and a confidence
figure.

TypeSafe calls this class a **System One model**, after Kahneman's fast,
intuitive thinking. The bet: most decisions inside software are System 1
judgments ("which bucket is this?", "is this urgent?", "is this risky?"), and
we have been renting System 2 reasoning to make them.

The best mental model, from the community: **Jev is a smart `if` statement.**
Ordinary code branches on values it can compute (`if (order.total > 100)`).
Jev lets code branch on judgments it cannot phrase (`if (customer_is_angry)`).

It is trained with **RLCD** (Reinforcement Learning for Calibrated Decisions),
which optimises probabilities against outcomes rather than human preference.
It is trained exclusively on synthetic data. The architecture is undisclosed;
outside observers suspect an open-weight LLM underneath.

## 2. How it differs from a normal agentic/LLM implementation

| | Jev | Frontier LLM |
|---|---|---|
| Output | typed decision + probabilities + confidence | tokens (text/JSON) |
| Generation | single parallel pass, non-autoregressive | token by token |
| End-to-end latency | ~70-500 ms | ~3 s to 300 s+ |
| Input price | ~$0.042 / MTok | ~$0.20-$10 / MTok |
| Output price | free | ~5x input |
| Schema errors | 0% by construction | 0.58%-45.5% |
| Can hallucinate? | cannot return a value outside your schema; **can** return the wrong valid one | yes |
| Can it write? | no. Not trained to generate text at all | yes |

Three structural consequences that change how you design:

1. **No parsing layer.** In a normal agent you prompt for JSON, get a string,
   strip code fences, `JSON.parse`, validate, retry on failure. All of that code
   stops existing. The type is guaranteed.
2. **Confidence is a real signal.** Because of RLCD, higher confidence really
   does correlate with higher accuracy in aggregate. You can gate on it.
   With an LLM, "I'm 90% sure" in prose means nothing.
3. **Extra questions are nearly free in time.** Questions run in parallel over
   state ingested once, so the tenth question costs tokens but almost no
   latency. This inverts the usual instinct to ask one cheap question first.

Jev is **not** a replacement for an LLM. It is the thing that decides which
requests deserve one.

## 3. How an agent gets fast with it

The pattern that matters is the **cascade**: keep the loop, the safety and the
arithmetic in ordinary code, and use Jev for the narrow judgment in the middle
that code finds hard to phrase.

```
request
  │
  ├─ Jev: intent + complexity + risk   (one call, ~100-300ms)
  │
  ├─ confidence < threshold ──────────► human
  ├─ simple lookup ───────────────────► pure code, no model at all
  ├─ needs writing ───────────────────► LLM specialist
  └─ edge case ───────────────────────► LLM + human review
```

On a support workload of a million tickets, TypeSafe's own per-case figures put
this at roughly $6,480 instead of $30,400, with ~800k answered in under half a
second instead of ten.

Launch-week results that show the shape (all self-reported by their authors):

- **Browser agent** (browser-use/jev-ultrafast): Zürich→London booked on real
  Google Flights in **7.1 s for $0.0039**, page loads included. One Jev request
  picks both the operation (CLICK / TYPE_TEXT / SELECT / SCROLL / WAIT / DONE /
  BLOCKED) and its target from an indexed element table. A small LLM runs only
  when the operation is TYPE_TEXT.
- **Computer use** (awlevin/typesafe-computer-use): $0.0002 per decision vs
  $0.032 for a frontier model on a bare screenshot; 0.13-0.38 s model latency
  vs 5.2 s.
- **Classification at volume** (1kpapers.com): 1,018 papers classified for
  **$0.08** (the summaries from a generative model cost $3.99), median 256 ms
  per paper.
- **Drone** (RomanSlack/jev-drone): Jev runs at ~2.5 Hz as an **advisory**
  tactical layer only; a 500 Hz geometric controller and a 50 Hz safety reflex
  stay in code. Jev "cannot be the perception layer, and it cannot run at
  control rate."

The lesson from the computer-use repo is the sharpest one:
**every piece of reasoning a frontier model does for free has to be rebuilt
here as deterministic state.**

## 4. Setup and authentication

Get a key from `https://console.typesafe.ai/settings/keys` (early access is
waitlisted) or via the Vercel AI Gateway.

```bash
export TYPESAFE_API_KEY="sk-..."
```

Never hardcode the key or commit it. Both SDKs read `TYPESAFE_API_KEY` from the
environment automatically and default to the `jev-latest` alias.

```bash
pip install typesafe-sdk        # Python 3.10+
npm install @typesafe-ai/sdk    # Node 20+
```

Direct HTTP, if you prefer no SDK: `POST https://api.typesafe.ai/v1/systemone`
with the API key as a bearer token. Check the docs for the exact body shape
before relying on it.

## 5. The three primitives

The whole API is three question types. This is the design, not a limitation to
route around.

**Choice** — one option from a set.
```python
Choice(
    instructions="Which team should handle this",
    criteria={
        "billing":   "Payment or subscription issues",
        "technical": "Bugs or integration problems",
        "sales":     "Pricing or account questions",
        "other":     "Nothing above fits",
    },
)
```
Returns `.choice`, `.probabilities` (one per option), `.confidence`.
Up to **255 options**, each costing a few tokens — pass the full list, not a
shortlist. **Always include an explicit `other`** so the model can say nothing
fits instead of picking the closest wrong thing.

**Score** — a position on a spectrum.
```python
Score(
    instructions="How frustrated the customer appears",
    criteria=[
        "Calm, just stating facts",
        "Frustrated but civil",
        "Very angry, strong language",
    ],
)
```
Two to ten ordered levels described in words. Returns `.score`, which can land
*between* levels (e.g. `1.035`), plus `.probabilities` and `.confidence`.
Level index comes from array order: level 0 is the first entry.

**Noul** — yes or no, as a probability.
```python
Noul(instructions="The message conveys urgency or time-sensitivity")
```
Returns `.noul`, a single number 0-1: the probability the answer is yes.
No confidence field — the number already is the belief.

## 6. A full call

```python
from typesafe_sdk import Choice, Noul, Score, TypeSafeClient

client = TypeSafeClient()

response = client.system_one(
    state={
        "ticket": {
            "subject": "Duplicate charge",
            "messages": [
                {"from": "customer",
                 "text": "I was charged twice for order A-104. Please refund the duplicate."},
            ],
        },
        "order": {"id": "A-104", "charges": [
            {"amount_usd": 49, "status": "captured"},
            {"amount_usd": 49, "status": "captured"},
        ]},
        "refund_policy": "Duplicate charges are eligible for a refund.",
    },
    questions={
        "department": Choice(
            instructions="Which team should handle this",
            criteria={"billing": "Payment or subscription issues",
                      "technical": "Bugs or integration problems",
                      "sales": "Pricing or account questions",
                      "other": "Nothing above fits"}),
        "frustration": Score(
            instructions="How frustrated the customer appears",
            criteria=["Calm, just stating facts",
                      "Frustrated but civil",
                      "Very angry, strong language"]),
        "refund_requested": Noul(
            instructions="The customer is explicitly asking for a refund"),
        "policy_supports": Noul(
            instructions="The stated refund policy covers this situation"),
    },
)

dept = response.answers["department"]
print(dept.choice, dept.confidence)
print(response.answers["frustration"].score)
print(response.answers["refund_requested"].noul)
```

TypeScript is the same shape, with the question helpers lowercased and types
inferred from the questions object:

```ts
import { choice, noul, TypeSafeClient } from "@typesafe-ai/sdk";

const client = new TypeSafeClient();

const response = await client.systemOne({
  state: { document: "I was charged twice. Please fix this ASAP." },
  questions: {
    category: choice("What is this ticket about?", {
      billing: "Payment or subscription issues",
      technical: "Bugs or integration problems",
      other: "Anything else",
    }),
    urgent: noul("The message conveys urgency"),
  },
});

console.log(response.answers.category.choice);
```

**State** can be a string, a JSON object, or an array of strings (e.g. a
conversation). Use an object when there is more than one piece of context.
Text only — no images, audio or video; transcribe or caption first.

**Context limits** work differently from an LLM, because state is ingested once
and questions run in parallel over it:
- 64k tokens for state and all questions together
- 32k tokens for state plus the single longest question

## 7. Patterns worth using

**Speculative fan-out.** Ask everything up front, let code decide what was
relevant. Asking a question that turns out to be irrelevant is nearly free.
TypeSafe's cookbook reports batching 13 questions into one call is 12.2x
cheaper and 10.0x faster than asking one at a time, with identical answers.

**Confidence-gated routing.** One threshold per action, scaled to what being
wrong costs — not one global threshold.
```python
a = response.answers["intent"]
if a.confidence < 0.5:
    route_to_human(msg)                       # floor: genuinely unsure
elif a.choice == "check_balance":
    show_balance(account_id)                  # read-only, low bar
elif a.choice == "approve_transfer":
    if a.confidence > 0.85:                   # moves money, high bar
        approve_transfer(account_id)
    else:
        ask_user_to_confirm()
else:
    route_to_human(msg)
```
A flat `.probabilities` distribution usually means your *criteria* are wrong,
not that the model is confused.

**Composite scoring.** Break a fuzzy judgment into independent dimensions,
score each atomically, combine with weights you control in code. Re-weighting
becomes a code change you can A/B, not a re-prompt.

**Retrieve, then judge.** Jev knows nothing beyond the state you hand it and
cannot look anything up. Whatever assembles the state decides what Jev is
allowed to know. Retrieve and filter in code first, and send only the fields
the question needs.

**Filter before the expensive context.** One Noul per retrieved passage to drop
irrelevant material before a frontier model ever sees it. At $0.042/MTok with
free output, the filter costs less than the context window it saves.

## 8. Failure modes — read before shipping

TypeSafe publishes a `jaggedness` page per version (e.g.
`docs.typesafe.ai/model-jaggedness/jev-1.13`) listing what the model is bad at.
Read the one for your pinned version.

- **It reads literally.** It answers the question you wrote, not the one you
  meant. Negations, scoping words and implied conditions land at face value.
  The tell: you look at a wrong answer and catch yourself explaining what you
  really meant. That explanation is the missing half of your instruction.
- **It is not a calculator.** It does not count reliably and error grows with
  the size of the thing counted. Iterate in code, one Noul per item, and sum
  in Python.
- **Dates are text, not ordered quantities.** Which came first, how far apart,
  whether one falls in a window — all unreliable. Extract with a Choice over
  enumerated values (with a "not stated" option); do ordering and arithmetic in
  code.
- **Context rot is real.** Accuracy falls as state fills with material the
  question does not need.
- **State is not treated as hostile.** Text engineered to argue for its own
  classification can move the answer — this is live prompt-injection surface if
  user content goes into state, and press coverage has already flagged it.
  If you put user-controlled content into state, that is your threat model to
  handle. Test it. Never let a Jev decision be the *only* thing standing
  between untrusted input and a destructive or irreversible action.
- **Contradictory instructions and criteria confuse it.** Treat criteria as an
  extension of the instruction; don't map `true` to "no".
- **It does not generate.** For value extraction, get candidates with a regex
  or a generative model and let Jev pick.

Meta-rule from their docs, and good design advice generally:
*avoid asking the model something code can compute exactly; avoid hiding
several judgments inside one question.*

## 9. Operational notes

- **Rate limits** for `jev-1.13`: 250,000 tokens/second and 1,200
  requests/minute; over either returns `429`. Both SDKs retry with exponential
  backoff and honour `retry-after`. TypeSafe warns these limits move without
  notice while GPU capacity lands.
- **Pin the version if you tune thresholds.** `jev-latest` resolves to a
  specific release and will move under you, changing answers.
  `TypeSafeClient(model="jev-1.13.0")`. The response's `model` field reports
  the versioned ID that answered — log it.
- **Billing is input-only.** Output is free, which is why fan-out is cheap and
  why adding options to a Choice costs almost nothing.
- **Evaluate on your own traffic.** TypeSafe's benchmark numbers are self-run,
  unreproduced, and scored against consensus labels from two frontier models
  rather than ground truth; TypeSafe itself says this biases the comparison.
  "0% structured-output errors" is asserted by construction, not measured — and
  it means *invalid* values are impossible, not *wrong* ones.

## 10. When to use it, and when not to

**Yes:** routing and triage, moderation, relevance filtering before an
expensive context window, scoring or guardrailing LLM output, tagging at
volumes that were previously uneconomic, choosing the next action in a
real-time agent loop, anything sub-second inside a request handler.

**No:** generating anything; arithmetic, counting or date math; decisions that
need a written rationale for an auditor; one-off complex reasoning; genuinely
open answer spaces; perception; anything running at control rate; sole
authority over an irreversible action.

## 11. Checklist when building with Jev

1. Is this judgment something code could compute exactly? If yes, use code.
2. Is it one judgment, or several hidden in one question? Split it.
3. Does state contain only what the question needs? Filter it.
4. Is there an `other` option on every Choice?
5. Is there a confidence threshold per action, sized to the cost of being wrong?
6. Is anything irreversible gated behind more than a Jev call?
7. Is the model version pinned and logged?
8. Is there an eval on real traffic before this replaces an existing path?