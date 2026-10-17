"use client";

// More forms for Jenny's stage, each for its kind of question (the FT Visual Vocabulary's families):
//   series    change over time — a line per category over days; a second metric gets its own panel (one axis each)
//   heatmap   distribution / pattern — day × hour (or two categories); hatched cells had nothing recorded
//   scatter   correlation — two measures per slice (volume across, the rate up)
//   deviation deviation — each slice above or below its usual, either side of zero
//   share     part-to-whole — one 100% bar, the four biggest and "Other"
// Categorical colours in a fixed order, validated for colour-blindness (light surface): #5148E0 #eb6834 #1baf7a
// #eda100; every series is labelled directly, so identity never rests on colour alone. Sequential = one hue.

import { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "motion/react";
import { line as d3line, curveMonotoneX } from "d3-shape";
import { scaleLinear } from "d3-scale";

import { cn } from "@/lib/utils";
import type { Scene } from "@/lib/stage";

export const SERIES = ["#5148E0", "#eb6834", "#1baf7a", "#eda100"];
const OTHER = "#B4B8C2";
const EASE = [0.22, 1, 0.36, 1] as const;
const T = { frame: 0, normal: 0.2, values: 0.4, focus: 0.95, note: 1.15 };
const HATCH = "repeating-linear-gradient(135deg, var(--hairline) 0 3px, transparent 3px 6px)";

const compact = (v: number | null | undefined) =>
  v == null
    ? "–"
    : Math.abs(v) >= 1e5
      ? `${(v / 1e5).toFixed(1)}L`
      : Math.abs(v) >= 1000
        ? Math.round(v).toLocaleString()
        : Math.abs(v) < 1 && v !== 0
          ? `${(v * 100).toFixed(1)}%`
          : `${+v.toFixed(2)}`;

function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(680);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(300, Math.round(e.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

/** Label positions pushed apart so none overlaps (keeping their order). */
function spread(ys: (number | null)[], gap: number): (number | null)[] {
  const order = ys.map((y, i) => [y, i] as const).filter((d): d is readonly [number, number] => d[0] != null).map(([y, i]) => [y, i]).sort((a, b) => a[0] - b[0]);
  for (let k = 1; k < order.length; k++) order[k][0] = Math.max(order[k][0], order[k - 1][0] + gap);
  const out = ys.slice();
  order.forEach(([y, i]) => (out[i] = y));
  return out;
}

function Legend({ items }: { items: { label: string; color: string; dim?: boolean }[] }) {
  return (
    <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-ink-muted">
      {items.map((it) => (
        <span key={it.label} className={cn("inline-flex items-center gap-1.5 transition-opacity", it.dim && "opacity-40")}>
          <span className="h-[3px] w-4 rounded" style={{ background: it.color }} /> {it.label}
        </span>
      ))}
    </div>
  );
}

// ── series: change over time ─────────────────────────────────────────

export function SeriesScene({ scene, focus }: { scene: Scene; focus: string[] | null }) {
  const [ref, width] = useWidth();
  const [hover, setHover] = useState<number | null>(null);
  const xs = scene.data.x ?? [];
  const labels = scene.data.x_labels ?? xs;
  const panels = scene.data.panels ?? [];
  const lit = new Set(focus ?? []);
  const litLines = panels[0]?.lines.filter((l) => lit.has(l.key)).map((l) => l.key) ?? [];
  const litX = xs.findIndex((x) => lit.has(`x:${x}`));
  const H = panels.length > 1 ? 170 : 260;
  const pad = { l: 8, r: 112, t: 10, b: 26 };
  const x = scaleLinear().domain([0, Math.max(1, xs.length - 1)]).range([pad.l + 56, width - pad.r]);
  const step = labels.length > 10 ? Math.ceil(labels.length / 8) : 1;
  return (
    <div ref={ref} className="space-y-3">
      <Legend items={(panels[0]?.lines ?? []).map((l, i) => ({ label: l.label, color: SERIES[i % 4], dim: litLines.length > 0 && !litLines.includes(l.key) }))} />
      {panels.map((p, pi) => {
        const vals = p.lines.flatMap((l) => l.values.filter((v): v is number => v != null));
        const hi = Math.max(...vals, 1e-9) * 1.1;
        const y = scaleLinear().domain([0, hi]).range([H - pad.b, pad.t]);
        const ends = spread(
          p.lines.map((ln) => {
            const at = ln.values.reduce<number>((a, v, i) => (v != null ? i : a), -1);
            return at < 0 ? null : y(ln.values[at] as number) + 4;
          }),
          15
        );
        return (
          <div key={p.metric_label} className="relative">
            {panels.length > 1 && <p className="mb-1 text-[11px] font-medium text-ink-muted">{p.metric_label}</p>}
            <svg
              width={width}
              height={H}
              className="block overflow-visible"
              onMouseLeave={() => setHover(null)}
              onMouseMove={(e) => {
                const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
                setHover(Math.max(0, Math.min(xs.length - 1, Math.round(x.invert(e.clientX - r.left)))));
              }}
            >
              {[0, 0.5, 1].map((f) => (
                <g key={f}>
                  <line x1={pad.l + 56} x2={width - pad.r} y1={y(hi * f)} y2={y(hi * f)} stroke="var(--hairline)" />
                  <text x={pad.l + 22} y={y(hi * f) + 4} textAnchor="end" className="fill-[var(--ink-subtle)] text-[10px]">
                    {compact(hi * f)}
                  </text>
                </g>
              ))}
              {pi === panels.length - 1 &&
                labels.map((l, i) =>
                  i % step === 0 || i === labels.length - 1 ? (
                    <text key={i} x={x(i)} y={H - 6} textAnchor="middle" className={cn("text-[10.5px]", i === litX ? "fill-[var(--ink)] font-semibold" : "fill-[var(--ink-subtle)]")}>
                      {l}
                    </text>
                  ) : null
                )}
              {litX >= 0 && (
                <motion.rect initial={{ opacity: 0 }} animate={{ opacity: 1 }} x={x(litX) - 16} width={32} y={pad.t} height={H - pad.b - pad.t} rx={6} fill="var(--brand-soft)" />
              )}
              {p.lines.map((ln, li) => {
                const pts = ln.values.map((v, i) => [i, v] as const).filter((d): d is readonly [number, number] => d[1] != null);
                const path = d3line<readonly [number, number]>().x((d) => x(d[0])).y((d) => y(d[1])).curve(curveMonotoneX)(pts) ?? "";
                const on = litLines.length === 0 || litLines.includes(ln.key);
                const last = pts[pts.length - 1];
                const color = SERIES[li % 4];
                return (
                  <g key={ln.key} style={{ opacity: on ? 1 : 0.25, transition: "opacity 300ms" }}>
                    <motion.path d={path} fill="none" stroke={color} strokeWidth={2.5} strokeLinecap="round" initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ delay: T.values + li * 0.12, duration: 0.8, ease: EASE }} />
                    {pts.map(([i, v]) => (
                      <motion.circle key={i} cx={x(i)} cy={y(v)} r={i === litX || i === hover ? 5 : 3.5} fill={color} stroke="var(--surface)" strokeWidth={1.5} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: T.values + 0.5 }} />
                    ))}
                    {last && (
                      <motion.text initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: T.focus }} x={x(last[0]) + 10} y={ends[li] ?? y(last[1]) + 4} className="text-[11.5px] font-semibold" fill="var(--ink)">
                        {ln.label.length > 14 ? ln.label.slice(0, 13) + "…" : ln.label}
                      </motion.text>
                    )}
                    {on && litX >= 0 && ln.values[litX] != null && (
                      <text
                        x={x(litX) + (litX === 0 ? 8 : litX === xs.length - 1 ? -8 : 0)}
                        y={y(ln.values[litX] as number) - 10}
                        textAnchor={litX === 0 ? "start" : litX === xs.length - 1 ? "end" : "middle"}
                        className="text-[11px] font-semibold"
                        fill="var(--ink)"
                      >
                        {compact(ln.values[litX])}
                      </text>
                    )}
                  </g>
                );
              })}
            </svg>
            {hover !== null && pi === 0 && (
              <div className="pointer-events-none absolute top-2 z-10 rounded-lg border border-hairline bg-surface px-3 py-2 text-[12px] text-ink-2 shadow-lg" style={{ left: Math.min(width - 200, x(hover) + 12) }}>
                <b className="text-ink">{labels[hover]}</b>
                {panels.map((pp) =>
                  pp.lines.map((ln, li) => (
                    <span key={pp.metric_label + ln.key} className="flex items-center gap-1.5">
                      <span className="h-2 w-2 rounded-full" style={{ background: SERIES[li % 4] }} />
                      {panels.length > 1 ? `${pp.metric_label}: ` : `${ln.label}: `}
                      {compact(ln.values[hover])}
                    </span>
                  ))
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── heatmap: patterns in a grid ─────────────────────────────────────

const ramp = (t: number) => {
  // one hue, light → dark (brand-soft → brand-strong)
  const a = [238, 240, 253];
  const b = [63, 55, 201];
  return `rgb(${a.map((v, i) => Math.round(v + (b[i] - v) * t)).join(",")})`;
};

export function HeatmapScene({ scene, focus }: { scene: Scene; focus: string[] | null }) {
  const rows = scene.data.rows ?? [];
  const cols = scene.data.cols ?? [];
  const cells = scene.data.cells ?? [];
  const lo = scene.data.min ?? 0;
  const hi = scene.data.max ?? 1;
  const lit = new Set(focus ?? []);
  const every = cols.length > 12 ? 3 : 1;
  return (
    <div className="overflow-x-auto">
      <div className="mb-2 flex items-center gap-3 text-[11px] text-ink-muted">
        <span>less</span>
        <span className="h-2.5 w-28 rounded" style={{ background: `linear-gradient(90deg, ${ramp(0)}, ${ramp(1)})` }} />
        <span>more</span>
        <span className="ml-3 inline-flex items-center gap-1.5">
          <span className="h-3 w-3 rounded-sm border border-hairline" style={{ backgroundImage: HATCH }} /> nothing recorded
        </span>
      </div>
      <div className="grid gap-[2px]" style={{ gridTemplateColumns: `96px repeat(${cols.length}, minmax(18px, 1fr))` }}>
        <span />
        {cols.map((c, j) => (
          <span key={c.key} className={cn("overflow-visible whitespace-nowrap text-[10px]", lit.has(c.key) ? "font-semibold text-ink" : "text-ink-subtle")}>
            {j % every === 0 ? c.label : ""}
          </span>
        ))}
      </div>
      {rows.map((r, i) => (
        <motion.div
          key={r.key}
          className="mt-[2px] grid gap-[2px]"
          style={{ gridTemplateColumns: `96px repeat(${cols.length}, minmax(18px, 1fr))` }}
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: T.values + i * 0.06, duration: 0.3, ease: EASE }}
        >
          <span className={cn("truncate pr-2 text-[11.5px] leading-6", lit.has(r.key) ? "font-semibold text-ink" : "text-ink-muted")}>{r.label}</span>
          {cols.map((c, j) => {
            const v = cells[i]?.[j];
            const on = lit.size === 0 || lit.has(r.key) || lit.has(c.key);
            return (
              <span
                key={c.key}
                title={`${r.label}, ${c.label}: ${v == null ? "nothing recorded" : compact(v)}`}
                className={cn("h-6 rounded-[3px] transition-opacity duration-300", lit.has(r.key) && lit.has(c.key) && "ring-2 ring-ink")}
                style={{ opacity: on ? 1 : 0.3, ...(v == null ? { backgroundImage: HATCH } : { background: ramp(hi > lo ? (v - lo) / (hi - lo) : 0.5) }) }}
              />
            );
          })}
        </motion.div>
      ))}
    </div>
  );
}

// ── scatter: two measures per slice ─────────────────────────────────

export function ScatterScene({ scene, focus }: { scene: Scene; focus: string[] | null }) {
  const [ref, width] = useWidth();
  const pts = scene.data.points ?? [];
  const lit = new Set(focus ?? []);
  const H = 300;
  const pad = { l: 52, r: 24, t: 14, b: 34 };
  const { x, y } = useMemo(() => {
    const xs = pts.map((p) => p.x);
    const ys = pts.map((p) => p.y);
    return {
      x: scaleLinear().domain([0, Math.max(...xs, 1e-9) * 1.05]).range([pad.l, width - pad.r]).nice(),
      y: scaleLinear().domain([Math.min(0, ...ys), Math.max(...ys, 1e-9) * 1.1]).range([H - pad.b, pad.t]).nice(),
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pts, width]);
  const labelled = new Set([...[...pts].sort((a, b) => b.x - a.x).slice(0, 4).map((p) => p.key), ...lit]);
  return (
    <div ref={ref}>
      <svg width={width} height={H} className="block overflow-visible" role="img" aria-label={scene.title}>
        {x.ticks(4).map((t) => (
          <g key={`x${t}`}>
            <line x1={x(t)} x2={x(t)} y1={pad.t} y2={H - pad.b} stroke="var(--hairline)" />
            <text x={x(t)} y={H - pad.b + 16} textAnchor="middle" className="fill-[var(--ink-subtle)] text-[10px]">{compact(t)}</text>
          </g>
        ))}
        {y.ticks(4).map((t) => (
          <g key={`y${t}`}>
            <line x1={pad.l} x2={width - pad.r} y1={y(t)} y2={y(t)} stroke="var(--hairline)" />
            <text x={pad.l - 8} y={y(t) + 4} textAnchor="end" className="fill-[var(--ink-subtle)] text-[10px]">{compact(t)}</text>
          </g>
        ))}
        <text x={width - pad.r} y={H - 4} textAnchor="end" className="fill-[var(--ink-muted)] text-[11px]">{scene.data.x_label} →</text>
        <text x={pad.l} y={pad.t - 2} className="fill-[var(--ink-muted)] text-[11px]">↑ {scene.data.y_label}</text>
        {pts.map((p, i) => {
          const on = lit.size === 0 || lit.has(p.key);
          return (
            <motion.g key={p.key} initial={{ opacity: 0, scale: 0 }} animate={{ opacity: on ? 1 : 0.3, scale: 1 }} transition={{ delay: T.values + i * 0.02 }} style={{ transformOrigin: `${x(p.x)}px ${y(p.y)}px` }}>
              <circle cx={x(p.x)} cy={y(p.y)} r={lit.has(p.key) ? 8 : 5.5} fill={SERIES[0]} stroke="var(--surface)" strokeWidth={1.5}>
                <title>{`${p.label}: ${scene.data.x_label} ${compact(p.x)}, ${scene.data.y_label} ${compact(p.y)}`}</title>
              </circle>
              {labelled.has(p.key) && (
                <text x={x(p.x) + 10} y={y(p.y) + 4} className={cn("text-[11px]", lit.has(p.key) ? "font-semibold" : "")} fill="var(--ink)">{p.label}</text>
              )}
            </motion.g>
          );
        })}
      </svg>
    </div>
  );
}

// ── deviation: above or below usual ──────────────────────────────────

export function DeviationScene({ scene, focus }: { scene: Scene; focus: string[] | null }) {
  const rows = (scene.data.rows ?? []).slice(0, 10);
  const lim = Math.max(...rows.map((r) => Math.abs(r.pct ?? 0)), 1) * 1.1;
  const lit = new Set(focus ?? []);
  return (
    <div className="space-y-1">
      <div className="mb-2 flex items-center gap-4 text-[11px] text-ink-muted">
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-4 rounded-l-[3px]" style={{ background: SERIES[1] }} /> below its usual</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-4 rounded-r-[3px]" style={{ background: SERIES[0] }} /> above its usual</span>
      </div>
      {rows.map((r, i) => {
        const pct = r.pct ?? 0;
        const w = (Math.abs(pct) / lim) * 50;
        const on = lit.size === 0 || lit.has(r.key);
        return (
          <div key={r.key} className="grid grid-cols-[120px_minmax(0,1fr)_64px] items-center gap-3" style={{ opacity: on ? 1 : 0.35, transition: "opacity 300ms" }}>
            <span className={cn("truncate text-k-body", on && lit.size ? "font-semibold text-ink" : "text-ink-2")}>{r.label}</span>
            <span className="relative h-6">
              <span className="absolute inset-y-0 left-1/2 w-px bg-ink-subtle" />
              <motion.span
                className={cn("absolute inset-y-1", pct >= 0 ? "rounded-r-[4px]" : "rounded-l-[4px]")}
                style={{ background: pct >= 0 ? SERIES[0] : SERIES[1], backgroundImage: r.low_volume ? HATCH : undefined, [pct >= 0 ? "left" : "right"]: "50%" }}
                initial={{ width: 0 }}
                animate={{ width: `${w}%` }}
                transition={{ delay: T.values + i * 0.05, duration: 0.5, ease: EASE }}
              />
            </span>
            <span className="text-right text-k-body tabular-nums text-ink">{pct > 0 ? "+" : ""}{pct.toFixed(1)}%</span>
          </div>
        );
      })}
    </div>
  );
}

// ── share: part of the whole ─────────────────────────────────────────

export function ShareScene({ scene, focus }: { scene: Scene; focus: string[] | null }) {
  const parts = scene.data.parts ?? [];
  const lit = new Set(focus ?? []);
  const color = (p: { key: string }, i: number) => (p.key === "Other" ? OTHER : SERIES[i % 4]);
  return (
    <div className="space-y-4 py-2">
      <div className="flex h-14 w-full overflow-hidden rounded-lg">
        {parts.map((p, i) => (
          <motion.div
            key={p.key}
            title={`${p.label}: ${(p.share * 100).toFixed(1)}%`}
            className="h-full border-r-2 border-surface last:border-r-0"
            style={{ background: color(p, i), opacity: lit.size === 0 || lit.has(p.key) ? 1 : 0.3 }}
            initial={{ width: 0 }}
            animate={{ width: `${p.share * 100}%` }}
            transition={{ delay: T.values + i * 0.08, duration: 0.6, ease: EASE }}
          />
        ))}
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        {parts.map((p, i) => (
          <div key={p.key} className={cn("flex items-center gap-2 text-k-body", lit.size && !lit.has(p.key) && "opacity-40")}>
            <span className="h-3 w-3 rounded-sm" style={{ background: color(p, i) }} />
            <span className={cn("min-w-0 flex-1 truncate", lit.has(p.key) ? "font-semibold text-ink" : "text-ink-2")}>{p.label}</span>
            <span className="tabular-nums font-semibold text-ink">{(p.share * 100).toFixed(1)}%</span>
            <span className="w-16 text-right text-[11px] tabular-nums text-ink-subtle">{compact(p.value)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
