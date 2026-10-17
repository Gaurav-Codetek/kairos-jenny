import ELK from "elkjs/lib/elk.bundled.js";

import { fetchApi } from "@/lib/api";

/** Bundle kinds, in the order they nest. */
export type ResourceType = "catalog" | "schema" | "table" | "volume" | "pipeline" | "task" | "product";

/** containment/pipeline: what holds what. flow/storage/depends_on: how data and work move. */
export type RelationshipGroup = "containment" | "pipeline" | "depends_on" | "flow" | "storage";

export interface Bundle {
  unique_id: string;
  resource_type: ResourceType;
  name: string;
  fqn: string[];
  entity_id: string | null;
  parent: string | null;
  children: Partial<Record<ResourceType, number>>;
  /** Sub-grains folded into this bundle: columns, runs, task runs, volume paths. */
  inherited: {
    columns?: number;
    runs?: number;
    task_runs?: number;
    failed_runs?: number;
    by_result?: Record<string, number>;
    recent?: { run_id: string; result: string | null; start_time: string | null; duration_ms: number | null }[];
    paths?: number;
    // data products
    metrics?: number;
    inputs?: number;
    sample?: string[];
  };
  status?: string | null;
  description?: string | null;
  table_type?: string;
  format?: string | null;
  task_type?: string;
  notebook_path?: string | null;
  path?: string;
  schedule?: string | null;
}

export interface Relationship {
  relationship_id: string;
  group: RelationshipGroup;
  source: string;
  target: string;
  types: string[];
  origins: string[];
  confidence: number | null;
}

export interface Mesh {
  workspaces: { id: string; name: string; slug: string }[];
  bundles: Bundle[];
  relationships: Relationship[];
  stats: {
    bundles: Record<string, number>;
    relationships: Record<string, number>;
    inherited: { columns: number; runs: number; task_runs: number };
  };
}

export function fetchMesh(): Promise<Mesh> {
  return fetchApi("/mesh");
}

export const FAILED = new Set(["FAILED", "TIMEDOUT", "INTERNAL_ERROR", "UPSTREAM_FAILED"]);

// ── Visible mesh: expansion + roll-up ────────────────────────────────

export interface VisibleEdge {
  id: string;
  source: string;
  target: string;
  group: RelationshipGroup;
  /** How many underlying relationships this edge stands for. */
  count: number;
  /** True when at least one endpoint is a collapsed bundle standing in for a child. */
  rolledUp: boolean;
  types: string[];
}

export class MeshIndex {
  readonly byId: Map<string, Bundle>;
  readonly childrenOf: Map<string, string[]>;

  constructor(readonly mesh: Mesh) {
    this.byId = new Map(mesh.bundles.map((b) => [b.unique_id, b]));
    this.childrenOf = new Map();
    for (const b of mesh.bundles) {
      if (b.parent && this.byId.has(b.parent)) {
        const list = this.childrenOf.get(b.parent) ?? [];
        list.push(b.unique_id);
        this.childrenOf.set(b.parent, list);
      }
    }
  }

  /** Bundles with no (known) parent: catalogs, pipelines, and any orphans. */
  roots(): string[] {
    return this.mesh.bundles
      .filter((b) => !b.parent || !this.byId.has(b.parent))
      .map((b) => b.unique_id);
  }

  ancestors(uid: string): string[] {
    const out: string[] = [];
    let current = this.byId.get(uid)?.parent;
    while (current && this.byId.has(current)) {
      out.push(current);
      current = this.byId.get(current)!.parent;
    }
    return out;
  }

  visibleSet(expanded: Set<string>): Set<string> {
    const visible = new Set<string>();
    const stack = this.roots();
    while (stack.length) {
      const uid = stack.pop()!;
      visible.add(uid);
      if (expanded.has(uid)) stack.push(...(this.childrenOf.get(uid) ?? []));
    }
    return visible;
  }

