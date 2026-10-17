"use client";

/**
 * The connection's data products as a graph.
 *
 *  lineage   input tables → data products (with their output ports) → agents that use them.
 *            A table that feeds two products sits between them, so overlap shows at a glance.
 *  semantic  data products ↔ the dimensions they are sliced by. A dimension shared by
 *            several products is the conformed vocabulary between them.
 *
 * Positions are computed (columns, inputs ordered by the products they feed), so the
 * graph is stable between visits. Hovering a node lights its own edges.
 */

import { createContext, memo, useContext, useMemo, useState } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Bot, Braces, CalendarDays, Database, Hash, Layers, Plug, Tag, Wrench } from "lucide-react";

import { cn } from "@/lib/utils";
import { HEALTH_TONE, pretty, tail, type ProductSummary } from "@/lib/products";

export type GraphMode = "lineage" | "semantic";

const INPUT_W = 230;
const INPUT_H = 54;
const PRODUCT_W = 290;
const PRODUCT_H = 196;
const AGENT_W = 210;
const DIM_W = 200;
const COL_GAP = 170;
const ROW_GAP = 16;

const ROLE_COLOR: Record<string, string> = {
  fact: "var(--brand)",
  aggregate: "var(--ok-dot)",
  dimension: "var(--warn-dot)",
  reference: "var(--neutral-dot)",
};
const roleColor = (r: string) => ROLE_COLOR[r] ?? "var(--neutral-dot)";

const handle = "!h-2 !w-2 !min-h-0 !min-w-0 !border-0 !bg-transparent";

// Hover lives in context, not in node data: hovering re-renders the node faces, never the layout.
const HoverCtx = createContext<{ hover: string | null; near: Map<string, Set<string>> }>({ hover: null, near: new Map() });
const useDim = (id: string) => {
  const { hover, near } = useContext(HoverCtx);
  return !!hover && hover !== id && !near.get(hover)?.has(id);
};

// ── nodes ────────────────────────────────────────────────────────────

type InputData = { table: string; roles: string[]; products: number };
type ProductData = { p: ProductSummary; selected: boolean; mode: GraphMode };
type AgentData = { name: string; sub: string; generic: boolean };
type DimData = { name: string; label: string; type: string; products: number };

const InputNode = memo(function InputNode({ id, data }: NodeProps) {
  const d = data as unknown as InputData;
  const role = d.roles[0] ?? "reference";
  return (
    <div
      className={cn(
        "flex items-center gap-2.5 rounded-[10px] border border-hairline bg-surface px-3 transition-opacity duration-200",
        useDim(id) && "opacity-25"
      )}
      style={{ width: INPUT_W, height: INPUT_H, borderLeft: `3px solid ${roleColor(role)}` }}
      title={d.table}
    >
      <Database className="h-3.5 w-3.5 shrink-0 text-ink-subtle" />
      <div className="min-w-0 flex-1">
        <p className="truncate font-mono text-[11.5px] font-semibold text-ink">{tail(d.table)}</p>
        <p className="truncate text-[10.5px] text-ink-muted">
          {d.roles.join(" · ")}
          {d.products > 1 && <span className="ml-1 font-semibold text-brand">· shared by {d.products}</span>}
        </p>
      </div>
      <Handle type="source" position={Position.Right} className={handle} />
    </div>
  );
});

const PORTS = [
  { id: "query", label: "Query port", icon: Braces },
  { id: "tools", label: "Domain tools", icon: Wrench },
  { id: "mcp", label: "MCP", icon: Plug },
] as const;

