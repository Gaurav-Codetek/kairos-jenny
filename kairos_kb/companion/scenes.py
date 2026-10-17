"""Jenny's stage: the charts she puts beside the conversation while she talks.

Jenny chooses what to show; the system draws it. She calls `show` with a scene kind and the lookup it comes from
(each lookup in a turn gets an id: L1, L2…), and a scene is built here from that lookup's own numbers — never from
anything the model writes — so the chart and her words can't disagree. Without a lookup, the scene is read fresh
(compare_to_normal) and becomes a lookup of the turn, so it backs what she says too.

The form follows the question (the FT Visual Vocabulary's families; one axis, never two):

  breakdown   magnitude / ranking — slices ranked (cities, restaurants…), today against each one's usual
  deviation   deviation — each slice above or below its usual, as bars either side of zero
  share       part-to-whole — what share of the total each slice is (the top four, the rest as "Other")
  series      change over time — a line per day (a line per category to compare them; a second metric gets its
              own panel, never a second y-axis)
  heatmap     distribution / pattern — a grid (day × hour, or two categories): where it's high, low, or missing
  scatter     correlation — two measures per slice (volume against a rate: is a high rate just low volume?)
  trend       today against a normal day, hour by hour (the normal band and median, today's line up to now)
  hours       particular hours of today, each against the same hour on normal days
  number      one figure with its normal and range
  compare     two figures side by side (two lookups)

A query's shape picks its form when she doesn't (auto_kind): days and a number → series; days, hours and a number →
heatmap; a category and two numbers → scatter; a category and a number → breakdown.

Every scene lists its entities (a city, an hour) with the ways they're said aloud ("Delhi"; "nine a.m.", "9 am"),
so the screen can light each one up as she says it.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

KINDS = ("breakdown", "deviation", "share", "series", "heatmap", "scatter", "trend", "hours", "number", "compare")
MAX_LINES = 4        # lines on one series (more categories: the four biggest)
MAX_PARTS = 4        # slices on a share bar (the rest: "Other")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ](\d{2}):\d{2}(?::\d{2})?)?")
_WEEKDAY = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_MONTH = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
MAX_ROWS = 10        # bars on one breakdown
MAX_PER_TURN = 2     # scenes in one answer
LOW_VOLUME = 50      # a slice with fewer orders than this is noise: drawn muted

_WORDS = ["twelve", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven"]


def public(res: Any) -> Any:
    """A tool result without its private keys (`_raw`…): what the model sees. The full result stays for scenes."""
    if isinstance(res, dict):
        return {k: public(v) for k, v in res.items() if not str(k).startswith("_")}
    if isinstance(res, list):
        return [public(v) for v in res]
    return res


def _num(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def hour_aliases(h: int) -> List[str]:
    """How an hour is said: "nine a.m.", "9 am", "09:00", "nine o'clock"; "three p.m.", "15:00"."""
    twelve = h % 12 or 12
    ampm = "am" if h < 12 else "pm"
    word = _WORDS[twelve % 12]
    return [f"{twelve} {ampm}", f"{twelve}{ampm}", f"{twelve} {ampm[0]}.{ampm[1]}.", f"{word} {ampm}",
            f"{word} {ampm[0]}.{ampm[1]}.", f"{h:02d}:00", f"{h}:00", f"{word} o'clock", f"{twelve} o'clock"]


def slice_aliases(label: str) -> List[str]:
    """How a slice is said: its name, and without a trailing code ("Noida-1" → "Noida")."""
    out = [label]
    plain = re.sub(r"[-_ ]*\d+$", "", label).strip()
    if plain and plain != label:
        out.append(plain)
    return out


def _scene(kind: str, title: str, subtitle: str, data: Dict[str, Any], entities: List[Dict[str, Any]],
           source: Dict[str, Any], **kw) -> Dict[str, Any]:
    return {"id": uuid.uuid4().hex[:10], "kind": kind, "title": title, "subtitle": subtitle, "data": data,
            "entities": entities, "source": source, "focus": [], "annotations": [], **kw}


# ── builders, one per kind of lookup result ─────────────────────────────


def _breakdown_from_compare(res: Dict[str, Any], src) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    where = (res.get("_where") or res.get("where") or [None])[0]
    if not where or where.get("error"):
        return None, "That lookup has no breakdown by a dimension: run compare_to_normal with a dimension first."
    rows, seen = [], set()
    for r in (where.get("top") or []) + (where.get("against") or []):
        label = str(r.get("slice"))
        if label in seen:
            continue
        seen.add(label)
        value = _num(r.get("_today", r.get("today")))
        usual = _num(r.get("_usual", r.get("usual")))
        volume = _num(r.get("_volume"))
        if value is None:
            continue
        rows.append({"key": label, "label": label, "value": value, "display": r.get("today_display"),
                     "usual": usual, "usual_display": r.get("usual_display"), "change_pct": r.get("change_pct"),
                     "volume": volume, "volume_display": r.get("volume_display"),
                     "extra_display": r.get("extra_display") or r.get("delta_display"),
                     "low_volume": volume is not None and volume < LOW_VOLUME})
    if not rows:
        return None, "That breakdown came back empty."
    rows = rows[:MAX_ROWS]
    dim = where.get("dimension") or "slice"
    label = res.get("label") or res.get("metric")
    return _scene("breakdown", f"{label} by {dim}", f"Today so far against usual · {res.get('as_of', '')}".strip(" ·"),
                  {"rows": rows, "rate": res.get("kind") == "rate", "dimension": dim},
                  [{"key": r["key"], "label": r["label"], "aliases": slice_aliases(r["label"])} for r in rows], src,
                  metric_label=label), None


def _breakdown_from_query(res: Dict[str, Any], src) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """A query by one dimension: the bar is the metric she sorted by (else the first one); the other figures ride
    along on each bar ("4 delivered orders")."""
    cols = [str(c.get("name")) for c in res.get("columns") or []]
    if len(cols) < 2:
        return None, "A breakdown needs a query by one dimension with a metric."
    order = str((src.get("args") or {}).get("order") or "").split(" ")[0].lower()
    vi = next((i for i, c in enumerate(cols) if i > 0 and c.lower() == order), 1)
    rows = []
    for r in (res.get("rows") or [])[:MAX_ROWS]:
        value = _num(r[vi])
        if value is None:
            continue
        others = [f"{_fmt(r[i])} {cols[i].replace('_', ' ').lower()}" for i in range(1, len(cols))
                  if i != vi and _num(r[i]) is not None]
        label, n = str(r[0]), sum(1 for x in rows if x["label"] == str(r[0]))
        rows.append({"key": label if not n else f"{label} #{n + 1}", "label": label, "value": value,
                     "display": _fmt(r[vi]), "usual": None, "extra_display": " · ".join(others) or None})
    if not rows:
        return None, "That query came back empty."
    metric = cols[vi].replace("_", " ").lower()
    return _scene("breakdown", f"{metric.capitalize()} by {cols[0].replace('_', ' ').lower()}", "From her query", {
        "rows": rows, "rate": False, "dimension": cols[0].lower()},
        [{"key": r["key"], "label": r["label"], "aliases": slice_aliases(r["label"])} for r in rows], src,
        metric_label=metric), None


def _fmt(v: Any) -> str:
    n = _num(v)
    if n is None:
        return str(v)
    return f"{n:,.0f}" if float(n).is_integer() else f"{n:,.2f}"


def _hours_from_compare(res: Dict[str, Any], src) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    hours = ((res.get("by_hour") or {}).get("hours")) or []
    if not hours:
        return None, "That lookup has no hours: run compare_to_normal with hours (or a time dimension) first."
    rows = [{"key": f"h{h['hour']}", "hour": h["hour"], "label": hour_aliases(h["hour"])[0],
             "value": h.get("actual"), "display": h.get("actual_display"), "usual": h.get("expected"),
             "usual_display": h.get("expected_display"), "low": h.get("low"), "high": h.get("high"),
             "gap_display": h.get("gap_display"), "partial": h.get("partial")} for h in hours]
    label = res.get("label") or res.get("metric")
    basis = (res.get("by_hour") or {}).get("basis") or res.get("basis") or "normal days"
    return _scene("hours", f"{label}, hour by hour", f"Each hour today against the same hour on {basis}",
                  {"rows": rows}, [{"key": r["key"], "label": r["label"], "aliases": hour_aliases(r["hour"])}
                                   for r in rows], src, metric_label=label), None


def _hours_from_query(res: Dict[str, Any], src) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    rows_in = res.get("rows") or []
    if not rows_in or len(rows_in[0]) != 2 or not re.match(r"\d{4}-\d{2}-\d{2}[T ]\d{2}", str(rows_in[0][0])):
        return None, "Hours need a query by event_time:hour with one metric."
    latest = max(str(r[0])[:10] for r in rows_in)
    rows = []
    for r in rows_in:
        if str(r[0])[:10] != latest:
            continue
        h = int(str(r[0])[11:13])
        rows.append({"key": f"h{h}", "hour": h, "label": hour_aliases(h)[0], "value": _num(r[1]), "display": None,
                     "usual": None})
    rows.sort(key=lambda r: r["hour"])
    cols = [c.get("name") for c in res.get("columns") or []]
    metric = str(cols[1] if len(cols) > 1 else "value").replace("_", " ").lower()
    return _scene("hours", f"{metric.capitalize()}, hour by hour", f"On {latest}", {"rows": rows},
                  [{"key": r["key"], "label": r["label"], "aliases": hour_aliases(r["hour"])} for r in rows], src,
                  metric_label=metric), None


def _status(res: Dict[str, Any]) -> str:
    a, lo, hi = _num(res.get("actual")), _num(res.get("low")), _num(res.get("high"))
    if a is None or lo is None or hi is None:
        return "normal"
    return "above" if a > hi else "below" if a < lo else "normal"


def _trend_from_compare(res: Dict[str, Any], src) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    curve = res.get("_curve")
    if not curve or len(curve.get("typical") or []) < 2:
        return None, "There's no hour-by-hour curve for that metric today yet."
    label = res.get("label") or res.get("metric")
    cumulative = res.get("kind") == "additive"
    return _scene("trend", f"{label} today against normal",
                  (f"{'Running total' if cumulative else 'Each hour'} · normal is {res.get('basis', 'recent weeks')}"),
                  {"typical": curve["typical"], "today": curve["today"], "cumulative": cumulative,
                   "actual_display": res.get("actual_display"), "expected_display": res.get("expected_display"),
                   "as_of": res.get("as_of"), "status": _status(res)},
                  [{"key": "now", "label": "now", "aliases": ["right now", "so far", "at the moment"]}], src,
                  metric_label=label), None


def _number_from_compare(res: Dict[str, Any], src) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if res.get("actual") is None:
        return None, "That lookup has no single figure."
    label = res.get("label") or res.get("metric")
    return _scene("number", str(label), f"Today so far · normal is {res.get('basis', 'recent weeks')}", {
        "value": res.get("actual"), "display": res.get("actual_display"), "usual": res.get("expected"),
        "usual_display": res.get("expected_display"), "low_display": res.get("low_display"),
        "high_display": res.get("high_display"), "dev_pct": res.get("dev_pct"), "status": _status(res),
        "projection_display": res.get("projection_display")},
        [{"key": "value", "label": str(label), "aliases": [str(label).lower()]}], src, metric_label=label), None


# ── reading a query's shape ──────────────────────────────────────────────


def _kinds(res: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """Each column of a query result: time (dates), hour (0–23), num, or cat."""
    cols = [str(c.get("name")) for c in res.get("columns") or []]
    rows = res.get("rows") or []
    kinds = []
    for i, name in enumerate(cols):
        vals = [r[i] for r in rows[:80] if i < len(r) and r[i] not in (None, "")]
        if vals and all(_DATE.match(str(v)) for v in vals):
            kinds.append("time")
        elif vals and all(_num(v) is not None for v in vals):
            hourish = "hour" in name.lower() and all(0 <= (_num(v) or 0) <= 23 and float(_num(v)).is_integer() for v in vals)
            kinds.append("hour" if hourish else "num")
        else:
            kinds.append("cat")
    return cols, kinds


def _hourly(values: List[Any]) -> bool:
    """Timestamps at more than one time of day (an hourly grain), not one per day."""
    hours = {(_DATE.match(str(v)) or [None, None])[1] for v in values}
    return len(hours - {None, "00"}) > 0


def _day(v: Any) -> str:
    return str(v)[:10]


def day_label(iso: str) -> Tuple[str, List[str]]:
    """'2026-10-11' → 'Sun 11 Oct', and how it's said: 'Sunday', 'Sun', '11 October', 'October 11'."""
    from datetime import date as _d

    try:
        d = _d.fromisoformat(iso[:10])
    except ValueError:
        return iso, [iso]
    wd, mo = _WEEKDAY[d.weekday()], _MONTH[d.month - 1]
    return f"{wd[:3]} {d.day} {mo[:3]}", [wd, wd[:3], f"{d.day} {mo}", f"{mo} {d.day}", f"{d.day} {mo[:3]}", iso[:10]]


