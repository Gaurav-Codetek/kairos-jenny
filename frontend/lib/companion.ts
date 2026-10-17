import { API_BASE, fetchApi } from "@/lib/api";
import type { Pointing, Scene } from "@/lib/stage";

// ── the companion: its live view of the business, its moments, and conversation ────

export type VitalStatus = "normal" | "early" | "above" | "below" | "stale" | "error" | "learning";

export interface Vital {
  key: string;
  product: string;
  metric: string;
  label: string;
  unit: string;
  additive: boolean;
  good_direction: "up" | "down" | "neutral";
  why?: string;
  status: VitalStatus;
  direction?: "up" | "down" | null;
  strength?: "clear" | "strong" | null;
  valence?: "good" | "bad" | "neutral";
  actual?: number;
  expected?: number;
  low?: number;
  high?: number;
  dev_pct?: number | null;
  z?: number;
  projection?: number | null;
  expected_full?: number | null;
  share_done?: number;
  basis?: string;
  cut?: string;
  lag_minutes?: number;
  actual_display?: string;
  expected_display?: string;
  low_display?: string;
  high_display?: string;
  projection_display?: string;
  expected_full_display?: string;
  data_until?: string | null;
  error?: string;
  note?: string;
  hour?: { hour: number; actual: number; expected: number; dev_pct: number | null; actual_display?: string; expected_display?: string };
  curve?: { typical: [number, number, number, number][]; today: [number, number][] };
}

export interface Snapshot {
  as_of: string;
  live: boolean;
  local_time: string | null;
  local_now: string | null;
  weekday: string;
  today: string | null;
  offset_minutes: number | null;
  tz_source: string | null;
  data_now: string | null;
  lag_minutes: number | null;
  stalled: boolean;
  vitals: Vital[];
  reason: string | null;
  headline?: string;
}

