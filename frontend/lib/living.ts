import { fetchApi } from "@/lib/api";

// ── the living agent: what it watches, what it noticed, its looks and replays ─────

export type Direction = "up" | "down" | "neutral";
export type NoteStatus = "open" | "provisional" | "confirmed" | "withdrawn" | "resolved" | "dismissed" | "grouped";
export type NoteKind = "finding" | "data_issue" | "correction" | "briefing" | "reflection";

export interface WatchView {
  id: string;
  product: string | null;
  product_id: string;
  metric: string;
  label: string | null;
  time_dim: string;
  slices: string[];
  good_direction: Direction;
  settle_periods: number;
  settle_measured: boolean;
  settle_reason: string | null;
  maturity_curve: { age: number; mean_revision_pct: number; samples: number }[];
  looks: number;
  why: string | null;
  min_impact_pct: number;
  sensitivity: number;
  status: "active" | "muted";
  origin: string;
  series: [string, number][];
  attention: string[];
}

export interface SignalFacts {
  kind: string;
  period: string;
  value: number;
  baseline: number | null;
  impact_pct: number | null;
  direction: "up" | "down";
  value_display?: string;
  baseline_display?: string;
  since?: string;
  streak?: number;
  p_value?: number;
  normal_range?: [number, number];
  seasonal?: { yoy_pct: number; usual: boolean };
}

export interface WhereItMoved {
  dimension: string;
  slices_compared: number;
  top: { slice: string; value: number; baseline: number; delta: number; change_pct: number | null; share_of_change_pct?: number }[];
}

export interface NoteFacts {
  product?: string;
  metric?: string;
  label?: string;
  signal?: SignalFacts;
  also?: { kind: string; impact_pct: number | null }[];
  valence?: "good" | "bad" | "neutral";
  status?: string;
  where?: WhereItMoved[];
  maturity?: { measured: boolean; settle_periods: number; reason: string | null; looks: number };
  partial?: { period: string; data_until: string } | null;
  held_for_data?: boolean;
  query?: { sql?: string; source?: string; table?: string };
  series_tail?: [string, number][];
  written_by?: string;
  problems?: string[];
  held?: string[];
  last_period?: string;
  stats?: Record<string, number>;
  catch_up?: boolean;
  as_of_last_data?: string;
  grouped?: number;
  members?: { label: string; product: string; impact_pct: number | null; value_display?: string; baseline_display?: string; valence?: string }[];
}

export interface AgentNote {
  id: string;
  kind: NoteKind;
  signal: string | null;
  title: string;
  body: string | null;
  facts: NoteFacts | null;
  period: string | null;
  as_of: string | null;
  importance: number;
  confidence: number;
  status: NoteStatus;
  feedback: "useful" | "not_useful" | null;
  mode: "live" | "replay";
  watch_id: string | null;
  product_id: string | null;
  created_at: string;
}

export interface AgentRunView {
  id: string;
  mode: "live" | "replay";
  status: "running" | "completed" | "failed";
  stats: Record<string, unknown> | null;
  error: string | null;
  step: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface LivingState {
  workspace: string;
  products: number;
  watches: WatchView[];
  notes: AgentNote[];
  runs: AgentRunView[];
}

export const getState = (workspaceId: string): Promise<LivingState> => fetchApi(`/living/state?workspace_id=${workspaceId}`);

export const startRun = (body: { workspace_id: string; mode: "live" | "replay"; start?: string; end?: string }): Promise<AgentRunView> =>
  fetchApi(`/living/runs`, { method: "POST", body: JSON.stringify(body) });

export const getRun = (id: string): Promise<AgentRunView> => fetchApi(`/living/runs/${id}`);

export const getReplay = (workspaceId: string): Promise<{ run: AgentRunView | null; notes: AgentNote[] }> =>
  fetchApi(`/living/replay?workspace_id=${workspaceId}`);

export const sendFeedback = (id: string, body: { feedback?: "useful" | "not_useful"; status?: "dismissed" | "resolved" | "open" }): Promise<AgentNote> =>
  fetchApi(`/living/notes/${id}`, { method: "PATCH", body: JSON.stringify(body) });

export const updateWatch = (id: string, body: { status?: "active" | "muted"; good_direction?: Direction; min_impact_pct?: number }) =>
  fetchApi(`/living/watches/${id}`, { method: "PATCH", body: JSON.stringify(body) });

export function fmt(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  const a = Math.abs(v);
  if (a >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (a >= 1e4) return `${(v / 1e3).toFixed(1)}k`;
  if (a >= 100) return Math.round(v).toLocaleString();
  return a < 1 ? v.toPrecision(3) : v.toFixed(2);
}

export const monthLabel = (iso: string | null | undefined) =>
  iso ? new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString(undefined, { month: "short", year: "numeric" }) : "";
