"""Pacing: how today is going against a normal day, at this time of day. Pure functions.

Normal is learned from the business's own history: the same weekday over the last eight weeks
(a Friday is compared with Fridays), or the last two weeks when there are too few. For a number
that adds up over the day (orders, revenue) the companion compares today-so-far with what those
days had reached by the same minute, and projects the day's close from the share of a normal day
that is usually done by now. For a rate or an average (cancellation rate, order value) it compares
the value so far with theirs at the same minute. The spread of those days says how unusual a gap
is; a robust spread (median absolute deviation) keeps one odd day from setting the bar.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

WEEKS = 8
MIN_DAYS = 3


def median(xs: Sequence[float]) -> float:
    s = sorted(xs)
    n = len(s)
    if not n:
        return 0.0
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def quantile(xs: Sequence[float], q: float) -> float:
    s = sorted(xs)
    if not s:
        return 0.0
    i = (len(s) - 1) * q
    lo = int(i)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (i - lo)


def mad(xs: Sequence[float]) -> float:
    m = median(xs)
    return median([abs(x - m) for x in xs])


def pct(a: float, b: float) -> Optional[float]:
    return round((a / b - 1) * 100, 1) if b and b > 0 and a is not None else None


def baseline_days(today: date, available: Iterable[date], weeks: int = WEEKS) -> Tuple[List[date], str]:
    """The days today is compared with, and how they were chosen."""
    have = set(available)
    same = [today - timedelta(days=7 * k) for k in range(1, weeks + 1) if today - timedelta(days=7 * k) in have]
    if len(same) >= MIN_DAYS:
        return same, f"the last {len(same)} {today.strftime('%A')}s"
    recent = [today - timedelta(days=k) for k in range(1, 15) if today - timedelta(days=k) in have]
    return recent, f"the last {len(recent)} days"


def by_day(hourly: Dict[datetime, float]) -> Dict[date, List[float]]:
    out: Dict[date, List[float]] = {}
    for t, v in hourly.items():
        out.setdefault(t.date(), [0.0] * 24)[t.hour] += v or 0.0
    return out


def hours_vs_normal(hourly: Dict[datetime, float], today: date, cut: datetime,
                    hours: Optional[Iterable[int]] = None) -> Optional[Dict[str, Any]]:
    """Each hour of today so far (or just the ones asked for) against the same hour on normal days — for "what did
    the 5 a.m. outage cost us": the hour's actual, its usual, a typical range and the gap. The current hour is still
    running, so it is compared with the same part of a usual hour."""
    days = by_day(hourly)
    base, basis = baseline_days(today, [d for d in days if d < today])
    if not base:
        return None
    now_h = cut.hour
    frac_now = (cut.minute * 60 + cut.second) / 3600
    mine = days.get(today, [0.0] * 24)
    rows = []
    for h in sorted(set(hours)) if hours is not None else range(now_h + 1):
        if not 0 <= h <= now_h:
            continue
        frac = frac_now if h == now_h else 1.0
        usual = [days[d][h] * frac for d in base if d in days]
        exp, spread = median(usual), mad(usual) * 1.4826
        rows.append({"hour": h, "actual": mine[h], "expected": exp, "low": max(0.0, exp - spread), "high": exp + spread,
                     "gap": mine[h] - exp, "dev_pct": pct(mine[h], exp), "partial": h == now_h})
    skipped = [h for h in (hours or []) if not 0 <= h <= now_h]
    out: Dict[str, Any] = {"basis": basis, "hours": rows}
    if skipped:
        out["not_yet"] = f"Hours {skipped} haven't happened yet today."
    return out


def _cum_to(h24: List[float], hour: int, frac: float) -> float:
    return sum(h24[:hour]) + h24[hour] * frac


def pace_additive(hourly: Dict[datetime, float], today: date, cut: datetime, *, count_like: bool = True) -> Optional[Dict[str, Any]]:
    """Today-so-far against normal days at the same minute, for a number that adds up over the day."""
    days_map = by_day(hourly)
    available = [d for d, h in days_map.items() if d < today and sum(h) > 0]
    days, basis = baseline_days(today, available)
    if len(days) < MIN_DAYS:
        return None
    ch, frac = cut.hour, (cut.minute * 60 + cut.second) / 3600
    today_h = days_map.get(today, [0.0] * 24)
    actual = sum(today_h[: ch + 1])
    cums = [_cum_to(days_map[d], ch, frac) for d in days]
    fulls = [sum(days_map[d]) for d in days]
    expected = median(cums)
    spread = max(1.4826 * mad(cums), 0.03 * abs(expected), (expected ** 0.5) if count_like and expected > 0 else 0.0, 1e-9)
    shares = [c / f for c, f in zip(cums, fulls) if f > 0]
    share = median(shares) if shares else 0.0
    out: Dict[str, Any] = {
        "kind": "additive", "actual": actual, "expected": expected,
        "low": quantile(cums, 0.1), "high": quantile(cums, 0.9),
        "spread": spread, "z": (actual - expected) / spread, "dev_pct": pct(actual, expected),
        "share_done": round(share, 4), "projection": actual / share if share >= 0.05 else None,
        "expected_full": median(fulls), "basis": basis, "days": [d.isoformat() for d in days],
        "cut": cut.isoformat(sep=" "),
        "curve": {
            "typical": [[0, 0.0, 0.0, 0.0]] + [
                [h + 1, median(v), quantile(v, 0.1), quantile(v, 0.9)]
                for h in range(24) for v in [[sum(days_map[d][: h + 1]) for d in days]]],
            "today": [[0, 0.0]] + [[h + 1, sum(today_h[: h + 1])] for h in range(ch)] + [[round(ch + frac, 3), actual]],
        },
    }
    if ch >= 1:
        h = ch - 1
        vals = [days_map[d][h] for d in days]
        e = median(vals)
        s = max(1.4826 * mad(vals), 0.05 * abs(e), (e ** 0.5) if count_like and e > 0 else 0.0, 1e-9)
        out["hour"] = {"hour": h, "actual": today_h[h], "expected": e, "z": (today_h[h] - e) / s, "dev_pct": pct(today_h[h], e)}
    return out


def pace_rate(actual: Optional[float], baseline: Dict[date, float], hourly: Dict[datetime, float],
              today: date, cut: datetime) -> Optional[Dict[str, Any]]:
    """The value so far against normal days' values at the same minute, for a rate or an average."""
    if actual is None:
        return None
    days, basis = baseline_days(today, [d for d, v in baseline.items() if v is not None])
    vals = [baseline[d] for d in days]
    if len(vals) < MIN_DAYS:
        return None
    expected = median(vals)
    spread = max(1.4826 * mad(vals), 0.02 * abs(expected), 1e-9)
    days_map: Dict[date, Dict[int, float]] = {}
    for t, v in hourly.items():
        days_map.setdefault(t.date(), {})[t.hour] = v
    typical = []
    for h in range(24):
        v = [days_map[d][h] for d in days if d in days_map and h in days_map[d]]
        if v:
            typical.append([h + 0.5, median(v), quantile(v, 0.1), quantile(v, 0.9)])
    today_pts = [[h + 0.5, v] for h, v in sorted(days_map.get(today, {}).items()) if h <= cut.hour]
    return {"kind": "rate", "actual": actual, "expected": expected, "low": quantile(vals, 0.1),
            "high": quantile(vals, 0.9), "spread": spread, "z": (actual - expected) / spread,
            "dev_pct": pct(actual, expected), "basis": basis, "days": [d.isoformat() for d in days],
            "cut": cut.isoformat(sep=" "), "projection": None, "expected_full": None,
            "curve": {"typical": typical, "today": today_pts}}


