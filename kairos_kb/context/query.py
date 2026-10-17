"""Read-only SQL for agents, governed by the map.

The map tells an agent what data means and how far to trust it; run_sql lets
it read the values. So the query path enforces what the map knows instead of
going around it:

  read-only      one statement; SELECT, WITH, SHOW, DESCRIBE or EXPLAIN only;
                 writes and state changes refused (string literals and
                 comments ignored when checking)
  no side doors  no file or path reads (read_files, `/Volumes/…`, csv.`…`),
                 no secrets, no external calls (http_request, ai_query, …)
  in the map     tables fully qualified (catalog.schema.table), known to the
                 map, visible to the agent, and in its allowed catalogs
  personal data  identifying columns — from profiles where Kairos has them,
                 from column-name patterns where it does not — are masked in
                 the result, including through aliases and expressions; only
                 counting them (COUNT, COUNT DISTINCT) passes through
  context        every result carries the map's facts about the tables used:
                 trust level, grain, caveats, freshness, personal-data columns;
                 an unprofiled table comes with a prompt to read its context
  bounded        row and time limits; long values cut
  audited        the SQL, its tables and its cost are recorded

These checks are one layer. The Databricks identity Kairos runs as should be
read-only and limited to what agents may see, with column masks for personal
data — no text check is a complete SQL parser.
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.config import get_settings
from kairos_kb.connectors.factory import connector_for_tables
from kairos_kb.context.access import AgentIdentity
from kairos_kb.context.documents import first_sentence, load_profile
from kairos_kb.models.column import Column
from kairos_kb.models.context import ContextDocument
from kairos_kb.models.table import Table

ALLOWED_FIRST = {"SELECT", "WITH", "SHOW", "DESCRIBE", "DESC", "EXPLAIN", "VALUES"}
# Writes recognised by their syntax, not by a bare word: a column may be called COMMENT, and
# REPLACE() is a string function. Each pattern is the statement form that changes data.
WRITE_SYNTAX = [
    (re.compile(r"\bINSERT\s+(INTO|OVERWRITE)\b", re.I), "INSERT"),
    (re.compile(r"\bUPDATE\s+(`[^`]+`|\"[^\"]+\"|[\w.$]+)\s+SET\b", re.I), "UPDATE"),
    (re.compile(r"\bDELETE\s+FROM\b", re.I), "DELETE"),
    (re.compile(r"\bMERGE\s+INTO\b", re.I), "MERGE"),
    (re.compile(r"\bREPLACE\s+(INTO|TABLE)\b", re.I), "REPLACE"),
    (re.compile(r"\bCOMMENT\s+(ON|IF)\b", re.I), "COMMENT"),
]
# Words that only ever start a statement that changes something. Inside a read they are refused
# unless they are plainly an identifier: after a dot (t.load), or followed by a comma, a closing
# parenthesis, a comparison, AS, FROM, ASC/DESC or the end.
STATEMENT_WORDS = {
    "DROP", "CREATE", "ALTER", "TRUNCATE", "GRANT", "REVOKE", "COPY", "OPTIMIZE", "VACUUM", "REFRESH",
    "CALL", "RESET", "USE", "CACHE", "UNCACHE", "RESTORE", "REPAIR", "MSCK", "ANALYZE", "LOAD", "EXECUTE",
}
_AS_IDENTIFIER = re.compile(r"\s*(,|\)|=|<|>|!|\bAS\b|\bFROM\b|\bASC\b|\bDESC\b|$)", re.I)
# Functions that read files, secrets or the outside world: not the map's tables.
BLOCKED_FUNCTIONS = re.compile(
    r"\b(read_files|read_csv|read_json|read_kafka|read_kinesis|read_pubsub|read_pulsar|read_eventhub|"
    r"read_statestore|read_state_metadata|cloud_files|secret|try_secret|list_secrets|http_request|"
    r"ai_[a-z_]+|vector_search|remote_query|java_method|reflect|"
    # Snowflake: system functions, earlier results, files on stages, LLM calls.
    r"system\$[a-z_]+|result_scan|infer_schema|get_presigned_url|build_scoped_file_url|build_stage_file_url|"
    r"get_absolute_path|get_relative_path|snowflake\.cortex\.[a-z_]+)\s*\(",
    re.I,
)
# Snowflake stage references: @stage, @~ (user stage), @%table (table stage).
STAGE_REF = re.compile(r"(?<![\w$])@[~%A-Za-z_\"]")
# csv.`/path`, delta.`abfss://…`, `/Volumes/…` — a path used as a table.
PATH_TABLE = re.compile(r"(\b\w+\s*\.\s*)?`\s*(/|[a-z][a-z0-9+.-]*://)", re.I)

CELL_CHARS = 500
MASK = "<masked: personal data>"

_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_STRING = re.compile(r"'(?:[^'\\]|\\.|'')*'|\"(?:[^\"\\]|\\.|\"\")*\"", re.S)
_WORD = re.compile(r"[A-Za-z_]+")
_IDENT = r"`[^`]+`|[A-Za-z_][A-Za-z0-9_]*"
_TABLE_REF = re.compile(rf"({_IDENT})\s*\.\s*({_IDENT})\s*\.\s*({_IDENT})")
_FROM_TARGET = re.compile(rf"\b(?:FROM|JOIN|TABLE|IN)\s+((?:{_IDENT})(?:\s*\.\s*(?:{_IDENT}))*)", re.I)
_CTE_NAME = re.compile(rf"(?:\bWITH\b|,)\s*(?:RECURSIVE\s+)?({_IDENT})\s+AS\s*\(", re.I)

# Identifying columns, by name, for tables Kairos has not profiled (and raw
# feeds whose names it did not tag). Organisation, contract and product names
# are not personal data; geography is configurable.
_PERSONAL = re.compile(
    r"(e_?mail|phone|mobile|fax|\bssn\b|social_sec|birth|\bdob\b|passport|driver_?lic|"
    r"addr|address|street|postal|\bzip\b|_zip\b|zip_?code|"
    r"\bdea\b|_dea\b|dea_n|\bhin\b|_hin\b|hin_n|policy_n|internal_cust|"
    r"(cust|customer|patient|member|contact|person|prescriber|physician|first|last|full|middle|given|family|"
    r"recipient|payee|subscriber|report_group(_additional_\d)?)_?(name|nm)\b)",
    re.I,
)
_GEOGRAPHY = re.compile(r"(state|city|country|county|region)(_(nm|name|cd|code))?$", re.I)
# Aggregates that only count — they reveal no value.
_COUNTING = re.compile(r"^\s*(count|approx_count_distinct)\s*\(", re.I)


def _code_only(sql: str) -> str:
    """The SQL with comments and string literals blanked, so keywords inside them don't count."""
    text = _BLOCK_COMMENT.sub(" ", sql or "")
    text = _LINE_COMMENT.sub(" ", text)
    return _STRING.sub("''", text)


