import { fetchApi } from "@/lib/api";

// ── the Test screen: chat through a Kairos MCP connector, watch every call ─────

export interface ConsoleConnector {
  id: string;
  label: string;
  detail: string;
  path: string;
  tools: number;
  platform: string | null;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  at: string;
  connector: string;
  turn?: number;
  ms?: number;
  tools?: string[];
  tokens?: number;
  error?: boolean;
}

export type TraceEvent =
  | { type: "connect"; at: string; turn: number; connector: string; url: string; tools: string[]; instructions_chars: number; ms: number }
  | { type: "llm"; at: string; turn: number; step: number; model: string; input_tokens: number; output_tokens: number; ms: number; tool_calls: string[]; thought: string | null }
  | { type: "tool_call"; at: string; turn: number; tool: string; args: Record<string, unknown>; ok: boolean; local: boolean; ms: number; result_chars: number; result: string; truncated: boolean }
  | { type: "answer"; at: string; turn: number; ms: number; input_tokens: number; output_tokens: number; tools: string[]; step_limit: boolean }
  | { type: "switch"; at: string; turn: number; from: string; to: string }
  | { type: "error"; at: string; turn: number; error: string };

export interface ConsoleSession {
  id: string;
  connector: string;
  status: "idle" | "running";
  created_at: string;
  messages: ChatMessage[];
  trace: TraceEvent[];
  trace_total: number;
  turns: number;
  totals: { input_tokens: number; output_tokens: number; tool_calls: number; tool_errors: number; llm_steps: number };
  error: string | null;
}

export interface AuditRow {
  id: string;
  at: string;
  channel: string;
  tool: string;
  arguments: Record<string, unknown> | null;
  entities: string[];
  ok: boolean;
  error: string | null;
  duration_ms: number;
  result_size: number;
  args_tokens: number | null;
  result_tokens: number | null;
  est_cost_usd: number | null;
}

export const listConnectors = (): Promise<{ connectors: ConsoleConnector[] }> => fetchApi(`/test/connectors`);

export const createSession = (connector: string): Promise<ConsoleSession> =>
  fetchApi(`/test/sessions`, { method: "POST", body: JSON.stringify({ connector }) });

export const getSession = (id: string, after = 0): Promise<ConsoleSession> => fetchApi(`/test/sessions/${id}?after=${after}`);

export const switchConnector = (id: string, connector: string): Promise<ConsoleSession> =>
  fetchApi(`/test/sessions/${id}`, { method: "PATCH", body: JSON.stringify({ connector }) });

export const sendMessage = (id: string, text: string): Promise<ConsoleSession> =>
  fetchApi(`/test/sessions/${id}/messages`, { method: "POST", body: JSON.stringify({ text }) });

export const getAudit = (id: string): Promise<{ audit: AuditRow[] }> => fetchApi(`/test/sessions/${id}/audit`);
