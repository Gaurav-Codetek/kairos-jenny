"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Background,
  BackgroundVariant,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  Crosshair,
  Maximize2,
  Minus,
  Plus,
  RotateCcw,
  Search,
  X,
} from "lucide-react";

import { Segmented, Spinner } from "@/components/kairos/ds";
import { PageHeader } from "@/components/shell/app-shell";
import { lineageNodeTypes, kindVisual } from "@/components/graph/lineage-card";
import { MeshWorkspace } from "@/components/mesh/mesh-view";
import { EntityDetailPanel } from "@/components/warehouse/entity-detail";
import { computeFocus } from "@/lib/graph-focus";
import {
  fetchGraph,
  layoutGraph,
  mergeGraph,
  type EntityEdge,
  type EntityNode as EntityNodeModel,
  type RelationGroup,
} from "@/lib/warehouse";
import { searchEntities } from "@/lib/warehouse";
import { cn } from "@/lib/utils";

const DEFAULT_DEPTH = 1;
const DEFAULT_LIMIT = 15;
// Flow-first: how data actually moves. Structural (every column) and
// operational (every run) are available behind a toggle but would bury the
// lineage they surround.
const FLOW_GROUPS: RelationGroup[] = ["lineage", "discovered", "pipeline"];
const DETAIL_GROUPS: RelationGroup[] = ["lineage", "discovered", "pipeline", "structural", "operational"];

