"""Snowflake connector — concrete implementation of PlatformConnector.

Reads a Snowflake account the way the Databricks connector reads a workspace,
and hands the sync the same shapes, so catalog, job and lineage sync run
unchanged:

  databases                         → catalogs
  schemas                           → schemas, with their procedures, functions,
                                      stages, pipes and file formats as properties
  tables, transient / dynamic /     → tables, with rows, bytes, clustering, retention,
  external / Iceberg tables, views,   view and dynamic-table definitions, stream
  materialized views, streams         sources, tags and masking policies
  columns                           → columns, with exact types
  task graphs (root + children)     → jobs (id: the root task DB.SCHEMA.NAME) and tasks;
                                      runs from TASK_HISTORY
  Snowpipes                         → jobs (id: DB.SCHEMA.PIPE~pipe); runs from COPY_HISTORY
  dynamic tables                    → jobs (id: DB.SCHEMA.TABLE~refresh); runs from refresh history
  OBJECT_DEPENDENCIES, ACCESS_HISTORY → table and column lineage

Account-level views (SNOWFLAKE.ACCOUNT_USAGE) need a role granted IMPORTED
PRIVILEGES on the SNOWFLAKE database; ACCESS_HISTORY needs Enterprise edition.
Whatever the role cannot read is skipped and recorded in ``notes`` rather than
failing the sync. Code — task SQL, procedure bodies, view DDL — is read with
GET_DDL through ``read_workspace_file("snowflake://<kind>/<object>")``.

The Python driver is synchronous; every call runs in a worker thread over one
shared connection per account, user and role.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import decimal
import json
import logging
import re
import threading
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

from kairos_kb.config import get_settings
from kairos_kb.connectors.base import PlatformConnector
from kairos_kb.exceptions import ConnectorError

logger = logging.getLogger(__name__)

PLATFORM = "Snowflake"
CODE_SCHEME = "snowflake://"
DEFINITION_CHARS = 20000

# Snowflake task state → the run vocabulary the rest of Kairos speaks.
TASK_RESULT = {
    "SUCCEEDED": "SUCCESS", "FAILED": "FAILED", "FAILED_AND_AUTO_SUSPENDED": "FAILED",
    "CANCELLED": "CANCELED", "SKIPPED": "SKIPPED", "UPSTREAM_FAILED": "SKIPPED",
}
TABLE_TYPE = {"BASE TABLE": "MANAGED", "VIEW": "VIEW", "MATERIALIZED VIEW": "MATERIALIZED_VIEW",
              "EXTERNAL TABLE": "EXTERNAL", "EVENT TABLE": "EVENT_TABLE", "TEMPORARY TABLE": "TEMPORARY",
              "LOCAL TEMPORARY": "TEMPORARY"}

_CONNECTIONS: Dict[Tuple[str, str, str, str], Any] = {}
_CONN_LOCK = threading.Lock()


# Snowflake codes for a session or token that is no longer valid (expired, invalid, not found).
_SESSION_CODES = {390111, 390112, 390113, 390114, 390195, 390318, 250001, 250002, 251005}
_SESSION_WORDS = ("token has expired", "authenticate again", "session no longer exists", "session does not exist",
                  "connection is closed", "not connected", "session expired", "invalid session")


def _session_lost(exc: Exception) -> bool:
    """Whether an error means the session (not the statement) is gone, so a fresh sign-in will fix it."""
    if getattr(exc, "errno", None) in _SESSION_CODES:
        return True
    text = str(exc).lower()
    return any(w in text for w in _SESSION_WORDS)


def quote_ident(name: str) -> str:
    """An identifier as Snowflake needs it: bare when it is plain upper case, else double-quoted."""
    if re.fullmatch(r"[A-Z_][A-Z0-9_$]*", name or ""):
        return name
    return '"' + (name or "").replace('"', '""') + '"'


def quote_name(full_name: str) -> str:
    return ".".join(quote_ident(p) for p in split_name(full_name))


def split_name(full_name: str) -> List[str]:
    """DB.SCHEMA.OBJECT → parts, honouring double-quoted parts that contain dots."""
    parts, buf, quoted = [], "", False
    for ch in full_name or "":
        if ch == '"':
            quoted = not quoted
            continue
        if ch == "." and not quoted:
            parts.append(buf)
            buf = ""
            continue
        buf += ch
    parts.append(buf)
    return parts


def _iso(value: Any) -> Any:
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, bytes):
        return value.hex()
    return value


def _ms(value: Any) -> Optional[int]:
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt.timezone.utc)
        return int(value.timestamp() * 1000)
    return None


def _cell(value: Any) -> Optional[str]:
    """A result cell as the SQL Statements API returns it: a string, or null."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(_iso(value))


def _short(text: Optional[str], n: int = DEFINITION_CHARS) -> Optional[str]:
    if text is None:
        return None
    return text if len(text) <= n else text[:n] + "\n-- …truncated"


def _json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value
    return value


# Statements that create or change a table's data, and the table they target.
BUILD_TYPES = ("CREATE_TABLE_AS_SELECT", "INSERT", "MERGE", "UPDATE", "DELETE", "COPY", "TRUNCATE_TABLE")
_LEADING_COMMENT = re.compile(r"^\s*(/\*.*?\*/\s*|--[^\n]*\n\s*)*", re.S)
_TARGET = re.compile(
    r"^\s*(?:create\s+(?:or\s+replace\s+)?(?:(?:local|global)\s+)?(?:temporary\s+|temp\s+|transient\s+|volatile\s+)?"
    r"table\s+(?:if\s+not\s+exists\s+)?|insert\s+(?:overwrite\s+)?(?:all\s+)?into\s+|merge\s+into\s+|update\s+|"
    r"delete\s+from\s+|copy\s+into\s+|truncate\s+(?:table\s+)?(?:if\s+exists\s+)?)([A-Za-z0-9_$.\"]+)",
    re.I)
_DBT_NODE = re.compile(r'"node_id"\s*:\s*"([^"]+)"')


def statement_target(text: str, database: Optional[str], schema: Optional[str]) -> Optional[str]:
    """The table a statement writes, fully qualified the way Snowflake resolves it (unquoted parts upper-cased)."""
    body = _LEADING_COMMENT.sub("", text or "", count=1)
    m = _TARGET.match(body)
    if not m:
        return None
    raw = m.group(1).rstrip(";(")
    if raw.startswith("@"):
        return None
    parts = []
    for p in split_name(raw):
        parts.append(p if raw.count('"') and f'"{p}"' in raw else p.upper())
    if len(parts) == 1:
        parts = [database or "", schema or "", parts[0]]
    elif len(parts) == 2:
        parts = [database or "", *parts]
    if len(parts) != 3 or not all(parts):
        return None
    return ".".join(parts)


def dbt_node(text: str) -> Optional[str]:
    """dbt stamps every statement with a JSON comment naming the model: model.<project>.<name>."""
    head = (text or "")[:2000]
    m = _DBT_NODE.search(head)
    return m.group(1) if m else None


