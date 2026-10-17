"""Designing a data product from a business concept: the LLM proposes, code checks.

Two passes over one connection's enriched map:

  1. inputs   given the concept ("Sales") and the person's intent, pick every table
              in the warehouse that belongs to it — the facts that record it, the
              dimensions that describe it, the aggregates already built for it.
              These become the product's input ports.
  2. model    from those inputs (columns with enriched meanings, grain, build SQL),
              define the product's semantic model: metrics once each, as an
              aggregate over a base table with mart shortcuts; dimensions with
              where they live and how they join; entities; domain tools (named
              queries agents call); a glossary, caveats and rules for agents.

Code then keeps only what holds: tables are inputs, columns exist, joins have both
keys, every tool compiles — and every metric and dimension is compiled on the
platform itself (WHERE 1 = 0: checked, nothing scanned). What fails is dropped
and recorded.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from kairos_kb.context.privacy import is_masked, tagged_personal
from kairos_kb.products.semantic import QueryError, compile_query


# ── pass 1: inputs ───────────────────────────────────────────────────


class InputPick(BaseModel):
    table: str = Field(description="Full table name, exactly as listed.")
    role: str = Field(description="fact (records the concept's events), dimension (describes its entities), "
                                  "aggregate (a mart already built for it), or reference.")
    why: str = Field(description="One sentence: what this table contributes to the product.")


class LeftOut(BaseModel):
    table: str
    why: str


class Selection(BaseModel):
    name: str = Field(description="Product name, e.g. 'Sales'.")
    domain: str = Field(description="Business domain, e.g. 'Commercial'.")
    inputs: List[InputPick]
    left_out: List[LeftOut] = Field(default_factory=list,
                                    description="Tables that look related but do not belong, and why (at most 8).")


SELECT_SYSTEM = """You assemble data products. A data product consolidates everything one business
concept needs (Sales, Delivery performance, Customer) from a warehouse into a single unit.
Given the concept, the person's intent, and the warehouse's tables (each with its layer, role,
grain and columns), pick the tables that belong to the concept:
- the fact tables that record its events, at the finest clean grain available (prefer curated
  facts over raw or staging copies of the same data);
