import dagre from "dagre";
import { fetchApi } from "@/lib/api";

// ── Types mirroring /api/v1/warehouse ────────────────────────────────

/** Kinds the connector syncs. The agent can mint others at runtime. */
export type SyncedKind =
  | "workspace"
  | "catalog"
  | "schema"
  | "table"
  | "column"
  | "job"
  | "task"
  | "run"
  | "taskrun"
  | "evidence"
  | "change"
  | "syncstate";

/**
 * Open vocabulary: the enrichment agent registers kinds nobody declared —
 * volume, file, notebook, genie_space, external_connection, cluster — so this
 * must stay a string while keeping autocomplete for the known ones.
 */
export type EntityKind = SyncedKind | (string & {});

export type RelationGroup =
  | "structural"
  | "pipeline"
  | "operational"
  | "lineage"
  | "provenance"
  | "discovered";

export const ALL_RELATION_GROUPS: RelationGroup[] = [
  "structural",
  "pipeline",
  "operational",
  "lineage",
  "discovered",
  "provenance",
];

export interface EntityNode {
  id: string;
  kind: EntityKind;
  label: string;
  sublabel: string;
  known: boolean;
  /** True when this node exists only because the enrichment agent found it. */
  discovered?: boolean;
  status?: string | null;
  attrs: Record<string, unknown>;
  depth: number;
  is_root: boolean;
  expandable: boolean;
}

export interface EntityEdge {
  id: string;
  source: string;
  target: string;
  relation: string;
  group: RelationGroup;
}

export interface GraphResponse {
  root: string;
  depth: number;
  relation_groups: RelationGroup[];
  nodes: EntityNode[];
  edges: EntityEdge[];
  truncations: Array<{ node: string; relation: string; shown: number; has_more: boolean }>;
  stats: {
    nodes: number;
    edges: number;
    by_kind: Record<string, number>;
    by_relation: Record<string, number>;
    truncated: boolean;
  };
}

export interface EntityMapDocument {
  kinds: Array<{
    kind: EntityKind;
    label: string;
    table: string;
    grain: string;
    id_format: string;
    natural_entity_id: boolean;
    count: number;
  }>;
  relations: Array<{
    name: string;
    source: string;
    target: string;
    group: RelationGroup;
    via: string;
    description: string;
  }>;
  relation_groups: RelationGroup[];
  default_relation_groups: RelationGroup[];
  id_convention: string;
  totals: {
    entities: number;
    lineage_edges: number;
    table_lineage_edges: number;
    column_lineage_edges: number;
  };
}

export interface WarehouseRoot {
  id: string;
  kind: "workspace";
  label: string;
  host: string;
  status: string;
  last_synced_at: string | null;
  catalogs: number;
  jobs: number;
  failed_runs: number;
}

export interface EntityDetail {
  id: string;
  kind: EntityKind;
  known: boolean;
  attributes: Record<string, unknown>;
  relations: Array<{ relation: string; group: RelationGroup; count: number; sample: string[] }>;
  relation_total: number;
  note?: string;
}

export interface SearchResponse {
  query: string;
  count: number;
  results: Array<{
    id: string;
    kind: EntityKind;
    label: string;
    sublabel: string;
    known: boolean;
    attrs: Record<string, unknown>;
  }>;
}

// ── API ──────────────────────────────────────────────────────────────

export function fetchEntityMap(): Promise<EntityMapDocument> {
  return fetchApi("/warehouse/map");
}

export function fetchRoots(): Promise<{ roots: WarehouseRoot[] }> {
  return fetchApi("/warehouse/roots");
}

export function fetchGraph(
  entityId: string,
  depth: number,
  relationGroups: RelationGroup[],
  limitPerRelation: number
): Promise<GraphResponse> {
  const params = new URLSearchParams({
    entity_id: entityId,
    depth: String(depth),
    relation_groups: relationGroups.join(","),
    limit_per_relation: String(limitPerRelation),
  });
  return fetchApi(`/warehouse/graph?${params.toString()}`);
}

export function fetchEntityDetail(entityId: string): Promise<EntityDetail> {
  return fetchApi(`/warehouse/entity?entity_id=${encodeURIComponent(entityId)}`);
}

