"""A data product's semantic model, and the query port that serves it.

The model says, once, what the product means: its metrics (each an aggregate
expression over one base table, with optional mart shortcuts), the dimensions
to slice by (where each lives and how it joins to each base table), and the
entities they describe. A consumer asks the product — "gmv by city, month" —
and never names a table. The compiler picks the source:

  shortcut  a mart that already holds every requested metric and dimension, when
            rolling it up is allowed (additive metrics, or the mart's own grain)
  base      the base table, computing each metric from its expression and joining
            the dimension tables

and returns plain read-only SQL, which runs through the same guard as run_sql:
read-only, mapped tables only, personal columns masked.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

TIME_GRAINS = ("hour", "day", "week", "month", "quarter", "year")
OPS = {"=", "!=", "<>", ">", ">=", "<", "<=", "in", "not in", "between", "like"}


class QueryError(ValueError):
    """The request cannot be answered from this product; the message says why and what to do."""


def _norm(s: str) -> str:
    return re.sub(r"[`\"\s]", "", str(s or "")).upper()


def _literal(v: Any) -> str:
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, date):
        return f"'{v.isoformat()}'"
    s = str(v)
    if re.fullmatch(r"-?\d+(\.\d+)?", s):
        return s
    return "'" + s.replace("'", "''") + "'"


def _parse_by(item: str) -> Tuple[str, Optional[str]]:
    name, _, grain = str(item).partition(":")
    grain = grain.strip().lower() or None
    if grain and grain not in TIME_GRAINS:
        raise QueryError(f"Unknown time grain '{grain}'; use one of {', '.join(TIME_GRAINS)}.")
    return name.strip(), grain


class Model:
    """Index over a stored semantic model (the dict kept in DataProduct.spec['model'])."""

    def __init__(self, model: Dict[str, Any]) -> None:
        self.raw = model or {}
        self.metrics = {m["name"].lower(): m for m in self.raw.get("metrics") or []}
        self.dimensions = {d["name"].lower(): d for d in self.raw.get("dimensions") or []}

    def metric(self, name: str) -> Dict[str, Any]:
        m = self.metrics.get(str(name).lower())
        if m is None:
            raise QueryError(f"No metric '{name}'. This product has: {', '.join(self.metrics) or 'none'}.")
        return m

    def dimension(self, name: str) -> Dict[str, Any]:
        d = self.dimensions.get(str(name).lower())
        if d is None:
            raise QueryError(f"No dimension '{name}'. This product has: {', '.join(self.dimensions) or 'none'}.")
        return d

    # ── where a dimension lives ──

    def dim_column_in(self, dim: Dict[str, Any], table: str) -> Optional[str]:
        if _norm(dim["table"]) == _norm(table):
            return dim["column"]
        for loc in dim.get("also_in") or []:
            if _norm(loc["table"]) == _norm(table):
                return loc["column"]
        return None

    def dim_join_from(self, dim: Dict[str, Any], base: str) -> Optional[Dict[str, Any]]:
        for j in dim.get("joins") or []:
            if _norm(j["from_table"]) == _norm(base):
                return j
        return None


def _time(expr: str, grain: Optional[str]) -> str:
    return f"DATE_TRUNC('{grain.upper()}', {expr})" if grain else expr


def _where(parts: List[str]) -> str:
    return (" WHERE " + " AND ".join(parts)) if parts else ""


def _filter_sql(expr: str, f: Dict[str, Any]) -> str:
    op = str(f.get("op") or "=").lower().strip()
    if op not in OPS:
        raise QueryError(f"Unknown filter operator '{op}'; use one of {', '.join(sorted(OPS))}.")
    value = f.get("value")
    if op in ("in", "not in"):
        values = value if isinstance(value, list) else [value]
        if not values:
            raise QueryError("An 'in' filter needs at least one value.")
        return f"{expr} {op.upper()} ({', '.join(_literal(v) for v in values)})"
    if op == "between":
        if not isinstance(value, list) or len(value) != 2:
            raise QueryError("A 'between' filter needs two values: [from, to].")
        return f"{expr} BETWEEN {_literal(value[0])} AND {_literal(value[1])}"
    return f"{expr} {'<>' if op == '!=' else op.upper()} {_literal(value)}"


def compile_query(model: Dict[str, Any], metrics: List[str], by: Optional[List[str]] = None,
                  filters: Optional[List[Dict[str, Any]]] = None, order: str = "") -> Dict[str, Any]:
    """Compile a product query to SQL. Returns {sql, source, table, notes}; raises QueryError."""
    idx = Model(model)
    if not metrics:
        raise QueryError("Ask for at least one metric.")
    ms = [idx.metric(m) for m in metrics]
    by_items = [_parse_by(b) for b in (by or [])]
    dims = [(idx.dimension(n), g) for n, g in by_items]
    flts = [(idx.dimension(f.get("dimension", "")), f) for f in (filters or [])]
    for d, g in dims:
        if g and d.get("type") != "time":
            raise QueryError(f"'{d['name']}' is not a time dimension; a grain like ':month' only applies to dates.")
    notes: List[str] = []

    # ── 1. A shortcut: one mart holding every metric and dimension, when rolling it up is allowed ──
    coarsening = any(g for _, g in dims)
    shortcut_tables = None
    for m in ms:
        tables = {_norm(s["table"]): s["table"] for s in m.get("shortcuts") or []}
        shortcut_tables = tables if shortcut_tables is None else {k: v for k, v in shortcut_tables.items() if k in tables}
    for key, table in (shortcut_tables or {}).items():
        cols = [idx.dim_column_in(d, table) for d, _ in dims] + [idx.dim_column_in(d, table) for d, _ in flts]
        if any(c is None for c in cols):
            continue
        rollups = []
        for m in ms:
            s = next(s for s in m["shortcuts"] if _norm(s["table"]) == key)
            rollups.append((m, s))
        if any(s.get("rollup", "sum") == "none" for _, s in rollups):
            # A ratio or average stored per row may only be read at the mart's own grain.
            carried = {d["name"] for d in idx.dimensions.values() if idx.dim_column_in(d, table)}
            if coarsening or {d["name"] for d, _ in dims} != carried:
                continue
        if coarsening and any(s.get("rollup", "sum") not in ("sum", "min", "max") for _, s in rollups):
            continue
        # At the mart's own grain with a non-additive metric, rows are read as they are; otherwise rolled up.
        own_grain = any(s.get("rollup", "sum") == "none" for _, s in rollups)
        select, group = [], []
        for d, g in dims:
            expr = _time(f"t.{idx.dim_column_in(d, table)}", g)
            select.append(f"{expr} AS {d['name']}")
            if not own_grain:
                group.append(expr)
        for m, s in rollups:
            agg = {"sum": "SUM", "min": "MIN", "max": "MAX"}.get(s.get("rollup", "sum"))
            select.append(f"t.{s['column']} AS {m['name']}" if own_grain else f"{agg}(t.{s['column']}) AS {m['name']}")
        where = [_filter_sql(f"t.{idx.dim_column_in(d, table)}", f) for d, f in flts]
        sql = (f"SELECT {', '.join(select)} FROM {table} t{_where(where)}"
               + (f" GROUP BY {', '.join(group)}" if group else "")
               + _order(order, dims, ms))
        notes.append(f"Answered from the pre-aggregated table {table}.")
        return {"sql": sql, "source": "shortcut", "table": table, "notes": notes}

    # ── 2. The base table: every metric from its expression, dimensions joined ──
    bases = {_norm(m["base_table"]): m["base_table"] for m in ms}
    if len(bases) > 1:
        raise QueryError("These metrics are computed from different base tables "
                         f"({', '.join(bases.values())}); ask for them in separate queries.")
    base = next(iter(bases.values()))
    joins: Dict[str, str] = {}
    alias: Dict[str, str] = {}

    def dim_expr(d: Dict[str, Any]) -> str:
        col = idx.dim_column_in(d, base)
        if col:
            return f"f.{col}"
        j = idx.dim_join_from(d, base)
        if j is None:
            raise QueryError(f"Dimension '{d['name']}' cannot be reached from {base}.")
        if _norm(j["to_column"]) == _norm(d["column"]):
            return f"f.{j['from_column']}"  # the dimension is the join key itself: no join needed
        key = _norm(d["table"])
        if key not in alias:
            alias[key] = f"d{len(alias) + 1}"
            joins[key] = (f" LEFT JOIN {d['table']} {alias[key]} "
                          f"ON f.{j['from_column']} = {alias[key]}.{j['to_column']}")
        return f"{alias[key]}.{d['column']}"

    select, group = [], []
    for d, g in dims:
        expr = _time(dim_expr(d), g)
        select.append(f"{expr} AS {d['name']}")
        group.append(expr)
    for m in ms:
        select.append(f"{m['expression']} AS {m['name']}")
    where = [_filter_sql(dim_expr(d), f) for d, f in flts]
    sql = (f"SELECT {', '.join(select)} FROM {base} f{''.join(joins.values())}{_where(where)}"
           + (f" GROUP BY {', '.join(group)}" if group else "")
           + _order(order, dims, ms))
    if shortcut_tables:
        notes.append("A pre-aggregated table exists but cannot answer this grain; computed from the base table.")
    return {"sql": sql, "source": "base", "table": base, "notes": notes}


def _order(order: str, dims, ms) -> str:
    names = {d["name"].lower() for d, _ in dims} | {m["name"].lower() for m in ms}
    if order:
        col, _, direction = order.strip().partition(" ")
        if col.lower() not in names:
            raise QueryError(f"Order by one of the requested metrics or dimensions: {', '.join(sorted(names))}.")
        return f" ORDER BY {col} {'ASC' if direction.strip().lower() == 'asc' else 'DESC'}"
    time_dims = [d["name"] for d, g in dims if d.get("type") == "time"]
    if time_dims:
        return f" ORDER BY {time_dims[0]}"
    return f" ORDER BY {ms[0]['name']} DESC" if dims else ""


def columns_used(model: Dict[str, Any]) -> Dict[str, set]:
    """Per table (upper-cased full name): the columns the model depends on — the input ports' schema contract."""
    out: Dict[str, set] = {}

    def add(table: str, col: Optional[str]) -> None:
        if table and col:
            out.setdefault(_norm(table), set()).add(col.upper())

    idents = re.compile(r"\bf\.([A-Za-z_][A-Za-z0-9_$]*)")
    for m in model.get("metrics") or []:
        for c in idents.findall(m.get("expression") or ""):
            add(m["base_table"], c)
        for s in m.get("shortcuts") or []:
            add(s["table"], s["column"])
    for d in model.get("dimensions") or []:
        add(d["table"], d["column"])
        for loc in d.get("also_in") or []:
            add(loc["table"], loc["column"])
        for j in d.get("joins") or []:
            add(j["from_table"], j["from_column"])
            add(d["table"], j["to_column"])
    return out