const ProductNode = memo(function ProductNode({ id, data }: NodeProps) {
  const { p, selected, mode } = data as unknown as ProductData;
  const dim = useDim(id);
  const tone = p.health ? HEALTH_TONE[p.health.status] : "neutral";
  if (p.ghost) {
    return (
      <div
        className={cn(
          "relative flex flex-col overflow-hidden rounded-2xl border-2 border-dashed bg-surface/80 transition-opacity duration-200",
          p.ghost === "failed" ? "border-danger-dot" : "border-brand-border",
          dim && "opacity-30"
        )}
        style={{ width: PRODUCT_W, height: PRODUCT_H }}
      >
        <Handle type="target" position={Position.Left} id="in" className={handle} style={{ top: 34 }} />
        <div className="flex items-center gap-2.5 bg-brand-soft px-3.5 py-2.5 text-brand-strong">
          <Layers className="h-4 w-4 shrink-0" />
          <span className="truncate text-[14px] font-bold">{p.name}</span>
        </div>
        <div className="flex flex-1 flex-col items-center justify-center gap-1.5 px-4 text-center">
          {p.ghost === "building" && <span className="k-spin inline-block h-4 w-4 rounded-full border-2 border-brand-soft" style={{ borderTopColor: "var(--brand)" }} />}
          <p className="text-[12px] font-semibold text-ink-2">
            {p.ghost === "building" ? "Building…" : p.ghost === "failed" ? "Build failed" : "Proposed by the engine"}
          </p>
          <p className="line-clamp-3 text-[11px] text-ink-muted">{p.description}</p>
        </div>
        <Handle type="source" position={Position.Right} id="mcp" className={handle} style={{ top: PRODUCT_H / 2 }} />
      </div>
    );
  }
  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-2xl border bg-surface transition-[opacity,box-shadow] duration-200",
        selected
          ? "border-brand shadow-[0_0_0_4px_var(--brand-soft)]"
          : "border-hairline-strong shadow-[0_10px_30px_-18px_rgb(26_29_36/0.35)] hover:shadow-[0_14px_34px_-16px_rgb(81_72_224/0.45)]",
        dim && "opacity-30"
      )}
      style={{ width: PRODUCT_W, height: PRODUCT_H }}
    >
      <Handle type="target" position={Position.Left} id="in" className={handle} style={{ top: 34 }} />
      <div className="flex items-center gap-2.5 bg-brand px-3.5 py-2.5 text-white">
        <Layers className="h-4 w-4 shrink-0" />
        <span className="truncate text-[14px] font-bold">{p.name}</span>
        <span
          className="ml-auto h-2.5 w-2.5 shrink-0 rounded-full ring-2 ring-white/60"
          style={{ background: `var(--${tone}-dot)` }}
          title={p.health ? `${p.health.status} · ${p.health.ok}/${p.health.total} contracts ok` : undefined}
        />
      </div>
      <div className="px-3.5 pt-2">
        <p className="truncate text-[11px] text-ink-muted">
          {p.domain ?? "data product"} · <span className={p.status === "confirmed" ? "text-ok" : "text-warn"}>{p.status}</span>
        </p>
        <div className="mt-1.5 grid grid-cols-3 gap-1.5 text-center">
          {[
            [p.metrics.length, "metrics"],
            [p.dimensions.length, "dimensions"],
            [p.inputs.length, "inputs"],
          ].map(([n, l]) => (
            <div key={l as string} className="rounded-md bg-sunken py-1">
              <p className="text-[14px] font-bold tabular-nums text-ink">{n}</p>
              <p className="text-[9.5px] uppercase tracking-wide text-ink-subtle">{l}</p>
            </div>
          ))}
        </div>
      </div>
      {mode === "lineage" ? (
        <div className="mt-2 space-y-1 px-3.5">
          {PORTS.map(({ id, label, icon: Icon }) => (
            <div key={id} className="relative flex items-center gap-1.5 text-[11px] text-ink-2">
              <Icon className="h-3 w-3 text-brand" />
              {label}
              {id === "tools" && <span className="text-ink-subtle">· {p.tools.length}</span>}
              <Handle
                type="source"
                position={Position.Right}
                id={id}
                className={cn(handle, "!right-[-14px] !h-2.5 !w-2.5 !rounded-full !border-2 !border-white !bg-brand")}
                style={{ top: 8 }}
              />
            </div>
          ))}
        </div>
      ) : (
        <>
          <div className="mt-2 flex flex-wrap gap-1 px-3.5">
            {p.metrics.slice(0, 8).map((m) => (
              <span key={m.name} className="rounded-full bg-brand-soft px-2 py-0.5 text-[10.5px] font-medium text-brand-strong">
                {m.label || m.name}
              </span>
            ))}
            {p.metrics.length > 8 && <span className="text-[10.5px] text-ink-subtle">+{p.metrics.length - 8}</span>}
          </div>
          <Handle type="source" position={Position.Right} className={handle} style={{ top: PRODUCT_H / 2 }} />
        </>
      )}
    </div>
  );
});

const AgentNode = memo(function AgentNode({ id, data }: NodeProps) {
  const d = data as unknown as AgentData;
  return (
    <div
      className={cn(
        "flex items-center gap-2.5 rounded-full border bg-surface px-3 py-2 transition-opacity duration-200",
        d.generic ? "border-dashed border-hairline-strong" : "border-hairline",
        useDim(id) && "opacity-25"
      )}
      style={{ width: AGENT_W }}
    >
      <Handle type="target" position={Position.Left} className={handle} />
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand">
        <Bot className="h-3.5 w-3.5" />
      </span>
      <div className="min-w-0">
        <p className="truncate text-[12px] font-semibold text-ink">{d.name}</p>
        <p className="truncate text-[10.5px] text-ink-muted">{d.sub}</p>
      </div>
    </div>
  );
});