def _unquote(ident: str) -> str:
    return ident.strip().strip("`").lower()


def check_read_only(sql: str) -> Optional[str]:
    """Why this SQL may not run, or None if it is a single read-only statement."""
    code = _code_only(sql)
    statements = [s for s in code.split(";") if s.strip()]
    if not statements:
        return "No SQL to run."
    if len(statements) > 1:
        return "One statement at a time."
    statement = statements[0]
    words = [w.upper() for w in _WORD.findall(statement)]
    if not words or words[0] not in ALLOWED_FIRST:
        return f"Only read-only statements may run ({', '.join(sorted(ALLOWED_FIRST))})."
    bad = {name for pattern, name in WRITE_SYNTAX if pattern.search(statement)}
    for m in re.finditer(r"[A-Za-z_]+", statement):
        word = m.group(0).upper()
        if word not in STATEMENT_WORDS:
            continue
        after_dot = statement[:m.start()].rstrip().endswith(".")
        if after_dot or _AS_IDENTIFIER.match(statement, m.end()):
            continue  # a column or alias that happens to share the name
        bad.add(word)
    if bad:
        return f"Refused: {', '.join(sorted(bad))} is not allowed in a read-only query."
    return None


def check_side_doors(sql: str, allow_files: bool = False) -> Optional[str]:
    """Refuse reads that bypass the map's tables: files, paths, secrets, external calls."""
    code = _code_only(sql)
    fn = BLOCKED_FUNCTIONS.search(code)
    if fn and not (allow_files and fn.group(1).lower().startswith(("read_files", "read_csv", "read_json"))):
        return (f"Refused: {fn.group(1)}() reads outside the map's tables. Query the tables the map describes; "
                "use get_context() to find the one that holds this data.")
    if not allow_files and (PATH_TABLE.search(code) or STAGE_REF.search(code)):
        return "Refused: reading files or storage paths directly is not allowed. Query tables in the map."
    return None


