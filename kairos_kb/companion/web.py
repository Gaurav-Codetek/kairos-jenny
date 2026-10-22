"""Weather that might affect deliveries: Tavily web search, bound to weather news for one city, and only when asked.

Jenny's numbers say *where* and *how much* (Delhi's orders are below a normal Tuesday); they can't say whether heavy
rain, a storm, a heatwave or fog is keeping riders off the road. With JENNY_WEB_SEARCH=1 and a Tavily key she can check
recent weather news and forecasts for a city — and only that:

- **Bound to weather.** She names a city; the search itself is built here (weather forecasts and alerts for that city),
  so she can't search the web for anything else. Results that aren't about the weather are dropped.
- **Only when asked.** The tool is offered on a turn only when the question is about the weather (asks_weather), and a
  call on any other turn is refused. Her pulse and desk never get it.
- **A lead, not a cause.** What comes back is marked as from the web: she names the source, and never says it caused a
  change in the numbers.

Settings:
    JENNY_WEB_SEARCH  turns it on (off by default)
    TAVILY_API_KEY    needed with it
    TAVILY_DAYS       how recent the news must be (default 3)
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

import httpx

from kairos_kb.config import get_settings

logger = logging.getLogger(__name__)

URL = "https://api.tavily.com/search"
MAX_RESULTS = 5
SNIPPET = 400

# Weather that can keep riders off the road or people indoors, as a person would ask about it.
WEATHER = re.compile(
    r"\b(weather|forecast|rain\w*|downpour|drizzle|monsoon|storm\w*|thunder\w*|lightning|cyclone|hurricane|typhoon|"
    r"flood\w*|waterlogg\w*|water-logg\w*|heat ?wave|heatstroke|temperature|cold ?wave|"
    r"snow(?:fall|storm|ing|y)?|hail(?:storm|stones?)?|fog(?:gy)?|"
    r"smog|wind ?storm|gale|imd|met department|weather alert|red alert|orange alert|yellow alert)\b",
    re.I,
)


def enabled() -> bool:
    s = get_settings()
    return bool(s.jenny_web_search and s.tavily_api_key)


def asks_weather(question: str) -> bool:
    """The owner is asking about the weather (so the weather lookup may be offered this turn)."""
    return bool(WEATHER.search(question or ""))


def _about_weather(item: Dict[str, Any]) -> bool:
    return bool(WEATHER.search(f"{item.get('title') or ''} {item.get('content') or ''}"))


async def weather_news(place: str, days: int | None = None) -> Dict[str, Any]:
    """Recent weather news, forecasts and alerts for a city that could affect deliveries: a short answer and sources."""
    s = get_settings()
    if not enabled():
        return {"error": "Weather lookup is off (JENNY_WEB_SEARCH, TAVILY_API_KEY)."}
    place = (place or "").strip()
    if not place:
        return {"error": "Name the city, e.g. 'Delhi'."}
    query = f"{place} weather forecast alert heavy rain storm flooding heatwave fog"
    body = {"query": query, "topic": "news", "days": days or s.tavily_days, "max_results": MAX_RESULTS,
            "search_depth": "basic", "include_answer": True}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(URL, json=body, headers={"Authorization": f"Bearer {s.tavily_api_key}"})
        if r.status_code != 200:
            return {"error": f"Weather lookup failed ({r.status_code})."}
        data = r.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Tavily weather search failed: %s", exc)
        return {"error": "Weather lookup is unreachable right now."}
    results: List[Dict[str, Any]] = [
        {"title": x.get("title"), "source": _host(x.get("url") or ""), "url": x.get("url"),
         "published": x.get("published_date"), "snippet": (x.get("content") or "")[:SNIPPET]}
        for x in (data.get("results") or [])[:MAX_RESULTS] if _about_weather(x)
    ]
    answer = data.get("answer") if results else None
    return {
        "place": place,
        "answer": answer,
        "results": results,
        "note": ("Weather news from the web, not from the business's data. If nothing here is about weather in this "
                 "city, say you found no weather news. Otherwise mention it only as a possible factor for deliveries, "
                 "naming the source. Never say it caused a change in the numbers; the data can't show that."),
    }


def _host(url: str) -> str:
    try:
        return httpx.URL(url).host.removeprefix("www.")
    except Exception:  # noqa: BLE001
        return ""