export function searchEntities(query: string, limit = 25): Promise<SearchResponse> {
  return fetchApi(`/warehouse/search?q=${encodeURIComponent(query)}&limit=${limit}`);
}

// ── Per-kind presentation ────────────────────────────────────────────

export interface KindStyle {
  border: string;
  chip: string;
  dot: string;
  label: string;
}

export const KIND_STYLE: Record<string, KindStyle> = {
  workspace: {
    border: "border-slate-400/60",
    chip: "bg-slate-400/15 text-slate-200 border-slate-400/30",
    dot: "#94a3b8",
    label: "Workspace",
  },
  catalog: {
    border: "border-amber-500/60",
    chip: "bg-amber-500/15 text-amber-300 border-amber-500/30",
    dot: "#f59e0b",
    label: "Catalog",
  },
  schema: {
    border: "border-orange-500/60",
    chip: "bg-orange-500/15 text-orange-300 border-orange-500/30",
    dot: "#f97316",
    label: "Schema",
  },
  table: {
    border: "border-emerald-500/60",
    chip: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
    dot: "#10b981",
    label: "Table",
  },
  column: {
    border: "border-teal-500/60",
    chip: "bg-teal-500/15 text-teal-300 border-teal-500/30",
    dot: "#14b8a6",
    label: "Column",
  },
  job: {
    border: "border-sky-500/60",
    chip: "bg-sky-500/15 text-sky-300 border-sky-500/30",
    dot: "#0ea5e9",
    label: "Job",
  },
  task: {
    border: "border-indigo-500/60",
    chip: "bg-indigo-500/15 text-indigo-300 border-indigo-500/30",
    dot: "#6366f1",
    label: "Task",
  },
  run: {
    border: "border-violet-500/60",
    chip: "bg-violet-500/15 text-violet-300 border-violet-500/30",
    dot: "#8b5cf6",
    label: "Run",
  },
  taskrun: {
    border: "border-fuchsia-500/60",
    chip: "bg-fuchsia-500/15 text-fuchsia-300 border-fuchsia-500/30",
    dot: "#d946ef",
    label: "TaskRun",
  },
  evidence: {
    border: "border-yellow-500/60",
    chip: "bg-yellow-500/15 text-yellow-300 border-yellow-500/30",
    dot: "#eab308",
    label: "Evidence",
  },
  change: {
    border: "border-pink-500/60",
    chip: "bg-pink-500/15 text-pink-300 border-pink-500/30",
    dot: "#ec4899",
    label: "Change",
  },
  syncstate: {
    border: "border-cyan-500/60",
    chip: "bg-cyan-500/15 text-cyan-300 border-cyan-500/30",
    dot: "#06b6d4",
    label: "SyncState",
  },
};

/** Styling for kinds the agent invents at runtime. */
const DISCOVERED_KIND_STYLE: Record<string, KindStyle> = {
  volume: {
    border: "border-rose-500/60",
    chip: "bg-rose-500/15 text-rose-300 border-rose-500/30",
    dot: "#f43f5e",
    label: "Volume",
  },
  file: {
    border: "border-lime-500/60",
    chip: "bg-lime-500/15 text-lime-300 border-lime-500/30",
    dot: "#84cc16",
    label: "File",
  },
  notebook: {
    border: "border-blue-500/60",
    chip: "bg-blue-500/15 text-blue-300 border-blue-500/30",
    dot: "#3b82f6",
    label: "Notebook",
  },
  cluster: {
    border: "border-orange-400/60",
    chip: "bg-orange-400/15 text-orange-200 border-orange-400/30",
    dot: "#fb923c",
    label: "Cluster",
  },
  genie_space: {
    border: "border-purple-500/60",
    chip: "bg-purple-500/15 text-purple-300 border-purple-500/30",
    dot: "#a855f7",
    label: "Genie Space",
  },
  external_connection: {
    border: "border-red-500/60",
    chip: "bg-red-500/15 text-red-300 border-red-500/30",
    dot: "#ef4444",
    label: "External",
  },
  dashboard: {
    border: "border-pink-500/60",
    chip: "bg-pink-500/15 text-pink-300 border-pink-500/30",
    dot: "#ec4899",
    label: "Dashboard",
  },
};

const UNKNOWN_KIND_STYLE: KindStyle = {
  border: "border-zinc-500/60",
  chip: "bg-zinc-500/15 text-zinc-300 border-zinc-500/30",
  dot: "#a1a1aa",
  label: "Entity",
};

