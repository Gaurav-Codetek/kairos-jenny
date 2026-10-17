"""Every Snowflake object beyond tables and task graphs, and how they connect.

The catalog phase reads databases, schemas, tables, views and columns; the jobs
phase reads task graphs, Snowpipes and dynamic-table refreshes. This reads the
rest of the account, so the map holds all of it:

  account     warehouses, roles, users (no personal details), integrations — storage,
              notification, API, external access, security — with their DESC properties,
              shares, resource monitors, network policies, external volumes, compute pools,
              applications
  database    stages (with DESC: location, integration, format, copy options, directory),
              file formats, procedures and functions (with code), pipes, sequences, tags,
              masking / row access / aggregation / projection policies (with bodies),
              alerts, notebooks, Streamlit apps, ML models, semantic views (with
              definitions), Cortex Search services, network rules, secrets (names only),
              database roles, git repositories, dbt projects
  links       bucket → integration → stage → COPY INTO / pipe → table; file format → stage;
              policy → table/column; tag → table/column; stream → table; task → procedure;
              alert / notebook / Streamlit → warehouse; warehouse → resource monitor;
              role → role, user → role; share → database; external access integration →
              network rule / secret; code → the tables it reads and writes

Each object: {"kind", "name", "full_name", "parent", "owner", "comment", "definition",
"properties"}. Each link: {"source": (kind, full_name), "target": (kind, full_name),
"relation", "detail"}. Whatever the role may not read is skipped and noted.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from kairos_kb.connectors.snowflake import SnowflakeConnector, _iso, _json, _short, quote_ident, quote_name, split_name

# Properties that are secrets or credentials are never kept, whatever object they come from.
_SECRET_PROP = re.compile(r"SECRET|PASSWORD|PRIVATE_KEY|TOKEN|CREDENTIAL|ENCRYPTION_KEY|AZURE_SAS|EXTERNAL_ID", re.I)
# Personal fields on users: never synced.
_USER_PERSONAL = {"EMAIL", "FIRST_NAME", "LAST_NAME", "MIDDLE_NAME", "DISPLAY_NAME", "LOGIN_NAME", "PHONE"}
_STAGE_REF = re.compile(r"@([A-Za-z0-9_$.\"]+)(/[^\s'\";)]*)?")
_COPY_TARGET = re.compile(r"copy\s+into\s+([A-Za-z0-9_$.\"]+)", re.I)

OBJECT_KINDS = (
    "warehouse", "role", "database_role", "user", "integration", "share", "resource_monitor", "network_policy",
    "external_volume", "compute_pool", "application", "stage", "file_format", "procedure", "function", "pipe",
    "sequence", "tag", "policy", "alert", "notebook", "streamlit", "model", "semantic_view", "cortex_search",
    "network_rule", "secret", "git_repository", "dbt_project", "location",
)


def _clean(row: Dict[str, Any], drop: Tuple[str, ...] = ()) -> Dict[str, Any]:
    """A SHOW row as plain, safe properties: lower-case keys, no empties, no secrets."""
    out = {}
    for k, v in row.items():
        if k in drop or v in (None, "", "[]", "null") or _SECRET_PROP.search(k):
            continue
        out[k.lower()] = _iso(v)
    return out


def _fqn(row: Dict[str, Any], db: Optional[str] = None) -> str:
    return f"{row.get('DATABASE_NAME') or db}.{row.get('SCHEMA_NAME')}.{row.get('NAME')}"


def _desc(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """DESC output (property, value, parent property) as a nested dict, secrets dropped."""
    out: Dict[str, Any] = {}
    for r in rows:
        prop = r.get("PROPERTY") or r.get("NAME")
        if not prop or _SECRET_PROP.search(prop):
            continue
        value = r.get("PROPERTY_VALUE", r.get("VALUE"))
        if value in (None, "", "[]"):
            continue
        parent = r.get("PARENT_PROPERTY")
        target = out.setdefault(parent.lower(), {}) if parent else out
        target[prop.lower()] = _iso(value)
    return out


def _list_value(value: Any) -> List[str]:
    """'[s3://a/, s3://b/]' or 'a,b' → ['s3://a/', 's3://b/']."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    text = str(value).strip().strip("[]")
    return [p.strip().strip("'\"") for p in text.split(",") if p.strip().strip("'\"")]