const DimNode = memo(function DimNode({ id, data }: NodeProps) {
  const d = data as unknown as DimData;
  const Icon = d.type === "time" ? CalendarDays : d.type === "numeric" ? Hash : Tag;
  return (
    <div
      className={cn(
        "flex items-center gap-2 rounded-full border px-3 py-1.5 transition-opacity duration-200",
        d.products > 1 ? "border-brand-border bg-brand-soft" : "border-hairline bg-surface",
        useDim(id) && "opacity-25"
      )}
      style={{ width: DIM_W }}
    >
      <Handle type="target" position={Position.Left} className={handle} />
      <Icon className={cn("h-3.5 w-3.5 shrink-0", d.products > 1 ? "text-brand" : "text-ink-subtle")} />
      <span className="truncate text-[12px] font-medium text-ink">{d.label || pretty(d.name)}</span>
      {d.products > 1 && <span className="ml-auto text-[10.5px] font-semibold text-brand">×{d.products}</span>}
    </div>
  );
});

const nodeTypes = { table: InputNode, product: ProductNode, agent: AgentNode, dim: DimNode };

// ── layout ───────────────────────────────────────────────────────────

function lineage(products: ProductSummary[], selected: string | null) {
  const nodes: Node[] = [];
  const edges: Edge[] = [];
  // Inputs: grouped by the products they feed, shared ones between them.
  const inputs = new Map<string, { table: string; roles: Set<string>; products: number[] }>();
  products.forEach((p, pi) =>
    p.inputs.forEach((i) => {
      const e = inputs.get(i.entity_id) ?? { table: i.table, roles: new Set<string>(), products: [] };
      e.roles.add(i.role);
      if (!e.products.includes(pi)) e.products.push(pi);
      inputs.set(i.entity_id, e);
    })
  );
  const ROLE_ORDER = ["fact", "aggregate", "dimension", "reference"];
  const ordered = [...inputs.entries()].sort(([, a], [, b]) => {
    const pa = a.products.reduce((s, x) => s + x, 0) / a.products.length;
    const pb = b.products.reduce((s, x) => s + x, 0) / b.products.length;
    return pa - pb || ROLE_ORDER.indexOf([...a.roles][0]) - ROLE_ORDER.indexOf([...b.roles][0]) || a.table.localeCompare(b.table);
  });
  const yOf = new Map<string, number>();
  ordered.forEach(([id], i) => yOf.set(id, i * (INPUT_H + ROW_GAP)));

  const productX = INPUT_W + COL_GAP;
  let floor = -Infinity;
  const productY: number[] = [];
  products.forEach((p, pi) => {
    const ys = p.inputs.map((i) => yOf.get(i.entity_id) ?? 0);
    const centre = ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length + INPUT_H / 2 : 0;
    const y = Math.max(centre - PRODUCT_H / 2, floor);
    floor = y + PRODUCT_H + 40;
    productY[pi] = y;
  });

  ordered.forEach(([id, e]) => {
    nodes.push({
      id: `in:${id}`, type: "table", position: { x: 0, y: yOf.get(id)! },
      data: { table: e.table, roles: [...e.roles], products: e.products.length },
    });
  });
  const agentX = productX + PRODUCT_W + COL_GAP;
  const agents = new Map<string, { sub: string; products: number[]; generic: boolean }>();
  products.forEach((p, pi) => {
    if (p.ghost) return;
    const used = p.consumers ?? [];
    if (!used.length) {
      const g = agents.get("any") ?? { sub: "via MCP · not used yet", products: [], generic: true };
      g.products.push(pi);
      agents.set("any", g);
    }
    used.forEach((c) => {
      const a = agents.get(c.agent) ?? { sub: `${c.channel} · ${c.calls} call${c.calls === 1 ? "" : "s"}`, products: [], generic: false };
      a.products.push(pi);
      agents.set(c.agent, a);
    });
  });

  products.forEach((p, pi) => {
    const id = `p:${p.id}`;
    nodes.push({
      id, type: "product", position: { x: productX, y: productY[pi] },
      data: { p, selected: selected === p.id, mode: "lineage" },
    });
    p.inputs.forEach((i) => {
      edges.push({
        id: `e:${i.entity_id}>${p.id}`, source: `in:${i.entity_id}`, target: id, targetHandle: "in",
        style: { stroke: roleColor(i.role), strokeWidth: 1.5, opacity: p.ghost ? 0.45 : 0.85, strokeDasharray: p.ghost ? "5 5" : undefined },
        animated: !p.ghost && i.role === "fact",
      });
    });
  });

  [...agents.entries()].forEach(([name, a], ai) => {
    const ys = a.products.map((pi) => productY[pi] + 150);
    const y = ys.reduce((s, x) => s + x, 0) / ys.length - 20 + ai * 6;
    const id = `ag:${name}`;
    nodes.push({
      id, type: "agent", position: { x: agentX, y },
      data: { name: name === "any" ? "Any agent" : name, sub: a.sub, generic: a.generic },
    });
    a.products.forEach((pi) => {
      const pid = `p:${products[pi].id}`;
      edges.push({
        id: `e:${pid}>${id}`, source: pid, sourceHandle: "mcp", target: id,
        style: { stroke: "var(--brand)", strokeWidth: 1.5, strokeDasharray: a.generic ? "4 4" : undefined, opacity: 0.7 },
      });
    });
  });
  return { nodes, edges };
}

