// Connections kept off the screens (for a demo, say), by name: NEXT_PUBLIC_HIDDEN_CONNECTIONS, comma-separated —
// "ICS Sales Warehouse" unless set (set it empty to show everything). Nothing is deleted: Kairos keeps them and agents
// still reach them; the screens just don't show them. Applied to every API response in one place (fetchApi), so no
// screen has to remember.
//
// What a hidden connection looks like in a response:
//   its workspace     { id: <uuid>, name: "ICS Sales Warehouse" }, or workspace_id: <uuid> on anything it owns
//   its entities      "table:ICS Sales Warehouse:cat.schema.t"   (entity_id, id)
//   its mesh bundles  "table.ics_sales_warehouse.cat.schema.t"   (unique_id)
//   its agent channel "mcp:ics-sales-warehouse"

import { API_BASE } from "@/lib/api";

const HIDDEN = (process.env.NEXT_PUBLIC_HIDDEN_CONNECTIONS ?? "ICS Sales Warehouse")
  .split(",")
  .map((s) => s.trim().toLowerCase())
  .filter(Boolean);
const slug = (s: string, sep: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, sep).replace(new RegExp(`^${sep}|${sep}$`, "g"), "");
const SLUGS = new Set(HIDDEN.map((n) => slug(n, "_")));
const CHANNELS = new Set(HIDDEN.map((n) => `mcp:${slug(n, "-")}`));

export const hiding = HIDDEN.length > 0;

export const hiddenName = (name: unknown): boolean => typeof name === "string" && HIDDEN.includes(name.trim().toLowerCase());

/** An entity or bundle id that belongs to a hidden connection. */
export function hiddenEntity(id: unknown): boolean {
  if (!hiding || typeof id !== "string") return false;
  const byName = id.split(":");
  if (byName.length >= 2 && hiddenName(byName[1])) return true;
  const bySlug = id.split(".");
  return bySlug.length >= 2 && SLUGS.has(bySlug[1]);
}

export const hiddenChannel = (channel: unknown): boolean => typeof channel === "string" && CHANNELS.has(channel);

// The hidden connections' workspace ids, learned from /workspaces (fetched once when a screen hasn't yet).
const hiddenIds = new Set<string>();
const visibleIds: string[] = [];
let known: Promise<void> | null = null;

function learn(workspaces: { id: string; name: string }[]): void {
  hiddenIds.clear();
  visibleIds.length = 0;
  for (const w of workspaces) {
    if (hiddenName(w.name)) hiddenIds.add(w.id);
    else visibleIds.push(w.id);
  }
}

function ensureKnown(): Promise<void> {
  known ??= fetch(`${API_BASE}/workspaces`)
    .then((r) => (r.ok ? r.json() : []))
    .then((ws) => learn(Array.isArray(ws) ? ws : []))
    .catch(() => {
      known = null; // try again next time
    });
  return known;
}

type Row = Record<string, unknown>;

function hiddenRow(r: unknown): boolean {
  if (!r || typeof r !== "object") return false;
  const o = r as Row;
  return (
    hiddenEntity(o.entity_id) ||
    hiddenEntity(o.id) ||
    hiddenEntity(o.unique_id) ||
    (typeof o.workspace_id === "string" && hiddenIds.has(o.workspace_id)) ||
    (typeof o.id === "string" && hiddenIds.has(o.id)) ||
    hiddenName(o.name) ||
    hiddenName(o.label) ||
    hiddenChannel(o.channel) ||
    (Array.isArray(o.entity_ids) && o.entity_ids.some(hiddenEntity))
  );
}

