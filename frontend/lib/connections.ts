import { fetchApi } from "@/lib/api";

export type Platform = "databricks" | "snowflake";

export interface Workspace {
  id: string;
  workspace_id: string;
  name: string;
  host: string;
  platform: Platform;
  cloud: string;
  region: string;
  status: string;
  last_synced_at: string | null;
  description: string | null;
}

export interface DomainState {
  domain: "catalog" | "jobs" | "objects" | "lineage";
  status: "never_run" | "idle" | "running" | "error";
  last_sync_at: string | null;
  items_synced: number;
  error_message: string | null;
  entities_in_warehouse: number;
}

export interface WorkspaceStatus {
  workspace_id: string;
  name: string;
  platform: Platform;
  host: string;
  status: string;
  last_synced_at: string | null;
  connection_config: Record<string, unknown>;
  /** This connection's own MCP endpoint: only this connection, with its platform's tools. */
  mcp_slug?: string;
  mcp_url?: string;
  mcp_tools?: string[];
  domains: DomainState[];
  counts: Record<string, number>;
}

export interface SyncOptions {
  catalog_filter?: string[] | null;
  /** Pipelines to sync, by job name or job id. */
  job_filter?: string[] | null;
  run_limit?: number;
  skip_lineage?: boolean;
}

export function listWorkspaces(): Promise<Workspace[]> {
  return fetchApi("/workspaces");
}

export function getWorkspaceStatus(id: string): Promise<WorkspaceStatus> {
  return fetchApi(`/workspaces/${id}/status`);
}

/** For Snowflake: who Kairos is connected as, and which kinds of metadata that role can read. */
export interface ConnectionAccess {
  account?: string;
  user_name?: string;
  role?: string;
  warehouse?: string;
  region?: string;
  can_read?: Record<string, { ok: boolean; rows?: number; error?: string }>;
}

export interface TestResult {
  connected: boolean;
  platform?: Platform;
  access?: ConnectionAccess;
  access_error?: string;
}

export function testConnection(id: string): Promise<TestResult> {
  return fetchApi(`/workspaces/${id}/test-connection`, { method: "POST" });
}

export type SyncPhase = "catalog" | "jobs" | "objects" | "lineage" | "index";

export interface SyncPhaseState {
  status: "pending" | "running" | "completed" | "failed" | "skipped";
  started_at: string | null;
  finished_at: string | null;
  items: number;
  error: string | null;
}

/** A sync as it happens — GET /workspaces/{id}/sync/live. */
export interface SyncLive {
  id: string;
  workspace_id: string;
  status: "running" | "completed" | "failed";
  options: SyncOptions;
  started_at: string;
  finished_at: string | null;
  phase: SyncPhase | null;
  step: string;
  step_at: string;
  /** Where the current phase is, when the total is known: job 4 of 12. */
  position: { index: number; total: number; unit: string } | null;
  phases: Record<SyncPhase, SyncPhaseState>;
  counts: Record<string, number>;
  log: { at: string; message: string; level: "info" | "warning" | "error" }[];
  error: string | null;
  server_now: string;
}

/** Starts the sync in the background and returns its first snapshot. */
export function triggerSync(id: string, options: SyncOptions): Promise<SyncLive> {
  return fetchApi(`/workspaces/${id}/sync`, {
    method: "POST",
    body: JSON.stringify(options),
  });
}

/** The latest sync for a workspace, or {status: "none"} if there has been none since the API started. */
export function getSyncLive(id: string): Promise<SyncLive | { status: "none" }> {
  return fetchApi(`/workspaces/${id}/sync/live`);
}

export function createWorkspace(body: {
  name: string;
  host?: string;
  platform?: Platform;
  /** Non-secret settings. Snowflake: account, warehouse, role, databases. */
  connection_config?: Record<string, unknown>;
  cloud?: string;
  region?: string;
  description?: string;
}): Promise<Workspace> {
  return fetchApi("/workspaces", { method: "POST", body: JSON.stringify(body) });
}

/** Remove a connection and everything mirrored or learned from it. Nothing changes on the platform. */
export function deleteWorkspace(id: string): Promise<null> {
  return fetchApi(`/workspaces/${id}`, { method: "DELETE" });
}

/** Presentation for each supported platform. */
export const PLATFORM_META: Record<
  Platform,
  { label: string; blurb: string; accent: string; tint: string }
> = {
  databricks: {
    label: "Databricks",
    blurb: "Unity Catalog, Jobs, and system-table lineage",
    accent: "oklch(0.55 0.18 30)",
    tint: "oklch(0.96 0.03 30)",
  },
  snowflake: {
    label: "Snowflake",
    blurb: "Databases, tables, views, streams, task graphs, Snowpipes, dynamic tables, access-history lineage",
    accent: "oklch(0.60 0.15 230)",
    tint: "oklch(0.96 0.03 230)",
  },
};

export const DOMAIN_META: Record<
  DomainState["domain"],
  { label: string; description: string }
> = {
  catalog: {
    label: "Catalog",
    description: "Catalogs, schemas, tables and columns",
  },
  jobs: {
    label: "Pipelines",
    description: "Jobs, tasks, runs and task runs",
  },
  objects: {
    label: "Objects",
    description: "Warehouses, roles, integrations, stages, procedures, policies and more",
  },
  lineage: {
    label: "Lineage",
    description: "Table and column level data flow",
  },
};

export function relativeTime(iso: string | null): string {
  if (!iso) return "Never";
  const then = new Date(iso).getTime();
  const mins = Math.round((Date.now() - then) / 60000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}