function semantic(products: ProductSummary[], selected: string | null) {
  const nodes: Node[] = [];
  const edges: Edge[] = [];
  const dims = new Map<string, { label: string; type: string; products: number[] }>();
  products.forEach((p, pi) =>
    p.dimensions.forEach((d) => {
      const e = dims.get(d.name) ?? { label: d.label ?? d.name, type: "categorical", products: [] };
      if (/date|day|month|time|hour/.test(d.name)) e.type = "time";
      if (!e.products.includes(pi)) e.products.push(pi);
      dims.set(d.name, e);
    })
  );
  const ordered = [...dims.entries()].sort(
    ([, a], [, b]) => b.products.length - a.products.length || a.products[0] - b.products[0] || a.label.localeCompare(b.label)
  );
  const DIM_H = 34;
  const dimX = PRODUCT_W + COL_GAP + 40;
  ordered.forEach(([name, d], i) => {
    const id = `d:${name}`;
    nodes.push({
      id, type: "dim", position: { x: dimX, y: i * (DIM_H + 12) },
      data: { name, label: d.label, type: d.type, products: d.products.length },
    });
  });
  const span = ordered.length * (DIM_H + 12);
  products.forEach((p, pi) => {
    const id = `p:${p.id}`;
    const y = products.length === 1 ? Math.max(0, span / 2 - PRODUCT_H / 2) : (pi * Math.max(span, products.length * (PRODUCT_H + 40))) / products.length;
    nodes.push({
      id, type: "product", position: { x: 0, y },
      data: { p, selected: selected === p.id, mode: "semantic" },
    });
    p.dimensions.forEach((d) => {
      const shared = (dims.get(d.name)?.products.length ?? 1) > 1;
      edges.push({
        id: `s:${p.id}>${d.name}`, source: id, target: `d:${d.name}`,
        style: { stroke: shared ? "var(--brand)" : "var(--hairline-strong)", strokeWidth: shared ? 1.8 : 1.2, opacity: 0.8 },
      });
    });
  });
  return { nodes, edges };
}

export function ProductGraph({
  products,
  mode,
  selected,
  onSelect,
  padLeft = 0,
}: {
  products: ProductSummary[];
  mode: GraphMode;
  selected: string | null;
  onSelect: (id: string | null) => void;
  /** Room kept free on the left for an overlaid panel, in pixels. */
  padLeft?: number;
}) {
  const [hover, setHover] = useState<string | null>(null);
  // The layout depends on the products only; hover changes nothing but highlighting.
  const { nodes, edges: base } = useMemo(
    () => (mode === "lineage" ? lineage(products, selected) : semantic(products, selected)),
    [products, mode, selected]
  );
  const near = useMemo(() => {
    const m = new Map<string, Set<string>>();
    for (const e of base) {
      if (!m.has(e.source)) m.set(e.source, new Set());
      if (!m.has(e.target)) m.set(e.target, new Set());
      m.get(e.source)!.add(e.target);
      m.get(e.target)!.add(e.source);
    }
    return m;
  }, [base]);
  const edges = useMemo(
    () =>
      hover
        ? base.map((e) => {
            const lit = e.source === hover || e.target === hover;
            return { ...e, style: { ...e.style, opacity: lit ? 1 : 0.08, strokeWidth: lit ? 2.2 : e.style?.strokeWidth } };
          })
        : base,
    [base, hover]
  );
  const ctx = useMemo(() => ({ hover, near }), [hover, near]);

  return (
    <HoverCtx.Provider value={ctx}>
      <ReactFlow
      key={`${mode}:${padLeft}:${products.map((p) => p.id).join(",")}`}
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      nodesDraggable={false}
      nodesConnectable={false}
      fitView
      fitViewOptions={{ padding: padLeft ? { top: "6%", bottom: "8%", right: "4%", left: `${padLeft}px` } : 0.18, maxZoom: 1.1 }}
      minZoom={0.2}
      proOptions={{ hideAttribution: true }}
      onNodeClick={(_, n) => onSelect(n.id.startsWith("p:") ? n.id.slice(2) : null)}
      onPaneClick={() => onSelect(null)}
      onNodeMouseEnter={(_, n) => setHover(n.id)}
      onNodeMouseLeave={() => setHover(null)}
    >
      <Background variant={BackgroundVariant.Dots} gap={22} size={1.2} color="var(--hairline-strong)" />
      <Controls showInteractive={false} position="bottom-left" />
      </ReactFlow>
    </HoverCtx.Provider>
  );
}