- the dimension tables that describe its entities (who, where, what, when);
- aggregate marts already built for it (they become fast shortcuts).
Do not pick raw or staging tables when a curated table holds the same data; do not pick tables
that serve a different concept. Use table names exactly as given."""


def _cols(m: Dict[str, Any], limit: int, meaning: bool) -> str:
    out = []
    for c in (m.get("columns") or [])[:limit]:
        bit = f"{c['name']} {c.get('type') or ''}".strip()
        if meaning and c.get("meaning"):
            bit += f" — {str(c['meaning'])[:160]}"
        if meaning and c.get("aggregation"):
            bit += f" [{c['aggregation']}]"
        out.append(bit)
    return ("\n    - " + "\n    - ".join(out)) if meaning else ", ".join(out)


def owned_section(owned: str) -> List[str]:
    return ["", "OWNED BY OTHER DATA PRODUCTS — these metrics are defined there; do not define them again "
                "(shared dimension tables may still be used):", owned, ""] if owned else []


def selection_brief(concept: str, intent: str, tables: List[Dict[str, Any]], owned: str = "") -> str:
    lines = [f"CONCEPT: {concept}", f"INTENT: {intent or '(none: use the concept)'}", *owned_section(owned),
             "", "WAREHOUSE TABLES:"]
    for t in tables:
        lines.append(f"- {t['full_name']} [{t.get('lane') or '?'} · {t.get('role') or 'unclassified'}"
                     f"{' · ' + format(t['row_count'], ',') + ' rows' if t.get('row_count') else ''}]"
                     f"\n  grain: {(t.get('grain') or '-')[:200]}\n  summary: {(t.get('summary') or '-')[:220]}"
                     f"\n  columns: {_cols(t, 40, False)}")
    return "\n".join(lines)


# ── pass 2: the semantic model ───────────────────────────────────────


class Join(BaseModel):
    from_table: str = Field(description="A base (fact) table.")
    from_column: str = Field(description="Key column on the base table.")
    to_column: str = Field(description="Matching key column on this dimension's table.")


class Location(BaseModel):
    table: str
    column: str


class Dimension(BaseModel):
    name: str = Field(description="snake_case id, e.g. city, order_date, cuisine.")
    label: str
    description: str
    type: str = Field(description="categorical, time, or numeric.")
    table: str = Field(description="The table that defines it (a dimension table, or the base table).")
    column: str
    joins: List[Join] = Field(default_factory=list, description="How each base table reaches this table. "
                                                               "Empty when the column is on the base table.")
    also_in: List[Location] = Field(default_factory=list, description="Aggregate marts carrying the same "
                                                                      "dimension, and the column there.")


class Shortcut(BaseModel):
    table: str = Field(description="An aggregate mart that already holds this metric.")
    column: str
    rollup: str = Field(description="sum when the column can be summed across the mart's rows; "
                                    "none for ratios, averages or percentiles stored per row.")


class Metric(BaseModel):
    name: str = Field(description="snake_case id, e.g. gmv, orders, aov, cancel_rate.")
    label: str
    description: str = Field(description="One sentence a business user understands.")
    unit: str = ""
    base_table: str = Field(description="The fact table it is computed from.")
    expression: str = Field(description="One SQL aggregate over the base table, columns prefixed with 'f.', "
                                        "e.g. SUM(IFF(f.is_delivered, f.sales_amount, 0)). Take the logic "
                                        "from the marts' build SQL when shown, so shortcut and base agree.")
    additive: bool = Field(description="True when values can be summed across any dimension.")
    shortcuts: List[Shortcut] = Field(default_factory=list)
    caveat: str = ""


class Entity(BaseModel):
    name: str
    description: str
    table: str
    key: str


class Tool(BaseModel):
    name: str = Field(description="snake_case, reads as a question, e.g. revenue_by_city_month.")
    description: str = Field(description="When an agent should call it.")
    metrics: List[str]
    by: List[str] = Field(default_factory=list, description="Dimension names; time dimensions may carry a "
                                                            "grain: 'order_date:month'.")


class Term(BaseModel):
    term: str
    meaning: str


class SemanticModel(BaseModel):
    description: str = Field(description="Two or three sentences: what the product is and holds.")
    purpose: str = Field(description="Who uses it and for which decisions.")
    consumers: List[str] = Field(default_factory=list)
    entities: List[Entity] = Field(default_factory=list)
    dimensions: List[Dimension]
    metrics: List[Metric]
    tools: List[Tool] = Field(default_factory=list, description="4 to 8 domain tools agents call by name.")
    glossary: List[Term] = Field(default_factory=list, description="Business terms and synonyms users say.")
    caveats: List[str] = Field(default_factory=list)
    agent_guidance: List[str] = Field(default_factory=list, description="Concrete rules for answering from "
                                                                        "this product.")


MODEL_SYSTEM = """You define the semantic model of a data product: the single, consolidated
interface through which people and agents use one business concept, without naming tables.
- Metrics: each defined ONCE, as one SQL aggregate over its base fact table (columns prefixed
  'f.'). Copy the logic from the marts' build SQL when shown, so the base computation and the
  mart agree. When a mart already holds the metric, add it as a shortcut (rollup 'sum' only if
  its rows can be summed; 'none' for ratios, averages, percentiles). Ratios like AOV or a rate
  are defined from their parts, e.g. SUM(...) / NULLIF(COUNT(...), 0) — never AVG of a ratio.
- Dimensions: what users slice by. Say which table defines each, how every base table joins to
  it (from_column on the base, to_column on that table), and which marts carry it (also_in).
  Dates: type 'time'.
- Only include metrics that belong to the concept and intent; measures for other concepts stay out.
- Metrics are what the business tracks and asks about (orders, GMV, AOV, cancellation rate, units
  sold), not one metric per numeric column. The measures the marts already compute are the best
  evidence of what is tracked: define those first, then the base totals they are built from.
  Prices, line attributes and fees are metrics only when the intent asks for them.