def close_additive(hourly: Dict[datetime, float], day: date) -> Optional[Dict[str, Any]]:
    """How a finished day closed against normal days (same weekday)."""
    days_map = by_day(hourly)
    if day not in days_map:
        return None
    days, basis = baseline_days(day, [d for d, h in days_map.items() if d < day and sum(h) > 0])
    if len(days) < MIN_DAYS:
        return None
    fulls = [sum(days_map[d]) for d in days]
    actual = sum(days_map[day])
    e = median(fulls)
    s = max(1.4826 * mad(fulls), 0.03 * abs(e), 1e-9)
    return {"day": day.isoformat(), "actual": actual, "expected": e, "dev_pct": pct(actual, e),
            "z": (actual - e) / s, "basis": basis}


def close_rate(daily: Dict[date, float], day: date) -> Optional[Dict[str, Any]]:
    if day not in daily:
        return None
    days, basis = baseline_days(day, [d for d in daily if d < day])
    vals = [daily[d] for d in days]
    if len(vals) < MIN_DAYS:
        return None
    e = median(vals)
    s = max(1.4826 * mad(vals), 0.02 * abs(e), 1e-9)
    return {"day": day.isoformat(), "actual": daily[day], "expected": e, "dev_pct": pct(daily[day], e),
            "z": (daily[day] - e) / s, "basis": basis}


def judge(p: Dict[str, Any], good: str, *, min_pct: float = 5.0, sensitivity: float = 1.0) -> Dict[str, Any]:
    """normal / above / below normal, how strongly, and whether that is good for the business.
    Early in the day (little of a normal day done yet) the bar is higher: a quiet first hour says little."""
    early = p.get("kind") == "additive" and (p.get("share_done") or 0) < 0.08
    if p.get("kind") == "additive" and (p.get("share_done") or 0) < 0.03:
        # The first few percent of a normal day (a handful of orders after midnight) can't be read at all.
        return {"status": "early", "direction": None, "strength": None, "valence": "neutral"}
    need = 2.5 * sensitivity * (1.6 if early else 1.0)
    z, dev = p["z"], p.get("dev_pct")
    if abs(z) < need or (dev is not None and abs(dev) < min_pct):
        return {"status": "early" if early else "normal", "direction": None, "strength": None, "valence": "neutral"}
    direction = "up" if z > 0 else "down"
    strong = abs(z) >= 1.6 * need and (dev is None or abs(dev) >= 2 * min_pct)
    valence = "neutral" if good == "neutral" else ("good" if (direction == "up") == (good == "up") else "bad")
    return {"status": "above" if direction == "up" else "below", "direction": direction,
            "strength": "strong" if strong else "clear", "valence": valence}
