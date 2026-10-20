"""What's happening outside the data: Tavily web search, for possible causes the business's data can't see.

Jenny's numbers say *where* and *how much* (Delhi's cancellations are up 20%); they can't say *why* when the reason is
outside the business — heavy rain, a festival, a city-wide outage, a strike, a cricket final. With TAVILY_API_KEY set
she gets one more tool, outside_context, to look that up after she has looked at the data. What comes back is a lead,
not a finding: she says it's from the web, names the source, and never claims it caused the change.

Settings:
    JENNY_WEB_SEARCH  turns the tool on (off by default: she answers from the business's data only)
    TAVILY_API_KEY    needed with it
    TAVILY_DAYS       how recent the news must be (default 3)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import httpx

from kairos_kb.config import get_settings

logger = logging.getLogger(__name__)

URL = "https://api.tavily.com/search"
MAX_RESULTS = 5
SNIPPET = 400


def enabled() -> bool:
    s = get_settings()
    return bool(s.jenny_web_search and s.tavily_api_key)


async def outside_context(query: str, place: str = "", days: int | None = None) -> Dict[str, Any]:
    """Recent news and events that might bear on a change in the data: a short answer and its sources."""
    s = get_settings()
    if not enabled():
        return {"error": "Web search is off (JENNY_WEB_SEARCH, TAVILY_API_KEY)."}
    q = " ".join(x for x in (query.strip(), place.strip()) if x)
    if not q:
        return {"error": "Say what to look for, e.g. 'heavy rain or flooding' with the place."}
    body = {"query": q, "topic": "news", "days": days or s.tavily_days, "max_results": MAX_RESULTS,
            "search_depth": "basic", "include_answer": True}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(URL, json=body, headers={"Authorization": f"Bearer {s.tavily_api_key}"})
        if r.status_code != 200:
            return {"error": f"Web search failed ({r.status_code})."}
        data = r.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Tavily search failed: %s", exc)
        return {"error": "Web search is unreachable right now."}
    results: List[Dict[str, Any]] = [
        {"title": x.get("title"), "source": _host(x.get("url") or ""), "url": x.get("url"),
         "published": x.get("published_date"), "snippet": (x.get("content") or "")[:SNIPPET]}
        for x in (data.get("results") or [])[:MAX_RESULTS]
    ]
    return {
        "query": q,
        "answer": data.get("answer"),
        "results": results,
        "note": ("From the web, not from the business's data: a possible explanation to mention as such, naming the "
                 "source. Never say it caused the change; the data can't show that."),
    }


def _host(url: str) -> str:
    try:
        return httpx.URL(url).host.removeprefix("www.")
    except Exception:  # noqa: BLE001
        return ""
