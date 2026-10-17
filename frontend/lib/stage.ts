// Jenny's stage: the charts she puts beside the conversation, and what's lit up as she talks.
//
// Scenes are built on the server from her own lookups (kairos_kb/companion/scenes.py) and arrive on her messages.
// One small store is shared by the chat (which brings the scenes in), the call (which reports what she's saying,
// and how far into the line) and the stage (which draws them): the name she says lights up as she says it.

import { useSyncExternalStore } from "react";

export type SceneKind = "breakdown" | "deviation" | "share" | "series" | "heatmap" | "scatter" | "trend" | "hours" | "number" | "compare";

export interface SceneEntity {
  key: string;
  label: string;
  aliases: string[];
}

export interface BarRow {
  key: string;
  label: string;
  value: number;
  display?: string | null;
  usual?: number | null;
  usual_display?: string | null;
  change_pct?: number | null;
  volume?: number | null;
  volume_display?: string | null;
  extra_display?: string | null;
  low_volume?: boolean;
  // deviation: percent above (+) or below (−) its usual
  pct?: number | null;
  // hours
  hour?: number;
  low?: number | null;
  high?: number | null;
  gap_display?: string | null;
  partial?: boolean;
}

export interface Scene {
  id: string;
  kind: SceneKind;
  title: string;
  subtitle: string;
  metric_label?: string;
  data: {
    rows?: BarRow[];
    rate?: boolean;
    dimension?: string;
    // trend: [hour, median, p10, p90] and [hour, value]
    typical?: [number, number, number, number][];
    today?: [number, number][];
    cumulative?: boolean;
    actual_display?: string;
    expected_display?: string;
    as_of?: string;
    status?: "above" | "below" | "normal";
    // number
    value?: number;
    display?: string;
    usual?: number;
    usual_display?: string;
    low_display?: string;
    high_display?: string;
    dev_pct?: number | null;
    projection_display?: string | null;
    // compare
    items?: { key: string; label: string; value: number; display: string; usual_display?: string; status?: string }[];
    // series: a line per category over days (a panel per metric)
    x?: string[];
    x_labels?: string[];
    panels?: { metric_label: string; lines: { key: string; label: string; values: (number | null)[] }[] }[];
    hourly?: boolean;
    // heatmap: rows × cols, a value (or nothing recorded) per cell
    cols?: { key: string; label: string }[];
    cells?: (number | null)[][];
    min?: number;
    max?: number;
    metric?: string;
    // scatter: two measures per slice
    x_label?: string;
    y_label?: string;
    points?: { key: string; label: string; x: number; y: number }[];
    // share: parts of a whole
    parts?: { key: string; label: string; value: number; share: number }[];
    total?: number;
  };
  entities: SceneEntity[];
  focus: string[];
  annotations: { key: string | null; text: string }[];
  source?: { tool?: string; lookup_id?: string; args?: Record<string, unknown> };
  auto?: boolean;
}

/** What the owner is pointing at on the stage: "this one" in their next words. */
export interface Pointing {
  scene_id: string;
  key: string;
  label: string;
  title: string;
}

// ── linking what she says to what's on screen ──────────────────────────

const norm = (t: string) =>
  ` ${t
    .toLowerCase()
    .replace(/\[[a-z]+\]/g, " ")
    .replace(/[’‘]/g, "'")
    .replace(/[^a-z0-9.:'\- ]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()} `;

/** Where each entity is first named in the text (by its label or any way it's said), in order of mention. */
export function mentions(text: string, entities: SceneEntity[]): { key: string; at: number }[] {
  const t = norm(text);
  const found: { key: string; at: number }[] = [];
  for (const e of entities) {
    let best = -1;
    for (const a of [e.label, ...(e.aliases ?? [])]) {
      const n = norm(a).trim();
      if (!n) continue;
      // whole words only: "Pune" isn't found in "Punekar", "9 am" isn't "19 am"
      const re = new RegExp(`(?<![a-z0-9])${n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?![a-z0-9])`);
      const m = re.exec(t);
      if (m && (best < 0 || m.index < best)) best = m.index;
    }
    if (best >= 0) found.push({ key: e.key, at: Math.max(0, best - 1) / Math.max(1, t.length - 2) });
  }
  return found.sort((a, b) => a.at - b.at);
}

