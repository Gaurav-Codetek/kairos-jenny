"""How the living agent notices things: statistics, never the language model.

Each detector reads one series (oldest first) and says whether its newest settled
period is worth a person's attention, with the numbers that justify it:

  spike / drop  the value sits far outside its recent normal: robust z-score against the
                median and MAD of the trailing window (one outlier cannot move the baseline)
  trend         it has kept moving one way: Mann-Kendall test over the last periods, plus
                the run of consecutive moves in that direction
  shift         it moved to a new level and stayed: the best two-segment split of the
                recent series, by Welch's t, with the break inside the recent window
  crossing      it crossed zero (a loss turned into a profit, or back)
  record        it is the highest or lowest value on record

Every signal must also clear a minimum business impact (percent change), so a tiny
move in a perfectly flat series does not raise an alarm just because it is unusual.
A seasonal check compares the period with the same period a year earlier: a December
that is always high is not news.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

Point = Tuple[date, float]


@dataclass
class Signal:
    kind: str                      # spike · drop · trend · shift · crossing · record
    period: date                   # the period the signal is about
    value: float
    baseline: Optional[float]
    impact_pct: Optional[float]    # change against the baseline, in percent
    score: float                   # strength: z, t or a normal score
    direction: str                 # up · down
    detail: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "period": self.period.isoformat(), "value": self.value,
                "baseline": self.baseline, "impact_pct": self.impact_pct, "score": round(self.score, 2),
                "direction": self.direction, **self.detail}


def median(xs: Sequence[float]) -> float:
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def mad(xs: Sequence[float]) -> float:
    """Median absolute deviation, scaled to a standard deviation for normal data."""
    m = median(xs)
    return 1.4826 * median([abs(x - m) for x in xs])


def pct(new: float, old: float) -> Optional[float]:
    if old == 0:
        return None
    return round((new - old) / abs(old) * 100, 2)


def change(new: float, old: float, values: Sequence[float]) -> Tuple[Optional[float], bool]:
    """(percent change, scaled): against the baseline when it is positive; otherwise against the series'
    typical size, flagged as scaled, since a percent of a negative or zero baseline reads backwards."""
    if old > 0:
        return pct(new, old), False
    typical = median([abs(v) for v in values]) or max(abs(v) for v in values) or 0
    return (round((new - old) / typical * 100, 2), True) if typical else (None, True)


def _phi(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


# ── detectors ─────────────────────────────────────────────────────────


def spike(series: List[Point], *, window: int = 12, z_min: float = 3.5, min_impact: float = 5.0) -> Optional[Signal]:
    """The newest value against the robust normal of the trailing window."""
    if len(series) < 7:
        return None
    hist = [v for _, v in series[-window - 1:-1]]
    if len(hist) < 6:
        return None
    m, s = median(hist), mad(hist)
    period, value = series[-1]
    impact, scaled = change(value, m, hist)
    if s == 0:
        # A perfectly flat history: any change is unusual, so only the impact decides.
        z = math.inf if value != m else 0.0
    else:
        z = (value - m) / s
    if abs(z) < z_min or impact is None or abs(impact) < min_impact:
        return None
    up = value > m
    return Signal("spike" if up else "drop", period, value, m, impact, abs(z) if math.isfinite(z) else 99.0,
                  "up" if up else "down", {"window": len(hist), "normal_range": [round(m - 2 * s, 4), round(m + 2 * s, 4)],
                                           "scaled": scaled})


def mann_kendall(xs: Sequence[float]) -> Tuple[float, float]:
    """(S statistic, two-sided p-value) of the Mann-Kendall trend test (no tie correction needed here)."""
    n = len(xs)
    s = sum((xs[j] > xs[i]) - (xs[j] < xs[i]) for i in range(n - 1) for j in range(i + 1, n))
    var = n * (n - 1) * (2 * n + 5) / 18
    if var == 0:
        return 0.0, 1.0
    z = (s - 1) / math.sqrt(var) if s > 0 else (s + 1) / math.sqrt(var) if s < 0 else 0.0
    return float(s), 2 * (1 - _phi(abs(z)))


def trend(series: List[Point], *, n: int = 6, p_max: float = 0.05, min_impact: float = 5.0) -> Optional[Signal]:
    """A run of periods moving one way: significant by Mann-Kendall, and large enough to matter."""
    if len(series) < n:
        return None
    tail = series[-n:]
    vals = [v for _, v in tail]
    s, p = mann_kendall(vals)
    impact, scaled = change(vals[-1], vals[0], vals)
    if p > p_max or impact is None or abs(impact) < min_impact:
        return None
    up = s > 0
    streak = 0
    for a, b in zip(reversed(vals[:-1]), reversed(vals[1:])):
        if (b > a) == up and b != a:
            streak += 1
        else:
            break
    return Signal("trend", tail[-1][0], vals[-1], vals[0], impact, round(-math.log10(max(p, 1e-12)), 2),
                  "up" if up else "down",
                  {"periods": n, "p_value": round(p, 4), "streak": streak, "since": tail[0][0].isoformat(),
                   "scaled": scaled})


def shift(series: List[Point], *, recent: int = 6, min_seg: int = 3, t_min: float = 4.0,
          min_impact: float = 5.0, lookback: int = 24) -> Optional[Signal]:
    """A move to a new level that has held: the best two-segment split, recent enough to be news."""
    pts = series[-lookback:]
    if len(pts) < 2 * min_seg + 1:
        return None
    vals = [v for _, v in pts]
    best = None
    for k in range(min_seg, len(vals) - min_seg + 1):
        a, b = vals[:k], vals[k:]
        ma, mb = sum(a) / len(a), sum(b) / len(b)
        va = sum((x - ma) ** 2 for x in a) / max(1, len(a) - 1)
        vb = sum((x - mb) ** 2 for x in b) / max(1, len(b) - 1)
        se = math.sqrt(va / len(a) + vb / len(b))
        t = abs(mb - ma) / se if se > 0 else (math.inf if mb != ma else 0.0)
        if best is None or t > best[0]:
            best = (t, k, ma, mb)
    if best is None:
        return None
    t, k, ma, mb = best
    impact, scaled = change(mb, ma, vals)
    breaks_recently = len(vals) - k <= recent
    if t < t_min or not breaks_recently or impact is None or abs(impact) < min_impact:
        return None
    return Signal("shift", pts[-1][0], round(mb, 4), round(ma, 4), impact, t if math.isfinite(t) else 99.0,
                  "up" if mb > ma else "down", {"since": pts[k][0].isoformat(), "periods_at_new_level": len(vals) - k,
                                                "scaled": scaled})


def crossing(series: List[Point]) -> Optional[Signal]:
    """The value changed sign: a loss became a profit, or the reverse."""
    if len(series) < 2:
        return None
    (_, prev), (period, value) = series[-2], series[-1]
    if prev == 0 or value == 0 or (prev > 0) == (value > 0):
        return None
    return Signal("crossing", period, value, prev, None, 10.0, "up" if value > 0 else "down",
                  {"from": prev, "to": value})


def record(series: List[Point], *, min_history: int = 12, min_impact: float = 5.0, quiet_for: int = 6) -> Optional[Signal]:
    """A new high or low on record that is news: the first in at least quiet_for periods, or by twice the
    minimum impact. A growing business sets records every few months; that alone is not news."""
    if len(series) < min_history + 1:
        return None
    period, value = series[-1]
    hist = [v for _, v in series[:-1]]
    for up in (True, False):
        best = max(hist) if up else min(hist)
        if (value > best) if up else (value < best):
            impact = pct(value, best)
            if impact is None or abs(impact) < min_impact:
                continue
            last_at = max(i for i, v in enumerate(hist) if v == best)
            age = len(hist) - last_at
            if age < quiet_for and abs(impact) < 2 * min_impact:
                continue
            return Signal("record", period, value, best, impact, 5.0, "up" if up else "down",
                          {"previous_record": best, "history": len(hist), "months_since_previous": age})
    return None


def seasonal_note(series: List[Point], period_len: int = 12) -> Optional[Dict[str, Any]]:
    """How the newest period compares with the same period one cycle earlier, and whether that is usual.

    Returns {"yoy_pct", "usual_range", "usual"}: usual when the year-on-year change sits within the
    range of the series' other year-on-year changes (median ± 3 MAD).
    """
    if len(series) < period_len + 6:
        return None
    vals = [v for _, v in series]
    yoys = [pct(vals[i], vals[i - period_len]) for i in range(period_len, len(vals))]
    yoys = [y for y in yoys if y is not None]
    if len(yoys) < 4:
        return None
    last = yoys[-1]
    m, s = median(yoys[:-1]), mad(yoys[:-1]) or 1.0
    return {"yoy_pct": last, "usual_range": [round(m - 3 * s, 2), round(m + 3 * s, 2)],
            "usual": abs(last - m) <= 3 * s}


def detect(series: List[Point], *, min_impact: float = 5.0, sensitivity: float = 1.0) -> List[Signal]:
    """Every signal on the newest period of a settled series, strongest first.

    sensitivity > 1 asks for stronger evidence (after a person said a metric is noisy).
    """
    found: List[Signal] = []
    for sig in (spike(series, z_min=3.5 * sensitivity, min_impact=min_impact * sensitivity),
                trend(series, p_max=0.05 / sensitivity, min_impact=min_impact * sensitivity),
                shift(series, t_min=4.0 * sensitivity, min_impact=min_impact * sensitivity),
                crossing(series),
                record(series, min_impact=min_impact * sensitivity)):
        if sig:
            found.append(sig)
    season = seasonal_note(series)
    for sig in found:
        if season:
            sig.detail["seasonal"] = season
    # A spike that the same month always shows is seasonal, not news.
    found = [s for s in found if not (s.kind in ("spike", "drop") and season and season["usual"])]
    return sorted(found, key=lambda s: -s.score)