def stage_reference(text: str) -> Optional[Tuple[str, str]]:
    """The first @stage in a statement, as (DB.SCHEMA.STAGE as written, path)."""
    m = _STAGE_REF.search(text or "")
    if not m or m.group(1).startswith(("~", "%")):
        return None
    return m.group(1), (m.group(2) or "")


def _infer_stage_locations(reader: "ObjectReader") -> None:
    """A stage whose URL is unknown but whose loads came from a cloud path is stored there."""
    described = {o["full_name"] for o in reader.objects if o["kind"] == "stage"}
    feeds = defaultdict(set)
    for link in reader.links:
        if link["relation"] == "FEEDS" and link["source"][0] == "stage":
            feeds[link["target"][1]].add(link["source"][1])
    inferred = set()
    for link in reader.links:
        if link["relation"] == "LOADS_INTO" and link["source"][0] == "location":
            for stage in feeds.get(link["target"][1], ()):
                if stage not in described and (stage, link["source"][1]) not in inferred:
                    inferred.add((stage, link["source"][1]))
                    reader.link(("stage", stage), ("location", link["source"][1]), "STORED_AT",
                                inferred_from="copy history: this stage's loads read files from here")


class ObjectReader:
    def __init__(self, c: SnowflakeConnector) -> None:
        self.c = c
        self.role_privileges: Dict[str, Dict[str, List[str]]] = {}
        self.objects: List[Dict[str, Any]] = []
        self.links: List[Dict[str, Any]] = []
        self.counts: Dict[str, int] = defaultdict(int)
        self._seen: set = set()

    def obj(self, kind: str, name: str, full_name: str, *, parent: Optional[str] = None, owner: Any = None,
            comment: Any = None, definition: Optional[str] = None, properties: Optional[Dict[str, Any]] = None) -> None:
        key = (kind, full_name.upper())
        if key in self._seen:
            return
        self._seen.add(key)
        self.objects.append({"kind": kind, "name": name, "full_name": full_name, "parent": parent,
                             "owner": owner or None, "comment": comment or None,
                             "definition": _short(definition) if definition else None,
                             "properties": properties or {}})
        self.counts[kind] += 1

    def link(self, source: Tuple[str, str], target: Tuple[str, str], relation: str, **detail) -> None:
        if not source[1] or not target[1]:
            return
        self.links.append({"source": source, "target": target, "relation": relation,
                           "detail": {k: v for k, v in detail.items() if v not in (None, "", [], {})}})

    async def resolve_name(self, written: str, db: str, schema: str) -> str:
        parts = [p if f'"{p}"' in written else p.upper() for p in split_name(written)]
        if len(parts) == 1:
            parts = [db, schema, parts[0]]
        elif len(parts) == 2:
            parts = [db, *parts]
        return ".".join(parts)

    # ── account level ────────────────────────────────────────────────
    async def account(self) -> None:
        c = self.c
        for r in await c._try("warehouses", "SHOW WAREHOUSES"):
            self.obj("warehouse", r["NAME"], r["NAME"], owner=r.get("OWNER"), comment=r.get("COMMENT"),
                     properties=_clean(r, ("NAME", "OWNER", "COMMENT")))
            if r.get("RESOURCE_MONITOR") and r.get("RESOURCE_MONITOR") != "null":
                self.link(("warehouse", r["NAME"]), ("resource_monitor", r["RESOURCE_MONITOR"]), "LIMITED_BY")
        credits = await c._try("warehouse credits (ACCOUNT_USAGE)", (
            "SELECT warehouse_name, SUM(credits_used) AS credits, MAX(end_time) AS last_used "
            "FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY "
            "WHERE start_time > DATEADD('day', %s, CURRENT_TIMESTAMP()) GROUP BY 1"), [-c.history_days])
        usage = {r["WAREHOUSE_NAME"]: {"credits_used": _iso(r.get("CREDITS")), "last_used": _iso(r.get("LAST_USED")),
                                       "window_days": c.history_days} for r in credits}
        work = await c._try("warehouse workload (ACCOUNT_USAGE)", (
            "SELECT warehouse_name, role_name, user_name, database_name, query_type, COUNT(*) AS queries, "
            "SUM(total_elapsed_time) / 1000 AS seconds FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY "
            "WHERE start_time > DATEADD('day', %s, CURRENT_TIMESTAMP()) AND warehouse_name IS NOT NULL "
            "GROUP BY 1, 2, 3, 4, 5"), [-c.history_days])
        workload: Dict[str, Dict[str, Dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
        for r in work:
            wh = r["WAREHOUSE_NAME"]
            n = int(r.get("QUERIES") or 0)
            for dim, key in (("by_role", "ROLE_NAME"), ("by_user", "USER_NAME"), ("by_database", "DATABASE_NAME"),
                             ("by_query_type", "QUERY_TYPE")):
                workload[wh][dim][r.get(key) or "(none)"] += n
            workload[wh]["totals"]["queries"] += n
            workload[wh]["totals"]["seconds"] += int(r.get("SECONDS") or 0)
        for o in self.objects:
            if o["kind"] == "warehouse" and o["name"] in usage:
                o["properties"]["usage"] = usage[o["name"]]
            if o["kind"] == "warehouse" and o["name"] in workload:
                w = workload[o["name"]]
                o["properties"]["workload"] = {
                    "window_days": c.history_days, **dict(w["totals"]),
                    **{dim: dict(sorted(w[dim].items(), key=lambda kv: -kv[1])[:15])
                       for dim in ("by_role", "by_user", "by_database", "by_query_type")}}

        for r in await c._try("resource monitors", "SHOW RESOURCE MONITORS"):
            self.obj("resource_monitor", r["NAME"], r["NAME"], owner=r.get("OWNER"), comment=r.get("COMMENT"),
                     properties=_clean(r, ("NAME", "OWNER", "COMMENT")))
        for r in await c._try("roles", "SHOW ROLES"):
            self.obj("role", r["NAME"], r["NAME"], owner=r.get("OWNER"), comment=r.get("COMMENT"),
                     properties=_clean(r, ("NAME", "OWNER", "COMMENT")))
        for r in await c._try("users", "SHOW USERS"):
            props = _clean({k: v for k, v in r.items() if k not in _USER_PERSONAL}, ("NAME", "OWNER", "COMMENT"))
            self.obj("user", r["NAME"], r["NAME"], owner=r.get("OWNER"), properties=props)
        for r in await c._try("network policies", "SHOW NETWORK POLICIES"):
            self.obj("network_policy", r["NAME"], r["NAME"], comment=r.get("COMMENT"),
                     properties=_clean(r, ("NAME", "COMMENT")))
        for r in await c._try("shares", "SHOW SHARES"):
            name = r.get("NAME")
            self.obj("share", name.split(".")[-1], name, owner=r.get("OWNER"), comment=r.get("COMMENT"),
                     properties=_clean(r, ("NAME", "OWNER", "COMMENT")))
            if r.get("DATABASE_NAME"):
                self.link(("share", name), ("catalog", r["DATABASE_NAME"]),
                          "SHARES_OUT" if (r.get("KIND") or "").upper() == "OUTBOUND" else "SHARES_IN",
                          to=r.get("TO"))
        for r in await c._try("external volumes", "SHOW EXTERNAL VOLUMES"):
            desc = _desc(await c._try(f"external volume {r['NAME']}", f"DESC EXTERNAL VOLUME {quote_ident(r['NAME'])}"))
            self.obj("external_volume", r["NAME"], r["NAME"], comment=r.get("COMMENT"),
                     properties={**_clean(r, ("NAME", "COMMENT")), "describe": desc})
            for v in desc.values():
                loc = _json(v) if isinstance(v, str) else None
                if isinstance(loc, dict) and loc.get("STORAGE_BASE_URL"):
                    self.link(("external_volume", r["NAME"]), ("location", loc["STORAGE_BASE_URL"]), "STORED_AT")
        for r in await c._try("compute pools", "SHOW COMPUTE POOLS"):
            self.obj("compute_pool", r["NAME"], r["NAME"], owner=r.get("OWNER"), comment=r.get("COMMENT"),
                     properties=_clean(r, ("NAME", "OWNER", "COMMENT")))
        for r in await c._try("applications", "SHOW APPLICATIONS"):
            self.obj("application", r["NAME"], r["NAME"], owner=r.get("OWNER"), comment=r.get("COMMENT"),
                     properties=_clean(r, ("NAME", "OWNER", "COMMENT")))

        for r in await c._try("integrations", "SHOW INTEGRATIONS"):
            name = r["NAME"]
            desc = _desc(await c._try(f"integration {name}", f"DESC INTEGRATION {quote_ident(name)}"))
            self.obj("integration", name, name, comment=r.get("COMMENT"),
                     properties={**_clean(r, ("NAME", "COMMENT")), "describe": desc})
            for loc in _list_value(desc.get("storage_allowed_locations")):
                self.link(("integration", name), ("location", loc), "ALLOWS")
            for loc in _list_value(desc.get("storage_blocked_locations")):
                self.link(("integration", name), ("location", loc), "BLOCKS")
            for rule in _list_value(desc.get("allowed_network_rules")):
                self.link(("integration", name), ("network_rule", rule), "ALLOWS")
            for secret in _list_value(desc.get("allowed_authentication_secrets")):
                self.link(("integration", name), ("secret", secret), "USES")

    # ── database level ───────────────────────────────────────────────
    async def database(self, db: str) -> None:
        c, q = self.c, quote_ident(db)
        cache = await c._database(db)

        for r in await c._try("stages", f"SHOW STAGES IN DATABASE {q}"):
            fqn = _fqn(r, db)
            desc = _desc(await c._try(f"stage {fqn}", f"DESC STAGE {quote_name(fqn)}"))
            self.obj("stage", r["NAME"], fqn, parent=f"{db}.{r.get('SCHEMA_NAME')}", owner=r.get("OWNER"),
                     comment=r.get("COMMENT"), properties={**_clean(r, ("NAME", "OWNER", "COMMENT")), "describe": desc})
            if r.get("URL"):
                for url in _list_value(r["URL"]):
                    self.link(("stage", fqn), ("location", url), "STORED_AT")
            if r.get("STORAGE_INTEGRATION"):
                self.link(("stage", fqn), ("integration", r["STORAGE_INTEGRATION"]), "USES_INTEGRATION")
            fmt = (desc.get("stage_file_format") or {}).get("format_name")
            if fmt:
                self.link(("stage", fqn), ("file_format", await self.resolve_name(fmt, db, r.get("SCHEMA_NAME"))),
                          "USES_FORMAT")

        for r in await c._try("file formats", f"SHOW FILE FORMATS IN DATABASE {q}"):
            fqn = _fqn(r, db)
            props = _clean(r, ("NAME", "OWNER", "COMMENT", "FORMAT_OPTIONS"))
            props["options"] = _json(r.get("FORMAT_OPTIONS")) or r.get("FORMAT_OPTIONS")
            self.obj("file_format", r["NAME"], fqn, parent=f"{db}.{r.get('SCHEMA_NAME')}", owner=r.get("OWNER"),
                     comment=r.get("COMMENT"), properties=props)

        for p in cache["procedures"]:
            sig = c._arg_types(p.get("ARGUMENT_SIGNATURE"))
            fqn = f"{db}.{p['PROCEDURE_SCHEMA']}.{p['PROCEDURE_NAME']}"
            self.obj("procedure", f"{p['PROCEDURE_NAME']}{sig}", f"{fqn}{sig}", parent=f"{db}.{p['PROCEDURE_SCHEMA']}",
                     owner=p.get("PROCEDURE_OWNER"), comment=p.get("COMMENT"), definition=p.get("PROCEDURE_DEFINITION"),
                     properties={"arguments": p.get("ARGUMENT_SIGNATURE"), "returns": p.get("DATA_TYPE"),
                                 "language": p.get("PROCEDURE_LANGUAGE"), "created": _iso(p.get("CREATED")),
                                 "last_altered": _iso(p.get("LAST_ALTERED"))})
        for f in cache["functions"]:
            sig = c._arg_types(f.get("ARGUMENT_SIGNATURE"))
            fqn = f"{db}.{f['FUNCTION_SCHEMA']}.{f['FUNCTION_NAME']}{sig}"
            self.obj("function", f"{f['FUNCTION_NAME']}{sig}", fqn, parent=f"{db}.{f['FUNCTION_SCHEMA']}",
                     owner=f.get("FUNCTION_OWNER"), comment=f.get("COMMENT"), definition=f.get("FUNCTION_DEFINITION"),
                     properties={"arguments": f.get("ARGUMENT_SIGNATURE"), "returns": f.get("DATA_TYPE"),
                                 "language": f.get("FUNCTION_LANGUAGE"), "external": f.get("IS_EXTERNAL") == "YES"})

        pipes_show = {_fqn(r, db): r for r in await c._try("pipes", f"SHOW PIPES IN DATABASE {q}")}
        for p in cache["pipes"]:
            fqn = f"{db}.{p['PIPE_SCHEMA']}.{p['PIPE_NAME']}"
            extra = pipes_show.get(fqn, {})
            self.obj("pipe", p["PIPE_NAME"], fqn, parent=f"{db}.{p['PIPE_SCHEMA']}", owner=p.get("PIPE_OWNER"),
                     comment=p.get("COMMENT"), definition=p.get("DEFINITION"),
                     properties={"auto_ingest": p.get("IS_AUTOINGEST_ENABLED") == "YES", "pattern": p.get("PATTERN"),
                                 **_clean(extra, ("NAME", "OWNER", "COMMENT", "DEFINITION", "DATABASE_NAME", "SCHEMA_NAME")),
                                 "runs_as_pipeline": f"job:{{workspace}}:{fqn}~pipe"})
            await self._copy_links(("pipe", fqn), p.get("DEFINITION") or "", db, p["PIPE_SCHEMA"])
            if extra.get("INTEGRATION"):
                self.link(("integration", extra["INTEGRATION"]), ("pipe", fqn), "TRIGGERS")

        for r in await c._try("sequences", f"SELECT * FROM {q}.INFORMATION_SCHEMA.SEQUENCES"):
            fqn = f"{db}.{r['SEQUENCE_SCHEMA']}.{r['SEQUENCE_NAME']}"
            self.obj("sequence", r["SEQUENCE_NAME"], fqn, parent=f"{db}.{r['SEQUENCE_SCHEMA']}",
                     owner=r.get("SEQUENCE_OWNER"), comment=r.get("COMMENT"),
                     properties=_clean(r, ("SEQUENCE_SCHEMA", "SEQUENCE_NAME", "COMMENT", "SEQUENCE_OWNER")))

        for r in await c._try("tags", f"SHOW TAGS IN DATABASE {q}"):
            self.obj("tag", r["NAME"], _fqn(r, db), parent=f"{db}.{r.get('SCHEMA_NAME')}", owner=r.get("OWNER"),
                     comment=r.get("COMMENT"), properties=_clean(r, ("NAME", "OWNER", "COMMENT")))
        for t in cache["tags"]:
            tag_fqn = await self.resolve_name(t.get("TAG_NAME") or "", db, "")
            target = f"{t['OBJECT_DATABASE']}.{t['OBJECT_SCHEMA']}.{t['OBJECT_NAME']}" if t.get("OBJECT_SCHEMA") else None
            if target and (t.get("DOMAIN") or "").upper() in ("TABLE", "COLUMN", "VIEW"):
                self.link(("tag", tag_fqn if tag_fqn.count(".") == 2 else t.get("TAG_NAME")), ("table", target), "TAGS",
                          column=t.get("COLUMN_NAME"), value=t.get("TAG_VALUE"))

        for label, show, kind in (("masking policies", "MASKING POLICIES", "MASKING_POLICY"),
                                  ("row access policies", "ROW ACCESS POLICIES", "ROW_ACCESS_POLICY"),
                                  ("aggregation policies", "AGGREGATION POLICIES", "AGGREGATION_POLICY"),
                                  ("projection policies", "PROJECTION POLICIES", "PROJECTION_POLICY")):
            for r in await c._try(label, f"SHOW {show} IN DATABASE {q}"):
                fqn = _fqn(r, db)
                body = await c._try(f"policy {fqn}", "SELECT GET_DDL('POLICY', %s) AS DDL", [fqn])
                self.obj("policy", r["NAME"], fqn, parent=f"{db}.{r.get('SCHEMA_NAME')}", owner=r.get("OWNER"),
                         comment=r.get("COMMENT"), definition=(body[0]["DDL"] if body else None),
                         properties={"policy_kind": kind, **_clean(r, ("NAME", "OWNER", "COMMENT"))})
        for p in cache["policies"]:
            target = f"{p['REF_DATABASE_NAME']}.{p['REF_SCHEMA_NAME']}.{p['REF_ENTITY_NAME']}"
            pol = await self.resolve_name(p.get("POLICY_NAME") or "", db, p.get("REF_SCHEMA_NAME") or "")
            self.link(("policy", pol), ("table", target), "PROTECTS", column=p.get("REF_COLUMN_NAME"),
                      policy_kind=p.get("POLICY_KIND"), status=p.get("POLICY_STATUS"))

        for r in await c._try("alerts", f"SHOW ALERTS IN DATABASE {q}"):
            fqn = _fqn(r, db)
            code = f"-- condition\n{r.get('CONDITION') or ''}\n-- action\n{r.get('ACTION') or ''}"
            self.obj("alert", r["NAME"], fqn, parent=f"{db}.{r.get('SCHEMA_NAME')}", owner=r.get("OWNER"),
                     comment=r.get("COMMENT"), definition=code,
                     properties=_clean(r, ("NAME", "OWNER", "COMMENT", "CONDITION", "ACTION")))
            if r.get("WAREHOUSE"):
                self.link(("alert", fqn), ("warehouse", r["WAREHOUSE"]), "RUNS_ON")

        for label, show, kind, wh_key in (("notebooks", "NOTEBOOKS", "notebook", "QUERY_WAREHOUSE"),
                                           ("streamlit apps", "STREAMLITS", "streamlit", "QUERY_WAREHOUSE"),
                                           ("ML models", "MODELS", "model", None),
                                           ("Cortex Search services", "CORTEX SEARCH SERVICES", "cortex_search", "WAREHOUSE"),
                                           ("git repositories", "GIT REPOSITORIES", "git_repository", None),
                                           ("dbt projects", "DBT PROJECTS", "dbt_project", None),
                                           ("network rules", "NETWORK RULES", "network_rule", None),
                                           ("secrets", "SECRETS", "secret", None),
                                           ("semantic views", "SEMANTIC VIEWS", "semantic_view", None)):
            for r in await c._try(label, f"SHOW {show} IN DATABASE {q}"):
                fqn = _fqn(r, db)
                definition = r.get("DEFINITION")
                if kind == "semantic_view":
                    ddl = await c._try(f"semantic view {fqn}", "SELECT GET_DDL('SEMANTIC_VIEW', %s) AS DDL", [fqn])
                    definition = ddl[0]["DDL"] if ddl else None
                if kind == "network_rule":
                    desc = await c._try(f"network rule {fqn}", f"DESC NETWORK RULE {quote_name(fqn)}")
                    r = {**r, **{k: v for d in desc for k, v in d.items() if k in ("VALUE_LIST", "MODE", "TYPE")}}
                props = _clean(r, ("NAME", "OWNER", "COMMENT", "DEFINITION"))
                self.obj(kind, r["NAME"], fqn, parent=f"{db}.{r.get('SCHEMA_NAME')}", owner=r.get("OWNER"),
                         comment=r.get("COMMENT"), definition=definition, properties=props)
                if wh_key and r.get(wh_key):
                    self.link((kind, fqn), ("warehouse", r[wh_key]), "RUNS_ON")
                if kind == "git_repository" and r.get("API_INTEGRATION"):
                    self.link((kind, fqn), ("integration", r["API_INTEGRATION"]), "USES_INTEGRATION")

        for r in await c._try("database roles", f"SHOW DATABASE ROLES IN DATABASE {q}"):
            self.obj("database_role", r["NAME"], f"{db}.{r['NAME']}", parent=db, owner=r.get("OWNER"),
                     comment=r.get("COMMENT"), properties=_clean(r, ("NAME", "OWNER", "COMMENT")))

        # Streams track a table; dynamic tables and views already carry lineage.
        for s in cache["streams"]:
            if s.get("TABLE_NAME"):
                src = ".".join(p.upper() if '"' not in s["TABLE_NAME"] else p for p in split_name(s["TABLE_NAME"]))
                self.link(("table", src), ("table", f"{db}.{s.get('SCHEMA_NAME')}.{s.get('NAME')}"), "TRACKED_BY",
                          mode=s.get("MODE"))

        # How raw tables are loaded: COPY INTO statements and the copy history.
        for (t_fqn, build) in cache["builds"].items():
            copy = build["latest"].get("COPY")
            if copy:
                await self._copy_links(None, copy["sql"] or "", db, split_name(t_fqn)[1], target=t_fqn,
                                       at=copy.get("at"), by=copy.get("by"), loads=build["counts"].get("COPY"))
        loads = await c._try("copy history (ACCOUNT_USAGE)", (
            "SELECT table_catalog_name, table_schema_name, table_name, stage_location, COUNT(*) AS files, "
            "SUM(row_count) AS rows_loaded, SUM(error_count) AS errors, MAX(last_load_time) AS last_load, "
            "COUNT_IF(status <> 'Loaded') AS failed_files FROM SNOWFLAKE.ACCOUNT_USAGE.COPY_HISTORY "
            "WHERE table_catalog_name = %s AND last_load_time > DATEADD('day', %s, CURRENT_TIMESTAMP()) "
            "GROUP BY 1, 2, 3, 4"), [db, -c.history_days])
        for r in loads:
            target = f"{r['TABLE_CATALOG_NAME']}.{r['TABLE_SCHEMA_NAME']}.{r['TABLE_NAME']}"
            self.link(("location", r.get("STAGE_LOCATION")), ("table", target), "LOADS_INTO",
                      files=_iso(r.get("FILES")), rows=_iso(r.get("ROWS_LOADED")), errors=_iso(r.get("ERRORS")),
                      failed_files=_iso(r.get("FAILED_FILES")), last_load=_iso(r.get("LAST_LOAD")),
                      window_days=c.history_days)

    async def _copy_links(self, source: Optional[Tuple[str, str]], sql: str, db: str, schema: str, *,
                          target: Optional[str] = None, **detail) -> None:
        """A COPY INTO statement: stage → table (and the pipe or statement that does it)."""
        ref = stage_reference(sql)
        if target is None:
            m = _COPY_TARGET.search(sql)
            target = await self.resolve_name(m.group(1), db, schema) if m else None
        if not ref or not target:
            return
        stage = await self.resolve_name(ref[0], db, schema)
        self.link(("stage", stage), ("table", target), "FEEDS", path=ref[1] or None, via="COPY INTO", **detail)
        if source:
            self.link(source, ("stage", stage), "READS_FILE", path=ref[1] or None)
            self.link(source, ("table", target), "WRITES_TABLE")

    # ── grants and role hierarchy ────────────────────────────────────
    async def grants(self) -> Dict[str, Dict[str, List[str]]]:
        """Privileges on each object by role, and role → role / user → role links."""
        c = self.c
        rows = await c._try("grants (ACCOUNT_USAGE)", (
            "SELECT privilege, granted_on, name, table_catalog, table_schema, grantee_name, granted_to "
            "FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES WHERE deleted_on IS NULL"))
        by_object: Dict[str, Dict[str, List[str]]] = defaultdict(lambda: defaultdict(list))
        held: Dict[str, Dict[str, set]] = defaultdict(lambda: defaultdict(set))
        for r in rows:
            on = (r.get("GRANTED_ON") or "").upper()
            if on == "ROLE" and (r.get("PRIVILEGE") or "").upper() == "USAGE":
                self.link(("role", r["GRANTEE_NAME"]), ("role", r["NAME"]), "INHERITS")
                continue
            if on == "DATABASE_ROLE":
                continue
            # For a database or schema grant the name repeats in the catalog/schema columns.
            if on == "DATABASE":
                parts = [r.get("NAME")]
            elif on == "SCHEMA":
                parts = [p for p in (r.get("TABLE_CATALOG"), r.get("NAME")) if p]
            else:
                parts = [p for p in (r.get("TABLE_CATALOG"), r.get("TABLE_SCHEMA"), r.get("NAME")) if p]
            if parts and c._skip_db(parts[0]) and on not in ("ACCOUNT", "WAREHOUSE", "INTEGRATION", "USER", "ROLE"):
                continue
            by_object[f"{on}:{'.'.join(parts).upper()}"][r["GRANTEE_NAME"]].append(r["PRIVILEGE"])
            held[r["GRANTEE_NAME"]][f"{on.lower()} {'.'.join(parts)}"].add(r["PRIVILEGE"])
        self.role_privileges = {role: {obj: sorted(p) for obj, p in sorted(objs.items())}
                                for role, objs in held.items()}
        for r in await c._try("user roles (ACCOUNT_USAGE)", (
                "SELECT role, grantee_name FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS WHERE deleted_on IS NULL")):
            self.link(("user", r["GRANTEE_NAME"]), ("role", r["ROLE"]), "HAS_ROLE")
        return {k: {role: sorted(set(p)) for role, p in v.items()} for k, v in by_object.items()}


async def read_objects(c: SnowflakeConnector) -> Dict[str, Any]:
    reader = ObjectReader(c)
    await reader.account()
    for db in await c._databases():
        await reader.database(db)
    grants = await reader.grants()
    for o in reader.objects:
        if o["kind"] in ("role", "database_role") and reader.role_privileges.get(o["name"]):
            o["properties"]["privileges_held"] = reader.role_privileges[o["name"]]
    _infer_stage_locations(reader)
    # Every location named by a stage, integration, volume or load becomes an object, nested in its parent.
    locations = sorted({name for link in reader.links for kind, name in (link["source"], link["target"])
                        if kind == "location" and name}, key=len)
    for name in locations:
        scheme = name.split("://", 1)[0] if "://" in name else "path"
        reader.obj("location", name.rstrip("/").rsplit("/", 1)[-1] or name, name, properties={"scheme": scheme})
        parent = next((p for p in reversed(locations) if p != name and name.startswith(p.rstrip("/") + "/")), None)
        if parent:
            reader.link(("location", name), ("location", parent), "WITHIN")
    # Objects that links name but this role cannot describe still belong on the map.
    seen = {(o["kind"], o["full_name"].upper()) for o in reader.objects}
    for link in reader.links:
        for kind, name in (link["source"], link["target"]):
            if kind in ("table", "catalog") or not name or (kind, name.upper()) in seen:
                continue
            seen.add((kind, name.upper()))
            reader.obj(kind, split_name(name)[-1] if kind != "location" else name, name, properties={
                "describable": False,
                "note": f"Named by {link['relation']} metadata; the role Kairos uses cannot see or describe this "
                        f"{kind.replace('_', ' ')}. Grant it usage to read its definition."})
    return {"objects": reader.objects, "links": reader.links, "grants": grants, "counts": dict(reader.counts)}