def _metric(name: str) -> str:
    return str(name).replace("_", " ").lower()


def query_kind(res: Dict[str, Any]) -> Optional[str]:
    """The form a query's shape asks for."""
    cols, k = _kinds(res)
    rows = res.get("rows") or []
    if len(cols) < 2 or len(rows) < 2:
        return None
    nums = [i for i, x in enumerate(k) if x == "num"]
    if not nums:
        return None
    if "time" in k:
        t = k.index("time")
        times = [r[t] for r in rows]
        if _hourly(times):
            days = {_day(v) for v in times}
            return "heatmap" if len(days) >= 2 and "cat" not in k else "hours" if len(days) < 2 and len(cols) == 2 else "series"
        if "hour" in k:
            return "heatmap"
        return "series"
    if "hour" in k:
        return "heatmap" if "cat" in k else "hours"
    cats = [i for i, x in enumerate(k) if x == "cat"]
    if len(cats) >= 2:
        return "heatmap"
    if len(nums) >= 2 and len(rows) >= 5:
        return "scatter"
    return "breakdown"


def _series_from_query(res: Dict[str, Any], src) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Change over time: a line per category (or one line), a panel per metric (never a second y-axis)."""
    cols, k = _kinds(res)
    rows = res.get("rows") or []
    if "time" not in k:
        return None, "A series needs a query by a date (event_time:day or a date dimension)."
    t = k.index("time")
    hourly = _hourly([r[t] for r in rows])
    cat = k.index("cat") if "cat" in k else None
    nums = [i for i, x in enumerate(k) if x == "num"][:2]
    xs = sorted({(str(r[t])[:13] if hourly else _day(r[t])) for r in rows})
    if len(xs) < 2:
        return None, "A series needs at least two days."
    xlabels = [(f"{x[11:13]}:00" if hourly else day_label(x)[0]) for x in xs]
    panels = []
    for n in nums:
        groups: Dict[str, Dict[str, float]] = {}
        for r in rows:
            g = str(r[cat]) if cat is not None else _metric(cols[n])
            v = _num(r[n])
            if v is not None:
                x = str(r[t])[:13] if hourly else _day(r[t])
                groups.setdefault(g, {})[x] = groups.get(g, {}).get(x, 0.0) + v
        top = sorted(groups, key=lambda g: -sum(groups[g].values()))[:MAX_LINES]
        panels.append({"metric_label": _metric(cols[n]), "lines": [
            {"key": g, "label": g, "values": [groups[g].get(x) for x in xs]} for g in top]})
    if cat is None and len(panels) == 1:
        panels[0]["lines"][0]["key"] = panels[0]["lines"][0]["label"] = panels[0]["metric_label"]
    ents = [{"key": ln["key"], "label": ln["label"], "aliases": slice_aliases(ln["label"])} for ln in panels[0]["lines"]]
    if not hourly:
        ents += [{"key": f"x:{x}", "label": day_label(x)[0], "aliases": day_label(x)[1]} for x in xs]
    title = " and ".join(pnl["metric_label"] for pnl in panels).capitalize()
    title += f" by {('hour' if hourly else 'day')}" + (f", by {_metric(cols[cat])}" if cat is not None else "")
    span = f"{xlabels[0]} – {xlabels[-1]}"
    return _scene("series", title, span, {"x": xs, "x_labels": xlabels, "panels": panels, "hourly": hourly},
                  ents, src, metric_label=panels[0]["metric_label"]), None


def _heatmap_from_query(res: Dict[str, Any], src) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """A grid: day × hour (or category × category, category × hour); missing cells are shown as missing."""
    cols, k = _kinds(res)
    rows = res.get("rows") or []
    n = k.index("num") if "num" in k else None
    if n is None:
        return None, "A heatmap needs a number to colour the grid."
    if "time" in k and _hourly([r[k.index("time")] for r in rows]):  # one timestamp column: day × hour
        t = k.index("time")
        rkey = lambda r: _day(r[t])  # noqa: E731
        ckey = lambda r: int(str(r[t])[11:13])  # noqa: E731
        rname, cname = "day", "hour"
    else:
        dims = [i for i, x in enumerate(k) if x in ("time", "cat", "hour")]
        if len(dims) < 2:
            return None, "A heatmap needs two dimensions (day and hour, or two categories)."
        a, b = dims[0], dims[1]
        if k[a] == "hour":
            a, b = b, a
        rkey = (lambda r: _day(r[a])) if k[a] == "time" else (lambda r: str(r[a]))
        ckey = (lambda r: int(_num(r[b]) or 0)) if k[b] == "hour" else (lambda r: str(r[b]))
        rname, cname = _metric(cols[a]), ("hour" if k[b] == "hour" else _metric(cols[b]))
    cells: Dict[Tuple[Any, Any], float] = {}
    for r in rows:
        v = _num(r[n])
        if v is not None:
            key = (rkey(r), ckey(r))
            cells[key] = cells.get(key, 0.0) + v
    rkeys = sorted({x for x, _ in cells})[:14]
    ckeys = sorted({y for _, y in cells})
    if cname == "hour":
        ckeys = list(range(min(ckeys), max(ckeys) + 1)) if ckeys else []
    if len(rkeys) < 2 or len(ckeys) < 2:
        return None, "A heatmap needs at least two rows and two columns."
    is_day = rname in ("day",) or all(_DATE.match(str(x)) for x in rkeys)
    rlabel = lambda x: day_label(x)[0] if is_day else str(x)  # noqa: E731
    clabel = lambda y: hour_aliases(y)[0] if cname == "hour" else str(y)  # noqa: E731
    grid = [[cells.get((x, y)) for y in ckeys] for x in rkeys]
    vals = [v for row in grid for v in row if v is not None]
    ents = [{"key": f"r:{x}", "label": rlabel(x), "aliases": day_label(x)[1] if is_day else slice_aliases(str(x))}
            for x in rkeys]
    ents += [{"key": f"c:{y}", "label": clabel(y), "aliases": hour_aliases(y) if cname == "hour" else slice_aliases(str(y))}
             for y in ckeys]
    title = f"{_metric(cols[n]).capitalize()} by {rname} and {cname}"
    return _scene("heatmap", title, "One cell per hour; hatched cells had nothing recorded (or haven't come yet)", {
        "rows": [{"key": f"r:{x}", "label": rlabel(x)} for x in rkeys],
        "cols": [{"key": f"c:{y}", "label": clabel(y)} for y in ckeys],
        "cells": grid, "min": min(vals), "max": max(vals), "metric": _metric(cols[n])},
        ents, src, metric_label=_metric(cols[n])), None


def _scatter_from_query(res: Dict[str, Any], src) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Correlation: two measures per slice — the bigger one (volume) across, the other up."""
    cols, k = _kinds(res)
    rows = res.get("rows") or []
    if "cat" not in k:
        return None, "A scatter needs a category (city, restaurant) with two measures."
    c = k.index("cat")
    nums = [i for i, x in enumerate(k) if x == "num"][:2]
    if len(nums) < 2:
        return None, "A scatter needs two measures."
    a, b = nums
    if sum(abs(_num(r[b]) or 0) for r in rows) > sum(abs(_num(r[a]) or 0) for r in rows):
        a, b = b, a  # volume across the bottom
    pts = [{"key": str(r[c]), "label": str(r[c]), "x": _num(r[a]), "y": _num(r[b])} for r in rows[:60]
           if _num(r[a]) is not None and _num(r[b]) is not None]
    if len(pts) < 3:
        return None, "A scatter needs at least three points."
    return _scene("scatter", f"{_metric(cols[b]).capitalize()} against {_metric(cols[a])}, by {_metric(cols[c])}",
                  "Each dot is one " + _metric(cols[c]), {"x_label": _metric(cols[a]), "y_label": _metric(cols[b]),
                                                         "points": pts},
                  [{"key": p["key"], "label": p["label"], "aliases": slice_aliases(p["label"])} for p in pts], src,
                  metric_label=_metric(cols[b])), None


