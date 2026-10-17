import dagre from "dagre";
import { fetchApi } from "@/lib/api";

// ── Types mirroring /api/v1/lineage ──────────────────────────────────

export type LineageDirection = "root" | "upstream" | "downstream" | "both";

export interface LineageNode {
  id: string;
  entity_id: string;
  label: string;
  full_name: string;
  catalog: string;
  schema: string;
  table_type: string | null;
  /** False when the table is referenced by lineage but was never synced. */
  known: boolean;
  table_id: string | null;
  comment: string | null;
  row_count: number | null;
  direction: LineageDirection;
  depth: number;
  upstream_count: number;
  downstream_count: number;
  hidden_upstream: number;
  hidden_downstream: number;
  expandable: boolean;
}

export interface LineageEdge {
  id: string;
  source: string;
  target: string;
  via: string[];
  column_pairs: number;
  confidence: number;
  transformation: string | null;
}

export interface NeighborhoodResponse {
  root: { entity_id: string; label: string; full_name: string; known: boolean };
  nodes: LineageNode[];
  edges: LineageEdge[];
  depth: { upstream: number; downstream: number };
  stats: { nodes: number; edges: number; external_nodes: number; truncated: boolean };
}

export interface CatalogTreeTable {
  id: string;
  entity_id: string;
  name: string;
  full_name: string;
  table_type: string;
  upstream_count: number;
  downstream_count: number;
  has_lineage: boolean;
}

export interface CatalogTreeSchema {
  id: string;
  entity_id: string;
  name: string;
  full_name: string;
  table_count: number;
  lineage_table_count: number;
  tables: CatalogTreeTable[];
}

export interface CatalogTreeCatalog {
  id: string;
  entity_id: string;
  name: string;
  catalog_type: string;
  schema_count: number;
  table_count: number;
  lineage_table_count: number;
  schemas: CatalogTreeSchema[];
}

export interface LineageRootEntity {
  entity_id: string;
  name: string;
  schema: string;
  full_name: string;
  known: boolean;
  upstream_count: number;
  downstream_count: number;
  degree: number;
}

export interface LineageRootGroup {
  catalog: string;
  entity_count: number;
  known_count: number;
  entities: LineageRootEntity[];
}

export interface CatalogTreeResponse {
  catalogs: CatalogTreeCatalog[];
  lineage_roots: LineageRootGroup[];
  stats: {
    catalogs: number;
    schemas: number;
    tables: number;
    tables_with_lineage: number;
    lineage_edges: number;
    external_lineage_nodes: number;
  };
}

export interface NodeContext {
  entity_id: string;
  known: boolean;
  table: {
    id: string | null;
    name: string;
    full_name: string;
    catalog: string;
    schema: string;
    table_type: string | null;
    data_source_format: string | null;
    owner: string | null;
    comment: string | null;
    storage_location: string | null;
    row_count: number | null;
    size_bytes: number | null;
    first_seen_at: string | null;
    last_seen_at: string | null;
  };
  columns: Array<{
    name: string;
    data_type: string;
    full_data_type: string;
    is_nullable: boolean;
    is_partition_column: boolean;
    comment: string | null;
    ordinal_position: number;
  }>;
  column_count: number;
  changes: Array<{
    change_type: string;
    field_name: string | null;
    old_value: string | null;
    new_value: string | null;
    detected_at: string;
  }>;
  evidence: Array<{
    source_type: string;
    source_id: string | null;
    content_hash: string;
    observed_at: string;
    content_preview: string;
  }>;
  column_lineage: Array<{
    direction: "upstream" | "downstream";
    column: string;
    remote_entity_id: string;
    remote_full_name: string;
    transformation: string | null;
  }>;
}

// ── API calls ────────────────────────────────────────────────────────

export function fetchCatalogTree(lineageOnly = false): Promise<CatalogTreeResponse> {
  return fetchApi(`/lineage/catalog-tree?lineage_only=${lineageOnly}`);
}

export function fetchNeighborhood(
  entityId: string,
  upstream: number,
  downstream: number
): Promise<NeighborhoodResponse> {
  const params = new URLSearchParams({
    entity_id: entityId,
    upstream: String(upstream),
    downstream: String(downstream),
  });
  return fetchApi(`/lineage/neighborhood?${params.toString()}`);
}

export function fetchNodeContext(entityId: string): Promise<NodeContext> {
  return fetchApi(`/lineage/context?entity_id=${encodeURIComponent(entityId)}`);
}

// ── Graph assembly ───────────────────────────────────────────────────

export const NODE_WIDTH = 268;
export const NODE_HEIGHT = 88;

