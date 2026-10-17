"use client";

/**
 * A data product's supply chain as lanes: sources → raw → staging → facts &
 * dimensions → marts. Positions are computed, not measured, so edges are exact:
 * each lane is a column, and nodes in a lane are ordered by where their inputs
 * sit, which keeps lines from crossing. Edges draw in; dots travel into the
 * output tables. Hovering a node lights up its own lines.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { Database, HardDrive, Star } from "lucide-react";

import { stagger } from "@/components/kairos/ds";
import { cn } from "@/lib/utils";
import { entityLabel, LANE_LABEL, pretty, tail, type Bundle, type Lane, type Trust } from "@/lib/products";

const MIN_COL_W = 120;
const MAX_COL_W = 210;
const GAP_X = 40;
const NODE_H = 54;
const GAP_Y = 14;
const HEAD = 34;

type Node = {
  id: string;
  lane: Lane;
  label: string;
  sub: string;
  trust?: Trust | null;
  port: boolean;
  source: boolean;
};

const TRUST_DOT: Record<string, string> = { verified: "var(--ok-dot)", profiled: "var(--warn-dot)", synced: "var(--neutral-dot)" };

export function ProductFlow({ bundle, selected, onSelect }: { bundle: Bundle; selected?: string | null; onSelect?: (id: string) => void }) {
  const [hover, setHover] = useState<string | null>(null);
  // Lanes share the panel's width, so the whole flow is visible without scrolling.
  const box = useRef<HTMLDivElement>(null);
  const [avail, setAvail] = useState(900);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setAvail(Math.floor(e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const layout = useMemo(() => {
    const nodes: Node[] = [
      ...bundle.sources.map((o) => ({
        id: o.entity_id, lane: "source" as Lane, port: false, source: true, sub: pretty(o.kind),
        // A location is its path; its last segment alone ("raw") says nothing.
        label: o.kind === "location" ? entityLabel(o.entity_id) : o.name,
      })),
      ...bundle.members.map((m) => ({
        id: m.entity_id, lane: m.lane, label: m.name, sub: pretty(m.role) || pretty(m.layer) || "table",
        trust: m.trust, port: m.output_port, source: false,
      })),
    ];
    const ids = new Set(nodes.map((n) => n.id));
    const edges = bundle.flow.filter((e) => ids.has(e.source) && ids.has(e.target));
    const lanes = (["source", "raw", "staging", "core", "mart"] as Lane[]).filter((l) => nodes.some((n) => n.lane === l));
    const COL_W = Math.max(MIN_COL_W, Math.min(MAX_COL_W, Math.floor((avail - (lanes.length - 1) * GAP_X) / Math.max(1, lanes.length))));

    // Order each lane by the mean row of its inputs (barycentre), left to right.
    const row: Record<string, number> = {};
    const byLane: Record<string, Node[]> = {};
    for (const lane of lanes) {
      const here = nodes.filter((n) => n.lane === lane);
      const weight = (n: Node) => {
        const ins = edges.filter((e) => e.target === n.id && row[e.source] !== undefined).map((e) => row[e.source]);
        return ins.length ? ins.reduce((a, b) => a + b, 0) / ins.length : Number.MAX_SAFE_INTEGER;
      };
      here.sort((a, b) => weight(a) - weight(b) || Number(a.port) - Number(b.port) || a.label.localeCompare(b.label));
      here.forEach((n, i) => (row[n.id] = i));
      byLane[lane] = here;
    }
    const pos: Record<string, { x: number; y: number }> = {};
    lanes.forEach((lane, li) => byLane[lane].forEach((n, i) => (pos[n.id] = { x: li * (COL_W + GAP_X), y: HEAD + i * (NODE_H + GAP_Y) })));
    const rows = Math.max(1, ...lanes.map((l) => byLane[l].length));
    const width = lanes.length * COL_W + (lanes.length - 1) * GAP_X;
    const height = HEAD + rows * (NODE_H + GAP_Y);
    const paths = edges.map((e) => {
      const a = pos[e.source], b = pos[e.target];
      const x1 = a.x + COL_W, y1 = a.y + NODE_H / 2, x2 = b.x, y2 = b.y + NODE_H / 2;
      let d: string;
      if (x2 > x1) {
        const mid = (x2 - x1) / 2;
        d = `M ${x1} ${y1} C ${x1 + mid} ${y1}, ${x2 - mid} ${y2}, ${x2} ${y2}`;
      } else {
        // Same lane (a staging table feeding another): loop out to the right and back in.
        const r = 28;
        d = `M ${x1} ${y1} C ${x1 + r} ${y1}, ${x1 + r} ${y2 + NODE_H / 2 + 8}, ${b.x + COL_W / 2} ${b.y + NODE_H}`;
      }
      return { ...e, d };
    });
    return { nodes, lanes, byLane, pos, width, height, paths, COL_W };
  }, [bundle, avail]);
  const COL_W = layout.COL_W;

  const lit = (e: { source: string; target: string }) => !hover || e.source === hover || e.target === hover;

  return (
    <div className="overflow-x-auto px-5 pb-5 pt-3">
      <div ref={box} className="w-full" />
      <div className="relative mx-auto" style={{ width: layout.width, height: layout.height }}>
        {layout.lanes.map((lane, li) => (
          <div
            key={lane}
            className="k-label absolute top-0 flex h-6 items-center truncate whitespace-nowrap"
            style={{ left: li * (COL_W + GAP_X), width: COL_W }}
          >
            {LANE_LABEL[lane]}
            <span className="ml-1.5 tabular-nums opacity-70">{layout.byLane[lane].length}</span>
          </div>
        ))}

        <svg className="pointer-events-none absolute inset-0" width={layout.width} height={layout.height} aria-hidden>
          {layout.paths.map((p, i) => {
            const verified = p.status === "verified";
            return (
              <path
                key={`${p.source}>${p.target}`}
                d={p.d}
                pathLength={1}
                className="k-draw"
                fill="none"
                stroke={verified ? "var(--brand)" : "var(--warn-dot)"}
                strokeWidth={hover && lit(p) ? 2 : 1.5}
                strokeOpacity={lit(p) ? (verified ? 0.55 : 0.8) : 0.08}
                strokeDasharray={verified ? undefined : "4 4"}
                style={{ ...stagger(i % 12), transition: "stroke-opacity .2s, stroke-width .2s" }}
              >
                <title>{`${tail(p.source)} → ${tail(p.target)} · ${p.relation.toLowerCase()} · ${p.status} · ${p.via}`}</title>
              </path>
            );
          })}
        </svg>

        {/* Data travelling into the output tables. */}
        {layout.paths
          .filter((p) => layout.nodes.find((n) => n.id === p.target)?.port)
          .map((p, i) => (
            <span
              key={`dot-${p.source}>${p.target}`}
              aria-hidden
              className="k-travel pointer-events-none absolute left-0 top-0 h-1.5 w-1.5 rounded-full"
              style={{ background: "var(--brand)", offsetPath: `path('${p.d}')`, ...stagger(i) }}
            />
          ))}

        {layout.nodes.map((n, i) => {
          const p = layout.pos[n.id];
          const Icon = n.source ? HardDrive : Database;
          const on = selected === n.id;
          return (
            <button
              key={n.id}
              type="button"
              onClick={() => onSelect?.(n.id)}
              onMouseEnter={() => setHover(n.id)}
              onMouseLeave={() => setHover(null)}
              title={n.id.split(":").slice(2).join(":")}
              className={cn(
                "k-pop absolute flex items-center gap-2 rounded-[10px] border px-2.5 text-left transition-shadow duration-200",
                n.port ? "border-brand bg-brand-soft" : "border-hairline bg-surface",
                on ? "shadow-[0_0_0_3px_var(--brand-soft)] ring-1 ring-brand" : "hover:shadow-[0_6px_18px_rgb(26_29_36/0.08)]"
              )}
              style={{ left: p.x, top: p.y, width: COL_W, height: NODE_H, ...stagger(i % 14) }}
            >
              <span
                className={cn(
                  "flex h-7 w-7 shrink-0 items-center justify-center rounded-full",
                  n.port ? "bg-brand text-white" : "bg-sunken text-ink-muted"
                )}
              >
                {n.port ? <Star className="h-3.5 w-3.5" /> : <Icon className="h-3.5 w-3.5" />}
              </span>
              <span className="min-w-0 flex-1">
                <span className="line-clamp-2 break-all font-mono text-[11.5px] font-semibold leading-tight text-ink">{n.label}</span>
                <span className="flex items-center gap-1.5 truncate text-[11px] text-ink-muted">
                  {n.trust && <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: TRUST_DOT[n.trust] }} />}
                  {n.port ? "input port · " : ""}
                  {n.sub}
                </span>
              </span>
            </button>
          );
        })}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1.5 text-k-caption text-ink-muted">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-0.5 w-5 rounded" style={{ background: "var(--brand)" }} /> verified flow
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-0 w-5 border-t-2 border-dashed" style={{ borderColor: "var(--warn-dot)" }} /> proposed by enrichment
        </span>
        <span className="inline-flex items-center gap-1.5">
          <Star className="h-3 w-3 text-brand" /> input port of the product
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: "var(--ok-dot)" }} /> verified
          <span className="ml-2 h-1.5 w-1.5 rounded-full" style={{ background: "var(--warn-dot)" }} /> profiled
        </span>
      </div>
    </div>
  );
}