def _deviation_from_compare(res: Dict[str, Any], src) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Deviation: each slice above or below its usual, either side of zero."""
    s, err = _breakdown_from_compare(res, src)
    if err:
        return None, err
    rows = [r for r in s["data"]["rows"] if r.get("change_pct") is not None]
    if not rows:
        return None, "That breakdown has no change against usual."
    rows.sort(key=lambda r: -(r["change_pct"] or 0))
    s.update(kind="deviation", title=f"{s['metric_label']}: each {s['data']['dimension']} against its usual",
             subtitle="Above or below its own usual, in percent")
    s["data"] = {"rows": [{"key": r["key"], "label": r["label"], "pct": r["change_pct"], "display": r.get("display"),
                           "usual_display": r.get("usual_display"), "low_volume": r.get("low_volume")} for r in rows]}
    return s, None


def _share_from(rows: List[Tuple[str, float]], title: str, src) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    rows = [(k, v) for k, v in rows if v and v > 0]
    total = sum(v for _, v in rows)
    if len(rows) < 2 or not total:
        return None, "A share needs at least two slices with something in them."
    rows.sort(key=lambda x: -x[1])
    parts = [{"key": k, "label": k, "value": v, "share": v / total} for k, v in rows[:MAX_PARTS]]
    rest = sum(v for _, v in rows[MAX_PARTS:])
    if rest:
        parts.append({"key": "Other", "label": f"Other ({len(rows) - MAX_PARTS})", "value": rest, "share": rest / total})
    return _scene("share", title, "Share of the total", {"parts": parts, "total": total},
                  [{"key": p["key"], "label": p["label"], "aliases": slice_aliases(p["key"])} for p in parts], src), None


def _share_from_lookup(tool: str, res: Dict[str, Any], src) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if tool == "compare_to_normal":
        s, err = _breakdown_from_compare(res, src)
        if err:
            return None, err
        if s["data"]["rate"]:
            return None, "A rate doesn't add up to a whole: a share needs a count or an amount."
        return _share_from([(r["label"], r["value"]) for r in s["data"]["rows"]], f"Share of {s['metric_label']}", src)
    cols, k = _kinds(res)
    if "cat" not in k or "num" not in k:
        return None, "A share needs a query by one category with an amount."
    c, n = k.index("cat"), k.index("num")
    return _share_from([(str(r[c]), _num(r[n]) or 0.0) for r in res.get("rows") or []],
                       f"Share of {_metric(cols[n])} by {_metric(cols[c])}", src)


def build(kind: str, lookup: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """A scene of this kind from one lookup of the turn ({id, tool, args, result})."""
    tool, res = lookup.get("tool"), lookup.get("result") or {}
    if res.get("error"):
        return None, f"That lookup failed ({res['error']}), so there's nothing to show from it."
    src = {"tool": tool, "args": lookup.get("args"), "lookup_id": lookup.get("id")}
    if kind == "breakdown":
        return (_breakdown_from_compare(res, src) if tool == "compare_to_normal" else
                _breakdown_from_query(res, src) if tool == "query" else (None, "A breakdown comes from "
                                                                              "compare_to_normal or a query."))
    if kind == "hours":
        return (_hours_from_compare(res, src) if tool == "compare_to_normal" else
                _hours_from_query(res, src) if tool == "query" else (None, "Hours come from compare_to_normal "
                                                                          "or a query by event_time:hour."))
    if kind == "series":
        return _series_from_query(res, src) if tool == "query" else (
            None, "A series comes from a query by a date (event_time:day), optionally with a category.")
    if kind == "heatmap":
        return _heatmap_from_query(res, src) if tool == "query" else (
            None, "A heatmap comes from a query by two dimensions (event_time:hour over several days, or two "
                  "categories).")
    if kind == "scatter":
        return _scatter_from_query(res, src) if tool == "query" else (
            None, "A scatter comes from a query by one category with two measures.")
    if kind == "deviation":
        return _deviation_from_compare(res, src) if tool == "compare_to_normal" else (
            None, "A deviation comes from compare_to_normal with a dimension.")
    if kind == "share":
        return _share_from_lookup(tool, res, src)
    if kind == "trend":
        return _trend_from_compare(res, src) if tool == "compare_to_normal" else (
            None, "A trend comes from compare_to_normal on one metric.")
    if kind == "number":
        return _number_from_compare(res, src) if tool == "compare_to_normal" else (
            None, "A single figure comes from compare_to_normal on one metric.")
    return None, f"Unknown scene '{kind}'. One of: {', '.join(KINDS)}."


def auto_kind(tool: str, res: Dict[str, Any]) -> Optional[str]:
    """The scene a lookup naturally makes, when a picture helps and she hasn't chosen one: a breakdown for a split by
    a dimension, hours for hour by hour, a trend for one metric against normal."""
    if not isinstance(res, dict) or res.get("error"):
        return None
    if tool == "compare_to_normal":
        return "breakdown" if res.get("_where") else "hours" if res.get("by_hour") else "trend" if res.get("_curve") else None
    if tool == "query":
        return query_kind(res)
    return None


def compare(a: Dict[str, Any], b: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Two figures side by side, each from its own lookup."""
    out = []
    for lk in (a, b):
        s, err = build("number", lk)
        if err:
            return None, err
        args = lk.get("args") or {}
        out.append({"key": lk.get("id"), "label": s["title"] + (f" · {args['dimension']}" if args.get("dimension") else ""),
                    "value": s["data"]["value"], "display": s["data"]["display"],
                    "usual_display": s["data"]["usual_display"], "status": s["data"]["status"]})
    return _scene("compare", f"{out[0]['label']} and {out[1]['label']}", "Today so far", {"items": out},
                  [{"key": o["key"], "label": o["label"], "aliases": [o["label"].lower()]} for o in out],
                  {"tool": "compare", "lookup_ids": [a.get("id"), b.get("id")]}), None


