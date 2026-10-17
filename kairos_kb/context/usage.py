"""What a tool call costs the agent that made it.

Kairos never sees a connected agent's own model usage, but it knows exactly
what each call adds to that agent's context:

  arguments   tokens the agent's model wrote to make the call   → its output
  response    tokens the agent's model must read back           → its input

Counted with the GPT-5 family tokenizer and priced at the configured model's
rates (gpt-5-mini by default), this is the cost of using each Kairos tool —
the number to watch when a tool's responses grow too large.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Dict

from kairos_kb.config import get_settings


@lru_cache(maxsize=1)
def _encoder():
    try:
        import tiktoken

        return tiktoken.get_encoding("o200k_base")
    except Exception:  # noqa: BLE001 — fall back to an estimate if the tokenizer is unavailable
        return None


def count_tokens(text: str) -> int:
    if not text:
        return 0
    enc = _encoder()
    if enc is None:
        return max(1, len(text) // 4)
    return len(enc.encode(text, disallowed_special=()))


def as_agent_sees(value: Any) -> str:
    """The text an MCP client receives: the tool's JSON, indented as the server sends it."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, indent=2, default=str, ensure_ascii=False)


def call_usage(arguments: Any, result: Any) -> Dict[str, Any]:
    settings = get_settings()
    args_tokens = count_tokens(json.dumps(arguments, default=str, ensure_ascii=False)) if arguments else 0
    result_tokens = count_tokens(as_agent_sees(result))
    cost = (result_tokens * settings.llm_price_input_per_m + args_tokens * settings.llm_price_output_per_m) / 1e6
    return {"args_tokens": args_tokens, "result_tokens": result_tokens, "est_cost_usd": round(cost, 8)}