/** A list without the hidden connections' rows; an object with each of its lists filtered the same way. */
function dropHidden<T>(data: T): T {
  if (Array.isArray(data)) return data.filter((r) => !hiddenRow(r)) as T;
  if (!data || typeof data !== "object") return data;
  const out: Row = { ...(data as Row) };
  for (const [k, v] of Object.entries(out)) {
    if (Array.isArray(v) && v.some((x) => x && typeof x === "object")) {
      const kept = v.filter((r) => !hiddenRow(r));
      if (kept.length !== v.length && out.count === v.length) out.count = kept.length;
      out[k] = kept;
    }
  }
  return out as T;
}

/** The mesh without the hidden connections' bundles, and without relationships that touch them. */
function scrubMesh(m: Row): Row {
  const bundles = (m.bundles as Row[]).filter((b) => !hiddenRow(b));
  const kept = new Set(bundles.map((b) => b.unique_id as string));
  const relationships = (m.relationships as Row[]).filter((r) => kept.has(r.source as string) && kept.has(r.target as string));
  const count = (rows: Row[], key: string) =>
    rows.reduce<Record<string, number>>((acc, r) => ((acc[r[key] as string] = (acc[r[key] as string] ?? 0) + 1), acc), {});
  const stats = (m.stats ?? {}) as Row;
  const folded = (key: string) => bundles.reduce((n, b) => n + (((b.inherited ?? {}) as Row)[key] as number ?? 0), 0);
  return {
    ...m,
    workspaces: (m.workspaces as Row[]).filter((w) => !hiddenRow(w)),
    bundles,
    relationships,
    stats: {
      ...stats,
      bundles: count(bundles, "resource_type"),
      relationships: count(relationships, "group"),
      inherited: { columns: folded("columns"), runs: folded("runs"), task_runs: folded("task_runs") },
    },
  };
}

/** Agent stats without the hidden connections' own channel (its calls and errors taken out of the totals). */
function scrubStats(s: Row): Row {
  const out: Row = { ...s };
  const byChannel = (s.by_channel ?? {}) as Record<string, { calls?: number; errors?: number }>;
  let calls = (s.calls as number) ?? 0;
  let errors = (s.errors as number) ?? 0;
  const kept: Record<string, unknown> = {};
  for (const [ch, v] of Object.entries(byChannel)) {
    if (hiddenChannel(ch)) {
      calls -= v.calls ?? 0;
      errors -= v.errors ?? 0;
    } else kept[ch] = v;
  }
  out.by_channel = kept;
  out.calls = Math.max(0, calls);
  out.errors = Math.max(0, errors);
  out.error_rate = calls > 0 ? errors / calls : 0;
  if (Array.isArray(s.most_requested)) out.most_requested = s.most_requested.filter((r) => !hiddenRow(r));
  return out;
}

// Endpoints that only return totals: asked for the visible connections only.
const SCOPED = ["/warehouse/map", "/enrichment/discovered"];

/** The endpoint as it should be asked (totals scoped to the visible connections). */
export async function prepare(endpoint: string, method: string): Promise<string> {
  const path = endpoint.split("?")[0];
  if (!hiding || method !== "GET" || !SCOPED.includes(path) || endpoint.includes("workspace_id=")) return endpoint;
  await ensureKnown();
  if (!hiddenIds.size || !visibleIds.length) return endpoint;
  const q = visibleIds.map((id) => `workspace_id=${encodeURIComponent(id)}`).join("&");
  return `${endpoint}${endpoint.includes("?") ? "&" : "?"}${q}`;
}

/** A response as the screens should see it: the hidden connections taken out. */
export async function scrub<T>(endpoint: string, method: string, data: T): Promise<T> {
  if (!hiding || method !== "GET" || data == null || typeof data !== "object") return data;
  const path = endpoint.split("?")[0];
  if (path === "/workspaces" && Array.isArray(data)) {
    learn(data as { id: string; name: string }[]);
    known ??= Promise.resolve();
  } else {
    await ensureKnown();
  }
  if (path === "/mesh") return scrubMesh(data as Row) as T;
  if (path === "/agents/stats") return scrubStats(data as Row) as T;
  return dropHidden(data);
}
