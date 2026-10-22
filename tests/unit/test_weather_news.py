"""Jenny's weather lookup (Tavily): weather news for a city that might affect deliveries — bound to weather, only when
asked about it, absent unless switched on."""

from kairos_kb.companion import chat, web
from kairos_kb.config import Settings


def settings(monkeypatch, key="tvly-test", on=True):
    s = Settings(_env_file=None, tavily_api_key=key, jenny_web_search=on)
    monkeypatch.setattr(web, "get_settings", lambda: s)
    return s


def tavily(monkeypatch, results, answer="Heavy rain is forecast for Delhi this evening."):
    sent = {}

    class Response:
        status_code = 200

        def json(self):
            return {"answer": answer, "results": results}

    class Client:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json, headers):
            sent.update(url=url, body=json, auth=headers["Authorization"])
            return Response()

    monkeypatch.setattr(web.httpx, "AsyncClient", Client)
    return sent


def test_only_a_question_about_the_weather_counts():
    for q in ["Is it raining in Delhi?", "Any weather alerts for Mumbai today?", "Could the heatwave be slowing orders?",
              "Is there flooding or waterlogging in Chennai?", "What's the forecast for Bangalore tonight?",
              "Any storm or fog warnings for Lucknow?"]:
        assert web.asks_weather(q), q
    for q in ["How are we doing today?", "Which cities are carrying GMV?", "Show me the Snowflake connection",
              "Why are cancellations up in Delhi?", "Is there a strike or a festival in Delhi?", "Train delays?"]:
        assert not web.asks_weather(q), q


async def test_off_unless_switched_on_with_a_key(monkeypatch):
    settings(monkeypatch, on=False)
    assert not web.enabled()
    assert "error" in await web.weather_news("Delhi")
    settings(monkeypatch, key="")
    assert not web.enabled()


async def test_the_search_is_weather_for_the_city_and_nothing_else_comes_back(monkeypatch):
    settings(monkeypatch)
    sent = tavily(monkeypatch, [
        {"title": "Delhi rain: waterlogging in several areas", "url": "https://www.example-news.in/delhi-rain",
         "published_date": "2026-10-21", "content": "Heavy showers lashed the city on Tuesday evening…" * 30},
        {"title": "Delhi election results", "url": "https://politics.example.com/x", "content": "Votes counted today."},
    ])
    out = await web.weather_news("Delhi")
    assert sent["body"]["query"].startswith("Delhi weather forecast") and sent["body"]["topic"] == "news"
    assert sent["auth"] == "Bearer tvly-test"
    assert [r["source"] for r in out["results"]] == ["example-news.in"]  # the election story is dropped
    assert len(out["results"][0]["snippet"]) <= web.SNIPPET
    assert "never say it caused" in out["note"].lower()


async def test_no_weather_news_means_no_answer_to_repeat(monkeypatch):
    settings(monkeypatch)
    tavily(monkeypatch, [{"title": "Delhi metro timings", "url": "https://x.example/y", "content": "Trains run late."}])
    out = await web.weather_news("Delhi")
    assert out["results"] == [] and out["answer"] is None


async def test_she_may_use_it_only_on_a_turn_about_the_weather(monkeypatch):
    settings(monkeypatch)
    tavily(monkeypatch, [{"title": "Rain alert for Delhi", "url": "https://n.example/a", "content": "Rain tonight."}])
    token = chat._TURN.set({"question": "Which cities are carrying GMV today?"})
    try:
        assert "error" in await chat.call_tool(None, "weather_news", {"place": "Delhi"})
    finally:
        chat._TURN.reset(token)
    token = chat._TURN.set({"question": "Is rain hitting deliveries in Delhi?"})
    try:
        out = await chat.call_tool(None, "weather_news", {"place": "Delhi"})
        assert out["results"][0]["title"] == "Rain alert for Delhi"
    finally:
        chat._TURN.reset(token)
    assert "weather_news" not in [t["function"]["name"] for t in chat.TOOLS + chat.LOOK_TOOLS]  # never on her own
