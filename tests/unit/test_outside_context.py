"""Jenny's outside_context (Tavily): news the data can't see, as a sourced lead — and absent without a key."""

from kairos_kb.companion import web
from kairos_kb.config import Settings


def settings(monkeypatch, key="", on=True):
    s = Settings(_env_file=None, tavily_api_key=key, jenny_web_search=on)
    monkeypatch.setattr(web, "get_settings", lambda: s)
    return s


async def test_without_a_key_there_is_no_web_search(monkeypatch):
    settings(monkeypatch)
    assert not web.enabled()
    assert "error" in await web.outside_context("heavy rain", "Delhi")


async def test_web_search_is_off_unless_asked_for_even_with_a_key(monkeypatch):
    s = Settings(_env_file=None, tavily_api_key="tvly-test")
    assert s.jenny_web_search is False
    settings(monkeypatch, key="tvly-test", on=False)
    assert not web.enabled()
    assert "error" in await web.outside_context("heavy rain", "Delhi")


async def test_a_search_comes_back_as_a_short_sourced_lead_never_a_cause(monkeypatch):
    settings(monkeypatch, key="tvly-test")
    sent = {}

    class Response:
        status_code = 200

        def json(self):
            return {"answer": "Heavy rain caused waterlogging across Delhi on Sunday evening.",
                    "results": [{"title": "Delhi rain: waterlogging in several areas", "url": "https://www.example-news.in/delhi-rain",
                                 "published_date": "2026-10-18", "content": "Heavy showers lashed the city…" * 50}]}

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
    out = await web.outside_context("heavy rain or flooding", "Delhi")
    assert sent["body"]["query"] == "heavy rain or flooding Delhi" and sent["body"]["topic"] == "news"
    assert sent["auth"] == "Bearer tvly-test"
    r = out["results"][0]
    assert r["source"] == "example-news.in" and len(r["snippet"]) <= web.SNIPPET
    assert "never say it caused" in out["note"].lower()