  /** The nearest bundle that is on screen — itself, or the collapsed ancestor holding it. */
  visibleFor(uid: string, visible: Set<string>): string | null {
    if (visible.has(uid)) return uid;
    for (const a of this.ancestors(uid)) if (visible.has(a)) return a;
    return null;
  }

  /**
   * Edges between visible bundles. Containment is drawn only between two
   * visible bundles; flow rolls up to the nearest visible ancestor so a
   * collapsed catalog still shows which pipelines read from and write to it.
   * Flow attached directly to an EXPANDED bundle is dropped: its children
   * now carry that detail, and drawing both is exactly the clutter to avoid.
   */
  visibleEdges(visible: Set<string>, expanded: Set<string>): VisibleEdge[] {
    const merged = new Map<string, VisibleEdge>();
    for (const r of this.mesh.relationships) {
      const structural = r.group === "containment" || r.group === "pipeline";
      if (structural) {
        if (!visible.has(r.source) || !visible.has(r.target)) continue;
      } else if (expanded.has(r.source) || expanded.has(r.target)) {
        continue;
      }
      const s = this.visibleFor(r.source, visible);
      const t = this.visibleFor(r.target, visible);
      if (!s || !t || s === t) continue;
      // An edge between a bundle and its own ancestor is internal to it.
      if (!structural && (this.ancestors(s).includes(t) || this.ancestors(t).includes(s))) continue;

      const key = `${r.group}|${s}|${t}`;
      const existing = merged.get(key);
      const rolledUp = s !== r.source || t !== r.target;
      if (existing) {
        existing.count += 1;
        existing.rolledUp ||= rolledUp;
        for (const ty of r.types) if (!existing.types.includes(ty)) existing.types.push(ty);
      } else {
        merged.set(key, {
          id: rolledUp ? `roll:${key}` : r.relationship_id,
          source: s,
          target: t,
          group: r.group,
          count: 1,
          rolledUp,
          types: [...r.types],
        });
      }
    }
    return Array.from(merged.values());
  }

  search(needle: string, limit = 12): Bundle[] {
    const q = needle.trim().toLowerCase();
    if (q.length < 2) return [];
    const scored: { b: Bundle; score: number }[] = [];
    for (const b of this.mesh.bundles) {
      const name = b.name.toLowerCase();
      const fqn = b.fqn.join(".").toLowerCase();
      const score = name === q ? 0 : name.startsWith(q) ? 1 : name.includes(q) ? 2 : fqn.includes(q) ? 3 : -1;
      if (score >= 0) scored.push({ b, score });
    }
    return scored.sort((a, b) => a.score - b.score || a.b.name.length - b.b.name.length).slice(0, limit).map((x) => x.b);
  }
}

// ── Scene: what is drawn ─────────────────────────────────────────────
//
// dbt's model: the canvas is a flat, left → right graph of how data moves.
// Kairos's flow alternates table → task → table, so nesting tables in catalog
// boxes and tasks in pipeline boxes would force every edge across a box
// boundary. Instead, containment is shown on each card (its open parent as a
// chip) and in the sidebar tree.
//
// Opening a bundle replaces its card with those of its children that carry
// lineage; the rest are listed in the sidebar.

export const LEAF_WIDTH = 236;
export const LEAF_HEIGHT = 58;

const STRUCTURAL = new Set<RelationshipGroup>(["containment", "pipeline"]);

export interface SceneNode {
  id: string;
  bundle: Bundle;
  /** The open bundle this card was revealed from (shown as a chip that closes it). */
  openParent: Bundle | null;
}

export interface Scene {
  nodes: SceneNode[];
  edges: VisibleEdge[];
}

