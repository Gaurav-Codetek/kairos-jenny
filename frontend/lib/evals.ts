import { fetchApi } from "@/lib/api";

// ── connector evaluations: runs, threads, transcripts ────────────────

/** v1, v2 (all connections), or "c:<connection slug>" for one connection's own endpoint. */
export type Connector = string;
export type RunStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
export type ThreadStatus = "queued" | "running" | "answered" | "scored" | "failed" | "cancelled";

export interface ConnectorSummary {
  threads: number;
  scored: number;
  passed: number;
  pass_rate: number | null;
  avg_score: number | null;
  avg_tool_calls: number | null;
  avg_tokens: number | null;
  avg_seconds: number | null;
  tool_errors: number;
  failed: number;
  invented: number;
}

export interface EvalRun {
  id: string;
  name: string;
  status: RunStatus;
  model: string;
  judge_model: string;
  connectors: Connector[];
  total_threads: number;
  finished_threads: number;
  summary: Partial<Record<Connector, ConnectorSummary>>;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface ThreadRow {
  id: string;
  run_id: string;
  case_id: string;
  connector: Connector;
  category: string | null;
  question: string;
  status: ThreadStatus;
  passed: boolean | null;
  judge_score: number | null;
  mention_score: number | null;
  tool_calls: number;
  tool_errors: number;
  tools_used: string[];
  tokens: number;
  duration_ms: number;
  verdict: string | null;
  step_limit_hit: boolean;
  error: string | null;
}

export type TranscriptItem =
  | { type: "text"; text: string }
  | { type: "answer"; text: string; ms?: number }
  | {
      type: "tool_call";
      tool: string;
      args: Record<string, unknown>;
      ok: boolean;
      local?: boolean;
      ms: number;
      result_chars: number;
      result: string;
      result_truncated: boolean;
    };

export interface ThreadDetail extends ThreadRow {
  reference: string | null;
  answer: string | null;
  transcript: TranscriptItem[];
  mentions_missing: string[];
  missing_context: string | null;
  input_tokens: number;
  output_tokens: number;
  tool_result_chars: number;
  started_at: string | null;
  finished_at: string | null;
}

export interface Question {
  id: string;
  category: string;
  question: string;
  reference: string;
  must_mention: string[][];
  source: string;
}

export interface QuestionBank {
  total: number;
  categories: Record<string, number>;
  sources: Record<string, number>;
  questions: Question[];
  connectors: Connector[];
  connector_options?: { id: string; label: string }[];
  default_model: string;
}

const LABELS: Record<string, string> = { v1: "v1 · 20 tools", v2: "v2 · 11 tools" };
/** A short label for a connector; connection endpoints read as their slug. */
export const CONNECTOR_LABEL = new Proxy(LABELS, {
  get: (target, key: string) => target[key] ?? (key.startsWith("c:") ? `${key.slice(2)} endpoint` : key),
}) as Record<string, string>;

export const getQuestionBank = (): Promise<QuestionBank> => fetchApi("/evals/questions");
export const listRuns = (): Promise<{ runs: EvalRun[] }> => fetchApi("/evals/runs");
export const getRun = (id: string): Promise<{ run: EvalRun; threads: ThreadRow[] }> => fetchApi(`/evals/runs/${id}`);
export const getThread = (id: string): Promise<ThreadDetail> => fetchApi(`/evals/threads/${id}`);
export const cancelRun = (id: string) => fetchApi(`/evals/runs/${id}/cancel`, { method: "POST" });
export const deleteRun = (id: string) => fetchApi(`/evals/runs/${id}`, { method: "DELETE" });
export const startRun = (body: {
  name?: string;
  connectors: Connector[];
  categories?: string[];
  case_ids?: string[];
  limit?: number;
}): Promise<EvalRun> => fetchApi("/evals/runs", { method: "POST", body: JSON.stringify(body) });

export const isActive = (s: RunStatus | ThreadStatus) => s === "queued" || s === "running" || s === "answered";

/** One line describing what a tool call asked for. */
export function argLine(args: Record<string, unknown>): string {
  const first = args.question ?? args.entity_id ?? args.concept_id ?? args.sql ?? args.path ?? args.query ?? args.from_entity;
  const text = typeof first === "string" ? first : Object.keys(args).length ? JSON.stringify(args) : "";
  const extra = Object.entries(args)
    .filter(([k, v]) => !["question", "entity_id", "concept_id", "sql", "path", "query", "from_entity"].includes(k) && v !== "" && v != null)
    .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join(" · ");
  const short = text.includes(":") && !args.sql && !args.question ? text.split(":").slice(2).join(":") || text : text;
  return [short.replace(/\s+/g, " "), extra].filter(Boolean).join("  ·  ");
}

export function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${Math.round(v * 100)}%`;
}
