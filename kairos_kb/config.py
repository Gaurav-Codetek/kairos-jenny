"""Centralized configuration loaded from environment variables.

Uses pydantic-settings so every value is validated at startup. A single
``get_settings()`` call (cached) is the only way the rest of the codebase
reads configuration — no scattered ``os.getenv`` calls.
"""

from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide settings loaded from ``.env`` / environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────────────
    app_name: str = "Kairos"
    app_env: str = "dev"
    app_version: str = "0.1.0"
    debug: bool = False
    secret_key: str = "change-me-in-production"

    # ── Database ─────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://kairos:kairos_dev@db:5432/kairos"

    # ── CORS ─────────────────────────────────────────────────────────────
    frontend_origins: List[str] = Field(
        default=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
    )

    # ── Databricks ───────────────────────────────────────────────────────
    databricks_host: str = ""
    databricks_token: str = ""
    databricks_jobs_api_version: str = "2.2"
    databricks_workspace_api_version: str = "2.0"
    databricks_sql_api_version: str = "2.0"
    databricks_unity_catalog_api_version: str = "2.1"
    databricks_sql_warehouse_id: str = ""
    databricks_request_timeout_seconds: int = 30
    databricks_statement_timeout_seconds: int = 300

    # ── LLM service ──────────────────────────────────────────────────────
    # "azure" (default: Azure AI Foundry) or "openai" (the OpenAI API platform,
    # kept as a fallback). See kairos_kb/llm/provider.py.
    llm_provider: str = "azure"
    openai_api_key: str = ""
    openai_model: str = "gpt-6-luna"
    # Same model and dimensions as the Azure deployment, so stored vectors stay valid.
    openai_embedding_model: str = "text-embedding-3-large"

    # ── Azure OpenAI ─────────────────────────────────────────────────────
    azure_openai_api_key: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_api_version: str = "2025-04-01-preview"
    azure_openai_deployment: str = "gpt-5-mini"
    # Embeddings for the context layer's meaning-based search. Empty disables
    # them: search then falls back to keyword and name matching.
    azure_openai_embedding_deployment: str = "text-embedding-3-large"
    embedding_dimensions: int = 1536

    # ── Agent access (MCP + REST context API) ────────────────────────────
    # off: no keys checked. optional: a key identifies the agent, but calls
    # without one are allowed and audited as "anonymous". required: every
    # call needs a valid key. Enterprise deployments should use required.
    agent_auth_mode: str = "optional"
    # What a caller without a key may do: "read" (the map) and optionally
    # "query" (run read-only SQL). Hosted clients that cannot send a key — a
    # claude.ai connector today — only get what is listed here.
    anonymous_scopes: str = "read"
    # run_sql: mask values in identifying columns (names, addresses, postal
    # codes, DEA/HIN numbers, emails, phones, dates of birth).
    sql_mask_personal_data: bool = True
    # Also treat state / city / country / region columns as personal data.
    sql_mask_geography: bool = False
    # Catalogs any agent may query (comma-separated; empty = every catalog in the map).
    sql_allowed_catalogs: str = ""
    # Catalogs a caller without a key may query (empty = same as everyone).
    anonymous_sql_catalogs: str = ""
    # Allow read_files() and path tables (`/Volumes/…`). Off: agents query the map's tables only.
    sql_allow_file_reads: bool = False
    # Allow tables Kairos has not synced. Off: only tables in the map.
    sql_allow_unmapped: bool = False
    # read_volume_file: bytes read from the start of a file (the rest is never fetched).
    file_read_max_bytes: int = 262144
    # Snowflake. Secrets live here; a workspace's connection_config may override the
    # non-secret ones (account, warehouse, role, databases). Authenticate with ONE of:
    # a programmatic access token, a key pair, or a password (no MFA).
    snowflake_account: str = ""
    snowflake_user: str = ""
    snowflake_token: str = ""
    snowflake_password: str = ""
    snowflake_private_key_path: str = ""
    snowflake_private_key_passphrase: str = ""
    snowflake_warehouse: str = ""
    snowflake_role: str = ""
    # Databases never synced; SNOWFLAKE is the system database (read for lineage and history).
    snowflake_exclude_databases: str = "SNOWFLAKE,SNOWFLAKE_SAMPLE_DATA"
    # How far back task, pipe, refresh and access history is read.
    snowflake_history_days: int = 30
    snowflake_statement_timeout_seconds: int = 180

    # Connector evaluations reach Kairos over MCP HTTP, as an outside agent does; inside the
    # container that is the API's own port. Threads run this many at a time.
    eval_mcp_base_url: str = "http://localhost:8000"
    eval_concurrency: int = 4
    # Industry knowledge pack (an Open Knowledge Format bundle) and the folders in it that are not industry knowledge.
    knowledge_pack_path: str = "/app/us-pharma-kb"
    knowledge_pack_name: str = "us-pharma"
    knowledge_pack_exclude: str = "warehouse"
    sql_max_rows: int = 1000
    sql_timeout_seconds: int = 120
    # Pricing used to estimate what each tool call costs the calling agent
    # (USD per million tokens). Defaults: gpt-5-mini list price.
    llm_pricing_model: str = "gpt-5-mini"
    llm_price_input_per_m: float = 0.25
    llm_price_output_per_m: float = 2.00
    # Where agents reach Kairos, shown on the Agents screen.
    public_api_url: str = "http://localhost:8888"
    # Extra hostnames the MCP endpoint answers to, comma-separated — e.g. a
    # tunnel or a public domain: "abc123-8888.inc1.devtunnels.ms". The MCP
    # library rejects any other Host header (DNS-rebinding protection), so a
    # hosted client such as claude.ai cannot connect until its route is listed.
    mcp_allowed_hosts: str = ""

    # ── TypeSafe Jev (experimental Jev-guided RCA) ───────────────────────
    typesafe_api_key: str = ""
    # Empty uses the SDK default (jev-latest). Pin a versioned ID once
    # confidence thresholds are tuned, or answers will move under you.
    typesafe_model: str = ""
    # Below this confidence the hypothesis is not given to the agent.
    jev_rca_confidence_threshold: float = 0.6

    # ── Local Storage ────────────────────────────────────────────────────
    storage_base_path: str = "./data"

    # ── Sync Settings ────────────────────────────────────────────────────
    sync_default_run_history_limit: int = 25
    sync_initial_lookback_hours: int = 24


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings singleton."""
    return Settings()
