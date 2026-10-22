"""NVIDIA Nemotron on Nebius Token Factory, switched on by settings — and nothing changes when they're unset."""

from kairos_kb.companion import chat
from kairos_kb.config import Settings
from kairos_kb.llm import provider as P


def use(monkeypatch, **over):
    base = dict(llm_provider="azure", azure_openai_api_key="az", azure_openai_endpoint="https://x.openai.azure.com",
                azure_openai_deployment="gpt-5-mini", nebius_api_key="", openai_api_key="")
    s = Settings(_env_file=None, **{**base, **over})
    monkeypatch.setattr(P, "get_settings", lambda: s)
    monkeypatch.setattr("kairos_kb.config.get_settings", lambda: s)
    return s


def test_unset_everything_stays_on_azure(monkeypatch):
    use(monkeypatch)
    assert P.provider() == "azure" and P.model_name() == "gpt-5-mini"
    assert P.embedding_provider() == "azure"


def test_nebius_runs_reasoning_on_nemotron_but_keeps_embeddings_where_the_vectors_were_made(monkeypatch):
    s = use(monkeypatch, llm_provider="nebius", nebius_api_key="nb")
    assert P.provider() == "nebius" and P.configured()
    assert P.model_name() == s.nebius_model and P.is_nemotron(P.model_name())
    assert P.embedding_provider() == "azure"  # same text-embedding-3-large vectors: no re-indexing
    assert P.embedding_model() == s.azure_openai_embedding_deployment
    assert str(P.async_client().base_url).startswith("https://api.tokenfactory.nebius.com")


def test_nemotron_structured_output_goes_through_tool_calling(monkeypatch):
    use(monkeypatch, llm_provider="nebius", nebius_api_key="nb")
    from pydantic import BaseModel

    class Plan(BaseModel):
        name: str

    llm = P.chat_model()
    runnable = llm.with_structured_output(Plan)
    first = getattr(runnable, "first", None)
    assert first is not None and "tools" in (getattr(first, "kwargs", {}) or {})


def test_jenny_on_nemotron_keeps_the_main_provider_as_her_backup(monkeypatch):
    s = use(monkeypatch, nebius_api_key="nb")
    monkeypatch.setattr(chat, "COMPANION_LLM", "nebius")
    monkeypatch.setattr(chat, "_nebius_client", None)
    order = chat._models("azure-client", "gpt-5-mini", "low")
    assert [(label, m) for label, _c, m, _e in order] == [("nebius", s.nebius_fast_model), ("azure", "gpt-5-mini")]
    monkeypatch.setattr(chat, "COMPANION_LLM", "nebius:nvidia/nemotron-3-super-120b-a12b")
    assert chat._models("azure-client", "gpt-5-mini", "low")[0][2] == "nvidia/nemotron-3-super-120b-a12b"


def test_with_everything_on_nebius_jenny_never_falls_back_to_the_heavy_model(monkeypatch):
    s = use(monkeypatch, llm_provider="nebius", nebius_api_key="nb")
    monkeypatch.setattr(chat, "COMPANION_LLM", "nebius")
    monkeypatch.setattr(chat, "_nebius_client", None)
    order = chat._models("main-client", s.nebius_model, "low")  # her callers pass the main (heavy) model
    assert [m for _l, _c, m, _e in order] == [s.nebius_fast_model, s.nebius_fast_model]


def test_jenny_asked_for_nemotron_without_a_key_stays_on_the_main_provider(monkeypatch):
    use(monkeypatch)
    monkeypatch.setattr(chat, "COMPANION_LLM", "nebius")
    monkeypatch.setattr(chat, "_nebius_client", None)
    assert [label for label, *_ in chat._models("azure-client", "gpt-5-mini", "low")] == ["azure"]


