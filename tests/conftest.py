"""Shared fixtures for the pure-logic tests.

Nothing here touches the network, the database or an LLM: tools and models
are replaced with small fakes so each test pins down logic only.
"""

from __future__ import annotations

import uuid
from typing import Any, Callable, Dict, List

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.prebuilt.tool_node import msg_content_output


class FakeTool:
    """Stands in for a LangChain tool: a name and an async ``ainvoke``."""

    def __init__(self, name: str, result: Any | Callable[[Dict[str, Any]], Any]):
        self.name = name
        self._result = result
        self.calls: List[Dict[str, Any]] = []

    async def ainvoke(self, args: Dict[str, Any]) -> Any:
        self.calls.append(args)
        return self._result(args) if callable(self._result) else self._result


class FakeStructuredLLM:
    """``llm.with_structured_output(Model).ainvoke(...)`` returning fixed field values."""

    def __init__(self, values: Dict[str, Any]):
        self.values = values

    def with_structured_output(self, model):
        values = self.values

        class _Bound:
            async def ainvoke(self, _messages):
                return model(**{k: v for k, v in values.items() if k in model.model_fields})

        return _Bound()


@pytest.fixture
def fake_tools(monkeypatch):
    """Install a fake tool registry for Agent B. Returns a function to register tools."""
    from kairos_kb.agent import plan_executor

    registry: Dict[str, FakeTool] = {}
    monkeypatch.setattr(plan_executor, "_tool_registry", lambda: registry)

    def add(name: str, result: Any) -> FakeTool:
        registry[name] = FakeTool(name, result)
        return registry[name]

    return add


@pytest.fixture
def stub_report(monkeypatch):
    """Agent B's report node without an LLM: echoes the fact labels it was given."""
    from kairos_kb.agent import plan_executor

    async def _report(args, failure_class):
        return f"REPORT {failure_class}: " + ",".join(sorted((args.get("facts") or {}).keys()))

    monkeypatch.setattr(plan_executor, "_run_report", _report)


@pytest.fixture
def playbook_store(monkeypatch, tmp_path):
    """Point the variant store at an empty temporary directory."""
    from kairos_kb.agent import playbooks

    monkeypatch.setattr(playbooks, "_root", lambda: tmp_path / "playbooks")
    return tmp_path / "playbooks"


class Trace:
    """Builds an Agent A message history the way LangGraph's ToolNode records it."""

    def __init__(self) -> None:
        self.messages: list = []

    def call(self, name: str, args: Dict[str, Any], result: Any) -> "Trace":
        call_id = str(uuid.uuid4())
        self.messages.append(AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}]))
        self.messages.append(ToolMessage(content=msg_content_output(result), tool_call_id=call_id))
        return self


@pytest.fixture
def trace() -> Trace:
    return Trace()
