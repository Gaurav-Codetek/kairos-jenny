"""Nemotron's structured answers: a function call written as text is read; none at all is asked again, then a clear
error, never None (the engine failed with "'NoneType' object has no attribute 'inputs'")."""

import asyncio
from typing import List

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel

from kairos_kb.llm.provider import _recovering, from_text


class Pick(BaseModel):
    table: str
    tags: List[str]


XML = ("<think>which one</think><tool_call>\n<function=Pick>\n<parameter=table>\nax_gold.default.coverage\n"
       "</parameter>\n<parameter=tags>\n[\"hcp\", \"country\"]\n</parameter>\n</function>\n</tool_call>")


def test_a_call_written_as_text_is_read():
    assert from_text(AIMessage(XML), Pick) == Pick(table="ax_gold.default.coverage", tags=["hcp", "country"])
    as_json = AIMessage('<tool_call>{"name": "Pick", "arguments": {"table": "t", "tags": ["a"]}}</tool_call>')
    assert from_text(as_json, Pick) == Pick(table="t", tags=["a"])
    assert from_text(AIMessage('Here it is: {"table": "t", "tags": "[a, b]"}'), Pick) == Pick(table="t", tags=["a", "b"])
    assert from_text(AIMessage("I could not decide."), Pick) is None


def answers(*outs):
    seen = []

    async def call(messages, config=None):
        seen.append(messages)
        return outs[len(seen) - 1]

    return RunnableLambda(lambda m: None, afunc=call), seen


def test_none_is_recovered_from_the_text_then_asked_again_then_an_error():
    inner, _ = answers({"parsed": None, "raw": AIMessage(XML), "parsing_error": None})
    assert asyncio.run(_recovering(inner, Pick).ainvoke([("human", "pick")])).table == "ax_gold.default.coverage"

    good = Pick(table="t", tags=[])
    inner, seen = answers({"parsed": None, "raw": AIMessage(""), "parsing_error": None},
                          {"parsed": good, "raw": AIMessage(""), "parsing_error": None})
    assert asyncio.run(_recovering(inner, Pick).ainvoke([("human", "pick")])) == good
    assert "calling the function Pick" in str(seen[1][-1])

    empty = {"parsed": None, "raw": AIMessage(""), "parsing_error": None}
    inner, _ = answers(empty, empty)
    with pytest.raises(ValueError, match="no usable Pick"):
        asyncio.run(_recovering(inner, Pick).ainvoke([("human", "pick")]))