export interface Moment {
  id: string;
  kind: "moment" | "daily_briefing" | "data_issue";
  signal: string | null;
  title: string;
  body: string | null;
  facts: Record<string, any> | null; // eslint-disable-line @typescript-eslint/no-explicit-any
  status: string;
  importance: number;
  confidence: number;
  feedback: string | null;
  period: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface TimelinePoint {
  as_of: string;
  headline: string | null;
  local_time: string | null;
  live: boolean;
  vitals: { key: string; label: string; status: VitalStatus; valence?: string; dev_pct?: number | null; actual_display?: string }[];
}

export interface CompanionState {
  workspace: string;
  enabled: boolean;
  interval_seconds: number;
  tz_offset_minutes: number | null;
  tz_source: string | null;
  live: boolean;
  status: "running" | "idle";
  error: string | null;
  last_pulse_at: string | null;
  next_pulse_at: string | null;
  next_pulse_in_seconds: number | null;
  headline: string | null;
  headline_at: string | null;
  snapshot: Snapshot | null;
  vitals: { key: string; label: string; product: string; why?: string }[];
  notes: Moment[];
  timeline: TimelinePoint[];
}

export interface ChatStep {
  tool: string;
  args: Record<string, unknown>;
  ok: boolean;
  ms: number;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "call" | "heard";
  /** In a meeting: who said it (a question to her, or something said in the room). */
  speaker?: string | null;
  text: string;
  at: string;
  steps?: ChatStep[];
  pending?: boolean;
  error?: boolean;
  ms?: number | null;
  voice?: boolean;
  interrupted?: boolean;
  heard?: string | null;
  from_memory?: { minutes_ago: number; similarity: number } | null;
  call?: { event: "start" | "end"; seconds: number | null } | null;
  /** What she said out loud while working: one line per look she took. */
  narration?: string[];
  /** The words of the turn being written right now (while pending). */
  live?: string;
  /** Known about half a second in: whether she'll be looking things up (so a call can say "hmm, let me see"). */
  looking?: boolean | null;
  /** How she read the turn before answering (Jev): kind of turn, mood, and her move. */
  /** She brought this up herself (a moment the pulse found); `recorded`: left as a voice note while you were away. */
  proactive?: { title?: string; kind?: string; recorded?: boolean; heard?: boolean; audio?: boolean } | null;
  /** Charts she put on her stage for this answer, built from her own lookups. */
  scenes?: Scene[];
  /** Her reply ends by offering to do something ("Shall I pull a breakdown by city?"): answerable Yes / No. */
  offer?: { question: string } | null;
  brain?: { turn: string | null; emotion: string | null; move: string | null; tone: string | null; turn_confidence: number | null; move_confidence: number | null; latency_ms: number | null } | null;
}

export interface ConversationSummary {
  id: string;
  title: string;
  last_at: string;
  messages: number;
  calls: number;
}

export interface ChatSession {
  id: string;
  workspace_id: string;
  title?: string | null;
  status: "idle" | "running";
  messages: ChatMessage[];
  error: string | null;
}

export const getCompanion = (workspaceId: string): Promise<CompanionState> => fetchApi(`/companion/state?workspace_id=${workspaceId}`);

export const pulseNow = (workspaceId: string) => fetchApi(`/companion/pulse?workspace_id=${workspaceId}`, { method: "POST" });

export const updateCompanion = (workspaceId: string, body: { enabled?: boolean; interval_seconds?: number; tz_offset_minutes?: number }) =>
  fetchApi(`/companion/settings?workspace_id=${workspaceId}`, { method: "PATCH", body: JSON.stringify(body) });

export const newChat = (workspaceId: string): Promise<ChatSession> =>
  fetchApi(`/companion/chat`, { method: "POST", body: JSON.stringify({ workspace_id: workspaceId }) });

export const getChat = (id: string): Promise<ChatSession> => fetchApi(`/companion/chat/${id}`);

export const latestChat = (workspaceId: string): Promise<ChatSession> => fetchApi(`/companion/chat/latest?workspace_id=${workspaceId}`);

export const listChats = (workspaceId: string): Promise<{ conversations: ConversationSummary[] }> =>
  fetchApi(`/companion/chats?workspace_id=${workspaceId}`);

export const logCall = (id: string, event: "start" | "end", seconds?: number): Promise<ChatSession> =>
  fetchApi(`/companion/chat/${id}/calls`, { method: "POST", body: JSON.stringify({ event, seconds }) });

export const markInterrupted = (id: string, messageId: string, heard: string): Promise<ChatSession> =>
  fetchApi(`/companion/chat/${id}/messages/${messageId}/interrupted`, { method: "POST", body: JSON.stringify({ heard }) });

export const say = (
  id: string,
  text: string,
  voice = false,
  cut?: { heard: string },
  speculation?: string | null,
  pointing?: Pointing | null,
  answering?: { message_id: string; answer: "yes" | "no" } | null
): Promise<ChatSession> =>
  fetchApi(`/companion/chat/${id}/messages`, {
    method: "POST",
    body: JSON.stringify({
      text,
      voice,
      interrupt: !!cut,
      heard: cut?.heard ?? "",
      speculation: speculation || undefined,
      pointing: pointing || undefined,
      answering: answering || undefined,
    }),
  });

/** The owner paused and has likely finished: start on their turn now (hidden until confirmed by `say`). */
export const speculate = (id: string, text: string): Promise<{ id: string }> =>
  fetchApi(`/companion/chat/${id}/speculation`, { method: "POST", body: JSON.stringify({ text, voice: true }) });

/** They carried on talking: forget the speculative turn. */
export const dropSpeculation = (id: string): Promise<unknown> =>
  fetch(`${API_BASE}/companion/chat/${id}/speculation`, { method: "DELETE" });

// ── Jenny speaks first ────────────────────────────────────────────────

export interface Raise {
  id: string;
  kind: string;
  title: string;
  importance: number;
  at: string;
}

/** What she'd bring up herself now. `onCall`: a call is open, so she says it live rather than leaving a voice note. */
export const getRaises = (workspaceId: string, onCall = false): Promise<{ raises: Raise[] }> =>
  fetchApi(`/companion/raises?workspace_id=${workspaceId}&on_call=${onCall}`);

export const raiseMoment = (id: string, noteId: string, voice = true): Promise<ChatSession> =>
  fetchApi(`/companion/chat/${id}/raise`, { method: "POST", body: JSON.stringify({ note_id: noteId, voice }) });

export interface Welcome {
  text: string | null;
  /** The moments it mentions: marked as told once she has said it. */
  notes: string[];
}

/** How a call opens: what changed since you were last here (null text: use the screen's own greeting). */
export const getWelcome = (workspaceId: string): Promise<Welcome> => fetchApi(`/companion/welcome?workspace_id=${workspaceId}`);

// Wording it takes a few seconds, so the screen asks ahead (when the companion opens) and a call that starts soon
// after uses that answer instead of waiting.
const WELCOME_FRESH_MS = 3 * 60_000;
let welcomeAhead: { workspaceId: string; at: number; promise: Promise<Welcome | null> } | null = null;

export function prepareWelcome(workspaceId: string): Promise<Welcome | null> {
  const w = welcomeAhead;
  if (w && w.workspaceId === workspaceId && Date.now() - w.at < WELCOME_FRESH_MS) return w.promise;
  const promise = getWelcome(workspaceId).catch(() => null);
  welcomeAhead = { workspaceId, at: Date.now(), promise };
  return promise;
}

/** The welcome is being said: use it once (the next call asks afresh). */
export function takeWelcome(workspaceId: string): Promise<Welcome | null> {
  const p = prepareWelcome(workspaceId);
  welcomeAhead = null;
  return p;
}

export const markSeen = (ids: string[]) =>
  ids.length ? fetchApi(`/companion/notes/seen`, { method: "POST", body: JSON.stringify({ ids }) }) : Promise.resolve();

// ── Jenny's desk: what she has committed to keep an eye on ────────────

export interface DeskItem {
  id: string;
  type: "watch" | "check";
  title: string;
  status: "open" | "running" | "tripped" | "done" | "expired" | "cancelled";
  line: string;
  until?: string | null;
  at?: string | null;
  last?: { at: string; value?: number; display?: string; error?: string } | null;
  origin?: { question?: string } | null;
  outcome?: string | null;
  created_at: string;
  /** A watch's day: over the line right now, each crossing, and today's readings ("HH:MM", value). */
  state?: "clear" | "crossed" | null;
  spec?: { condition: "above" | "below"; threshold: number; metric: string } | null;
  episodes?: { from: string; to: string | null; peak_d?: string; peak_at?: string; told?: boolean }[];
  readings?: [string, number][];
  summaries?: { day: string; text: string }[];
}

export const getDesk = (workspaceId: string): Promise<{ items: DeskItem[]; standing: string[] }> =>
  fetchApi(`/companion/desk?workspace_id=${workspaceId}`);

export const dropDeskItem = (workspaceId: string, id: string) =>
  fetchApi(`/companion/desk/${id}?workspace_id=${workspaceId}`, { method: "DELETE" });

export interface VoiceNote {
  id: string;
  conversation_id: string;
  workspace_id: string;
  text: string;
  title: string | null;
  kind: string | null;
  audio: boolean;
  at: string;
}

/** The voice notes she left while you were away, not yet played. */
export const getVoiceNotes = (): Promise<{ notes: VoiceNote[] }> => fetchApi(`/companion/voice-notes`);

export const voiceNoteUrl = (id: string) => `${API_BASE}/companion/voice-notes/${id}/audio`;

export const voiceNoteHeard = (id: string) => fetchApi(`/companion/voice-notes/${id}/heard`, { method: "POST" });

/** Tone cues Jenny puts in spoken answers ([upbeat], [concerned]…): for the voice, never for reading. */
export const TONE_TAG = /\[(warm|upbeat|concerned|thoughtful|reassuring|curious|excited|calm|happy|serious|sad)\]\s*/gi;
export const withoutTones = (text: string) => text.replace(TONE_TAG, "");

export function offsetLabel(min: number | null): string {
  if (min === null) return "";
  const sign = min >= 0 ? "+" : "−";
  const a = Math.abs(min);
  return `UTC${sign}${Math.floor(a / 60)}${a % 60 ? `:${String(a % 60).padStart(2, "0")}` : ""}`;
}

// ── Jenny's voice: open-source text to speech beside Kairos (Kokoro) ──

export const voiceInfo = (): Promise<{ available: boolean; voice: string; engine: string }> => fetchApi(`/companion/voice`);

/** One phrase as audio. The tone cue sets its pace; `previous` (the sentence before) lets the intonation flow on. */
export async function voiceAudio(text: string, tone?: string, signal?: AbortSignal, previous?: string): Promise<Blob> {
  const res = await fetch(`${API_BASE}/companion/voice/speak`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, tone, previous: previous || undefined }),
    signal,
  });
  if (!res.ok) throw new Error(`voice ${res.status}`);
  return res.blob();
}

