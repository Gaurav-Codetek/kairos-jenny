import { fetchApi } from "@/lib/api";

// ── data products: one business concept per product, per connection ─────

export type Lane = "source" | "raw" | "staging" | "core" | "mart";
export type Trust = "verified" | "profiled" | "synced";
export type ProductStatus = "draft" | "confirmed";
export type PortRole = "fact" | "dimension" | "aggregate" | "reference" | string;
export type HealthStatus = "healthy" | "degraded" | "broken";

export interface InputPort {
  entity_id: string;
  table: string;
  role: PortRole;
  why: string;
  lane: Lane;
  grain: string | null;
  trust: Trust;
}

export interface Health {
  status: HealthStatus;
  broken: number;
  breached: number;
  ok: number;
  total: number;
}

export interface Consumer {
  agent: string;
  channel: string;
  calls: number;
  last: string | null;
}

export interface ProductSummary {
  id: string;
  workspace_id: string;
  workspace: string;
  name: string;
  slug: string;
  domain: string | null;
  description: string | null;
  status: ProductStatus;
  intent: string | null;
  inputs: InputPort[];
  entities: string[];
  dimensions: { name: string; label: string | null; table: string | null }[];
  metrics: { name: string; label: string | null }[];
  tools: string[];
  health: Health | null;
  model: string | null;
  built_at: string | null;
  confirmed_at: string | null;
  consumers?: Consumer[];
  /** A product the engine has proposed and not built yet: drawn as a dashed card. */
  ghost?: "queued" | "building" | "failed";
}

export interface Metric {
  name: string;
  label: string;
  description: string;
  unit: string;
  base_table: string;
  base_entity_id: string;
  expression: string;
  additive: boolean;
  shortcuts: { table: string; column: string; rollup: string }[];
  caveat: string;
  verified?: string;
}

export interface Dimension {
  name: string;
  label: string;
  description: string;
  type: "categorical" | "time" | "numeric";
  table: string;
  column: string;
  entity_id: string;
  joins: { from_table: string; from_column: string; to_column: string }[];
  also_in: { table: string; column: string }[];
}

export interface Tool {
  name: string;
  description: string;
  metrics: string[];
  by: string[];
}

export interface SemanticModel {
  description: string;
  purpose: string;
  consumers: string[];
  entities: { name: string; description: string; table: string; key: string }[];
  dimensions: Dimension[];
  metrics: Metric[];
  tools: Tool[];
  glossary: { term: string; meaning: string }[];
  caveats: string[];
  agent_guidance: string[];
}

export interface Contract {
  contract: "schema" | "grain" | "pipeline" | "freshness" | "metric" | "reconcile" | string;
  port: string;
  status: "ok" | "broken" | "breached" | "info" | "error";
  detail: string | null;
  columns?: string[];
}

export interface FlowEdge {
  source: string;
  target: string;
  relation: string;
  status: string;
  via: string;
}

export interface Member {
  entity_id: string;
  kind: "table";
  name: string;
  full_name: string;
  lane: Lane;
  output_port: boolean;
  port_role?: PortRole;
  trust: Trust;
  role: string | null;
  layer: string | null;
  summary: string | null;
  grain: string | null;
  row_count: number | null;
  freshness: { last_altered?: string; built_by_role?: string; build_kind?: string };
}

export interface Bundle {
  lanes: Lane[];
  members: Member[];
  flow: FlowEdge[];
  sources: { entity_id: string; kind: string; name: string; role_in_product: string }[];
  objects: { entity_id: string; kind: string; name: string; role_in_product: string; summary?: string; comment?: string }[];
  attached: { object: string; relation: string; anchor: string; direction: string; status: string }[];
  pipelines: { entity_id: string; kind: string; name: string; runs?: { recent: number; succeeded: number; last_state: string | null } }[];
  health: { tables: number; trust: Record<Trust, number> };
}

export interface Product extends ProductSummary {
  spec: {
    concept: string;
    pins: string[];
    settings: { freshness_slo_hours?: number | null };
    inputs: InputPort[];
    left_out: { table: string; why: string }[];
    model: SemanticModel;
  };
  bundle: Bundle;
  validation: { dropped: { kind: string; item: string; reason: string }[]; repaired?: string[]; dialect?: string; live_at: string | null };
  contracts: { contracts: Contract[]; health: Health; live_at: string | null; freshness_slo_hours: number | null };
  consumers: Consumer[];
}

export interface Build {
  id: string;
  workspace_id: string;
  concept: string;
  status: "running" | "completed" | "failed";
  steps: { key: string; label: string; at: string }[];
  product_id: string | null;
  error: string | null;
}

export interface QueryResult {
  error?: string;
  product?: string;
  source?: "shortcut" | "base";
  table?: string;
  sql?: string;
  notes?: string[];
  columns?: ({ name: string } | string)[];
  rows?: unknown[][];
  row_count?: number;
  truncated?: boolean;
  duration_ms?: number;
  masked_columns?: string[];
  note?: string;
}