/**
 * Merge a freshly fetched neighborhood into the graph already on screen.
 *
 * Existing nodes keep their original direction/depth so that expanding a
 * branch never relabels the part of the graph the user already read.
 */
export function mergeGraph(
  current: { nodes: LineageNode[]; edges: LineageEdge[] },
  incoming: { nodes: LineageNode[]; edges: LineageEdge[] },
  options: { anchorId?: string } = {}
): { nodes: LineageNode[]; edges: LineageEdge[] } {
  const nodeMap = new Map<string, LineageNode>();
  current.nodes.forEach((n) => nodeMap.set(n.entity_id, n));

  const anchor = options.anchorId ? nodeMap.get(options.anchorId) : undefined;

  incoming.nodes.forEach((n) => {
    const existing = nodeMap.get(n.entity_id);
    if (existing) {
      // Refresh degree counts but preserve how the user first saw this node.
      nodeMap.set(n.entity_id, {
        ...n,
        direction: existing.direction,
        depth: existing.depth,
      });
      return;
    }
    // New nodes inherit the anchor's direction so colour keeps meaning
    // "which side of the originally selected table is this on".
    const inheritedDirection: LineageDirection =
      anchor && anchor.direction !== "root" && n.direction !== "root"
        ? anchor.direction
        : n.direction;
    nodeMap.set(n.entity_id, {
      ...n,
      direction: inheritedDirection,
      depth: (anchor?.depth ?? 0) + n.depth,
    });
  });

  const edgeMap = new Map<string, LineageEdge>();
  current.edges.forEach((e) => edgeMap.set(e.id, e));
  incoming.edges.forEach((e) => edgeMap.set(e.id, e));

  const nodes = Array.from(nodeMap.values());
  const edges = Array.from(edgeMap.values()).filter(
    (e) => nodeMap.has(e.source) && nodeMap.has(e.target)
  );

  return { nodes: recomputeHidden(nodes, edges), edges };
}

/**
 * Recompute per-node hidden-neighbour counts against what is actually on
 * screen. The server computes these relative to a single response, so after
 * a merge they must be derived from the union or expand buttons would
 * linger on fully expanded nodes.
 */
export function recomputeHidden(nodes: LineageNode[], edges: LineageEdge[]): LineageNode[] {
  const present = new Set(nodes.map((n) => n.entity_id));
  const upstreamPresent = new Map<string, Set<string>>();
  const downstreamPresent = new Map<string, Set<string>>();

  edges.forEach((e) => {
    if (!present.has(e.source) || !present.has(e.target)) return;
    if (!upstreamPresent.has(e.target)) upstreamPresent.set(e.target, new Set());
    upstreamPresent.get(e.target)!.add(e.source);
    if (!downstreamPresent.has(e.source)) downstreamPresent.set(e.source, new Set());
    downstreamPresent.get(e.source)!.add(e.target);
  });

  return nodes.map((n) => {
    const hiddenUpstream = Math.max(
      0,
      n.upstream_count - (upstreamPresent.get(n.entity_id)?.size ?? 0)
    );
    const hiddenDownstream = Math.max(
      0,
      n.downstream_count - (downstreamPresent.get(n.entity_id)?.size ?? 0)
    );
    return {
      ...n,
      hidden_upstream: hiddenUpstream,
      hidden_downstream: hiddenDownstream,
      expandable: hiddenUpstream > 0 || hiddenDownstream > 0,
    };
  });
}

/** Left-to-right dagre layout: upstream on the left, downstream on the right. */
export function layoutGraph(nodes: LineageNode[], edges: LineageEdge[]) {
  const graph = new dagre.graphlib.Graph();
  graph.setGraph({ rankdir: "LR", nodesep: 26, ranksep: 150, marginx: 48, marginy: 48 });
  graph.setDefaultEdgeLabel(() => ({}));

  nodes.forEach((n) => graph.setNode(n.entity_id, { width: NODE_WIDTH, height: NODE_HEIGHT }));
  edges.forEach((e) => {
    if (e.source !== e.target) graph.setEdge(e.source, e.target);
  });

  dagre.layout(graph);

  return nodes.map((n) => {
    const positioned = graph.node(n.entity_id);
    return {
      id: n.entity_id,
      type: "lineageTable",
      data: n as unknown as Record<string, unknown>,
      position: positioned
        ? { x: positioned.x - NODE_WIDTH / 2, y: positioned.y - NODE_HEIGHT / 2 }
        : { x: 0, y: 0 },
    };
  });
}

export function formatBytes(bytes: number | null): string {
  if (bytes === null || bytes === undefined) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

export function formatCount(count: number | null): string {
  if (count === null || count === undefined) return "—";
  return count.toLocaleString();
}
