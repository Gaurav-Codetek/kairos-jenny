"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  MiniMap,
  ReactFlow,
  useEdgesState,
  useNodesInitialized,
  useNodesState,
  useReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Crosshair, Maximize2, Minus, Plus, Shrink, X } from "lucide-react";

import { Callout, EmptyState, Spinner, StatusPill } from "@/components/kairos/ds";

import { PageHeader } from "@/components/shell/app-shell";
import { kindVisual } from "@/components/graph/lineage-card";
import { ACCENT, meshNodeTypes, type MeshNodeData } from "@/components/mesh/bundle-card";
import { MeshTree } from "@/components/mesh/mesh-tree";
import { EDGE_STYLE, meshEdgeTypes, type RoutedEdgeData } from "@/components/mesh/routed-edge";
import { MeshHighlightContext, type MeshHighlight } from "@/components/mesh/highlight";
import { EntityDetailPanel } from "@/components/warehouse/entity-detail";
import { computeFocus } from "@/lib/graph-focus";
import {
  FAILED,
  MeshIndex,
  buildScene,
  dataFlowBundles,
  defaultExpanded,
  fetchMesh,
  layoutScene,
  type MeshLayoutResult,
  type Bundle,
  type RelationshipGroup,
  type Scene,
} from "@/lib/mesh";
import { cn } from "@/lib/utils";

const PATH_GROUPS = new Set<RelationshipGroup>(["flow", "depends_on", "storage"]);