def referenced_tables(sql: str) -> Set[str]:
    """catalog.schema.table names the SQL mentions (lower-case)."""
    return {".".join(_unquote(g) for g in m.groups()) for m in _TABLE_REF.finditer(_code_only(sql))}


_FROM_FUNCTIONS = {"extract", "trim", "substring", "substr", "position", "overlay", "btrim", "ltrim", "rtrim"}


def _inside_function_from(code: str, pos: int) -> bool:
    """Is this FROM part of a function's syntax — EXTRACT(YEAR FROM d), TRIM(x FROM y)?"""
    depth = 0
    for i in range(pos - 1, -1, -1):
        ch = code[i]
        if ch == ")":
            depth += 1
        elif ch == "(":
            if depth == 0:
                before = re.search(r"([A-Za-z_]+)\s*$", code[:i])
                return bool(before and before.group(1).lower() in _FROM_FUNCTIONS)
            depth -= 1
    return False


def unqualified_tables(sql: str) -> List[str]:
    """Tables named after FROM / JOIN without catalog.schema — ambiguous, so refused."""
    code = _code_only(sql)
    if re.match(r"\s*SHOW\b", code, re.I):
        return []  # SHOW … IN catalog.schema names a schema, not a table
    ctes = {_unquote(m.group(1)) for m in _CTE_NAME.finditer(code)}
    out = []
    for m in _FROM_TARGET.finditer(code):
        if _inside_function_from(code, m.start()):
            continue
        name = m.group(1)
        parts = [p for p in re.split(r"\s*\.\s*", name) if p]
        if len(parts) >= 3 or _unquote(parts[0]) in ctes:
            continue
        word = _unquote(parts[0])
        if word in {"select", "values", "lateral", "unnest", "explode", "range", "with"}:
            continue
        out.append(name)
    return out


def is_personal(column: str, *, geography: bool) -> bool:
    if _GEOGRAPHY.search(column) and not geography:
        return False
    return bool(_PERSONAL.search(column))


def _split_top(text: str, sep: str = ",") -> List[str]:
    """Split on a separator outside parentheses."""
    out, depth, start = [], 0, 0
    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == sep and depth == 0:
            out.append(text[start:i])
            start = i + 1
    out.append(text[start:])
    return out


def _select_lists(code: str) -> List[str]:
    """The SELECT … FROM column lists in a query, innermost first, for taint tracking."""
    lists = []
    for m in re.finditer(r"\bSELECT\b", code, re.I):
        depth, i = 0, m.end()
        while i < len(code):
            if code[i] == "(":
                depth += 1
            elif code[i] == ")":
                if depth == 0:
                    break
                depth -= 1
            elif depth == 0 and re.match(r"\bFROM\b", code[i:i + 5], re.I) and not code[i - 1].isalnum():
                break
            i += 1
        lists.append(code[m.end():i])
    return list(reversed(lists))


def tainted_outputs(sql: str, personal: Set[str]) -> Set[str]:
    """Output column names that may carry personal values (lower-case).

    A select item that uses a personal column — or an alias already carrying one
    — taints its output name, unless it only counts. Aliases propagate through
    CTEs and subqueries, so `SELECT cust_name AS x` then `SELECT x FROM …` stays
    masked.
    """
    code = _code_only(sql)
    tainted = {p.lower() for p in personal}
    lists = _select_lists(code)
    # CTEs come before their use, subqueries after it: repeat until nothing new is tainted.
    for _ in range(6):
        before = len(tainted)
        _taint_pass(lists, tainted)
        if len(tainted) == before:
            break
    return tainted


