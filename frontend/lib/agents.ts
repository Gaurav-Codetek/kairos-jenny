import { fetchApi } from "@/lib/api";

// ── agents and keys ──────────────────────────────────────────────────

export interface AgentClient {
  id: string;
  name: string;
  description: string | null;
  key_prefix: string;
  workspace_ids: string[];
  scopes: string[];
  revoked: boolean;
  created_at: string;
  last_seen_at: string | null;
  call_count: number;
}

export interface AgentWithKey extends AgentClient {
  key: string;
  note: string;
}

export interface ActivityRow {
  id: string;
  at: string;
  agent: string;
  agent_id: string | null;
  channel: string;
  tool: string;
  arguments: Record<string, unknown> | null;
  entity_ids: string[] | null;
  ok: boolean;
  error: string | null;
  duration_ms: number;
  result_size: number;
  /** Tokens the agent wrote (arguments) and read back (response); null for calls before tracking began. */
  args_tokens: number | null;
  result_tokens: number | null;
  tokens: number | null;
  est_cost_usd: number | null;
}

export interface ChannelStats {
  calls: number;
  errors: number;
  tools_used: number;
  tokens: number;
  avg_tokens: number | null;
  est_cost_usd: number;
}

/** Which surface a call came through: the v1 MCP server, the v2 MCP server, or REST. */
export const CHANNELS: { id: string; label: string }[] = [
  { id: "", label: "All" },
  { id: "mcp", label: "MCP v1" },
  { id: "mcp-v2", label: "MCP v2" },
  { id: "rest", label: "REST" },
];

export interface AgentStats {
  days: number;
  channel: string | null;
  by_channel: Record<string, ChannelStats>;
  calls: number;
  errors: number;
  error_rate: number;
  by_tool: Record<string, number>;
  by_agent: Record<string, number>;
  most_requested: { entity_id: string; name: string; count: number }[];
  tokens: { args: number; results: number };
  est_cost_usd: number;
  tool_usage: Record<string, { measured_calls: number; args_tokens: number; result_tokens: number; avg_tokens: number | null; est_cost_usd: number }>;
  pricing: { model: string; input_per_m: number; output_per_m: number; basis: string };
}

export interface ConnectInfo {
  mcp_url: string;
  mcp_v2_url: string;
  /** One endpoint per connection, with its platform's tools. */
  connections?: { name: string; platform: string; slug: string; mcp_url: string; tools: string[] }[];
  rest_base: string;
  openapi_url: string;
  auth_mode: "off" | "optional" | "required";
  header: string;
  snippets: { claude_code: string; mcp_json: unknown; python_mcp: string; rest_curl: string };
}

export const listAgents = (): Promise<{ agents: AgentClient[] }> => fetchApi("/agents");
export const createAgent = (body: {
  name: string;
  description?: string;
  workspace_ids?: string[] | null;
  scopes: string[];
}): Promise<AgentWithKey> => fetchApi("/agents", { method: "POST", body: JSON.stringify(body) });
export const rotateAgentKey = (id: string): Promise<AgentWithKey> => fetchApi(`/agents/${id}/rotate`, { method: "POST" });
export const revokeAgent = (id: string): Promise<AgentClient> => fetchApi(`/agents/${id}/revoke`, { method: "POST" });
export const getActivity = (limit = 60, channel = ""): Promise<{ activity: ActivityRow[] }> =>
  fetchApi(`/agents/activity?limit=${limit}${channel ? `&channel=${channel}` : ""}`);
export const getAgentStats = (days = 7, channel = ""): Promise<AgentStats> =>
  fetchApi(`/agents/stats?days=${days}${channel ? `&channel=${channel}` : ""}`);
export const getConnectInfo = (): Promise<ConnectInfo> => fetchApi("/agents/connect");

// ── the context layer ────────────────────────────────────────────────

export type TrustLevel = "verified" | "profiled" | "synced";

