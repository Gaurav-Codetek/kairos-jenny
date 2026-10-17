"""A turn with a backup model: the first model to start answering gives the turn; the other says nothing."""

import asyncio
from types import SimpleNamespace

import pytest

from kairos_kb.companion import chat


class FakeStream:
    def __init__(self, words, delay, fail=None):
        self.words, self.delay, self.fail = words, delay, fail

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        await asyncio.sleep(self.delay)
        if self.fail:
            raise self.fail
        for w in self.words:
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=w, tool_calls=None))])

    async def close(self):
        pass


class FakeClient:
    def __init__(self, words, delay=0.0, fail=None):
        self.asked = 0
        self.stream = FakeStream(words, delay, fail)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kw):
        self.asked += 1
        return self.stream


@pytest.fixture
def two(monkeypatch):
    monkeypatch.setattr(chat, "HEDGE_S", 0.05)
    monkeypatch.setattr("kairos_kb.llm.provider.provider", lambda: "azure")

    def use(gemini, azure):
        monkeypatch.setattr(chat, "_models", lambda c, m, e: [("gemini", gemini, "g", "none"), ("azure", azure, "a", e)])

    return use


async def turn():
    said = []

    async def on_text(t):
        said.append(t)

    out = await chat._stream_turn(None, "a", "system", [], [], True, on_text, "low")
    return out, said


async def test_a_quick_first_model_answers_alone(two):
    g, a = FakeClient(["Hi ", "there."]), FakeClient(["backup"])
    two(g, a)
    out, said = await turn()
    assert out["text"] == "Hi there." and out["model"] == "gemini:g" and a.asked == 0


async def test_a_failing_first_model_hands_the_turn_to_the_backup(two):
    g, a = FakeClient([], fail=RuntimeError("429 quota")), FakeClient(["From ", "the backup."])
    two(g, a)
    out, said = await turn()
    assert out["text"] == "From the backup." and out["model"] == "azure:a"


async def test_a_slow_first_model_is_overtaken_and_says_nothing(two):
    g, a = FakeClient(["Too ", "late."], delay=0.5), FakeClient(["Backup ", "first."], delay=0.0)
    two(g, a)
    out, said = await turn()
    assert out["model"] == "azure:a" and out["text"] == "Backup first."
    assert all("late" not in s for s in said)  # the slow one never spoke


def test_history_is_adapted_to_each_model():
    history = [{"role": "assistant", "content": None, "_signatures": {"a": "SIG"},
                "tool_calls": [{"id": "a", "type": "function", "function": {"name": "pulse_now", "arguments": "{}"}},
                               {"id": "b", "type": "function", "function": {"name": "query", "arguments": "{}"}}]},
               {"role": "tool", "tool_call_id": "a", "content": "{}"}]
    g = chat._for_model(history, gemini=True)
    assert [c["extra_content"]["google"]["thought_signature"] for c in g[0]["tool_calls"]] == ["SIG", chat.SKIP_SIGNATURE]
    assert "_signatures" not in g[0]
    a = chat._for_model(history, gemini=False)
    assert all("extra_content" not in c for c in a[0]["tool_calls"]) and "_signatures" not in a[0]