function GraphWorkspace({ modeSwitch }: { modeSwitch: React.ReactNode }) {
  const [rootId, setRootId] = useState<string | null>(null);
  const [graph, setGraph] = useState<{ nodes: EntityNodeModel[]; edges: EntityEdge[] }>({
    nodes: [],
    edges: [],
  });
  const [loading, setLoading] = useState(false);
  const [depth, setDepth] = useState(DEFAULT_DEPTH);
  const [showDetail, setShowDetail] = useState(false);
  // Nodes the user has already expanded, so the + affordance retires.
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [expandingId, setExpandingId] = useState<string | null>(null);

  // Focus flow state: the node whose lineage path is currently isolated.
  const [focusId, setFocusId] = useState<string | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Array<{ id: string; kind: string; label: string; sublabel: string }>>([]);
  const [searching, setSearching] = useState(false);

  const [flowNodes, setFlowNodes, onNodesChange] = useNodesState<Node>([]);
  const [flowEdges, setFlowEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const { fitView, zoomIn, zoomOut } = useReactFlow();

  const load = useCallback((entityId: string, nextDepth: number) => {
    setRootId(entityId);
    setDetailId(entityId);
    setFocusId(null);
    setExpanded(new Set());
    setLoading(true);
    fetchGraph(entityId, nextDepth, showDetail ? DETAIL_GROUPS : FLOW_GROUPS, DEFAULT_LIMIT)
      .then((r) => setGraph({ nodes: r.nodes, edges: r.edges }))
      .catch(() => setGraph({ nodes: [], edges: [] }))
      .finally(() => setLoading(false));
  }, [showDetail]);

  useEffect(() => {
    if (rootId) load(rootId, depth);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [depth, showDetail]);

  // Debounced entity search — the graph's entry point.
  useEffect(() => {
    const needle = query.trim();
    if (needle.length < 2) {
      setResults([]);
      return;
    }
    setSearching(true);
    const handle = window.setTimeout(() => {
      searchEntities(needle, 12)
        .then((r) => setResults(r.results.map((x) => ({ id: x.id, kind: x.kind, label: x.label, sublabel: x.sublabel }))))
        .catch(() => setResults([]))
        .finally(() => setSearching(false));
    }, 220);
    return () => window.clearTimeout(handle);
  }, [query]);

  const focus = useMemo(
    () => (focusId ? computeFocus(focusId, graph.edges) : null),
    [focusId, graph.edges]
  );

  // Project domain graph into React Flow, applying focus dimming.
  useEffect(() => {
    const positioned = layoutGraph(graph.nodes, graph.edges);
    const byId = new Map(graph.nodes.map((n) => [n.id, n]));

    setFlowNodes(
      positioned.map((p) => {
        const model = byId.get(p.id)!;
        const onPath = focus ? focus.nodes.has(p.id) : true;
        return {
          ...p,
          type: "lineageCard",
          data: {
            entity_id: model.id,
            kind: model.kind,
            label: model.label,
            sublabel: model.sublabel,
            known: model.known,
            discovered: (model as unknown as { discovered?: boolean }).discovered,
            failed: ["FAILED", "TIMEDOUT", "UPSTREAM_FAILED"].includes(
              String(model.status ?? "").toUpperCase()
            ),
            isRoot: model.id === rootId,
            focused: Boolean(focus) && onPath,
            dimmed: Boolean(focus) && !onPath,
            canExpand: !expanded.has(p.id),
            expanding: expandingId === p.id,
          },
        } as Node;
      })
    );

    setFlowEdges(
      graph.edges.map((e) => {
        const onPath = focus ? focus.edges.has(e.id) : true;
        return {
          id: e.id,
          source: e.source,
          target: e.target,
          type: "smoothstep",
          // Hairline edges, no labels — the reference keeps the canvas quiet
          // and lets the cards carry the meaning.
          style: {
            stroke: focus && onPath ? "var(--edge-focus)" : focus ? "var(--edge-dim)" : "var(--edge)",
            strokeWidth: focus && onPath ? 1.6 : 1.2,
          },
          animated: false,
        } as Edge;
      })
    );

    if (positioned.length) {
      const h = window.setTimeout(() => fitView({ padding: 0.18, duration: 350 }), 60);
      return () => window.clearTimeout(h);
    }
  }, [graph, focus, rootId, expanded, expandingId, setFlowNodes, setFlowEdges, fitView]);

  const onNodeClick = useCallback(
    (_e: React.MouseEvent, node: Node) => {
      setDetailId(node.id);
      setFocusId((current) => (current === node.id ? null : node.id));

      // First click on a node also pulls in its next hop. The graph opens
      // shallow and grows where the user actually looks, instead of loading
      // hundreds of nodes nobody asked for.
      if (expanded.has(node.id) || expandingId) return;
      setExpandingId(node.id);
      fetchGraph(node.id, 1, showDetail ? DETAIL_GROUPS : FLOW_GROUPS, DEFAULT_LIMIT)
        .then((r) => {
          setGraph((current) => mergeGraph(current, { nodes: r.nodes, edges: r.edges }, node.id));
          setExpanded((s) => new Set(s).add(node.id));
        })
        .catch(() => undefined)
        .finally(() => setExpandingId(null));
    },
    [expanded, expandingId, showDetail]
  );

  const stats = useMemo(() => {
    const kinds = new Map<string, number>();
    graph.nodes.forEach((n) => kinds.set(n.kind, (kinds.get(n.kind) ?? 0) + 1));
    return Array.from(kinds.entries()).sort((a, b) => b[1] - a[1]);
  }, [graph.nodes]);

  return (
    <>
      <PageHeader
        title="Lineage"
        description={
          rootId
            ? `${graph.nodes.length} entities · ${graph.edges.length} relationships`
            : "Search an entity to explore how it connects"
        }
        actions={
          <>
          {rootId ? (
            <>
              {/* Structure and execution are one toggle away, but off by
                  default so lineage is not buried under columns and runs. */}
              <button
                onClick={() => setShowDetail((v) => !v)}
                className={cn("k-btn", showDetail && "!border-brand-border !bg-brand-soft !text-brand-strong")}
                title="Include columns, runs and containment"
              >
                Detail
              </button>
              <div className="flex h-[34px] items-center gap-1 rounded-lg border border-hairline bg-surface px-1">
                <button
                  onClick={() => setDepth((d) => Math.max(1, d - 1))}
                  className="rounded p-1 text-ink-subtle hover:bg-sunken hover:text-ink"
                  title="Fewer hops"
                >
                  <Minus className="h-3.5 w-3.5" />
                </button>
                <span className="min-w-[52px] text-center text-k-caption font-medium text-ink-muted">
                  {depth} hop{depth === 1 ? "" : "s"}
                </span>
                <button
                  onClick={() => setDepth((d) => Math.min(5, d + 1))}
                  className="rounded p-1 text-ink-subtle hover:bg-sunken hover:text-ink"
                  title="More hops"
                >
                  <Plus className="h-3.5 w-3.5" />
                </button>
              </div>
              <button
                onClick={() => rootId && load(rootId, depth)}
                className="k-btn !px-2.5"
                title="Reload"
              >
                <RotateCcw className="h-4 w-4" />
              </button>
            </>
          ) : null}
          {modeSwitch}
          </>
        }
      />

      <div className="flex min-h-0 flex-1">
        <div className="relative min-w-0 flex-1">
          {/* Search — floated over the canvas, dbt-style */}
          <div className="absolute left-4 top-4 z-20 w-[340px]">
            <div className="kairos-panel flex h-10 items-center gap-2 px-3 shadow-[0_6px_18px_-12px_rgb(26_29_36/0.25)] focus-within:border-brand focus-within:shadow-[0_0_0_3px_var(--brand-soft)]">
              <Search className="h-4 w-4 shrink-0 text-ink-subtle" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search tables, jobs, tasks, columns…"
                className="w-full bg-transparent text-k-body outline-none placeholder:text-ink-subtle"
              />
              {searching && <Spinner />}
              {query && !searching && (
                <button onClick={() => setQuery("")} className="text-ink-subtle hover:text-ink">
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>

            {results.length > 0 && (
              <div className="kairos-panel k-rise mt-1.5 max-h-[320px] overflow-y-auto p-1 shadow-[0_12px_32px_-16px_rgb(26_29_36/0.35)]">
                {results.map((r) => {
                  const v = kindVisual(r.kind);
                  return (
                    <button
                      key={r.id}
                      onClick={() => {
                        load(r.id, depth);
                        setQuery("");
                        setResults([]);
                      }}
                      className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-sunken"
                    >
                      <span
                        className="flex h-5 w-8 shrink-0 items-center justify-center rounded text-[8px] font-bold"
                        style={{ background: v.bg, color: v.fg }}
                      >
                        {v.code}
                      </span>
                      <span className="min-w-0">
                        <span className="block truncate text-k-body text-ink">{r.label}</span>
                        <span className="block truncate text-[11px] text-ink-subtle">
                          {r.sublabel}
                        </span>
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {/* Focus banner — states what isolation is active and how to leave */}
          {focus && (
            <div className="absolute left-1/2 top-4 z-20 -translate-x-1/2">
              <div className="kairos-panel k-pop flex items-center gap-3 rounded-full py-1.5 pl-3 pr-1.5 shadow-[0_8px_24px_-12px_rgb(81_72_224/0.45)]" style={{ borderColor: "var(--brand-border)" }}>
                <Crosshair className="h-4 w-4 text-brand" />
                <span className="text-k-caption text-ink">
                  Focused ·{" "}
                  <span className="font-medium">{focus.upstreamCount}</span> upstream ·{" "}
                  <span className="font-medium">{focus.downstreamCount}</span> downstream
                </span>
                <button
                  onClick={() => setFocusId(null)}
                  className="k-btn k-btn-sm !h-6 !rounded-full !border-transparent !bg-brand-soft !text-brand-strong"
                >
                  Clear
                </button>
              </div>
            </div>
          )}

          {/* Zoom controls, top-right as in the reference */}
          <div className="absolute right-4 top-4 z-20 flex items-center gap-1">
            <div className="kairos-panel flex items-center p-0.5">
              <button onClick={() => zoomOut({ duration: 150 })} className="k-btn k-btn-ghost k-btn-sm !h-7 !px-2" title="Zoom out">
                <Minus className="h-4 w-4" />
              </button>
              <span className="h-4 w-px bg-hairline" />
              <button onClick={() => zoomIn({ duration: 150 })} className="k-btn k-btn-ghost k-btn-sm !h-7 !px-2" title="Zoom in">
                <Plus className="h-4 w-4" />
              </button>
              <span className="h-4 w-px bg-hairline" />
              <button onClick={() => fitView({ padding: 0.18, duration: 300 })} className="k-btn k-btn-ghost k-btn-sm !h-7 !px-2" title="Fit to view">
                <Maximize2 className="h-4 w-4" />
              </button>
            </div>
          </div>

          {/* Kind legend, bottom-left */}
          {stats.length > 0 && (
            <div className="absolute bottom-4 left-4 z-20">
              <div className="kairos-panel flex flex-wrap items-center gap-2.5 rounded-full px-4 py-2">
                {stats.map(([kind, count]) => {
                  const v = kindVisual(kind);
                  return (
                    <span key={kind} className="flex items-center gap-1 text-[11px] text-ink-muted">
                      <span
                        className="flex h-4 w-7 items-center justify-center rounded text-[7px] font-bold"
                        style={{ background: v.bg, color: v.fg }}
                      >
                        {v.code}
                      </span>
                      {count}
                    </span>
                  );
                })}
              </div>
            </div>
          )}

          {loading && (
            <div className="absolute inset-0 z-30 flex items-center justify-center bg-sunken/60">
              <div className="kairos-panel k-pop flex items-center gap-2.5 rounded-full px-4 py-2">
                <Spinner />
                <span className="text-k-body font-medium text-ink">Building lineage…</span>
              </div>
            </div>
          )}

          {!rootId && !loading && (
            <div className="flex h-full items-center justify-center">
              <div className="max-w-sm text-center">
                <div
                  className="mx-auto flex h-10 w-10 items-center justify-center rounded-lg"
                  style={{ background: "var(--brand-soft)" }}
                >
                  <Crosshair className="h-5 w-5" style={{ color: "var(--brand)" }} />
                </div>
                <h2 className="mt-3 text-k-title font-semibold text-ink">Explore your lineage</h2>
                <p className="mt-1 text-k-body leading-relaxed text-ink-muted">
                  Search for a table, job or task above. Click any card to isolate its full
                  upstream and downstream path.
                </p>
              </div>
            </div>
          )}

          <ReactFlow
            nodes={flowNodes}
            edges={flowEdges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={onNodeClick}
            onPaneClick={() => setFocusId(null)}
            nodeTypes={lineageNodeTypes}
            minZoom={0.15}
            maxZoom={2}
            proOptions={{ hideAttribution: true }}
            className="kairos-canvas"
            nodesDraggable
            nodesConnectable={false}
          >
            <Background variant={BackgroundVariant.Dots} gap={16} size={1} color="transparent" />
          </ReactFlow>
        </div>

        {detailId && (
          <EntityDetailPanel
            entityId={detailId}
            onClose={() => setDetailId(null)}
            onFocus={(id) => load(id, depth)}
          />
        )}
      </div>
    </>
  );
}

type LineageMode = "mesh" | "explorer";

function ModeSwitch({ mode, onChange }: { mode: LineageMode; onChange: (m: LineageMode) => void }) {
  return (
    <Segmented
      items={[
        { id: "mesh" as const, label: "Mesh" },
        { id: "explorer" as const, label: "Explorer" },
      ]}
      value={mode}
      onChange={onChange}
    />
  );
}

export default function LineagePage() {
  const [mode, setMode] = useState<LineageMode>("mesh");
  const modeSwitch = <ModeSwitch mode={mode} onChange={setMode} />;
  return (
    // Keyed so each view gets a fresh React Flow instance and viewport.
    <ReactFlowProvider key={mode}>
      {mode === "mesh" ? <MeshWorkspace modeSwitch={modeSwitch} /> : <GraphWorkspace modeSwitch={modeSwitch} />}
    </ReactFlowProvider>
  );
}