- Tools: 4 to 8 named queries that answer the concept's everyday questions.
Use table and column names exactly as given. Never invent a column."""


DIALECTS = {
    "snowflake": "Snowflake SQL: IFF(cond, a, b) (there is no IF), COUNT_IF(cond), DIV0(a, b), "
                 "MEDIAN(x), PERCENTILE_CONT(p) WITHIN GROUP (ORDER BY x), DATE_TRUNC('MONTH', d).",
    "databricks": "Databricks SQL: IF(cond, a, b), COUNT_IF(cond), try_divide(a, b), "
                  "percentile_approx(x, p), DATE_TRUNC('MONTH', d).",
}


def model_brief(concept: str, intent: str, inputs: List[Dict[str, Any]], dialect: str = "databricks",
                owned: str = "") -> str:
    lines = [f"CONCEPT: {concept}", f"INTENT: {intent or '(none: use the concept)'}",
             f"SQL DIALECT — write every expression in it: {DIALECTS.get(dialect, dialect)}", *owned_section(owned),
             "", "INPUT TABLES:"]
    for m in inputs:
        lines.append(f"\n## {m['full_name']}  [role in product: {m.get('port_role')}; {m.get('role') or 'unclassified'}]"
                     f"\ngrain: {m.get('grain') or '-'}\ngrain_key: {m.get('grain_key') or '-'}"
                     f"\ncolumns:{_cols(m, 80, True)}"
                     + (f"\nbuild SQL:\n{m['build_sql'][:2500]}" if m.get("build_sql") else ""))
    return "\n".join(lines)


# ── checks ───────────────────────────────────────────────────────────


def _norm(s: str) -> str:
    return re.sub(r"[`\"\s]", "", str(s or "")).upper()


def _snake(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(s or "").lower()).strip("_") or "x"


def validate_model(model: SemanticModel, inputs: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    """Static checks against the map. Returns (model dict, dropped)."""
    tables = {_norm(m["full_name"]): m for m in inputs}
    dropped: List[Dict[str, str]] = []

    def table(name: str) -> Optional[Dict[str, Any]]:
        hit = tables.get(_norm(name))
        if hit:
            return hit
        short = [m for m in inputs if _norm(m["full_name"]).split(".")[-1] == _norm(name).split(".")[-1]]
        return short[0] if len(short) == 1 else None

    def col(m: Dict[str, Any], c: str) -> Optional[str]:
        return next((x["name"] for x in m["columns"] if _norm(x["name"]) == _norm(c)), None)

    def drop(kind: str, item: str, reason: str) -> None:
        dropped.append({"kind": kind, "item": item, "reason": reason})

    dims: List[Dict[str, Any]] = []
    for d in model.dimensions:
        t = table(d.table)
        c = col(t, d.column) if t else None
        if not t or not c:
            drop("dimension", d.name, f"{d.table}.{d.column} is not a column of an input table")
            continue
        if is_masked(c, tagged_personal(t["columns"])):
            drop("dimension", d.name, f"{c} holds personal data")
            continue
        joins = []
        for j in d.joins:
            bt = table(j.from_table)
            fc = col(bt, j.from_column) if bt else None
            tc = col(t, j.to_column)
            if bt and fc and tc:
                joins.append({"from_table": bt["full_name"], "from_column": fc, "to_column": tc})
            else:
                drop("join", f"{d.name} ← {j.from_table}", f"{j.from_table}.{j.from_column} = "
                                                           f"{d.table}.{j.to_column} names a missing column")
        also = []
        for loc in d.also_in:
            lt = table(loc.table)
            lc = col(lt, loc.column) if lt else None
            if lt and lc:
                also.append({"table": lt["full_name"], "column": lc})
        name = _snake(d.name)
        if any(x["name"] == name for x in dims):
            continue
        dims.append({"name": name, "label": d.label, "description": d.description,
                     "type": d.type if d.type in ("categorical", "time", "numeric") else "categorical",
                     "table": t["full_name"], "column": c, "entity_id": t["entity_id"],
                     "joins": joins, "also_in": also})

    metrics: List[Dict[str, Any]] = []
    for m in model.metrics:
        bt = table(m.base_table)
        if not bt:
            drop("metric", m.name, f"base table {m.base_table} is not an input")
            continue
        missing = [c for c in re.findall(r"\bf\.([A-Za-z_][A-Za-z0-9_$]*)", m.expression) if not col(bt, c)]
        if missing:
            drop("metric", m.name, f"{bt['full_name']} has no column {', '.join(sorted(set(missing)))}")
            continue
        if re.search(r";|\b(insert|update|delete|merge|drop|create|alter|grant)\b", m.expression, re.I):
            drop("metric", m.name, "the expression is not a read-only aggregate")
            continue
        shortcuts = []
        for s in m.shortcuts:
            st = table(s.table)
            sc = col(st, s.column) if st else None
            if st and sc:
                shortcuts.append({"table": st["full_name"], "column": sc,
                                  "rollup": s.rollup if s.rollup in ("sum", "min", "max", "none") else "none"})
            else:
                drop("shortcut", f"{m.name} → {s.table}.{s.column}", "not a column of an input table")
        name = _snake(m.name)
        if any(x["name"] == name for x in metrics):
            drop("metric", m.name, "defined twice")
            continue
        metrics.append({"name": name, "label": m.label, "description": m.description, "unit": m.unit,
                        "base_table": bt["full_name"], "base_entity_id": bt["entity_id"],
                        "expression": m.expression.strip(), "additive": m.additive,
                        "shortcuts": shortcuts, "caveat": m.caveat})

    out: Dict[str, Any] = {
        "description": model.description, "purpose": model.purpose, "consumers": model.consumers,
        "entities": [e.model_dump() for e in model.entities if table(e.table)],
        "dimensions": dims, "metrics": metrics,
        "glossary": [t.model_dump() for t in model.glossary],
        "caveats": model.caveats, "agent_guidance": model.agent_guidance,
    }
    tools = []
    for t in model.tools:
        try:
            compile_query(out, t.metrics, t.by)
        except QueryError as exc:
            drop("tool", t.name, str(exc))
            continue
        tools.append({**t.model_dump(), "name": _snake(t.name)})
    out["tools"] = tools
    return out, dropped


async def verify_on_platform(model: Dict[str, Any], connector) -> List[Dict[str, str]]:
    """Compile every metric and every joined dimension on the platform; drop what does not compile.

    WHERE 1 = 0 makes the platform parse, resolve and type-check the query without reading data.
    """
    from kairos_kb.context.query import check_read_only

    dropped: List[Dict[str, str]] = []

    async def compiles(sql: str) -> Optional[str]:
        problem = check_read_only(sql)
        if problem:
            return problem
        try:
            result = await connector.execute_query(sql, row_limit=1)
        except TypeError:
            result = await connector.execute_query(sql)
        except Exception as exc:  # noqa: BLE001
            return str(exc)[:300]
        status = (result or {}).get("status") or {}
        if status.get("state") not in (None, "SUCCEEDED"):
            return str(((status.get("error") or {}).get("message")) or status.get("state"))[:300]
        return None

    keep = []
    for m in model["metrics"]:
        err = await compiles(f"SELECT {m['expression']} AS v FROM {m['base_table']} f WHERE 1 = 0")
        if err:
            dropped.append({"kind": "metric", "item": m["name"], "reason": f"does not compile on the platform: {err}"})
        else:
            m["verified"] = "compiles"
            keep.append(m)
    model["metrics"] = keep
    for d in model["dimensions"]:
        for j in list(d.get("joins") or []):
            err = await compiles(f"SELECT d.{d['column']} FROM {j['from_table']} f LEFT JOIN {d['table']} d "
                                 f"ON f.{j['from_column']} = d.{j['to_column']} WHERE 1 = 0")
            if err:
                d["joins"].remove(j)
                dropped.append({"kind": "join", "item": f"{d['name']} ← {j['from_table']}",
                                "reason": f"does not compile on the platform: {err}"})
    # Tools that named a dropped metric no longer compile.
    tools = []
    for t in model.get("tools") or []:
        try:
            compile_query(model, t["metrics"], t["by"])
            tools.append(t)
        except QueryError as exc:
            dropped.append({"kind": "tool", "item": t["name"], "reason": str(exc)})
    model["tools"] = tools
    return dropped


async def select_inputs(concept: str, intent: str, tables: List[Dict[str, Any]], owned: str = "") -> Selection:
    from kairos_kb.llm.provider import chat_model

    llm = chat_model()
    if llm is None:
        raise RuntimeError("No LLM is configured; cannot design the product.")
    return await llm.with_structured_output(Selection).ainvoke(
        [("system", SELECT_SYSTEM), ("human", selection_brief(concept, intent, tables, owned))])


async def design_model(concept: str, intent: str, inputs: List[Dict[str, Any]], dialect: str = "databricks",
                       owned: str = "") -> SemanticModel:
    from kairos_kb.llm.provider import chat_model

    llm = chat_model()
    if llm is None:
        raise RuntimeError("No LLM is configured; cannot design the product.")
    return await llm.with_structured_output(SemanticModel).ainvoke(
        [("system", MODEL_SYSTEM), ("human", model_brief(concept, intent, inputs, dialect, owned))])


class Repaired(BaseModel):
    metrics: List[Metric]


async def repair_metrics(designed: SemanticModel, failures: List[Dict[str, str]], inputs: List[Dict[str, Any]],
                         dialect: str) -> List[Metric]:
    """One more pass for metrics the platform rejected: the model sees the platform's own error."""
    from kairos_kb.llm.provider import chat_model

    llm = chat_model()
    names = {f["item"] for f in failures}
    failed = [m for m in designed.metrics if _snake(m.name) in names]
    if llm is None or not failed:
        return []
    errors = "\n".join(f"- {f['item']}: {f['reason']}" for f in failures)
    listing = "\n".join(f"- {m.model_dump_json()}" for m in failed)
    out = await llm.with_structured_output(Repaired).ainvoke([
        ("system", MODEL_SYSTEM),
        ("human", f"{model_brief('', '', inputs, dialect)}\n\nThese metrics did not compile on the platform:\n"
                  f"{errors}\n\nTheir definitions:\n{listing}\n\nReturn them corrected, same names. Fix only "
                  "what the error points at; keep each metric's meaning."),
    ])
    return [m for m in out.metrics if _snake(m.name) in names]