/** What's lit up at this point in a spoken line (0–1): everything she has named so far in it; null when the line
 *  names nothing on screen (the focus then stays as it was). */
export function focusAt(text: string, progress: number, entities: SceneEntity[]): string[] | null {
  const all = mentions(text, entities);
  if (!all.length) return null;
  const said = all.filter((m) => m.at <= progress + 0.02).map((m) => m.key);
  return said.length ? said : null;
}

// ── the shared stage ───────────────────────────────────────────────────

export interface StageState {
  conversationId: string | null;
  scenes: Scene[];
  currentId: string | null;
  /** What's lit right now: from her words as she says them, else the scene's own focus. */
  focus: string[] | null;
  pointing: Pointing | null;
  /** Bumped each time something new goes on stage, so the page can bring the stage forward. */
  reveal: number;
}

let state: StageState = { conversationId: null, scenes: [], currentId: null, focus: null, pointing: null, reveal: 0 };
const listeners = new Set<() => void>();
const set = (patch: Partial<StageState>) => {
  state = { ...state, ...patch };
  listeners.forEach((l) => l());
};

export const stage = {
  get: () => state,
  subscribe(fn: () => void) {
    listeners.add(fn);
    return () => listeners.delete(fn);
  },
  /** The conversation's messages, as they stream: any new scene goes on stage. */
  sync(conversationId: string, scenesInOrder: Scene[]) {
    if (conversationId !== state.conversationId) {
      const last = scenesInOrder[scenesInOrder.length - 1];
      set({ conversationId, scenes: scenesInOrder, currentId: last?.id ?? null, focus: null, pointing: null });
      return;
    }
    const known = new Set(state.scenes.map((s) => s.id));
    const fresh = scenesInOrder.filter((s) => !known.has(s.id));
    if (!fresh.length) return;
    const now = fresh[fresh.length - 1];
    set({ scenes: scenesInOrder, currentId: now.id, focus: now.focus.length ? now.focus : null, reveal: state.reveal + 1 });
  },
  show(id: string) {
    const s = state.scenes.find((x) => x.id === id);
    if (s) set({ currentId: id, focus: s.focus.length ? s.focus : null, reveal: state.reveal + 1 });
  },
  /** She's saying `text`, this far through it (0–1): light up what she has named. */
  speech(text: string, progress: number) {
    const s = current();
    if (!s) return;
    const f = focusAt(text, progress, s.entities);
    if (f && f.join("|") !== (state.focus ?? []).join("|")) set({ focus: f });
  },
  /** A whole written answer: light up what it names (at most three). */
  read(text: string) {
    const s = current();
    if (!s || s.focus.length) return;
    const f = mentions(text, s.entities).slice(0, 3).map((m) => m.key);
    if (f.length) set({ focus: f });
  },
  point(p: Pointing | null) {
    set({ pointing: p, focus: p ? [p.key] : state.focus });
  },
  /** The pointing, once: it goes with the owner's next words. */
  takePointing(): Pointing | null {
    const p = state.pointing;
    if (p) set({ pointing: null });
    return p;
  },
};

function current(): Scene | undefined {
  return state.scenes.find((s) => s.id === state.currentId);
}

export function useStage(): StageState {
  return useSyncExternalStore(stage.subscribe, stage.get, stage.get);
}

/** All scenes of a conversation's messages, in order. */
export function scenesOf(messages: { scenes?: Scene[] }[]): Scene[] {
  return messages.flatMap((m) => m.scenes ?? []);
}