def test_a_models_reasoning_is_never_said():
    f = chat.ThinkFilter()
    for piece in ["<thi", "nk>Delhi is up, check H", "yderabad</think>", "Delhi leads", " today."]:
        f.feed(piece)
        assert "think" not in f.visible and "Hyderabad" not in f.visible
    assert f.visible == "Delhi leads today."
    g = chat.ThinkFilter()
    g.feed("The user wants cities.</think>\n\nDelhi and Hyderabad lead.")  # thinking prefilled by the template
    assert g.visible == "Delhi and Hyderabad lead."
    h = chat.ThinkFilter()
    h.feed("Cancellations are at 6% <")
    assert h.visible == "Cancellations are at 6% "  # might be a tag: held back
    h.feed("= normal.")
    assert h.visible == "Cancellations are at 6% <= normal."


def test_a_tool_call_written_as_text_is_never_said_and_still_made():
    xml = ("<tool_call>\n<function=compare_to_normal>\n<parameter=product>\nSales\n</parameter>\n"
           "<parameter=metric>\ncancel_rate\n</parameter>\n<parameter=limit>\n5\n</parameter>\n</function>\n</tool_call>")
    f = chat.ThinkFilter()
    for i in range(0, len(xml), 7):  # streamed in small pieces
        f.feed(xml[i:i + 7])
        assert "<" not in f.visible and "Sales" not in f.visible
    assert f.visible == ""
    [call] = chat.text_tool_calls(f.raw)
    assert call["name"] == "compare_to_normal"
    import json
    assert json.loads(call["arguments"]) == {"product": "Sales", "metric": "cancel_rate", "limit": 5}

    g = chat.ThinkFilter()
    g.feed('Let me look. <tool_call>{"name": "pulse_now", "arguments": {}}</tool_call>')
    assert g.visible == "Let me look. "
    assert chat.text_tool_calls(g.raw) == [{"name": "pulse_now", "arguments": "{}"}]
    assert chat.text_tool_calls("Delhi leads today.") == []


def test_lists_written_as_text_become_real_lists():
    fixed = chat.fix_lists({"product": "Sales", "metrics": "[cancel_rate]", "by": "[city, state]",
                            "filters": '[{"dimension": "city", "op": "in", "value": ["Delhi"]}]', "order": "cancel_rate"})
    assert fixed["metrics"] == ["cancel_rate"] and fixed["by"] == ["city", "state"]
    assert fixed["filters"][0]["value"] == ["Delhi"] and fixed["order"] == "cancel_rate"
    assert chat.fix_lists({"order": '"gmv desc"'})["order"] == "gmv desc"
    loose = chat.fix_lists({"filters": "[{dimension: city, op: =, value: Delhi}, {dimension: cuisine, op: in, value: [Pizza, Burger]}]"})
    assert loose["filters"] == [{"dimension": "city", "op": "=", "value": "Delhi"},
                                {"dimension": "cuisine", "op": "in", "value": ["Pizza", "Burger"]}]


async def test_nemotrons_last_step_is_offered_no_tools(monkeypatch):
    sent = []

    class Stream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class Completions:
        async def create(self, **kw):
            sent.append(kw)
            return Stream()

    class Client:
        chat = type("C", (), {"completions": Completions()})()

    async def quiet(_t):
        return None

    tools = [{"type": "function", "function": {"name": "query"}}]
    await chat._stream_once(Client(), "nvidia/Nemotron-3_5-Lightning", "s", [], tools, True, quiet, None, lambda: True)
    await chat._stream_once(Client(), "nvidia/Nemotron-3_5-Lightning", "s", [], tools, False, quiet, None, lambda: True)
    await chat._stream_once(Client(), "gpt-5-mini", "s", [], tools, True, quiet, None, lambda: True)
    assert "tools" not in sent[0]
    assert sent[1]["tools"] == tools and sent[1]["tool_choice"] == "auto"
    assert sent[2]["tool_choice"] == "none"  # other models: unchanged