export function buildScene(index: MeshIndex, expanded: Set<string>, pinned: Set<string> = new Set()): Scene {
  const visible = index.visibleSet(expanded);
  const edges = index.visibleEdges(visible, expanded).filter((e) => !STRUCTURAL.has(e.group));
  const busy = new Set<string>();
  edges.forEach((e) => {
    busy.add(e.source);
    busy.add(e.target);
  });

  const nodes: SceneNode[] = [];
  for (const id of visible) {
    if (expanded.has(id)) continue; // an open bundle is shown through its children
    if (!busy.has(id) && !pinned.has(id)) continue; // no lineage: the sidebar lists it
    const bundle = index.byId.get(id)!;
    const parent = bundle.parent ? index.byId.get(bundle.parent) ?? null : null;
    nodes.push({ id, bundle, openParent: parent && expanded.has(parent.unique_id) ? parent : null });
  }
  const drawn = new Set(nodes.map((n) => n.id));
  return { nodes, edges: edges.filter((e) => drawn.has(e.source) && drawn.has(e.target)) };
}

/**
 * Bundles that data flows into or out of. Task order alone is not lineage:
 * every pipeline has it, and counting it would call every pipeline "lineage".
 */
export function dataFlowBundles(index: MeshIndex): Set<string> {
  const out = new Set<string>();
  for (const r of index.mesh.relationships) {
    if (r.group !== "flow" && r.group !== "storage") continue;
    out.add(r.source);
    out.add(r.target);
  }
  return out;
}

/**
 * What to open on first load: every bundle holding lineage, so the user lands
 * on the actual flow rather than a handful of top-level cards. Stays at the
 * top level when there is too much lineage to show at once.
 */
export function defaultExpanded(index: MeshIndex, maxBundles = 80): Set<string> {
  const involved = dataFlowBundles(index);
  if (involved.size === 0 || involved.size > maxBundles) return new Set();
  const open = new Set<string>();
  involved.forEach((id) => index.ancestors(id).forEach((a) => open.add(a)));
  return open;
}

// ── Layout (ELK layered, left → right, with routed edges) ────────────
//
// ELK does two jobs React Flow cannot: it places cards in layers, and it
// routes every edge through the gaps between layers — a long edge travels in
// its own lane instead of cutting across the cards it skips. Edges into the
// same card are merged into one trunk, which keeps wide fan-ins tidy.

export interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface Point {
  x: number;
  y: number;
}

export interface MeshLayoutResult {
  boxes: Map<string, Box>;
  /** Edge id → the polyline ELK routed for it (start, bends, end). */
  routes: Map<string, Point[]>;
}

const elk = new ELK();

const LAYOUT: Record<string, string> = {
  "elk.algorithm": "layered",
  "elk.direction": "RIGHT",
  "elk.edgeRouting": "ORTHOGONAL",
  "elk.layered.mergeEdges": "true",
  "elk.layered.spacing.nodeNodeBetweenLayers": "96",
  "elk.layered.spacing.edgeNodeBetweenLayers": "28",
  "elk.layered.spacing.edgeEdgeBetweenLayers": "10",
  "elk.spacing.nodeNode": "22",
  "elk.spacing.edgeNode": "18",
  "elk.spacing.edgeEdge": "10",
  "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
  "elk.layered.crossingMinimization.strategy": "LAYER_SWEEP",
  "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
  "elk.separateConnectedComponents": "true",
  "elk.spacing.componentComponent": "64",
};

interface ElkEdgeOut {
  id: string;
  sections?: { startPoint: Point; endPoint: Point; bendPoints?: Point[] }[];
}