def focus(scene: Dict[str, Any], wanted: List[str], note: Optional[str]) -> Optional[str]:
    """Light up these entities first (by name or alias) and pin the note to the first. Error for a name that isn't
    in the scene, with the names that are."""
    keys = []
    for w in wanted or []:
        w_low = str(w).strip().lower()
        hit = next((e["key"] for e in scene["entities"]
                    if w_low in [e["label"].lower(), e["key"].lower(), *[a.lower() for a in e.get("aliases") or []]]),
                   None)
        if hit is None:
            names = ", ".join(e["label"] for e in scene["entities"][:12])
            return f"'{w}' isn't in that chart. It shows: {names}."
        keys.append(hit)
    scene["focus"] = keys
    if note:  # pinned to what the note names ("+60 at 14:00" goes on 2 pm), else the first in focus
        named = named_in(str(note), scene)
        scene["annotations"] = [{"key": named or (keys[0] if keys else None), "text": str(note)[:80]}]
    return None


def named_in(text: str, scene: Dict[str, Any]) -> Optional[str]:
    """The first entity of the scene a text names, by its label or any way it's said."""
    low = f" {text.lower()} "
    best = None
    for e in scene["entities"]:
        for a in [e["label"], *(e.get("aliases") or [])]:
            m = re.search(r"(?<![a-z0-9])" + re.escape(a.lower()) + r"(?![a-z0-9])", low)
            if m and (best is None or m.start() < best[0]):
                best = (m.start(), e["key"])
    return best[1] if best else None


def describe(scene: Dict[str, Any]) -> str:
    """What's on screen, in a line (for her, and for what backs her claims)."""
    lit = [e["label"] for e in scene["entities"] if e["key"] in scene.get("focus", [])]
    return scene["title"] + (f", with {', '.join(lit)} highlighted" if lit else "")