def test_nemotrons_final_answer_sees_its_lookups_as_notes_not_tool_calls():
    history = [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello."},
               {"role": "user", "content": "How many KFC restaurants are there?"},
               {"role": "assistant", "content": None, "tool_calls": [
                   {"id": "call_0", "type": "function", "function": {"name": "query", "arguments": '{"metrics": ["x"]}'}}]},
               {"role": "tool", "tool_call_id": "call_0", "content": '{"error": "No metric x"}'},
               {"role": "assistant", "content": "That didn't work, trying the index.", "tool_calls": [
                   {"id": "call_1", "type": "function", "function": {"name": "query", "arguments": '{"metrics": ["restaurants_count"]}'}}]},
               {"role": "tool", "tool_call_id": "call_1", "content": '{"rows": [[412]]}'}]
    flat = chat._flat(history)
    assert len(flat) == 3 and not any(m.get("tool_calls") or m.get("role") == "tool" for m in flat)
    ask = flat[-1]["content"]
    assert ask.startswith("How many KFC restaurants are there?")
    assert 'query {"metrics": ["restaurants_count"]} returned: {"rows": [[412]]}' in ask
    assert "No metric x" in ask and "trying the index" in ask
    assert chat._flat(history[:3]) == history[:3]  # nothing looked up: unchanged


def test_markdown_is_never_read_aloud():
    from kairos_kb.companion import voice

    said = voice._clean("The top cities are:\n\n- **Delhi**: 16\n- Bangalore: 13\n\n| City | Orders |\n|------|--------|\n"
                        "| Pune | 9 |\n## Summary\n1. Chennai leads.")
    assert said == "The top cities are: Delhi: 16 Bangalore: 13 City, Orders Pune, 9 Summary Chennai leads."


async def test_nemotron_on_a_voice_turn_gets_the_spoken_rules_last():
    sent = []

    class Stream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class Completions:
        async def create(self, **kw):
            sent.append(kw)
            return Stream()

    class Client:
        chat = type("C", (), {"completions": Completions()})()

    async def quiet(_t):
        return None

    for model in ("nvidia/Nemotron-3_5-Lightning", "gemini-3.5-flash"):
        await chat._stream_once(Client(), model, "rules" + chat.VOICE_MODE, [], [], False, quiet, None, lambda: True)
    await chat._stream_once(Client(), "nvidia/Nemotron-3_5-Lightning", "typed", [], [], False, quiet, None, lambda: True)
    assert sent[0]["messages"][0]["content"].endswith(chat.NEMOTRON_VOICE)
    assert chat.NEMOTRON_VOICE not in sent[1]["messages"][0]["content"]  # Gemini: unchanged
    assert sent[2]["messages"][0]["content"] == "typed"  # typed chat: unchanged


def test_each_lookup_says_what_its_numbers_cover():
    city_only = chat.covers({"product": "Sales", "metric": "orders", "dimension": "city",
                             "filters": [{"dimension": "city", "op": "=", "value": "Mumbai"}]})
    assert city_only.startswith("Sales, only where city = Mumbai") and "broken down by city" in city_only
    nothing = chat.covers({"product": "Delivered Orders Index", "metrics": ["restaurants_count"], "by": ["city"],
                           "filters": [{"dimension": "event_time", "op": "between", "value": ["a", "b"]}]})
    assert nothing.startswith("all of Delivered Orders Index: no restaurant, brand") and "by city" in nothing


def test_a_hosts_plain_postgres_url_gets_the_async_driver():
    for given in ("postgres://u:p@dpg-x.render.com/kairos", "postgresql://u:p@dpg-x/kairos"):
        assert Settings(_env_file=None, database_url=given).database_url.startswith("postgresql+asyncpg://u:p@dpg-x")
    already = "postgresql+asyncpg://kairos:kairos_dev@db:5432/kairos"
    assert Settings(_env_file=None, database_url=already).database_url == already