class SnowflakeConnector(PlatformConnector):
    """Talks to a Snowflake account through the official Python driver."""

    platform = "snowflake"

    def __init__(self, *, config: Optional[Dict[str, Any]] = None) -> None:
        s = get_settings()
        cfg = config or {}
        self.account = (cfg.get("account") or s.snowflake_account or "").strip()
        self.user = (cfg.get("user") or s.snowflake_user or "").strip()
        self.warehouse = (cfg.get("warehouse") or s.snowflake_warehouse or "").strip()
        self.role = (cfg.get("role") or s.snowflake_role or "").strip()
        only = cfg.get("databases")
        self.only_databases = {d.upper() for d in (only or [])} if isinstance(only, list) else None
        self.exclude = {d.strip().upper() for d in s.snowflake_exclude_databases.split(",") if d.strip()}
        self.history_days = int(cfg.get("history_days") or s.snowflake_history_days)
        self.timeout = s.snowflake_statement_timeout_seconds
        self.notes: List[str] = []
        self._db_cache: Dict[str, Dict[str, Any]] = {}
        self._account_meta: Optional[Dict[str, Any]] = None
        self._tasks: Optional[Dict[str, Dict[str, Any]]] = None
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._runs: Dict[str, Dict[str, Any]] = {}
        self._outputs: Dict[str, Dict[str, Any]] = {}

    # ── Connection ───────────────────────────────────────────────────
    def _connect(self):
        import snowflake.connector

        s = get_settings()
        if not self.account or not self.user:
            raise ConnectorError(PLATFORM, "SNOWFLAKE_ACCOUNT and SNOWFLAKE_USER must be set.")
        kwargs: Dict[str, Any] = {"account": self.account, "user": self.user, "client_session_keep_alive": True,
                                  "session_parameters": {"QUERY_TAG": "kairos",
                                                         "STATEMENT_TIMEOUT_IN_SECONDS": self.timeout},
                                  "login_timeout": 30, "network_timeout": 60, "application": "Kairos"}
        if self.warehouse:
            kwargs["warehouse"] = self.warehouse
        if self.role:
            kwargs["role"] = self.role
        if s.snowflake_token:
            kwargs.update(authenticator="PROGRAMMATIC_ACCESS_TOKEN", token=s.snowflake_token)
        elif s.snowflake_private_key_path:
            from cryptography.hazmat.primitives import serialization

            with open(s.snowflake_private_key_path, "rb") as fh:
                key = serialization.load_pem_private_key(
                    fh.read(), password=(s.snowflake_private_key_passphrase or None) and s.snowflake_private_key_passphrase.encode())
            kwargs["private_key"] = key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                                                      serialization.NoEncryption())
        elif s.snowflake_password:
            kwargs["password"] = s.snowflake_password
        else:
            raise ConnectorError(PLATFORM, "Set SNOWFLAKE_TOKEN, SNOWFLAKE_PRIVATE_KEY_PATH or SNOWFLAKE_PASSWORD.")
        return snowflake.connector.connect(**kwargs)

    def _conn(self):
        key = (self.account.lower(), self.user.lower(), self.role.upper(), self.warehouse.upper())
        with _CONN_LOCK:
            conn = _CONNECTIONS.get(key)
            if conn is None or conn.is_closed():
                conn = self._connect()
                _CONNECTIONS[key] = conn
            return conn

    def _run(self, sql: str, params: Optional[Sequence[Any]] = None, *, limit: Optional[int] = None,
             timeout: Optional[int] = None) -> Tuple[List[Dict[str, str]], List[tuple], bool]:
        """(columns, rows, truncated) for one statement, in this thread."""
        from snowflake.connector.errors import DatabaseError, ProgrammingError

        for attempt in (1, 2):
            conn = self._conn()
            try:
                cur = conn.cursor()
                try:
                    cur.execute(sql, params, timeout=timeout or self.timeout)
                    cols = [{"name": d[0], "type_name": str(d[1])} for d in (cur.description or [])]
                    if limit is None:
                        rows = cur.fetchall() if cur.description else []
                        return cols, rows, False
                    rows = cur.fetchmany(limit + 1) if cur.description else []
                    return cols, rows[:limit], len(rows) > limit
                finally:
                    cur.close()
            except DatabaseError as exc:
                # The shared session expired or was dropped (Snowflake ends idle sessions and
                # expires their tokens after some hours): sign in again once, whatever the error class.
                if attempt == 1 and _session_lost(exc):
                    self._forget_connection(conn)
                    continue
                if isinstance(exc, ProgrammingError):
                    raise
                raise ConnectorError(PLATFORM, str(exc)[:500])
        raise ConnectorError(PLATFORM, "Could not reconnect to Snowflake.")

    def _forget_connection(self, conn) -> None:
        key = (self.account.lower(), self.user.lower(), self.role.upper(), self.warehouse.upper())
        with _CONN_LOCK:
            if _CONNECTIONS.get(key) is conn:
                _CONNECTIONS.pop(key, None)
        try:
            conn.close()
        except Exception:  # noqa: BLE001 — it is already unusable
            pass

    async def _query(self, sql: str, params: Optional[Sequence[Any]] = None, **kw) -> List[Dict[str, Any]]:
        """Rows as dicts keyed by upper-case column name. Raises on SQL errors."""
        from snowflake.connector.errors import ProgrammingError

        try:
            cols, rows, _ = await asyncio.to_thread(self._run, sql, params, **kw)
        except ProgrammingError as exc:
            raise ConnectorError(PLATFORM, f"{exc.errno}: {exc.msg}"[:500])
        names = [c["name"].upper() for c in cols]
        return [dict(zip(names, r)) for r in rows]

    async def _try(self, label: str, sql: str, params: Optional[Sequence[Any]] = None) -> List[Dict[str, Any]]:
        """A metadata read the role may not be allowed: on failure, note it and carry on."""
        try:
            return await self._query(sql, params)
        except ConnectorError as exc:
            msg = f"{label}: {exc}"
            if msg not in self.notes:
                self.notes.append(msg)
            logger.info("Snowflake %s unavailable: %s", label, exc)
            return []

    # ── Catalog: databases, schemas, objects, columns ─────────────────
    async def list_catalogs(self) -> List[Dict[str, Any]]:
        rows = await self._query("SHOW DATABASES")
        out = []
        for r in rows:
            name = r.get("NAME") or ""
            if self._skip_db(name):
                continue
            out.append({
                "name": name, "comment": r.get("COMMENT") or None, "owner": r.get("OWNER") or None,
                "catalog_type": (r.get("KIND") or "STANDARD").upper(),
                "properties": {k: _iso(r.get(k.upper())) for k in
                               ("created_on", "origin", "retention_time", "kind", "options") if r.get(k.upper()) not in (None, "")},
            })
        return out

    async def _database(self, db: str) -> Dict[str, Any]:
        """Everything in one database, read in a handful of set-based queries and kept for the sync."""
        if db in self._db_cache:
            return self._db_cache[db]
        q = quote_ident(db)
        info = f"{q}.INFORMATION_SCHEMA"
        schemas = await self._query(
            f"SELECT schema_name, schema_owner, comment, created, last_altered, is_transient, is_managed_access, "
            f"retention_time FROM {info}.SCHEMATA WHERE schema_name <> 'INFORMATION_SCHEMA' ORDER BY schema_name")
        tables = await self._query(
            f"SELECT * FROM {info}.TABLES WHERE table_schema <> 'INFORMATION_SCHEMA' ORDER BY table_schema, table_name")
        columns = await self._query(
            f"SELECT table_schema, table_name, column_name, ordinal_position, data_type, is_nullable, comment, "
            f"character_maximum_length, numeric_precision, numeric_scale, datetime_precision, column_default, "
            f"is_identity FROM {info}.COLUMNS WHERE table_schema <> 'INFORMATION_SCHEMA' "
            f"ORDER BY table_schema, table_name, ordinal_position")
        views = await self._try("view definitions", f"SELECT table_schema, table_name, view_definition, is_secure "
                                                    f"FROM {info}.VIEWS WHERE table_schema <> 'INFORMATION_SCHEMA'")
        procedures = await self._try("procedures", f"SELECT procedure_schema, procedure_name, argument_signature, "
                                                   f"data_type, procedure_language, procedure_definition, comment, "
                                                   f"procedure_owner, created, last_altered FROM {info}.PROCEDURES")
        functions = await self._try("functions", f"SELECT function_schema, function_name, argument_signature, "
                                                 f"data_type, function_language, function_definition, is_external, "
                                                 f"comment, function_owner FROM {info}.FUNCTIONS")
        stages = await self._try("stages", f"SELECT stage_schema, stage_name, stage_url, stage_region, stage_type, "
                                           f"stage_owner, comment, created FROM {info}.STAGES")
        pipes = await self._try("pipes", f"SELECT pipe_schema, pipe_name, definition, is_autoingest_enabled, "
                                         f"notification_channel_name, pipe_owner, comment, pattern, created "
                                         f"FROM {info}.PIPES")
        formats = await self._try("file formats", f"SELECT file_format_schema, file_format_name, file_format_type, "
                                                  f"comment FROM {info}.FILE_FORMATS")
        streams = await self._try("streams", f"SHOW STREAMS IN DATABASE {q}")
        dynamic = await self._try("dynamic tables", f"SHOW DYNAMIC TABLES IN DATABASE {q}")
        meta = await self._account_metadata()
        builds = await self._build_statements(db)
        keys = await self._keys(db)
        usage = await self._usage(db)
        cache = {"builds": builds, "keys": keys, "usage": usage,
                 "schemas": schemas, "tables": tables, "columns": columns, "views": views,
                 "procedures": procedures, "functions": functions, "stages": stages, "pipes": pipes,
                 "formats": formats, "streams": streams, "dynamic": dynamic,
                 "tags": [t for t in meta["tags"] if (t.get("OBJECT_DATABASE") or "").upper() == db.upper()],
                 "policies": [p for p in meta["policies"] if (p.get("REF_DATABASE_NAME") or "").upper() == db.upper()]}
        self._db_cache[db] = cache
        return cache

    async def _build_statements(self, db: str) -> Dict[str, Dict[str, Any]]:
        """For each table in a database: the statements that built and changed it, from query history.

        The latest CREATE … AS SELECT (dbt's table models, CTAS jobs) is the table's build SQL; the
        latest COPY INTO is how a raw table is loaded. ACCOUNT_USAGE keeps a year but lags up to ~45
        minutes; the database's own QUERY_HISTORY function is immediate but covers 7 days and only
        statements this role can see. Both are read and merged.
        """
        types = ", ".join(f"'{t}'" for t in BUILD_TYPES)
        cols = ("query_id, query_type, query_text, start_time, user_name, role_name, database_name, "
                "schema_name, warehouse_name, query_tag, rows_produced")
        rows = await self._try("query history (ACCOUNT_USAGE)", (
            f"SELECT {cols} FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY "
            f"WHERE start_time > DATEADD('day', %s, CURRENT_TIMESTAMP()) AND execution_status = 'SUCCESS' "
            f"AND query_type IN ({types}) AND (database_name = %s OR query_text ILIKE %s) "
            f"ORDER BY start_time DESC LIMIT 20000"), [-self.history_days, db, f"%{db}.%"])
        recent = await self._try("query history (INFORMATION_SCHEMA)", (
            f"SELECT {cols} FROM TABLE({quote_ident(db)}.INFORMATION_SCHEMA."
            f"QUERY_HISTORY(END_TIME_RANGE_START => DATEADD('hour', -167, CURRENT_TIMESTAMP()), RESULT_LIMIT => 10000)) "
            f"WHERE execution_status = 'SUCCESS' AND query_type IN ({types}) ORDER BY start_time DESC"))
        seen, out = set(), {}
        for r in sorted(rows + recent, key=lambda r: r.get("START_TIME") or dt.datetime.min.replace(tzinfo=dt.timezone.utc),
                        reverse=True):
            qid = r.get("QUERY_ID")
            if qid in seen:
                continue
            seen.add(qid)
            target = statement_target(r.get("QUERY_TEXT") or "", r.get("DATABASE_NAME"), r.get("SCHEMA_NAME"))
            if not target or split_name(target)[0].upper() != db.upper():
                continue
            entry = out.setdefault(target.upper(), {"latest": {}, "counts": defaultdict(int), "last_write": None})
            qtype = r.get("QUERY_TYPE")
            entry["counts"][qtype] += 1
            if entry["last_write"] is None:
                entry["last_write"] = _iso(r.get("START_TIME"))
            if qtype not in entry["latest"]:
                entry["latest"][qtype] = {
                    "statement_type": qtype, "at": _iso(r.get("START_TIME")), "by": r.get("USER_NAME"),
                    "role": r.get("ROLE_NAME"), "warehouse": r.get("WAREHOUSE_NAME"), "query_id": qid,
                    "rows": _iso(r.get("ROWS_PRODUCED")), "dbt_model": dbt_node(r.get("QUERY_TEXT") or ""),
                    "query_tag": r.get("QUERY_TAG") or None, "sql": _short(r.get("QUERY_TEXT")),
                }
        return out

    async def _keys(self, db: str) -> Dict[str, Dict[str, Any]]:
        """Declared primary, unique and foreign keys (informational in Snowflake, but stated intent)."""
        q = quote_ident(db)
        out: Dict[str, Dict[str, Any]] = defaultdict(dict)
        for label, sql, key in (("primary keys", f"SHOW PRIMARY KEYS IN DATABASE {q}", "primary_key"),
                                ("unique keys", f"SHOW UNIQUE KEYS IN DATABASE {q}", "unique_keys")):
            groups: Dict[Tuple[str, str], List[Tuple[int, str]]] = defaultdict(list)
            for r in await self._try(label, sql):
                t = f"{r.get('DATABASE_NAME')}.{r.get('SCHEMA_NAME')}.{r.get('TABLE_NAME')}".upper()
                groups[(t, r.get("CONSTRAINT_NAME") or "")].append((int(r.get("KEY_SEQUENCE") or 0), r.get("COLUMN_NAME")))
            for (t, name), cols in groups.items():
                ordered = [c for _, c in sorted(cols)]
                if key == "primary_key":
                    out[t]["primary_key"] = ordered
                else:
                    out[t].setdefault("unique_keys", []).append(ordered)
        fks: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for r in await self._try("foreign keys", f"SHOW IMPORTED KEYS IN DATABASE {q}"):
            t = f"{r.get('FK_DATABASE_NAME')}.{r.get('FK_SCHEMA_NAME')}.{r.get('FK_TABLE_NAME')}".upper()
            ref = f"{r.get('PK_DATABASE_NAME')}.{r.get('PK_SCHEMA_NAME')}.{r.get('PK_TABLE_NAME')}"
            fk = fks.setdefault((t, r.get("FK_NAME") or ref), {"references": ref, "columns": [], "ref_columns": []})
            fk["columns"].append(r.get("FK_COLUMN_NAME"))
            fk["ref_columns"].append(r.get("PK_COLUMN_NAME"))
        for (t, _), fk in fks.items():
            out[t].setdefault("foreign_keys", []).append(fk)
        return out

    async def _usage(self, db: str) -> Dict[str, Dict[str, Any]]:
        """How much each object is read: queries naming it (a view, not the tables behind it), distinct users, last read."""
        rows = await self._try("usage (ACCESS_HISTORY)", (
            "SELECT UPPER(bo.value:\"objectName\"::string) AS obj, COUNT(DISTINCT ah.query_id) AS reads, "
            "COUNT(DISTINCT ah.user_name) AS readers, MAX(ah.query_start_time) AS last_read "
            "FROM SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY ah, LATERAL FLATTEN(ah.direct_objects_accessed) bo "
            "WHERE ah.query_start_time > DATEADD('day', %s, CURRENT_TIMESTAMP()) "
            "AND UPPER(bo.value:\"objectName\"::string) LIKE %s GROUP BY 1"),
            [-self.history_days, f"{db.upper()}.%"])
        return {r["OBJ"]: {"queries_reading_it": int(r.get("READS") or 0), "distinct_readers": int(r.get("READERS") or 0),
                           "last_read": _iso(r.get("LAST_READ")), "window_days": self.history_days} for r in rows}

    async def _account_metadata(self) -> Dict[str, Any]:
        """Tags and policies are account-wide views: read once per sync."""
        if self._account_meta is None:
            tags = await self._try("tags (ACCOUNT_USAGE)", "SELECT object_database, object_schema, object_name, "
                                   "column_name, domain, tag_name, tag_value FROM SNOWFLAKE.ACCOUNT_USAGE.TAG_REFERENCES "
                                   "WHERE object_deleted IS NULL")
            policies = await self._try("policies (ACCOUNT_USAGE)", "SELECT ref_database_name, ref_schema_name, "
                                       "ref_entity_name, ref_column_name, policy_kind, policy_name, policy_status "
                                       "FROM SNOWFLAKE.ACCOUNT_USAGE.POLICY_REFERENCES")
            self._account_meta = {"tags": tags, "policies": policies}
        return self._account_meta

    async def list_schemas(self, catalog_name: str) -> List[Dict[str, Any]]:
        c = await self._database(catalog_name)
        by_schema = defaultdict(lambda: defaultdict(list))
        for p in c["procedures"]:
            by_schema[p["PROCEDURE_SCHEMA"]]["procedures"].append({
                "name": p["PROCEDURE_NAME"], "arguments": p.get("ARGUMENT_SIGNATURE"), "returns": p.get("DATA_TYPE"),
                "language": p.get("PROCEDURE_LANGUAGE"), "comment": p.get("COMMENT"),
                "code_path": f"{CODE_SCHEME}procedure/{catalog_name}.{p['PROCEDURE_SCHEMA']}.{p['PROCEDURE_NAME']}"
                             f"{self._arg_types(p.get('ARGUMENT_SIGNATURE'))}",
                "definition": _short(p.get("PROCEDURE_DEFINITION"), 4000)})
        for f in c["functions"]:
            by_schema[f["FUNCTION_SCHEMA"]]["functions"].append({
                "name": f["FUNCTION_NAME"], "arguments": f.get("ARGUMENT_SIGNATURE"), "returns": f.get("DATA_TYPE"),
                "language": f.get("FUNCTION_LANGUAGE"), "external": f.get("IS_EXTERNAL") == "YES",
                "comment": f.get("COMMENT"), "definition": _short(f.get("FUNCTION_DEFINITION"), 2000)})
        for st in c["stages"]:
            by_schema[st["STAGE_SCHEMA"]]["stages"].append({
                "name": st["STAGE_NAME"], "url": st.get("STAGE_URL"), "type": st.get("STAGE_TYPE"),
                "region": st.get("STAGE_REGION"), "comment": st.get("COMMENT")})
        for pp in c["pipes"]:
            by_schema[pp["PIPE_SCHEMA"]]["pipes"].append({
                "name": pp["PIPE_NAME"], "definition": _short(pp.get("DEFINITION"), 4000),
                "auto_ingest": pp.get("IS_AUTOINGEST_ENABLED") == "YES", "pattern": pp.get("PATTERN"),
                "comment": pp.get("COMMENT")})
        for ff in c["formats"]:
            by_schema[ff["FILE_FORMAT_SCHEMA"]]["file_formats"].append({
                "name": ff["FILE_FORMAT_NAME"], "type": ff.get("FILE_FORMAT_TYPE"), "comment": ff.get("COMMENT")})
        out = []
        for s in c["schemas"]:
            name = s["SCHEMA_NAME"]
            props = {k.lower(): _iso(s.get(k)) for k in ("CREATED", "LAST_ALTERED", "IS_TRANSIENT", "IS_MANAGED_ACCESS",
                                                        "RETENTION_TIME") if s.get(k) is not None}
            props.update({k: v for k, v in by_schema.get(name, {}).items()})
            out.append({"name": name, "full_name": f"{catalog_name}.{name}", "comment": s.get("COMMENT"),
                        "owner": s.get("SCHEMA_OWNER"), "properties": props})
        return out

    @staticmethod
    def _arg_types(signature: Optional[str]) -> str:
        """'(A VARCHAR, B NUMBER)' → '(VARCHAR, NUMBER)', the form GET_DDL accepts."""
        if not signature:
            return "()"
        inner = signature.strip().strip("()")
        types = [part.strip().split(" ", 1)[-1] for part in inner.split(",") if part.strip()]
        return "(" + ", ".join(types) + ")"

    async def list_tables(self, catalog_name: str, schema_name: str) -> List[Dict[str, Any]]:
        c = await self._database(catalog_name)
        cols = defaultdict(list)
        for col in c["columns"]:
            if col["TABLE_SCHEMA"] == schema_name:
                cols[col["TABLE_NAME"]].append(col)
        views = {v["TABLE_NAME"]: v for v in c["views"] if v["TABLE_SCHEMA"] == schema_name}
        dynamic = {d.get("NAME") or d.get("name"): d for d in c["dynamic"]
                   if (d.get("SCHEMA_NAME") or "") == schema_name}
        tags = defaultdict(list)
        col_tags = defaultdict(lambda: defaultdict(list))
        for t in c["tags"]:
            if t.get("OBJECT_SCHEMA") != schema_name:
                continue
            label = f"{t['TAG_NAME']}={t.get('TAG_VALUE')}"
            if t.get("COLUMN_NAME"):
                col_tags[t["OBJECT_NAME"]][t["COLUMN_NAME"]].append(label)
            else:
                tags[t["OBJECT_NAME"]].append(label)
        policies = defaultdict(list)
        for p in c["policies"]:
            if p.get("REF_SCHEMA_NAME") == schema_name:
                policies[p["REF_ENTITY_NAME"]].append(
                    {"kind": p.get("POLICY_KIND"), "policy": p.get("POLICY_NAME"), "column": p.get("REF_COLUMN_NAME")})

        out = []
        for t in c["tables"]:
            if t["TABLE_SCHEMA"] != schema_name:
                continue
            name = t["TABLE_NAME"]
            kind = (t.get("TABLE_TYPE") or "").upper()
            table_type = TABLE_TYPE.get(kind, kind or "MANAGED")
            props: Dict[str, Any] = {k.lower(): _iso(t.get(k)) for k in (
                "CREATED", "LAST_ALTERED", "LAST_DDL", "LAST_DDL_BY", "CLUSTERING_KEY", "AUTO_CLUSTERING_ON",
                "RETENTION_TIME", "IS_TRANSIENT", "IS_ICEBERG", "IS_DYNAMIC", "IS_HYBRID", "IS_IMMUTABLE",
                "TABLE_OWNER") if t.get(k) not in (None, "")}
            if t.get("IS_TRANSIENT") == "YES":
                table_type = "TRANSIENT"
            if t.get("IS_ICEBERG") == "YES":
                table_type = "ICEBERG"
            if name in dynamic or t.get("IS_DYNAMIC") == "YES":
                table_type = "DYNAMIC_TABLE"
                d = dynamic.get(name) or {}
                props["dynamic"] = {k.lower(): _iso(d.get(k)) for k in ("TARGET_LAG", "REFRESH_MODE", "SCHEDULING_STATE",
                                                                       "WAREHOUSE", "DATA_TIMESTAMP") if d.get(k) is not None}
                if d.get("TEXT"):
                    props["definition"] = _short(d["TEXT"])
            if name in views:
                props["definition"] = _short(views[name].get("VIEW_DEFINITION"))
                props["is_secure"] = views[name].get("IS_SECURE")
            if tags.get(name):
                props["tags"] = tags[name]
            if col_tags.get(name):
                props["column_tags"] = {k: v for k, v in col_tags[name].items()}
            if policies.get(name):
                props["policies"] = policies[name]
            fqn = f"{catalog_name}.{schema_name}.{name}".upper()
            self._attach_build(props, c["builds"].get(fqn))
            if c["keys"].get(fqn):
                props.update(c["keys"][fqn])
            if c["usage"].get(fqn):
                props["usage"] = c["usage"][fqn]
            out.append({
                "name": name,
                "full_name": f"{catalog_name}.{schema_name}.{name}",
                "table_type": table_type,
                "data_source_format": "ICEBERG" if table_type == "ICEBERG" else "SNOWFLAKE",
                "comment": t.get("COMMENT"),
                "owner": t.get("TABLE_OWNER"),
                "row_count": _iso(t.get("ROW_COUNT")),
                "size_bytes": _iso(t.get("BYTES")),
                "storage_location": None,
                "properties": props,
                "columns": [self._column(col) for col in cols.get(name, [])],
            })

        for s in c["streams"]:
            if (s.get("SCHEMA_NAME") or "") != schema_name:
                continue
            name = s.get("NAME")
            out.append({
                "name": name, "full_name": f"{catalog_name}.{schema_name}.{name}", "table_type": "STREAM",
                "data_source_format": "SNOWFLAKE", "comment": s.get("COMMENT") or None, "owner": s.get("OWNER"),
                "properties": {"source": s.get("TABLE_NAME"), "source_type": s.get("SOURCE_TYPE"),
                               "mode": s.get("MODE"), "stale": s.get("STALE"), "stale_after": _iso(s.get("STALE_AFTER")),
                               "type": s.get("TYPE")},
                # A stream has its source's columns plus the change-tracking ones.
                "columns": [], "storage_location": None,
            })
        return out

    @staticmethod
    def _attach_build(props: Dict[str, Any], build: Optional[Dict[str, Any]]) -> None:
        """The table's build SQL and how its data changes, from the statements history recorded."""
        if not build:
            return
        latest = build["latest"]
        main = latest.get("CREATE_TABLE_AS_SELECT") or latest.get("MERGE") or latest.get("INSERT")
        if main:
            props["build_sql"] = main["sql"]
            props["build"] = {k: v for k, v in main.items() if k != "sql" and v is not None}
        if latest.get("COPY"):
            props["load_sql"] = latest["COPY"]["sql"]
            props["load"] = {k: v for k, v in latest["COPY"].items() if k != "sql" and v is not None}
        props["writes"] = {"by_statement": dict(build["counts"]), "last_write": build["last_write"],
                           "others": {t: {k: v for k, v in e.items() if k in ("at", "by", "role", "dbt_model")}
                                      for t, e in latest.items() if e is not main and t != "COPY"} or None}

    @staticmethod
    def _column(col: Dict[str, Any]) -> Dict[str, Any]:
        dtype = (col.get("DATA_TYPE") or "UNKNOWN").upper()
        text = dtype
        if dtype in ("NUMBER", "DECIMAL", "NUMERIC") and col.get("NUMERIC_PRECISION") is not None:
            text = f"NUMBER({col['NUMERIC_PRECISION']},{col.get('NUMERIC_SCALE') or 0})"
        elif dtype in ("TEXT", "VARCHAR", "CHAR", "STRING") and col.get("CHARACTER_MAXIMUM_LENGTH"):
            text = f"VARCHAR({col['CHARACTER_MAXIMUM_LENGTH']})"
        elif dtype.startswith("TIMESTAMP") and col.get("DATETIME_PRECISION") is not None:
            text = f"{dtype}({col['DATETIME_PRECISION']})"
        return {"name": col["COLUMN_NAME"], "type_name": "VARCHAR" if dtype == "TEXT" else dtype, "type_text": text,
                "nullable": (col.get("IS_NULLABLE") or "YES") == "YES", "comment": col.get("COMMENT"),
                "position": col.get("ORDINAL_POSITION"), "default": col.get("COLUMN_DEFAULT"),
                "identity": col.get("IS_IDENTITY") == "YES"}

    async def get_table(self, full_name: str) -> Dict[str, Any]:
        db, schema, name = split_name(full_name)
        for t in await self.list_tables(db, schema):
            if t["name"] == name:
                return t
        raise ConnectorError(PLATFORM, f"Table not found: {full_name}")

    # ── Pipelines: task graphs, Snowpipes, dynamic tables ─────────────
    async def _all_tasks(self) -> Dict[str, Dict[str, Any]]:
        if self._tasks is None:
            rows = await self._try("tasks", "SHOW TASKS IN ACCOUNT")
            tasks = {}
            for r in rows:
                db = r.get("DATABASE_NAME") or ""
                if self._skip_db(db):
                    continue
                fqn = f"{db}.{r.get('SCHEMA_NAME')}.{r.get('NAME')}"
                preds = _json(r.get("PREDECESSORS")) or []
                rel = _json(r.get("TASK_RELATIONS")) or {}
                tasks[fqn] = {**r, "FQN": fqn, "PREDS": [".".join(split_name(p)) for p in preds],
                              "FINALIZED_ROOT": (rel or {}).get("FinalizedRootTask") if isinstance(rel, dict) else None}
            self._tasks = tasks
        return self._tasks

    async def list_jobs(self) -> List[Dict[str, Any]]:
        tasks = await self._all_tasks()
        children = defaultdict(list)
        for fqn, t in tasks.items():
            for p in t["PREDS"]:
                children[p].append(fqn)
            if t.get("FINALIZED_ROOT"):
                children[".".join(split_name(t["FINALIZED_ROOT"]))].append(fqn)
        roots = [f for f, t in tasks.items() if not t["PREDS"] and not t.get("FINALIZED_ROOT")]
        jobs = []
        for root in sorted(roots):
            graph, queue = [], [root]
            while queue:
                f = queue.pop(0)
                if f in graph or f not in tasks:
                    continue
                graph.append(f)
                queue += children.get(f, [])
            keys = self._task_keys(graph)
            r = tasks[root]
            job = {
                "job_id": root,
                "fqn": root,
                "creator_user_name": r.get("OWNER"),
                "kind": "task_graph",
                "root_task_id": r.get("ID"),
                "database": r.get("DATABASE_NAME"),
                "settings": {
                    "name": f"{r.get('NAME')} (task graph)" if len(graph) > 1 else r.get("NAME"),
                    "schedule": {"snowflake_schedule": r.get("SCHEDULE"), "state": r.get("STATE"),
                                 "warehouse": r.get("WAREHOUSE")} if r.get("SCHEDULE") else None,
                    "tags": {"platform": "snowflake", "object": "task", "fqn": root, "state": r.get("STATE")},
                    "tasks": [self._task_dict(tasks[f], keys) for f in graph],
                },
            }
            jobs.append(job)
            self._jobs[job["job_id"]] = job

        for db in await self._databases():
            c = await self._database(db)
            for p in c["pipes"]:
                fqn = f"{db}.{p['PIPE_SCHEMA']}.{p['PIPE_NAME']}"
                job = {"job_id": f"{fqn}~pipe", "fqn": fqn, "creator_user_name": p.get("PIPE_OWNER"), "kind": "pipe",
                       "settings": {"name": f"{p['PIPE_NAME']} (Snowpipe)",
                                    "tags": {"platform": "snowflake", "object": "pipe", "fqn": fqn,
                                             "auto_ingest": p.get("IS_AUTOINGEST_ENABLED")},
                                    "tasks": [{"task_key": p["PIPE_NAME"], "description": p.get("COMMENT"),
                                               "sql_task": {"query": {"query_text": p.get("DEFINITION")}}}]}}
                jobs.append(job)
                self._jobs[job["job_id"]] = job
            for d in c["dynamic"]:
                fqn = f"{db}.{d.get('SCHEMA_NAME')}.{d.get('NAME')}"
                job = {"job_id": f"{fqn}~refresh", "fqn": fqn, "creator_user_name": d.get("OWNER"), "kind": "dynamic_table",
                       "settings": {"name": f"{d.get('NAME')} (dynamic table refresh)",
                                    "schedule": {"target_lag": d.get("TARGET_LAG"), "warehouse": d.get("WAREHOUSE")},
                                    "tags": {"platform": "snowflake", "object": "dynamic_table", "fqn": fqn,
                                             "refresh_mode": d.get("REFRESH_MODE")},
                                    "tasks": [{"task_key": d.get("NAME"),
                                               "sql_task": {"query": {"query_text": _short(d.get("TEXT"))}}}]}}
                jobs.append(job)
                self._jobs[job["job_id"]] = job
        return jobs

    async def _databases(self) -> List[str]:
        return [c["name"] for c in await self.list_catalogs()]

    @staticmethod
    def _task_keys(graph: List[str]) -> Dict[str, str]:
        """Short task names, schema-qualified only where two tasks in a graph share a name."""
        names = defaultdict(list)
        for f in graph:
            names[split_name(f)[-1]].append(f)
        keys = {}
        for short, fqns in names.items():
            for f in fqns:
                keys[f] = short if len(fqns) == 1 else ".".join(split_name(f)[1:])
        return keys

    def _task_dict(self, t: Dict[str, Any], keys: Dict[str, str]) -> Dict[str, Any]:
        definition = t.get("DEFINITION") or ""
        task: Dict[str, Any] = {
            "task_key": keys[t["FQN"]],
            "depends_on": [{"task_key": keys[p]} for p in t["PREDS"] if p in keys],
            "description": t.get("COMMENT") or None,
            "snowflake": {"fqn": t["FQN"], "warehouse": t.get("WAREHOUSE"), "condition": t.get("CONDITION"),
                          "state": t.get("STATE"), "config": _json(t.get("CONFIG"))},
        }
        call = re.match(r"\s*CALL\s+([\w$.\"]+)\s*\(", definition, re.I)
        if call:
            # The task runs a procedure: its code is where the work happens.
            proc = call.group(1)
            if proc.count(".") < 2:
                proc = f"{t['DATABASE_NAME']}.{t['SCHEMA_NAME']}.{proc.split('.')[-1]}"
            task["notebook_task"] = {"notebook_path": f"{CODE_SCHEME}procedure/{proc}",
                                     "base_parameters": {"call": definition.strip()[:2000]}}
        else:
            task["sql_task"] = {"query": {"query_text": _short(definition)}}
        return task

    async def get_job(self, job_id: str) -> Dict[str, Any]:
        if job_id not in self._jobs:
            await self.list_jobs()
        if job_id not in self._jobs:
            raise ConnectorError(PLATFORM, f"Unknown job {job_id}")
        return self._jobs[job_id]

    async def list_job_runs(self, job_id: str, *, limit: int = 25) -> List[Dict[str, Any]]:
        job = await self.get_job(job_id)
        kind, fqn = job["kind"], job["fqn"]
        if kind == "task_graph":
            runs = await self._task_graph_runs(job, limit)
        elif kind == "pipe":
            runs = await self._pipe_runs(fqn, limit)
        else:
            runs = await self._refresh_runs(fqn, limit)
        for r in runs:
            self._runs[str(r["run_id"])] = r
        return runs

    async def _task_graph_runs(self, job: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
        keys = {t["snowflake"]["fqn"]: t["task_key"] for t in job["settings"]["tasks"]}
        db = job.get("database")
        rows = []
        if db and job.get("root_task_id"):
            # Recent history straight from the database: no ACCOUNT_USAGE latency.
            rows = await self._try("task history (INFORMATION_SCHEMA)", (
                f"SELECT * FROM TABLE({quote_ident(db)}.INFORMATION_SCHEMA.TASK_HISTORY("
                f"SCHEDULED_TIME_RANGE_START => DATEADD('day', -7, CURRENT_TIMESTAMP()), "
                f"RESULT_LIMIT => 10000, ROOT_TASK_ID => %s)) ORDER BY scheduled_time DESC"), [job["root_task_id"]])
        if not rows and job.get("root_task_id"):
            rows = await self._try("task history (ACCOUNT_USAGE)", (
                "SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY WHERE root_task_id = %s "
                "AND scheduled_time > DATEADD('day', %s, CURRENT_TIMESTAMP()) ORDER BY scheduled_time DESC LIMIT 5000"),
                [job["root_task_id"], -self.history_days])
        groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for r in rows:
            gid = str(r.get("GRAPH_RUN_GROUP_ID") or r.get("RUN_ID") or r.get("QUERY_ID"))
            groups[gid].append(r)
        runs = []
        for gid, members in groups.items():
            tasks = []
            for m in members:
                fqn = f"{m.get('DATABASE_NAME')}.{m.get('SCHEMA_NAME')}.{m.get('NAME')}"
                state = (m.get("STATE") or "").upper()
                result = TASK_RESULT.get(state)
                err = m.get("ERROR_MESSAGE")
                qid = m.get("QUERY_ID") or f"{gid}:{m.get('NAME')}"
                if err:
                    self._outputs[qid] = {"error": f"{m.get('ERROR_CODE') or ''} {err}".strip(),
                                          "error_trace": err, "query_id": m.get("QUERY_ID")}
                tasks.append({
                    "task_key": keys.get(fqn, m.get("NAME")), "run_id": qid,
                    "attempt_number": max(0, int(m.get("ATTEMPT_NUMBER") or 1) - 1),
                    "state": {"life_cycle_state": "TERMINATED" if result else state or "PENDING",
                              "result_state": result, "state_message": err},
                    "start_time": _ms(m.get("QUERY_START_TIME") or m.get("SCHEDULED_TIME")),
                    "end_time": _ms(m.get("COMPLETED_TIME")),
                })
            results = [t["state"]["result_state"] for t in tasks]
            running = any(r is None for r in results)
            overall = ("FAILED" if "FAILED" in results else "CANCELED" if "CANCELED" in results
                       else None if running else "SUCCESS")
            first_error = next((t["state"]["state_message"] for t in tasks if t["state"]["state_message"]), None)
            starts = [t["start_time"] for t in tasks if t["start_time"]]
            ends = [t["end_time"] for t in tasks if t["end_time"]]
            trigger = (members[0].get("SCHEDULED_FROM") or "SCHEDULE").upper()
            runs.append({
                "run_id": gid, "run_name": job["settings"]["name"],
                "state": {"life_cycle_state": "RUNNING" if running else "TERMINATED", "result_state": overall,
                          "state_message": first_error},
                "start_time": min(starts) if starts else None, "end_time": max(ends) if ends and not running else None,
                "trigger": "PERIODIC" if trigger == "SCHEDULE" else "ONE_TIME",
                "execution_duration": (max(ends) - min(starts)) if starts and ends else None,
                "tasks": tasks,
            })
        runs.sort(key=lambda r: r["start_time"] or 0, reverse=True)
        return runs[:limit]

    async def _pipe_runs(self, fqn: str, limit: int) -> List[Dict[str, Any]]:
        db, schema, name = split_name(fqn)
        rows = await self._try("copy history (ACCOUNT_USAGE)", (
            "SELECT file_name, stage_location, last_load_time, row_count, row_parsed, error_count, "
            "first_error_message, first_error_line_number, first_error_column_name, status, table_name "
            "FROM SNOWFLAKE.ACCOUNT_USAGE.COPY_HISTORY WHERE pipe_catalog_name = %s AND pipe_schema_name = %s "
            "AND pipe_name = %s AND last_load_time > DATEADD('day', %s, CURRENT_TIMESTAMP()) "
            "ORDER BY last_load_time DESC LIMIT %s"), [db, schema, name, -self.history_days, limit])
        runs = []
        for r in rows:
            status = (r.get("STATUS") or "").upper()
            ok = status == "LOADED"
            rid = f"{fqn}:{r.get('FILE_NAME')}:{_ms(r.get('LAST_LOAD_TIME'))}"
            err = r.get("FIRST_ERROR_MESSAGE")
            if err:
                self._outputs[rid] = {"error": err, "error_trace": (
                    f"{err}\nfile: {r.get('FILE_NAME')} line {r.get('FIRST_ERROR_LINE_NUMBER')} "
                    f"column {r.get('FIRST_ERROR_COLUMN_NAME')} ({r.get('ERROR_COUNT')} errors of {r.get('ROW_PARSED')} rows)")}
            end = _ms(r.get("LAST_LOAD_TIME"))
            state = {"life_cycle_state": "TERMINATED", "result_state": "SUCCESS" if ok else "FAILED",
                     "state_message": None if ok else (err or status.lower())}
            runs.append({"run_id": rid, "run_name": f"load {r.get('FILE_NAME')}", "state": state,
                         "start_time": end, "end_time": end, "trigger": "FILE_ARRIVAL",
                         "tasks": [{"task_key": name, "run_id": rid, "attempt_number": 0, "state": state,
                                    "start_time": end, "end_time": end}]})
        return runs

    async def _refresh_runs(self, fqn: str, limit: int) -> List[Dict[str, Any]]:
        db = split_name(fqn)[0]
        rows = await self._try("dynamic table refresh history", (
            f"SELECT * FROM TABLE({quote_ident(db)}.INFORMATION_SCHEMA.DYNAMIC_TABLE_REFRESH_HISTORY("
            f"NAME => %s, RESULT_LIMIT => %s)) ORDER BY refresh_start_time DESC"), [fqn, max(limit, 1)])
        runs = []
        for r in rows:
            state_raw = (r.get("STATE") or "").upper()
            result = TASK_RESULT.get(state_raw)
            rid = str(r.get("QUERY_ID") or f"{fqn}:{_ms(r.get('REFRESH_START_TIME'))}")
            err = r.get("STATE_MESSAGE") if result in ("FAILED", "CANCELED") else None
            if err:
                self._outputs[rid] = {"error": f"{r.get('STATE_CODE') or ''} {err}".strip(), "error_trace": err}
            state = {"life_cycle_state": "TERMINATED" if result else state_raw or "PENDING", "result_state": result,
                     "state_message": err}
            start, end = _ms(r.get("REFRESH_START_TIME")), _ms(r.get("REFRESH_END_TIME"))
            runs.append({"run_id": rid, "run_name": f"refresh ({(r.get('REFRESH_ACTION') or '').lower()})",
                         "state": state, "start_time": start, "end_time": end,
                         "trigger": (r.get("REFRESH_TRIGGER") or "SCHEDULED").upper(),
                         "tasks": [{"task_key": split_name(fqn)[-1], "run_id": rid, "attempt_number": 0,
                                    "state": state, "start_time": start, "end_time": end}]})
        return runs

    async def get_run(self, run_id: str) -> Dict[str, Any]:
        if run_id in self._runs:
            return self._runs[run_id]
        raise ConnectorError(PLATFORM, f"Run {run_id} is not in the history read for this sync.")

    async def get_run_output(self, run_id: str) -> Dict[str, Any]:
        """The failure as Snowflake recorded it. Python procedures carry their traceback in the message."""
        out = self._outputs.get(run_id)
        if out is None:
            return {"error": None, "error_trace": None}
        return out

    # ── Code: task SQL, procedures, views, anything GET_DDL can describe ──
    async def read_workspace_file(self, file_path: str) -> str:
        if not file_path.startswith(CODE_SCHEME):
            raise ConnectorError(PLATFORM, f"Not a Snowflake object path: {file_path}")
        kind, _, obj = file_path[len(CODE_SCHEME):].partition("/")
        kind = {"procedure": "PROCEDURE", "task": "TASK", "view": "VIEW", "table": "TABLE", "function": "FUNCTION",
                "pipe": "PIPE", "stream": "STREAM", "dynamic_table": "DYNAMIC_TABLE"}.get(kind.lower(), kind.upper())
        if kind == "PROCEDURE" and "(" not in obj:
            obj = await self._procedure_signature(obj)
        rows = await self._query("SELECT GET_DDL(%s, %s, TRUE) AS DDL", [kind, obj])
        return (rows[0].get("DDL") if rows else "") or ""

    async def _procedure_signature(self, fqn: str) -> str:
        """A procedure called by name only: find its argument types (first overload)."""
        db, schema, name = split_name(fqn)
        c = await self._database(db)
        for p in c["procedures"]:
            if p["PROCEDURE_SCHEMA"] == schema and p["PROCEDURE_NAME"] == name:
                return f"{db}.{schema}.{name}{self._arg_types(p.get('ARGUMENT_SIGNATURE'))}"
        return f"{fqn}()"

    # ── Files on stages ──────────────────────────────────────────────
    async def list_stage(self, stage: str, path: str = "") -> List[Dict[str, Any]]:
        """Files under @DB.SCHEMA.STAGE/path: name (relative to the stage), size, last modified."""
        rows = await self._query(f"LIST @{quote_name(stage)}/{path.lstrip('/')}")
        out = []
        prefix_len = None
        for r in rows:
            full = r.get("NAME") or ""
            # LIST names files as <stage location>/<relative path>; keep the relative part.
            if prefix_len is None:
                lower_stage = split_name(stage)[-1].lower()
                idx = full.lower().find(lower_stage + "/")
                prefix_len = idx + len(lower_stage) + 1 if idx >= 0 else 0
            out.append({"name": full[prefix_len:] or full, "size": _iso(r.get("SIZE")),
                        "last_modified": _iso(r.get("LAST_MODIFIED")), "md5": r.get("MD5")})
        return out

    async def read_stage_head(self, stage: str, relative: str, max_bytes: int) -> Dict[str, Any]:
        """The first max_bytes of a staged file, via a short-lived presigned URL (read-only)."""
        import httpx

        rows = await self._query(f"SELECT GET_PRESIGNED_URL(@{quote_name(stage)}, %s, 300) AS URL", [relative])
        url = rows[0]["URL"] if rows else None
        if not url:
            raise ConnectorError(PLATFORM, f"No such file on @{stage}: {relative}")
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(url, headers={"Range": f"bytes=0-{max(0, max_bytes - 1)}"})
        if resp.status_code not in (200, 206):
            raise ConnectorError(PLATFORM, f"Could not read the staged file (HTTP {resp.status_code}).")
        total = None
        cr = resp.headers.get("content-range", "")
        if "/" in cr and cr.rsplit("/", 1)[1].isdigit():
            total = int(cr.rsplit("/", 1)[1])
        elif resp.status_code == 200:
            total = len(resp.content)
        return {"content": resp.content[:max_bytes], "total_bytes": total,
                "last_modified": resp.headers.get("last-modified")}

    async def read_stage_rows(self, stage: str, relative: str, max_rows: int, columns: int = 40) -> List[List[Any]]:
        """Rows of a delimited staged file, read with SQL (for stages whose files are encrypted client-side)."""
        cols = ", ".join(f"${i}" for i in range(1, columns + 1))
        rows = await self._query(f"SELECT {cols} FROM @{quote_name(stage)}/{relative.lstrip('/')} LIMIT {int(max_rows)}")
        out = []
        for r in rows:
            vals = [r.get(f"${i}") for i in range(1, columns + 1)]
            while vals and vals[-1] is None:
                vals.pop()
            out.append([_cell(v) for v in vals])
        return out

    # ── Every other object, and how they connect ─────────────────────
    async def read_objects(self) -> Dict[str, Any]:
        from kairos_kb.connectors.snowflake_objects import read_objects

        return await read_objects(self)

    # ── Who writes a table (the Delta-history equivalent) ─────────────
    async def write_history(self, full_name: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Recent writes into a table, shaped like Delta history rows: operation, timestamp, userName, job.

        ACCESS_HISTORY names the table each query modified; a write made inside a
        procedure carries the calling task's query as its root, so the task graph
        behind a write is found even when the task only CALLs a procedure.
        """
        tasks = await self._all_tasks()
        by_id = {str(t.get("ID")): fqn for fqn, t in tasks.items()}
        rows = await self._query(
            "WITH w AS (SELECT DISTINCT ah.query_id, COALESCE(ah.root_query_id, ah.query_id) AS root_id, "
            "ah.query_start_time AS ts, ah.user_name "
            "FROM SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY ah, LATERAL FLATTEN(ah.objects_modified) om "
            "WHERE UPPER(om.value:\"objectName\"::string) = UPPER(%s) "
            "AND ah.query_start_time > DATEADD('day', %s, CURRENT_TIMESTAMP())) "
            "SELECT w.ts, w.user_name, qh.query_type, th.root_task_id, "
            "th.database_name AS task_db, th.schema_name AS task_schema, th.name AS task_name "
            "FROM w JOIN SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY qh ON qh.query_id = w.query_id "
            "LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY th ON th.query_id = w.root_id "
            "ORDER BY w.ts DESC LIMIT %s",
            [".".join(split_name(full_name)), -self.history_days, limit])
        out = []
        for r in rows:
            row: Dict[str, Any] = {"operation": r.get("QUERY_TYPE") or "WRITE", "timestamp": _iso(r.get("TS")),
                                   "userName": r.get("USER_NAME")}
            if r.get("TASK_NAME"):
                root = by_id.get(str(r.get("ROOT_TASK_ID"))) or f"{r['TASK_DB']}.{r['TASK_SCHEMA']}.{r['TASK_NAME']}"
                row["job"] = {"jobId": root, "jobName": split_name(root)[-1],
                              "taskName": f"{r['TASK_DB']}.{r['TASK_SCHEMA']}.{r['TASK_NAME']}"}
            out.append(row)
        return out

    # ── Lineage ──────────────────────────────────────────────────────
    @staticmethod
    def _edge(src: str, tgt: str, **extra) -> Optional[Dict[str, Any]]:
        s, t = split_name(src), split_name(tgt)
        if len(s) != 3 or len(t) != 3 or s == t:
            return None
        return {"source_table_catalog": s[0], "source_table_schema": s[1], "source_table_name": s[2],
                "target_table_catalog": t[0], "target_table_schema": t[1], "target_table_name": t[2], **extra}

    async def get_table_lineage(self, *, catalog_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        edges: Dict[Tuple[str, str], Dict[str, Any]] = {}
        deps = await self._try("object dependencies (ACCOUNT_USAGE)", (
            "SELECT referenced_database, referenced_schema, referenced_object_name, referencing_database, "
            "referencing_schema, referencing_object_name, referencing_object_domain "
            "FROM SNOWFLAKE.ACCOUNT_USAGE.OBJECT_DEPENDENCIES "
            "WHERE referenced_object_domain IN ('TABLE', 'VIEW', 'MATERIALIZED VIEW', 'DYNAMIC TABLE', "
            "'EXTERNAL TABLE', 'STREAM') "
            "AND referencing_object_domain IN ('VIEW', 'MATERIALIZED VIEW', 'DYNAMIC TABLE', 'STREAM', 'TABLE')"))
        for d in deps:
            src = f"{d['REFERENCED_DATABASE']}.{d['REFERENCED_SCHEMA']}.{d['REFERENCED_OBJECT_NAME']}"
            tgt = f"{d['REFERENCING_DATABASE']}.{d['REFERENCING_SCHEMA']}.{d['REFERENCING_OBJECT_NAME']}"
            e = self._edge(src, tgt, evidence="object dependency",
                           transformation=f"{(d.get('REFERENCING_OBJECT_DOMAIN') or '').lower()} definition")
            if e:
                edges[(src, tgt)] = e
        writes = await self._try("access history (ACCOUNT_USAGE, Enterprise edition)", (
            "SELECT DISTINCT src.value:\"objectName\"::string AS src, tgt.value:\"objectName\"::string AS tgt "
            "FROM SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY ah, "
            "LATERAL FLATTEN(ah.base_objects_accessed) src, LATERAL FLATTEN(ah.objects_modified) tgt "
            "WHERE ah.query_start_time > DATEADD('day', %s, CURRENT_TIMESTAMP()) "
            "AND src.value:\"objectDomain\"::string IN ('Table', 'View', 'Materialized view', 'Dynamic table', "
            "'External table', 'Stream') "
            "AND tgt.value:\"objectDomain\"::string IN ('Table', 'Dynamic table', 'Materialized view')"),
            [-self.history_days])
        for w in writes:
            e = self._edge(w["SRC"], w["TGT"], evidence="access history", transformation="write observed")
            if e:
                edges.setdefault((w["SRC"], w["TGT"]), e)
        out = list(edges.values())
        if catalog_filter:
            cf = catalog_filter.upper()
            out = [e for e in out if cf in (e["source_table_catalog"].upper(), e["target_table_catalog"].upper())]
        return [e for e in out if self._wanted(e)]

    async def get_column_lineage(self, *, catalog_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        rows = await self._try("column lineage (ACCESS_HISTORY)", (
            "SELECT DISTINCT tgt.value:\"objectName\"::string AS tgt, col.value:\"columnName\"::string AS tgt_col, "
            "src.value:\"objectName\"::string AS src, src.value:\"columnName\"::string AS src_col "
            "FROM SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY ah, LATERAL FLATTEN(ah.objects_modified) tgt, "
            "LATERAL FLATTEN(tgt.value:\"columns\") col, LATERAL FLATTEN(col.value:\"directSources\") src "
            "WHERE ah.query_start_time > DATEADD('day', %s, CURRENT_TIMESTAMP()) "
            "AND src.value:\"columnName\" IS NOT NULL LIMIT 50000"), [-self.history_days])
        out = []
        for r in rows:
            e = self._edge(r["SRC"], r["TGT"])
            if not e or not self._wanted(e):
                continue
            if catalog_filter and catalog_filter.upper() not in (e["source_table_catalog"].upper(),
                                                                 e["target_table_catalog"].upper()):
                continue
            out.append({**e, "source_column_name": r["SRC_COL"], "target_column_name": r["TGT_COL"]})
        return out

    def _skip_db(self, name: str) -> bool:
        """Excluded, outside the configured list, or a personal USER$ workspace database."""
        up = (name or "").upper()
        return up in self.exclude or up.startswith("USER$") or bool(self.only_databases and up not in self.only_databases)

    def _wanted(self, e: Dict[str, Any]) -> bool:
        dbs = {e["source_table_catalog"].upper(), e["target_table_catalog"].upper()}
        if any(self._skip_db(d) for d in dbs):
            return False
        return not self.only_databases or dbs <= self.only_databases

    # ── SQL ──────────────────────────────────────────────────────────
    async def execute_query(self, sql: str, *, row_limit: Optional[int] = None,
                            timeout_seconds: Optional[int] = None) -> Dict[str, Any]:
        """Run one statement; the result in the SQL Statements API's shape, as the rest of Kairos reads it."""
        from snowflake.connector.errors import ProgrammingError

        try:
            cols, rows, truncated = await asyncio.to_thread(
                self._run, sql, None, limit=row_limit or 10000, timeout=timeout_seconds)
        except ProgrammingError as exc:
            return {"status": {"state": "FAILED", "error": {"message": f"{exc.errno}: {exc.msg}"[:1000]}}}
        return {
            "status": {"state": "SUCCEEDED"},
            "manifest": {"schema": {"columns": cols}, "total_row_count": len(rows), "truncated": truncated},
            "result": {"data_array": [[_cell(v) for v in row] for row in rows]},
        }

    @staticmethod
    def _rows_from_statement_result(result: Dict[str, Any]) -> List[Dict[str, Any]]:
        cols = [c["name"] for c in ((result.get("manifest") or {}).get("schema") or {}).get("columns", [])]
        return [dict(zip(cols, row)) for row in (result.get("result") or {}).get("data_array", [])]

    # ── Health ───────────────────────────────────────────────────────
    async def test_connection(self) -> bool:
        try:
            await self._query("SELECT 1")
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Snowflake connection test failed: %s", exc)
            return False

    async def describe_access(self) -> Dict[str, Any]:
        """Who Kairos is connected as, and which kinds of metadata that role can read."""
        who = (await self._query("SELECT CURRENT_ACCOUNT() AS account, CURRENT_USER() AS user_name, "
                                 "CURRENT_ROLE() AS role, CURRENT_WAREHOUSE() AS warehouse, "
                                 "CURRENT_REGION() AS region, CURRENT_VERSION() AS version"))[0]
        checks = {}
        for label, sql in (
            ("databases", "SHOW DATABASES"),
            ("tasks", "SHOW TASKS IN ACCOUNT"),
            ("account_usage", "SELECT 1 FROM SNOWFLAKE.ACCOUNT_USAGE.OBJECT_DEPENDENCIES LIMIT 1"),
            ("access_history", "SELECT 1 FROM SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY LIMIT 1"),
        ):
            try:
                rows = await self._query(sql)
                checks[label] = {"ok": True, "rows": len(rows)} if label in ("databases", "tasks") else {"ok": True}
            except ConnectorError as exc:
                checks[label] = {"ok": False, "error": str(exc)[:300]}
        return {**{k.lower(): _iso(v) for k, v in who.items()}, "can_read": checks}

    # Dialect helpers for code that writes SQL for whichever platform holds a table.
    quote_ident = staticmethod(quote_ident)
    quote_name = staticmethod(quote_name)