def _taint_pass(lists: List[str], tainted: Set[str]) -> None:
    for items in lists:
        for item in _split_top(items):
            # SELECT DISTINCT cust_name: the keyword is not an expression with an alias.
            text = re.sub(r"^\s*(DISTINCT|ALL)\s+", "", item.strip(), flags=re.I)
            if not text or text == "*":
                continue
            alias_m = re.search(rf"\s+(?:AS\s+)?({_IDENT})\s*$", text, re.I)
            expr = text[: alias_m.start()] if alias_m and not re.fullmatch(rf"({_IDENT})(\s*\.\s*({_IDENT}))*", text) else text
            out_name = _unquote(alias_m.group(1)) if alias_m else _unquote(re.split(r"\s*\.\s*", text)[-1])
            words = {w.lower() for w in re.findall(_IDENT, expr)} | {_unquote(w) for w in re.findall(r"`[^`]+`", expr)}
            if words & tainted and not _COUNTING.match(expr):
                tainted.add(out_name)
                tainted.add(re.sub(r"\s+", "", expr.lower()))


def shape_result(result: Dict[str, Any], tainted: Set[str], personal: Set[str]) -> Dict[str, Any]:
    """Columns and rows from a Statements API result, with personal values masked and long values cut."""
    manifest = result.get("manifest") or {}
    columns = [{"name": c.get("name"), "type": c.get("type_name") or c.get("type_text")}
               for c in (manifest.get("schema") or {}).get("columns") or []]
    lowered_personal = {p.lower() for p in personal}

    def must_mask(name: str) -> bool:
        n = (name or "").lower()
        squashed = re.sub(r"\s+", "", n)
        if n in tainted or squashed in tainted:
            return True
        # Expression output names (upper(cust_name)) contain the source column.
        return any(re.search(rf"\b{re.escape(p)}\b", n) for p in lowered_personal) and not _COUNTING.match(n)

    masked_idx = {i for i, c in enumerate(columns) if must_mask(str(c["name"]))}
    rows = []
    for raw in (result.get("result") or {}).get("data_array") or []:
        row = []
        for i, value in enumerate(raw):
            if i in masked_idx and value is not None:
                row.append(MASK)
            elif isinstance(value, str) and len(value) > CELL_CHARS:
                row.append(value[:CELL_CHARS] + "…")
            else:
                row.append(value)
        rows.append(row)
    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "truncated": bool(manifest.get("truncated")) or (
            manifest.get("total_row_count") is not None and manifest["total_row_count"] > len(rows)),
        "masked_columns": [columns[i]["name"] for i in sorted(masked_idx)],
    }


async def _table_facts(db: AsyncSession, tables: Set[str], geography: bool
                       ) -> Tuple[Dict[str, Dict[str, Any]], Set[str]]:
    """The map's facts about each referenced table, and every personal column across them."""
    # Snowflake keeps names in upper case; SQL refers to them in any case.
    rows = (await db.execute(select(Table).where(func.lower(Table.full_name).in_(list(tables))))).scalars().all()
    facts: Dict[str, Dict[str, Any]] = {}
    personal: Set[str] = set()
    for t in rows:
        cols = [c for (c,) in (await db.execute(select(Column.name).where(Column.table_id == t.id))).all()]
        profile = await load_profile(db, t.entity_id)
        doc = (await db.execute(select(ContextDocument).where(ContextDocument.entity_id == t.entity_id))).scalars().first()
        tagged = {c["name"] for c in ((profile or {}).get("shape") or {}).get("columns") or []
                  if isinstance(c, dict) and "pii" in str(c.get("tags") or "").lower() and c.get("name")}
        table_personal = sorted({c for c in tagged if geography or not _GEOGRAPHY.search(c)}
                                | {c for c in cols if is_personal(c, geography=geography)})
        personal |= {c.lower() for c in table_personal}
        trust = doc.trust_level if doc else ("profiled" if profile else "synced")
        verification = (profile or {}).get("verification") or {}
        failed = [f"{c.get('check')}: {c.get('detail')}" for c in verification.get("checks") or []
                  if c.get("result") not in ("ok", "holds", "corrected", "repaired", "skipped", None)]
        entry: Dict[str, Any] = {
            "entity_id": t.entity_id,
            "trust_level": trust,
            "what_it_is": (doc.headline if doc else None) or first_sentence((profile or {}).get("summary")),
            "grain": first_sentence(((profile or {}).get("shape") or {}).get("grain"), 300) or None,
            "grain_key": (profile or {}).get("grain_key") or None,
            "failed_checks": failed[:3] or None,
            "last_write": ((profile or {}).get("facts") or {}).get("last_write"),
            "personal_data_columns": table_personal[:40] or None,
        }
        if trust == "synced":
            entry["note"] = (f"Kairos has not profiled this table: its meaning, grain and caveats are unknown. "
                             f"Call get_context('{t.entity_id}') before relying on these numbers.")
        facts[t.full_name.lower()] = {k: v for k, v in entry.items() if v is not None}
    return facts, personal


