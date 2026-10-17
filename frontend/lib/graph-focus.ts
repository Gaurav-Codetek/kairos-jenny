/**
 * Focus flow: given a selected node, find everything on its lineage path.
 *
 * "Path" means the full ancestry and full descendancy — not one hop. Clicking
 * a gold table should light the whole chain back to the raw sources that feed
 * it and forward to everything it feeds, because that is the question someone
 * is actually asking when they click it.
 */

export interface FocusEdge {
  id: string;
  source: string;
  target: string;
}

export interface FocusResult {
  /** Every node on the selected node's upstream + downstream path. */
  nodes: Set<string>;
  /** Every edge connecting two nodes on that path, in the traversed direction. */
  edges: Set<string>;
  upstreamCount: number;
  downstreamCount: number;
}

function walk(
  start: string,
  adjacency: Map<string, { node: string; edge: string }[]>,
  visitedNodes: Set<string>,
  visitedEdges: Set<string>
): number {
  let discovered = 0;
  const queue = [start];
  const seen = new Set<string>([start]);

  while (queue.length) {
    const current = queue.shift()!;
    for (const step of adjacency.get(current) ?? []) {
      visitedEdges.add(step.edge);
      if (!seen.has(step.node)) {
        seen.add(step.node);
        visitedNodes.add(step.node);
        queue.push(step.node);
        discovered += 1;
      }
    }
  }
  return discovered;
}

export function computeFocus(selectedId: string, edges: FocusEdge[]): FocusResult {
  const downstream = new Map<string, { node: string; edge: string }[]>();
  const upstream = new Map<string, { node: string; edge: string }[]>();

  for (const edge of edges) {
    if (edge.source === edge.target) continue;
    (downstream.get(edge.source) ?? downstream.set(edge.source, []).get(edge.source)!).push({
      node: edge.target,
      edge: edge.id,
    });
    (upstream.get(edge.target) ?? upstream.set(edge.target, []).get(edge.target)!).push({
      node: edge.source,
      edge: edge.id,
    });
  }

  const nodes = new Set<string>([selectedId]);
  const edgeIds = new Set<string>();

  const downstreamCount = walk(selectedId, downstream, nodes, edgeIds);
  const upstreamCount = walk(selectedId, upstream, nodes, edgeIds);

  return { nodes, edges: edgeIds, upstreamCount, downstreamCount };
}