/** One phrase as a URL an audio element plays while it's still being made (the first audio in about a third of a
 *  second instead of after the whole phrase). */
export function voiceStreamUrl(text: string, tone?: string, previous?: string): string {
  const q = new URLSearchParams({ text });
  if (tone) q.set("tone", tone);
  if (previous) q.set("previous", previous.slice(-300));
  return `${API_BASE}/companion/voice/stream?${q}`;
}

// ── Jack: the same business through an ElevenLabs Agent (an experiment beside Jenny) ──

export interface JackSession {
  agent_id: string;
  conversation_token: string;
  dynamic_variables: Record<string, string>;
  llm: string;
  voice: string;
}
export const jackStatus = (): Promise<{ enabled: boolean }> => fetchApi(`/companion/jack/status`);
export const jackSession = (workspaceId: string): Promise<JackSession> =>
  fetchApi(`/companion/jack/session`, { method: "POST", body: JSON.stringify({ workspace_id: workspaceId }) });
/** One of Jack's tools (data products and the live pulse only), run by Kairos for his model. */
export const jackTool = (workspaceId: string, name: string, args: Record<string, unknown>): Promise<{ result: string }> =>
  fetchApi(`/companion/jack/tool`, { method: "POST", body: JSON.stringify({ workspace_id: workspaceId, name, args }) });

/** Have the everyday phrases made ahead of time, so they play instantly. */
export const warmVoice = (phrases: string[]) => fetchApi(`/companion/voice/warm`, { method: "POST", body: JSON.stringify({ phrases }) });

/** Has the owner finished their turn, judged from how they said it (Smart Turn)? `pcm`: their last few seconds,
 *  16 kHz mono 16-bit. */
export async function turnAudio(pcm: Int16Array<ArrayBuffer>): Promise<{ done: number | null; ms: number }> {
  const res = await fetch(`${API_BASE}/companion/turn/audio`, {
    method: "POST",
    headers: { "Content-Type": "application/octet-stream" },
    body: pcm.buffer,
  });
  if (!res.ok) throw new Error(`turn audio ${res.status}`);
  return res.json();
}

/** Has the owner finished their turn? 0–1 from their words so far (Jev), or null when it can't tell. */
export const turnFinished = (text: string, jennyLast = ""): Promise<{ done: number | null; ms: number }> =>
  fetchApi(`/companion/turn/finished`, { method: "POST", body: JSON.stringify({ text, jenny_last: jennyLast }) });