def _allowed_catalogs(identity: AgentIdentity) -> Optional[Set[str]]:
    settings = get_settings()
    configured = {c.strip().lower() for c in settings.sql_allowed_catalogs.split(",") if c.strip()}
    own = {c.lower() for c in identity.sql_catalogs} if identity.sql_catalogs else None
    if identity.agent_id is None:
        anon = {c.strip().lower() for c in settings.anonymous_sql_catalogs.split(",") if c.strip()}
        own = anon or None
    if configured and own:
        return configured & own
    return own or configured or None


async def run_sql(db: AsyncSession, identity: AgentIdentity, sql: str, limit: int = 100) -> Dict[str, Any]:
    settings = get_settings()
    if not identity.can("query"):
        return {"error": "This agent may not run SQL: it needs the 'query' permission."}
    problem = (check_read_only(sql) or check_side_doors(sql, settings.sql_allow_file_reads))
    if problem:
        return {"error": problem}
    loose = unqualified_tables(sql)
    if loose:
        return {"error": f"Use fully qualified names (catalog.schema.table): {', '.join(loose[:5])}. "
                         "find_data() gives each table's full name."}
    limit = max(1, min(int(limit or 100), settings.sql_max_rows))

    tables = referenced_tables(sql)
    known = {fn.lower(): eid for eid, fn in (await db.execute(
        select(Table.entity_id, Table.full_name).where(func.lower(Table.full_name).in_(list(tables)))
    )).all()} if tables else {}
    unknown = sorted(tables - set(known))
    if unknown and not settings.sql_allow_unmapped:
        return {"error": f"Not in the map: {', '.join(unknown)}. Only tables Kairos has synced can be queried; "
                         "find_data() lists them."}
    hidden = sorted(fn for fn, eid in known.items() if not identity.sees_entity(eid))
    if hidden:
        return {"error": f"Not visible to this agent: {', '.join(hidden)}"}
    allowed = _allowed_catalogs(identity)
    if allowed is not None:
        outside = sorted(t for t in tables if t.split(".", 1)[0] not in allowed)
        if outside:
            return {"error": f"Outside the catalogs this agent may query ({', '.join(sorted(allowed))}): "
                             f"{', '.join(outside)}"}

    facts, personal = await _table_facts(db, tables, settings.sql_mask_geography)
    tainted = tainted_outputs(sql, personal) if settings.sql_mask_personal_data else set()
    if not settings.sql_mask_personal_data:
        personal = set()

    connector, spans = await connector_for_tables(db, known.keys())
    if spans:
        return {"error": spans, "tables": facts}
    started = time.perf_counter()
    try:
        result = await connector.execute_query(
            sql.strip().rstrip(";"), row_limit=limit, timeout_seconds=settings.sql_timeout_seconds
        )
    except Exception as exc:  # noqa: BLE001 — returned to the agent to correct its query
        return {"error": f"The platform could not run this query: {str(exc)[:500]}", "tables": facts}
    status = result.get("status") or {}
    if status.get("state") not in (None, "SUCCEEDED"):
        message = ((status.get("error") or {}).get("message") or status.get("state") or "failed")
        return {"error": f"Query {str(status.get('state')).lower()}: {message[:800]}",
                "tables": facts,
                "hint": "get_context() on these tables lists their exact columns and meanings."}

    shaped = shape_result(result, tainted, personal)
    notes = []
    if shaped["masked_columns"]:
        notes.append("Values in personal-data columns are masked; counting them (COUNT DISTINCT) is allowed.")
    if shaped["truncated"]:
        notes.append(f"Result cut at {limit} rows; aggregate, filter or raise limit for more.")
    if any(f.get("trust_level") == "synced" for f in facts.values()):
        notes.append("Some tables are unprofiled — see each table's note before relying on the numbers.")
    shaped.update({
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "limit": limit,
        "tables": facts,
        **({"note": " ".join(notes)} if notes else {}),
    })
    return shaped