export function MeshWorkspace({ modeSwitch }: { modeSwitch: React.ReactNode }) {
  const [index, setIndex] = useState<MeshIndex | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [pinned, setPinned] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [laid, setLaid] = useState<{ scene: Scene; layout: MeshLayoutResult; request: Scene } | null>(null);
  const [fitTarget, setFitTarget] = useState<string | "all" | null>("all");

  const [flowNodes, setFlowNodes, onNodesChange] = useNodesState<Node>([]);
  const [flowEdges, setFlowEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const { fitView, zoomIn, zoomOut } = useReactFlow();

  useEffect(() => {
    fetchMesh()
      .then((m) => {
        const idx = new MeshIndex(m);
        // ?expand=<uid>,<uid>&select=<uid> — a view can be shared as a link.
        const params = new URLSearchParams(window.location.search);
        const open = (params.get("expand") ?? "").split(",").filter((id) => idx.byId.has(id));
        const pick = params.get("select");
        const initial = open.length ? new Set(open.flatMap((id) => [id, ...idx.ancestors(id)])) : defaultExpanded(idx);
        if (pick && idx.byId.has(pick)) {
          idx.ancestors(pick).forEach((id) => initial.add(id));
          setPinned(new Set([pick]));
          setSelected(pick);
        }
        setExpanded(initial);
        setIndex(idx);
      })
      .catch((e) => setError(String(e)));
  }, []);

  // Bundles with lineage and every bundle containing one — for the tree's markers.
  const withLineage = useMemo(() => {
    const out = new Set<string>();
    if (!index) return out;
    dataFlowBundles(index).forEach((id) => {
      out.add(id);
      index.ancestors(id).forEach((a) => out.add(a));
    });
    return out;
  }, [index]);

  // Scene → ELK layout. Layout is async; a result is kept only if it is for the
  // scene currently requested, so a newer change always wins.
  const requested = useMemo(() => (index ? buildScene(index, expanded, pinned) : null), [index, expanded, pinned]);
  useEffect(() => {
    if (!requested) return;
    let current = true;
    layoutScene(requested)
      .then((layout) => current && setLaid({ scene: requested, layout, request: requested }))
      .catch((e) => current && setError(`Layout failed: ${e}`));
    return () => {
      current = false;
    };
  }, [requested]);
  const laying = Boolean(requested) && laid?.request !== requested;
  const scene = laid?.scene ?? null;
  const boxes = laid?.layout.boxes;
  const routes = laid?.layout.routes;

  const toggle = useCallback(
    (uid: string) => {
      setExpanded((current) => {
        const next = new Set(current);
        if (next.has(uid)) {
          next.delete(uid);
          for (const id of Array.from(next)) if (index?.ancestors(id).includes(uid)) next.delete(id);
        } else {
          next.add(uid);
        }
        return next;
      });
      setFitTarget(uid);
    },
    [index]
  );

  /** Put a bundle on the canvas — open its containers, pin it — select it and fly to it. */
  const reveal = useCallback(
    (uid: string) => {
      if (!index) return;
      setExpanded((current) => new Set([...current, ...index.ancestors(uid)]));
      setPinned((current) => new Set(current).add(uid));
      setSelected(uid);
      setFitTarget(uid);
    },
    [index]
  );

  const focusId = selected ?? hovered;
  const focus = useMemo(() => {
    if (!scene || !focusId || !scene.nodes.some((n) => n.id === focusId)) return null;
    return computeFocus(focusId, scene.edges.filter((e) => PATH_GROUPS.has(e.group)));
  }, [scene, focusId]);

  // Nodes and edges are rebuilt only when the LAYOUT changes. Hover and
  // selection never touch them (see highlight.ts) — rebuilding here made
  // React Flow re-measure every card on each hover, which read as a stutter.
  useEffect(() => {
    if (!index || !scene || !boxes) return;
    setFlowNodes(
      scene.nodes
        .filter((n) => boxes.has(n.id))
        .map((n) => {
          const box = boxes.get(n.id)!;
          const data: MeshNodeData = {
            bundle: n.bundle,
            openParent: n.openParent,
            childCount: index.childrenOf.get(n.bundle.unique_id)?.length ?? 0,
            onToggle: toggle,
          };
          return { id: n.id, type: "bundle", position: { x: box.x, y: box.y }, data } as unknown as Node;
        })
    );
    setFlowEdges(
      scene.edges.map((e) => {
        const data: RoutedEdgeData = { points: routes?.get(e.id), group: e.group, count: e.count };
        // Beneath the cards: a line never draws over a card's text.
        return { id: e.id, source: e.source, target: e.target, type: "routed", zIndex: 0, data } as unknown as Edge;
      })
    );
  }, [index, scene, boxes, routes, toggle, setFlowNodes, setFlowEdges]);

  const highlight = useMemo<MeshHighlight>(
    () => ({
      selected,
      focusId: focus ? focusId : null,
      pathNodes: focus?.nodes ?? new Set(),
      pathEdges: focus?.edges ?? new Set(),
    }),
    [selected, focus, focusId]
  );

  // Fly to what changed — once React Flow has measured the new nodes.
  const nodesInitialized = useNodesInitialized();
  const firstFit = useRef(true);
  useEffect(() => {
    if (!fitTarget || !flowNodes.length || !nodesInitialized || laying) return;
    const duration = firstFit.current ? 0 : 450;
    const h = window.setTimeout(() => {
      firstFit.current = false;
      const target = fitTarget === "all" && selected ? selected : fitTarget;
      if (target === "all" || !flowNodes.some((n) => n.id === target)) {
        fitView({ padding: 0.1, duration, maxZoom: 1 });
      } else {
        const around = focus && target === selected ? Array.from(focus.nodes) : [];
        fitView({ nodes: [target, ...around].map((id) => ({ id })), padding: 0.3, duration, maxZoom: 1.1 });
      }
      setFitTarget(null);
    }, 40);
    return () => window.clearTimeout(h);
  }, [fitTarget, flowNodes, nodesInitialized, laying, fitView, selected, focus]);

  const selectedBundle = selected && index ? index.byId.get(selected) ?? null : null;
  const onCanvas = scene?.nodes.length ?? 0;
  const description = index
    ? `${onCanvas} of ${index.mesh.bundles.length} bundles on the canvas · ` +
      `${index.mesh.stats.inherited.columns.toLocaleString()} columns, ${index.mesh.stats.inherited.runs.toLocaleString()} runs, ` +
      `${index.mesh.stats.inherited.task_runs.toLocaleString()} task runs folded in`
    : "Loading the mesh…";

  return (
    <>
      <PageHeader
        title="Map"
        description={description}
        actions={
          <>
            {index && (
              <button
                onClick={() => {
                  setExpanded(new Set());
                  setPinned(new Set());
                  setSelected(null);
                  setFitTarget("all");
                }}
                className="k-btn"
                title="Close every bundle"
              >
                <Shrink className="h-4 w-4" /> Collapse all
              </button>
            )}
            {modeSwitch}
          </>
        }
      />

      <div className="flex min-h-0 flex-1">
        {index && (
          <div data-guide="map:tree" className="contents">
            <MeshTree index={index} withLineage={withLineage} selected={selected} onPick={reveal} />
          </div>
        )}

        <div data-guide="map:canvas" className="relative min-w-0 flex-1">
          {focus && selectedBundle && (
            <div className="absolute left-1/2 top-4 z-20 -translate-x-1/2">
              <div className="kairos-panel k-pop flex items-center gap-3 rounded-full py-1.5 pl-3 pr-1.5 shadow-[0_8px_24px_-12px_rgb(81_72_224/0.45)]" style={{ borderColor: "var(--brand-border)" }}>
                <Crosshair className="h-4 w-4 text-brand" />
                <span className="text-k-caption text-ink">
                  <span className="font-semibold">{selectedBundle.name}</span> · {focus.upstreamCount} upstream ·{" "}
                  {focus.downstreamCount} downstream
                </span>
                <button onClick={() => setSelected(null)} className="k-btn k-btn-sm !h-6 !rounded-full !border-transparent !bg-brand-soft !text-brand-strong">
                  Clear
                </button>
              </div>
            </div>
          )}

          <div data-guide="map:zoom" className="absolute right-4 top-4 z-20">
            <div className="kairos-panel flex items-center p-0.5">
              <button onClick={() => zoomOut({ duration: 150 })} className="k-btn k-btn-ghost k-btn-sm !h-7 !px-2" title="Zoom out">
                <Minus className="h-4 w-4" />
              </button>
              <span className="h-4 w-px bg-hairline" />
              <button onClick={() => zoomIn({ duration: 150 })} className="k-btn k-btn-ghost k-btn-sm !h-7 !px-2" title="Zoom in">
                <Plus className="h-4 w-4" />
              </button>
              <span className="h-4 w-px bg-hairline" />
              <button onClick={() => fitView({ padding: 0.1, duration: 300, maxZoom: 1 })} className="k-btn k-btn-ghost k-btn-sm !h-7 !px-2" title="Fit to view">
                <Maximize2 className="h-4 w-4" />
              </button>
            </div>
          </div>

          <div data-guide="map:legend" className="absolute bottom-4 left-4 z-20">
            <div className="kairos-panel flex items-center gap-4 rounded-full px-4 py-2 text-[11.5px] text-ink-muted">
              <LegendLine label="data flow" group="flow" />
              <LegendLine label="task order" group="depends_on" />
              <span className="flex items-center gap-1.5">
                <span className="rounded-full border border-hairline bg-surface px-1.5 font-mono text-[10px] font-semibold leading-4">3</span>
                flows inside a closed bundle
              </span>
            </div>
          </div>

          {(!index || laying) && !error && (
            <div className="pointer-events-none absolute inset-0 z-30 flex items-center justify-center">
              <div className="kairos-panel k-pop flex items-center gap-2.5 rounded-full px-4 py-2">
                <Spinner />
                <span className="text-k-body font-medium text-ink">{index ? "Laying out…" : "Building the mesh…"}</span>
              </div>
            </div>
          )}
          {error && (
            <div className="absolute inset-0 z-30 flex items-center justify-center">
              <Callout tone="danger">{error}</Callout>
            </div>
          )}
          {index && scene && !laying && scene.nodes.length === 0 && (
            <div className="absolute inset-0 z-10 flex items-center justify-center">
              <div className="kairos-panel k-pop">
                <EmptyState icon={Crosshair} title="No lineage to draw yet">
                  Pick any bundle in the sidebar to place it on the canvas, or enrich a pipeline so Kairos can read how
                  data moves through it.
                </EmptyState>
              </div>
            </div>
          )}

          <MeshHighlightContext.Provider value={highlight}>
          <ReactFlow
            nodes={flowNodes}
            edges={flowEdges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={(_e, node) => setSelected((cur) => (cur === node.id ? null : node.id))}
            onNodeDoubleClick={(_e, node) => {
              if (index?.childrenOf.get(node.id)?.length) toggle(node.id);
            }}
            onNodeMouseEnter={(_e, node) => setHovered(node.id)}
            onNodeMouseLeave={() => setHovered(null)}
            onPaneClick={() => setSelected(null)}
            nodeTypes={meshNodeTypes}
            edgeTypes={meshEdgeTypes}
            minZoom={0.1}
            maxZoom={1.75}
            zoomOnDoubleClick={false}
            nodesDraggable={false}
            nodesConnectable={false}
            proOptions={{ hideAttribution: true }}
            className="kairos-canvas"
          >
            <MiniMap
              pannable
              zoomable
              position="bottom-right"
              className="!rounded-[10px] !border !border-hairline !bg-surface"
              maskColor="rgb(243 244 246 / 0.7)"
              nodeColor={(n) => {
                const b = (n.data as unknown as MeshNodeData | undefined)?.bundle;
                return b ? ACCENT[b.resource_type] : "transparent";
              }}
              nodeStrokeWidth={0}
            />
          </ReactFlow>
          </MeshHighlightContext.Provider>
        </div>

        {selectedBundle && (
          <div className="k-rise flex h-full w-[400px] shrink-0 flex-col border-l border-hairline bg-surface">
            <InheritedPanel bundle={selectedBundle} />
            {selectedBundle.entity_id ? (
              <div className="flex min-h-0 flex-1">
                <EntityDetailPanel
                  entityId={selectedBundle.entity_id}
                  onClose={() => setSelected(null)}
                  onFocus={(entityId) => {
                    const target = index?.mesh.bundles.find((b) => b.entity_id === entityId);
                    if (target) reveal(target.unique_id);
                  }}
                />
              </div>
            ) : (
              <div className="flex flex-1 items-start justify-end p-3">
                <button onClick={() => setSelected(null)} className="k-btn k-btn-ghost k-btn-sm !px-1.5">
                  <X className="h-4 w-4" />
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </>
  );
}

function LegendLine({ label, group }: { label: string; group: RelationshipGroup }) {
  return (
    <span className="flex items-center gap-1.5">
      <svg width="24" height="6">
        <line x1="0" y1="3" x2="24" y2="3" stroke={EDGE_STYLE[group].stroke} strokeWidth={EDGE_STYLE[group].width + 0.4} strokeDasharray={EDGE_STYLE[group].dash} />
      </svg>
      {label}
    </span>
  );
}


/** What a bundle folds in — runs for a pipeline, run results for a task, paths for a volume. */
function InheritedPanel({ bundle: b }: { bundle: Bundle }) {
  const v = kindVisual(b.resource_type);
  const rows: React.ReactNode[] = [];

  if (b.resource_type === "pipeline" && b.inherited.recent?.length) {
    rows.push(
      <div key="runs" className="space-y-1">
        {b.inherited.recent.map((r) => (
          <div key={r.run_id} className="flex items-center justify-between text-k-caption">
            <span className="flex items-center gap-1.5">
              <span className={cn("h-2 w-2 rounded-full", FAILED.has(String(r.result).toUpperCase()) ? "bg-danger-dot" : "bg-ok-dot")} />
              <span className="text-ink">{r.result ?? "—"}</span>
            </span>
            <span className="text-ink-subtle">
              {r.start_time ? new Date(r.start_time).toLocaleString() : "—"}
              {r.duration_ms ? ` · ${(r.duration_ms / 1000).toFixed(0)}s` : ""}
            </span>
          </div>
        ))}
      </div>
    );
  }
  if (b.inherited.by_result && Object.keys(b.inherited.by_result).length) {
    rows.push(
      <div key="results" className="flex flex-wrap gap-1.5">
        {Object.entries(b.inherited.by_result).map(([state, n]) => (
          <StatusPill key={state} size="sm" tone={FAILED.has(state) ? "danger" : state === "SUCCESS" ? "ok" : "neutral"}>
            {state.toLowerCase()} {n}
          </StatusPill>
        ))}
      </div>
    );
  }
  if (b.resource_type === "volume" && b.inherited.sample?.length) {
    rows.push(
      <ul key="paths" className="space-y-0.5 font-mono text-k-caption text-ink-muted">
        {b.inherited.sample.map((p) => (
          <li key={p} className="truncate">{p}</li>
        ))}
      </ul>
    );
  }

  const heading =
    b.resource_type === "pipeline" ? `${b.inherited.runs ?? 0} runs folded in` :
    b.resource_type === "task" ? `${b.inherited.task_runs ?? 0} task runs folded in` :
    b.resource_type === "table" ? `${b.inherited.columns ?? 0} columns folded in` :
    b.resource_type === "volume" ? `${b.inherited.paths ?? 0} paths folded in` :
    `${Object.values(b.children).reduce((a, n) => a + (n ?? 0), 0)} child bundles`;

  return (
    <div className="shrink-0 border-b border-hairline bg-surface px-5 py-4">
      <div className="flex items-center gap-2.5">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full" style={{ background: v.bg, color: ACCENT[b.resource_type] }}>
          <v.icon className="h-4 w-4" />
        </span>
        <span className="truncate font-mono text-[15px] font-bold text-ink">{b.name}</span>
      </div>
      <p className="mt-1.5 break-all font-mono text-[11px] text-ink-subtle">{b.unique_id}</p>
      <p className="mt-3 text-k-caption font-semibold text-ink-2">{heading}</p>
      {rows.length > 0 && <div className="mt-2 space-y-2">{rows}</div>}
    </div>
  );
}