export async function layoutScene(scene: Scene): Promise<MeshLayoutResult> {
  // Stable input order → stable layout between small changes.
  const nodes = [...scene.nodes].sort((a, b) => a.id.localeCompare(b.id));
  const graph = {
    id: "root",
    layoutOptions: LAYOUT,
    children: nodes.map((n) => ({ id: n.id, width: LEAF_WIDTH, height: LEAF_HEIGHT })),
    edges: scene.edges.map((e) => ({ id: e.id, sources: [e.source], targets: [e.target] })),
  };
  const laid = (await elk.layout(graph)) as {
    children?: { id: string; x?: number; y?: number }[];
    edges?: ElkEdgeOut[];
  };

  const boxes = new Map<string, Box>();
  for (const n of laid.children ?? []) {
    boxes.set(n.id, { x: n.x ?? 0, y: n.y ?? 0, width: LEAF_WIDTH, height: LEAF_HEIGHT });
  }
  const routes = new Map<string, Point[]>();
  for (const e of laid.edges ?? []) {
    const points: Point[] = [];
    for (const s of e.sections ?? []) {
      if (!points.length) points.push(s.startPoint);
      points.push(...(s.bendPoints ?? []), s.endPoint);
    }
    if (points.length >= 2) routes.set(e.id, points);
  }
  return { boxes, routes };
}

/** An orthogonal polyline as an SVG path with rounded corners. */
export function roundedPath(points: Point[], radius = 10): string {
  if (points.length < 2) return "";
  let d = `M ${points[0].x} ${points[0].y}`;
  for (let i = 1; i < points.length - 1; i++) {
    const prev = points[i - 1];
    const cur = points[i];
    const next = points[i + 1];
    const inLen = Math.hypot(cur.x - prev.x, cur.y - prev.y);
    const outLen = Math.hypot(next.x - cur.x, next.y - cur.y);
    const r = Math.min(radius, inLen / 2, outLen / 2);
    if (r < 0.5) {
      d += ` L ${cur.x} ${cur.y}`;
      continue;
    }
    const a = { x: cur.x - ((cur.x - prev.x) / inLen) * r, y: cur.y - ((cur.y - prev.y) / inLen) * r };
    const b = { x: cur.x + ((next.x - cur.x) / outLen) * r, y: cur.y + ((next.y - cur.y) / outLen) * r };
    d += ` L ${a.x} ${a.y} Q ${cur.x} ${cur.y} ${b.x} ${b.y}`;
  }
  const last = points[points.length - 1];
  return `${d} L ${last.x} ${last.y}`;
}

/** Where to put a count label: the middle of the route's longest segment. */
export function labelPoint(points: Point[]): Point {
  let best = { x: points[0].x, y: points[0].y };
  let bestLen = -1;
  for (let i = 1; i < points.length; i++) {
    const len = Math.hypot(points[i].x - points[i - 1].x, points[i].y - points[i - 1].y);
    if (len > bestLen) {
      bestLen = len;
      best = { x: (points[i].x + points[i - 1].x) / 2, y: (points[i].y + points[i - 1].y) / 2 };
    }
  }
  return best;
}

/** One-line summary of what a bundle inherits and holds. */
export function bundleSummary(b: Bundle): string {
  const parts: string[] = [];
  const c = b.children;
  const n = (count: number | undefined, word: string) =>
    count ? `${count} ${word}${count === 1 ? "" : "s"}` : null;
  switch (b.resource_type) {
    case "catalog":
      parts.push(n(c.schema, "schema") ?? "no schemas");
      break;
    case "schema":
      parts.push(n(c.table, "table") ?? "no tables");
      if (c.volume) parts.push(n(c.volume, "volume")!);
      break;
    case "table":
      parts.push(n(b.inherited.columns, "col") ?? "no columns");
      if (b.format) parts.push(b.format);
      break;
    case "volume":
      parts.push(n(b.inherited.paths, "path") ?? "no paths seen");
      break;
    case "pipeline":
      parts.push(n(c.task, "task") ?? "no tasks");
      parts.push(n(b.inherited.runs, "run") ?? "no runs");
      break;
    case "product":
      parts.push(n(b.inherited.metrics, "metric") ?? "no metrics");
      parts.push(n(b.inherited.inputs, "input") ?? "no inputs");
      break;
    case "task":
      parts.push(n(b.inherited.task_runs, "run") ?? "no runs");
      if (b.task_type) parts.push(b.task_type.replace(/_task$/, ""));
      break;
  }
  return parts.join(" · ");
}
