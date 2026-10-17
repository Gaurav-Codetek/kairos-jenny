import { fetchApi } from "@/lib/api";

export interface RunTotals {
  total: number;
  completed: number;
  failed: number;
  skipped: number;
  remaining: number;
  percent: number;
}

export interface EnrichmentRun {
  id: string;
  workspace_id: string;
  status: "queued" | "running" | "paused" | "completed" | "failed" | "canceled";
  active_in_process: boolean;
  scope: {
    kinds: string[] | null;
    entity_ids: string[] | null;
    limit_per_kind: number | null;
    force: boolean;
  } | null;
  totals: RunTotals;
  discovered: { relations: number; entities: number };
  current_entity_id: string | null;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
  heartbeat_at: string | null;
  items_by_status?: Record<string, number>;
  /** Tokens and calls spent so far — updated after every LLM call. */
  usage?: RunUsage;
  /** What the agent is doing right now, in words. */
  activity?: string | null;
  activity_at?: string | null;
  /** get_run only: the entity being enriched right now. */
  current?: RunItem | null;
  /** get_run only: the most recently finished entities, newest first. */
  recent_items?: RunItem[];
  /** get_run only: the server's clock, so browser timers do not drift. */
  server_now?: string;
}

export interface RunUsage {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  llm_calls: number;
  tool_calls: number;
}

export interface RunItem {
  entity_id: string;
  name: string;
  kind: string;
  status: string;
  depth: number;
  /** Why the frontier queued it, e.g. "WRITES_TABLE · code line 142". Null for a seed. */
  via_relation: string | null;
  parent_entity_id: string | null;
  parent_name: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_s: number | null;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  llm_calls: number;
  tool_calls: number;
}

export interface EnrichmentEvent {
  sequence: number;
  event_type: string;
  level: "info" | "warning" | "error";
  entity_id: string | null;
  message: string;
  payload: Record<string, unknown> | null;
  created_at: string;
}

export interface DiscoveredSummary {
  relation_types: Array<{ relation_type: string; count: number }>;
  entity_kinds: Array<{ kind: string; count: number }>;
  relations: Array<{
    source: string;
    target: string;
    relation_type: string;
    confidence: number;
    rationale: string;
    source_ref: string | null;
    observed_at: string;
  }>;
  entities: Array<{
    entity_id: string;
    kind: string;
    name: string;
    full_name: string | null;
    rationale: string | null;
    first_seen_at: string;
  }>;
}

export interface ProfileIndexEntry {
  entity_id: string;
  kind: string;
  summary: string | null;
  purpose: string | null;
  data_product: string | null;
  semantic_tags: string[] | null;
  yaml_path: string;
  generated_at: string;
}

export const PROFILABLE_KINDS = ["workspace", "catalog", "schema", "table", "job", "task"] as const;

export type TargetKind = "job" | "catalog" | "schema" | "table";

export interface EnrichmentTarget {
  entity_id: string;
  kind: TargetKind;
  name: string;
  detail: string | null;
  owner: string | null;
  /** How many children a scoped run would pull in. */
  child_count: number;
  /** Total entities the run would cover, including this one. */
  entity_count: number;
  profiled: boolean;
  failed_runs: number;
}

export interface RunEstimate {
  entities_in_scope: number;
  already_profiled: number;
  to_process: number;
  by_kind: Record<string, number>;
  estimated_seconds: number;
  estimated_minutes: number;
  estimated_llm_calls: number;
  /** "measured" once this deployment has enough completed items to average. */
  basis: "measured" | "default";
  measured_kinds: Record<string, number>;
}

export interface StartRunOptions {
  workspace_id?: string;
  kinds?: string[];
  entity_ids?: string[];
  limit_per_kind?: number | null;
  include_descendants?: boolean;
  /** Frontier mode: follow relationships outward from the seeds. */
  follow_graph?: boolean;
  /** Hops the frontier may travel. Server default is 3. */
  max_depth?: number | null;
  /** Ceiling on entities profiled in one run. Server default is 30. */
  max_entities?: number | null;
  /** false: no entity ceiling; the walk is bounded by max_depth only. Server default true. */
  entity_cap?: boolean;
  force?: boolean;
}

export function listTargets(
  kind: TargetKind,
  q?: string
): Promise<{ kind: string; count: number; targets: EnrichmentTarget[] }> {
  const params = new URLSearchParams({ kind, limit: "300" });
  if (q) params.set("q", q);
  return fetchApi(`/enrichment/targets?${params.toString()}`);
}

export function estimateRun(
  entityIds: string[],
  includeDescendants: boolean,
  force: boolean
): Promise<RunEstimate> {
  return fetchApi("/enrichment/estimate", {
    method: "POST",
    body: JSON.stringify({
      entity_ids: entityIds,
      include_descendants: includeDescendants,
      force,
    }),
  });
}

export function formatDuration(minutes: number): string {
  if (minutes < 1) return "< 1 min";
  if (minutes < 60) return `${Math.round(minutes)} min`;
  const hours = minutes / 60;
  return `${hours.toFixed(1)} hr`;
}

export function startRun(options: StartRunOptions): Promise<EnrichmentRun> {
  return fetchApi("/enrichment/runs", {
    method: "POST",
    body: JSON.stringify(options),
  });
}

export function listRuns(): Promise<{ runs: EnrichmentRun[] }> {
  return fetchApi("/enrichment/runs");
}

export function getRun(runId: string): Promise<EnrichmentRun> {
  return fetchApi(`/enrichment/runs/${runId}`);
}

export function getEvents(
  runId: string,
  after: number
): Promise<{ events: EnrichmentEvent[]; last_sequence: number }> {
  return fetchApi(`/enrichment/runs/${runId}/events?after=${after}&limit=300`);
}

export function cancelRun(runId: string): Promise<unknown> {
  return fetchApi(`/enrichment/runs/${runId}/cancel`, { method: "POST" });
}

export function resumeRun(runId: string): Promise<unknown> {
  return fetchApi(`/enrichment/runs/${runId}/resume`, { method: "POST" });
}

export function getDiscovered(): Promise<DiscoveredSummary> {
  return fetchApi("/enrichment/discovered");
}

export function listProfiles(kind?: string): Promise<{ profiles: ProfileIndexEntry[] }> {
  return fetchApi(`/enrichment/profiles${kind ? `?kind=${kind}` : ""}`);
}

export function getProfileYaml(entityId: string): Promise<{ entity_id: string; yaml: string }> {
  return fetchApi(`/enrichment/profiles/yaml?entity_id=${encodeURIComponent(entityId)}`);
}

export function isTerminal(status: EnrichmentRun["status"]): boolean {
  return ["completed", "failed", "canceled"].includes(status);
}