export interface SearchHit {
  entity_id: string;
  kind: string;
  name: string;
  what_it_is: string | null;
  trust_level: TrustLevel;
  matched_by: string[];
  relevance: number;
  evidence: string | null;
}

export interface SearchResult {
  question: string;
  results: SearchHit[];
  retrievers: Record<string, number>;
  note: string | null;
}

export interface FlowEntry {
  entity_id: string;
  name: string;
  evidence: string;
  status?: string;
  via?: string;
}

export interface ContextCard {
  entity_id: string;
  kind: string;
  name: string;
  full_name?: string;
  workspace: string | null;
  data_product: string | null;
  summary: string | null;
  purpose: string | null;
  tags: string[];
  trust: {
    level: TrustLevel;
    profiled_at: string | null;
    stale: boolean;
    verification_passed: boolean | null;
    checks: { check: string; result: string; detail: string | null }[];
    classification: { role: string; layer: string; role_confidence: number; layer_confidence: number } | null;
    open_feedback: number;
  };
  shape?: {
    grain: string | null;
    grain_key: string[];
    grain_key_unique: boolean | null;
    column_count: number;
    columns: { name: string; type: string | null; meaning: string | null; tags: string | null; unit: string | null }[];
    columns_truncated: number;
  };
  flow?: {
    produced_by?: FlowEntry[];
    read_by?: FlowEntry[];
    upstream_tables?: FlowEntry[];
    downstream_tables?: FlowEntry[];
    reads?: FlowEntry[];
    writes?: FlowEntry[];
  };
  usage?: {
    example_sql: string | null;
    join_candidates: { entity_id: string; name: string; on: string[]; strength: number; evidence?: string }[];
  };
  tasks?: { entity_id: string; task_key: string; summary: string | null }[];
  health?: { recent_runs: number; by_result: Record<string, number>; last_failure: { at: string; message: string } | null };
  caveats: string[];
  feedback: { id: string; kind: string; reporter: string; message: string; at: string }[];
}

export interface ContextHealth {
  workspaces: {
    workspace_id: string;
    name: string;
    tables: number;
    tables_indexed: number;
    tables_profiled: number;
    tables_verified: number;
    documents: number;
    documents_embedded: number;
    open_feedback: number;
    indexing: boolean;
    last_synced_at: string | null;
  }[];
}

export interface FeedbackItem {
  id: string;
  entity_id: string;
  name: string;
  kind: string;
  message: string;
  field: string | null;
  suggestion: string | null;
  reporter: string;
  status: "open" | "applied" | "dismissed";
  resolution: string | null;
  created_at: string;
  /** Reports about a data product go through the report loop: triage, proposal, checks, proof. */
  loop?: ReportLoop;
}

export type LoopStage =
  | "new"
  | "triaged"
  | "proposed"
  | "verified"
  | "needs_person"
  | "building"
  | "merged"
  | "dismissed"
  | "rolled_back";

export interface ReportLoop {
  stage: LoopStage | null;
  category: "product_change" | "data_issue" | "description" | "new_product" | "not_actionable" | null;
  proposal: {
    adds: { kind: "dimension" | "metric" | "caveat" | "rule" | "term"; name: string; label: string; definition: string }[];
    reason: string | null;
    dropped: { kind: string; item: string; reason: string }[];
    answers?: number | null;
  } | null;
  checks: { what: string; ok: boolean; sample?: string[][]; error?: string | null; replay?: boolean }[] | null;
  history: { at: string; stage: string; note: string }[];
  question: string | null;
  also_reported: number;
  /** A report that needs an area no product covers: the product Kairos would build for it. */
  new_product: { concept: string; intent: string; why: string } | null;
  built_product: { id: string; name: string; slug: string } | null;
}

export const searchContext = (q: string, limit = 10): Promise<SearchResult> =>
  fetchApi(`/context/search?q=${encodeURIComponent(q)}&limit=${limit}`);