/**
 * Resolve styling for any kind, including ones invented after this file was
 * written — an unrecognised kind gets a neutral style and its raw name.
 */
export function kindStyle(kind: string): KindStyle {
  return (
    KIND_STYLE[kind] ??
    DISCOVERED_KIND_STYLE[kind] ?? {
      ...UNKNOWN_KIND_STYLE,
      label: kind.replace(/_/g, " "),
    }
  );
}

export const RELATION_GROUP_STYLE: Record<RelationGroup, { stroke: string; label: string }> = {
  structural: { stroke: "#f59e0b", label: "Structural" },
  pipeline: { stroke: "#6366f1", label: "Pipeline" },
  operational: { stroke: "#8b5cf6", label: "Operational" },
  lineage: { stroke: "#10b981", label: "Lineage" },
  provenance: { stroke: "#eab308", label: "Provenance" },
  discovered: { stroke: "#22d3ee", label: "Discovered" },
};

/** A failed run/task run should read as failed at a glance. */
export function isFailureStatus(status?: string | null): boolean {
  if (!status) return false;
  return ["FAILED", "TIMEDOUT", "ERROR", "UPSTREAM_FAILED", "CANCELED"].includes(
    status.toUpperCase()
  );
}

// ── Graph assembly ───────────────────────────────────────────────────

export const NODE_WIDTH = 250;
export const NODE_HEIGHT = 76;

/**
 * Merge an expansion into the graph on screen. Existing nodes keep the
 * depth they were first seen at so expanding never relabels prior context.
 */
export function mergeGraph(
  current: { nodes: EntityNode[]; edges: EntityEdge[] },
  incoming: { nodes: EntityNode[]; edges: EntityEdge[] },
  anchorId?: string
): { nodes: EntityNode[]; edges: EntityEdge[] } {
  const nodeMap = new Map<string, EntityNode>();
  current.nodes.forEach((n) => nodeMap.set(n.id, n));

  const anchorDepth = anchorId ? nodeMap.get(anchorId)?.depth ?? 0 : 0;

  incoming.nodes.forEach((n) => {
    const existing = nodeMap.get(n.id);
    if (existing) {
      nodeMap.set(n.id, { ...n, depth: existing.depth, is_root: existing.is_root });
      return;
    }
    nodeMap.set(n.id, { ...n, depth: anchorDepth + n.depth, is_root: false });
  });

  const edgeMap = new Map<string, EntityEdge>();
  current.edges.forEach((e) => edgeMap.set(e.id, e));
  incoming.edges.forEach((e) => edgeMap.set(e.id, e));

  const nodes = Array.from(nodeMap.values());
  const edges = Array.from(edgeMap.values()).filter(
    (e) => nodeMap.has(e.source) && nodeMap.has(e.target)
  );

  // A node the user has expanded should stop advertising itself as
  // expandable unless the server said it was truncated.
  if (anchorId) {
    const anchor = nodeMap.get(anchorId);
    const stillTruncated = incoming.nodes.find((n) => n.id === anchorId)?.expandable ?? false;
    if (anchor) nodeMap.set(anchorId, { ...anchor, expandable: stillTruncated });
  }

  return { nodes: Array.from(nodeMap.values()), edges };
}

/** Hierarchical left-to-right layout. */
export function layoutGraph(nodes: EntityNode[], edges: EntityEdge[]) {
  const graph = new dagre.graphlib.Graph();
  graph.setGraph({ rankdir: "LR", nodesep: 22, ranksep: 130, marginx: 48, marginy: 48 });
  graph.setDefaultEdgeLabel(() => ({}));

  nodes.forEach((n) => graph.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT }));
  edges.forEach((e) => {
    if (e.source !== e.target) graph.setEdge(e.source, e.target);
  });

  dagre.layout(graph);

  return nodes.map((n) => {
    const positioned = graph.node(n.id);
    return {
      id: n.id,
      type: "entityNode",
      data: n as unknown as Record<string, unknown>,
      position: positioned
        ? { x: positioned.x - NODE_WIDTH / 2, y: positioned.y - NODE_HEIGHT / 2 }
        : { x: 0, y: 0 },
    };
  });
}

export function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