export const listProducts = (workspaceId: string): Promise<{ workspace: string; products: ProductSummary[] }> =>
  fetchApi(`/products?workspace_id=${workspaceId}`);

export const getProduct = (id: string): Promise<Product> => fetchApi(`/products/${id}`);

export const getProductForAgent = (id: string): Promise<Record<string, unknown>> => fetchApi(`/products/${id}/agent`);

export const listEnrichedTables = (
  workspaceId: string
): Promise<{ tables: { entity_id: string; name: string; full_name: string; lane: Lane; role: string | null; trust: Trust }[] }> =>
  fetchApi(`/products/tables?workspace_id=${workspaceId}`);

export const startProduct = (body: { workspace_id: string; concept: string; intent?: string; pins?: string[] }): Promise<Build> =>
  fetchApi(`/products`, { method: "POST", body: JSON.stringify(body) });

export const rebuildProduct = (id: string, body: { concept?: string; intent?: string; pins?: string[] } = {}): Promise<Build> =>
  fetchApi(`/products/${id}/rebuild`, { method: "POST", body: JSON.stringify(body) });

export const getBuild = (id: string): Promise<Build> => fetchApi(`/products/builds/${id}`);

export const updateProduct = (
  id: string,
  body: { name?: string; description?: string; status?: ProductStatus; freshness_slo_hours?: number }
): Promise<Product> => fetchApi(`/products/${id}`, { method: "PATCH", body: JSON.stringify(body) });

export const deleteProduct = (id: string): Promise<null> => fetchApi(`/products/${id}`, { method: "DELETE" });

export const checkProduct = (id: string): Promise<Product["contracts"]> => fetchApi(`/products/${id}/check`, { method: "POST" });

export const queryProduct = (
  id: string,
  body: { metrics?: string[]; by?: string[]; filters?: { dimension: string; op: string; value: unknown }[]; order?: string; tool?: string; limit?: number }
): Promise<QueryResult> => fetchApi(`/products/${id}/query`, { method: "POST", body: JSON.stringify(body) });

export const LANE_LABEL: Record<Lane, string> = {
  source: "Sources",
  raw: "Raw",
  staging: "Staging",
  core: "Facts & dimensions",
  mart: "Marts",
};

export const ROLE_TONE: Record<string, "brand" | "ok" | "warn" | "neutral"> = {
  fact: "brand",
  aggregate: "ok",
  dimension: "warn",
  reference: "neutral",
};

export const HEALTH_TONE: Record<HealthStatus, "ok" | "warn" | "danger"> = { healthy: "ok", degraded: "warn", broken: "danger" };

export const trustTone = (t?: Trust | null) => (t === "verified" ? "ok" : t === "profiled" ? "warn" : "neutral") as "ok" | "warn" | "neutral";

/** "DB.SCHEMA.TABLE" → "TABLE"; entity ids → their last name part. */
export const tail = (name: string) => name.split(":").pop()!.split(".").pop()!;

/** A readable name for an entity id: a location is its path (s3://bucket/raw/), anything else its last part. */
export const entityLabel = (id: string) =>
  id.startsWith("location:") ? id.split(":").slice(2).join(":").replace(/^\w+:\/\//, "") : tail(id);

export const pretty = (s?: string | null) => (s ? s.toLowerCase().replace(/_/g, " ") : "");

// ── the engine: every product the warehouse's data flow supports ─────

export interface EngineProposal {
  concept: string;
  intent: string;
  rationale: string;
  tables: string[];
  pins: string[];
  inputs?: { entity_id: string; table: string; role: PortRole }[];
  status: "queued" | "building" | "built" | "kept" | "failed";
  product_id: string | null;
  error: string | null;
  steps: { key: string; label: string }[];
}

export interface EngineRun {
  id: string;
  workspace_id: string;
  status: "running" | "completed" | "failed";
  phase: "flow" | "plan" | "build" | "done";
  flow: { facts: string[]; marts: string[]; dimensions: string[]; operational: string[] } | null;
  proposals: EngineProposal[];
  not_covered: { table: string; why: string }[];
  error: string | null;
  rebuild_existing: boolean;
  started_at: string;
  finished_at: string | null;
}

export const runEngine = (body: { workspace_id: string; rebuild_existing?: boolean }): Promise<EngineRun> =>
  fetchApi(`/products/engine`, { method: "POST", body: JSON.stringify(body) });

export const getEngine = (id: string): Promise<EngineRun> => fetchApi(`/products/engine/${id}`);

export const latestEngine = (workspaceId: string): Promise<EngineRun | null> =>
  fetchApi(`/products/engine/latest?workspace_id=${workspaceId}`);