export const getContextCard = (entityId: string, maxColumns = 200): Promise<ContextCard> =>
  fetchApi(`/context/entities/${encodeURIComponent(entityId)}?max_columns=${maxColumns}&detail=full`);
export const getContextHealth = (): Promise<ContextHealth> => fetchApi("/context/health");
export const reindexWorkspace = (workspaceId: string) =>
  fetchApi(`/context/reindex?workspace_id=${workspaceId}`, { method: "POST" });
export const listFeedback = (status?: string): Promise<{ feedback: FeedbackItem[] }> =>
  fetchApi(`/context/feedback${status ? `?status=${status}` : ""}`);
export const updateFeedback = (id: string, status: string) =>
  fetchApi(`/context/feedback/${id}`, { method: "PATCH", body: JSON.stringify({ status }) });
/** The report loop's actions on a report about a data product. */
export const workOnReport = (id: string): Promise<FeedbackItem> => fetchApi(`/context/feedback/${id}/process`, { method: "POST" });
export const approveReport = (id: string): Promise<FeedbackItem> => fetchApi(`/context/feedback/${id}/approve`, { method: "POST" });
export const rejectReport = (id: string): Promise<FeedbackItem> => fetchApi(`/context/feedback/${id}/reject`, { method: "POST" });
export const rollBackReport = (id: string): Promise<FeedbackItem> => fetchApi(`/context/feedback/${id}/rollback`, { method: "POST" });
export const buildFromReport = (id: string): Promise<FeedbackItem> => fetchApi(`/context/feedback/${id}/build`, { method: "POST" });
export const postFeedback = (body: { entity_id: string; kind: string; message: string; field?: string }) =>
  fetchApi("/context/feedback", { method: "POST", body: JSON.stringify(body) });

// ── readiness: the cold-agent evaluation ─────────────────────────────

export interface EvalSummary {
  file: string;
  toolset: "full" | "legacy";
  ran_at: string;
  cases: number;
  passed: number;
  readiness: number;
  mean_judge_score: number;
  by_role: Record<string, string>;
  tool_calls: number;
  tokens: number;
}

export interface EvalReport extends EvalSummary {
  context_gaps: { case: string; gap: string }[];
  results: {
    id: string;
    role: string;
    question: string;
    passed: boolean;
    mention_score: number;
    mentions_missing: string[];
    judge_score: number;
    verdict: string | null;
    missing_context: string | null;
    tools_used: string[];
    tool_calls: number;
    seconds: number;
    answer: string;
  }[];
}

export const listEvals = (): Promise<{ running: string[]; reports: EvalSummary[] }> => fetchApi("/context/evals/cold-agent");
export const getEval = (file: string): Promise<EvalReport> => fetchApi(`/context/evals/cold-agent/${file}`);
export const runEval = (toolset: "full" | "legacy") =>
  fetchApi(`/context/evals/cold-agent?toolset=${toolset}`, { method: "POST" });

export const TRUST_META: Record<TrustLevel, { label: string; color: string; bg: string; hint: string }> = {
  verified: { label: "Verified", color: "var(--ok)", bg: "var(--ok-soft)", hint: "Profiled, every check passed" },
  profiled: { label: "Profiled", color: "var(--warn)", bg: "var(--warn-soft)", hint: "Described; a check failed or did not run" },
  synced: { label: "Synced", color: "var(--neutral)", bg: "var(--neutral-soft)", hint: "Platform metadata only" },
};

// ── agent demand ─────────────────────────────────────────────────────

export interface DemandItem {
  entity_id: string;
  kind: string;
  name: string;
  calls: number;
  queried_with_sql: number;
  last_used: string;
  trust_level: TrustLevel;
}

export const getDemand = (days = 14): Promise<{ days: number; entities: DemandItem[]; needs_enrichment: DemandItem[] }> =>
  fetchApi(`/context/demand?days=${days}`);
