"""Check Kairos's NVIDIA Nemotron setup on Nebius Token Factory, end to end, before switching to it.

    python -m kairos_kb.llm.nebius_check

1. models   the Nemotron models this key can use, and whether NEBIUS_MODEL / NEBIUS_FAST_MODEL are among them
2. tools    one streamed turn on each model with a tool, as Jenny's turns run: did it call the tool, how soon did the
            first token come, and did any reasoning leak into what she'd say
"""

from __future__ import annotations

import asyncio
import json
import time

from kairos_kb.config import get_settings
from kairos_kb.llm.provider import nebius_client

TOOL = {"type": "function", "function": {
    "name": "compare_to_normal",
    "description": "A metric today so far against a normal day at this hour, optionally broken down by a dimension.",
    "parameters": {"type": "object", "properties": {
        "product": {"type": "string"}, "metric": {"type": "string"}, "dimension": {"type": "string"}},
        "required": ["product", "metric"]}}}


async def turn(client, model: str) -> dict:
    from kairos_kb.companion.chat import ThinkFilter

    started = time.perf_counter()
    first = None
    think = ThinkFilter()
    calls: dict = {}
    stream = await client.chat.completions.create(
        model=model, stream=True, tools=[TOOL], tool_choice="auto",
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        messages=[{"role": "system", "content": "You are Jenny, a business companion. Use tools for numbers."},
                  {"role": "user", "content": "Which cities are driving cancellations today in the Sales product?"}])
    async for chunk in stream:
        if not chunk.choices:
            continue
        d = chunk.choices[0].delta
        if (d.content or d.tool_calls) and first is None:
            first = time.perf_counter() - started
        if d.content:
            think.feed(d.content)
        for tc in d.tool_calls or []:
            c = calls.setdefault(tc.index or 0, {"name": "", "arguments": ""})
            if tc.function and tc.function.name:
                c["name"] += tc.function.name
            if tc.function and tc.function.arguments:
                c["arguments"] += tc.function.arguments
    return {"first_token_s": round(first or 0, 2), "total_s": round(time.perf_counter() - started, 2),
            "tool_calls": list(calls.values()), "said": think.visible[:160],
            "reasoning_leaked": "<think>" in think.visible or "</think>" in think.visible}


async def main() -> None:
    s = get_settings()
    client = nebius_client()
    if client is None:
        print("NEBIUS_API_KEY is not set.")
        return
    print(f"Token Factory: {s.nebius_base_url}")
    models = [m.id for m in (await client.models.list()).data]
    nvidia = sorted(m for m in models if "nemotron" in m.lower() or m.lower().startswith("nvidia/"))
    print(f"\nNVIDIA models on this key ({len(nvidia)}):")
    for m in nvidia:
        print("  ", m)
    for label, m in (("NEBIUS_MODEL", s.nebius_model), ("NEBIUS_FAST_MODEL", s.nebius_fast_model)):
        print(f"\n{label} = {m}  {'✓ available' if m in models else '✗ NOT on this key — set it to one of the ids above'}")
        if m in models:
            try:
                print("  ", json.dumps(await turn(client, m), ensure_ascii=False))
            except Exception as exc:  # noqa: BLE001 — report and carry on
                print(f"   turn failed: {type(exc).__name__}: {str(exc)[:300]}")


if __name__ == "__main__":
    asyncio.run(main())
