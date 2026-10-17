"use client";

// The scenes Jenny puts on her stage, each drawn from her own lookup's numbers (see lib/stage.ts).
//
// Motion follows Heer & Robertson's staging — the frame first, then what's normal, then the values, then the focus,
// then the note — one change at a time. Each slice keeps its mark and colour wherever it appears. Colour does one
// job: brand for the values, a lighter step of the same hue for what's not in focus (validated pair: #5148E0 /
// #8F89EC), ink for "usual". Every mark is labelled, so nothing relies on colour alone, and every mark can be
// pointed at.

import { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "motion/react";
import { area as d3area, line as d3line, curveMonotoneX } from "d3-shape";
import { scaleLinear } from "d3-scale";

import { StatusPill } from "@/components/kairos/ds";
import { cn } from "@/lib/utils";
import type { BarRow, Scene } from "@/lib/stage";

export const FOCUS = "#5148E0";
export const CONTEXT = "#8F89EC";
const EASE = [0.22, 1, 0.36, 1] as const;
// The staging: frame → normal → values → focus → note (seconds).
const T = { frame: 0, normal: 0.2, values: 0.4, focus: 0.95, note: 1.15 };
const HATCH = `repeating-linear-gradient(135deg, ${CONTEXT} 0 3px, transparent 3px 6px)`;

type Point = (row: BarRow) => void;

const compact = (v: number) =>
  Math.abs(v) >= 1e5 ? `${(v / 1e5).toFixed(1)}L` : Math.abs(v) >= 1e3 ? v.toLocaleString(undefined, { maximumFractionDigits: 0 }) : `${+v.toFixed(2)}`;

function Note({ text, delay = T.note }: { text: string; delay?: number }) {
  return (
    <motion.span
      initial={{ opacity: 0, x: -6 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay, duration: 0.3, ease: EASE }}
      className="inline-flex items-center rounded-full border border-brand-border bg-brand-soft px-2 py-0.5 text-[11px] font-medium text-brand-strong"
    >
      {text}
    </motion.span>
  );
}

// ── breakdown: slices ranked, today against each one's usual ────────────

export function BreakdownScene({ scene, focus, onPoint }: { scene: Scene; focus: string[] | null; onPoint: Point }) {
  const rows = scene.data.rows ?? [];
  const max = Math.max(...rows.map((r) => Math.max(r.value, r.usual ?? 0)), 1e-9) * 1.08;
  const lit = new Set(focus ?? []);
  const any = lit.size > 0;
  const note = scene.annotations[0];
  return (
    <div>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: T.frame, duration: 0.25 }}
        className="mb-2 flex items-center gap-4 pl-[148px] text-[11px] text-ink-muted"
      >
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-4 rounded-r-[3px]" style={{ background: FOCUS }} />{" "}
          {rows.some((r) => r.usual != null) ? "today so far" : scene.metric_label}
        </span>
        {rows.some((r) => r.usual != null) && (
          <span className="inline-flex items-center gap-1.5">
            <span className="h-3 w-[2px] rounded bg-ink" /> usual
          </span>
        )}
        {rows.some((r) => r.low_volume) && (
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-4 rounded-r-[3px]" style={{ background: HATCH }} /> too few orders to read
          </span>
        )}
      </motion.div>
      <div className="space-y-0.5">
        {rows.map((r, i) => {
          const on = !any || lit.has(r.key);
          const w = (r.value / max) * 100;
          const u = r.usual != null ? (r.usual / max) * 100 : null;
          return (
            <motion.button
              key={r.key}
              layout="position"
              onClick={() => onPoint(r)}
              className="group relative grid w-full grid-cols-[136px_minmax(0,1fr)_auto] items-center gap-3 rounded-lg px-1.5 py-1 text-left hover:bg-sunken"
              aria-label={`${r.label}: ${r.display ?? r.value}${r.usual_display ? `, usual ${r.usual_display}` : ""}`}
            >
              <span className={cn("truncate text-k-body transition-colors duration-300", on ? "font-semibold text-ink" : "text-ink-muted")}>
                {r.label}
              </span>
              <span className="relative h-7">
                <motion.span
                  className="absolute inset-y-1 left-0 rounded-r-[4px]"
                  style={{ backgroundImage: r.low_volume ? HATCH : undefined }}
                  initial={{ width: 0, backgroundColor: FOCUS }}
                  animate={{ width: `${w}%`, backgroundColor: r.low_volume ? "rgba(0,0,0,0)" : on ? FOCUS : CONTEXT }}
                  transition={{
                    width: { delay: T.values + i * 0.05, duration: 0.55, ease: EASE },
                    backgroundColor: { duration: 0.3 },
                  }}
                />
                {u != null && (
                  <motion.span
                    className="absolute inset-y-0 w-[2px] rounded bg-ink"
                    style={{ left: `calc(${u}% - 1px)` }}
                    initial={{ opacity: 0, scaleY: 0.4 }}
                    animate={{ opacity: on ? 0.9 : 0.35, scaleY: 1 }}
                    transition={{ delay: T.normal + i * 0.03, duration: 0.25 }}
                  />
                )}
              </span>
              <span className="flex items-center gap-2 whitespace-nowrap text-k-body tabular-nums">
                <span className={on ? "font-semibold text-ink" : "text-ink-muted"}>{r.display ?? compact(r.value)}</span>
                {r.usual_display ? (
                  <span className="text-[11px] text-ink-subtle">usual {r.usual_display}</span>
                ) : (
                  r.extra_display && <span className="text-[11px] text-ink-subtle">{r.extra_display}</span>
                )}
                {note && note.key === r.key && on && <Note text={note.text} />}
              </span>
              {/* hover: everything known about this slice */}
              <span className="pointer-events-none absolute left-[148px] top-full z-10 mt-1 hidden rounded-lg border border-hairline bg-surface px-3 py-2 text-[12px] text-ink-2 shadow-lg group-hover:block">
                <b className="text-ink">{r.label}</b> · {r.display ?? compact(r.value)}
                {r.usual_display && <> against usual {r.usual_display}</>}
                {r.change_pct != null && <> ({r.change_pct > 0 ? "+" : ""}{r.change_pct}%)</>}
                {r.volume_display && <> · {r.volume_display}</>}
                {r.extra_display && <> · {r.extra_display}</>}
                {r.low_volume && <> · too few to read</>}
                <span className="block text-[11px] text-ink-subtle">Click to ask Jenny about it</span>
              </span>
            </motion.button>
          );
        })}
      </div>
    </div>
  );
}

// ── hours: each hour of today against the same hour normally ───────────

export function HoursScene({ scene, focus, onPoint }: { scene: Scene; focus: string[] | null; onPoint: Point }) {
  const rows = scene.data.rows ?? [];
  const max = Math.max(...rows.map((r) => Math.max(r.value ?? 0, r.high ?? 0, r.usual ?? 0)), 1e-9) * 1.1;
  const lit = new Set(focus ?? []);
  const any = lit.size > 0;
  const pct = (v: number) => `${(v / max) * 100}%`;
  const note = scene.annotations[0];
  return (
    <div>
      <div className="mb-2 flex items-center gap-4 text-[11px] text-ink-muted">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-3 w-3 rounded-t-[3px]" style={{ background: FOCUS }} /> today
        </span>
        {rows.some((r) => r.low != null) && (
          <span className="inline-flex items-center gap-1.5">
            <span className="h-3 w-3 rounded-sm bg-brand-soft ring-1 ring-brand-border" /> normal range
          </span>
        )}
        {rows.some((r) => r.usual != null) && (
          <span className="inline-flex items-center gap-1.5">
            <span className="h-[2px] w-3 rounded bg-ink" /> usual
          </span>
        )}
      </div>
      <div className="flex h-[240px] items-end gap-[2px]">
        {rows.map((r, i) => {
          const on = !any || lit.has(r.key);
          return (
            <button
              key={r.key}
              onClick={() => onPoint(r)}
              className="group relative flex h-full min-w-0 flex-1 flex-col justify-end"
              aria-label={`${r.label}: ${r.display ?? r.value}${r.usual_display ? `, usual ${r.usual_display}` : ""}`}
            >
              <span className="relative block h-[calc(100%-22px)] w-full">
                {r.low != null && r.high != null && (
                  <motion.span
                    className="absolute inset-x-0 rounded-sm bg-brand-soft"
                    style={{ bottom: pct(r.low), height: `calc(${pct(r.high)} - ${pct(r.low)})` }}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: T.normal + i * 0.02 }}
                  />
                )}
                <motion.span
                  className="absolute inset-x-[18%] bottom-0 rounded-t-[4px]"
                  style={{ backgroundImage: r.partial ? HATCH : undefined }}
                  initial={{ height: 0, backgroundColor: FOCUS }}
                  animate={{ height: pct(r.value ?? 0), backgroundColor: r.partial ? "rgba(0,0,0,0)" : on ? FOCUS : CONTEXT }}
                  transition={{ height: { delay: T.values + i * 0.04, duration: 0.55, ease: EASE }, backgroundColor: { duration: 0.3 } }}
                />
                {r.usual != null && (
                  <motion.span
                    className="absolute inset-x-[8%] h-[2px] rounded bg-ink"
                    style={{ bottom: pct(r.usual) }}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: on ? 0.9 : 0.35 }}
                    transition={{ delay: T.normal + i * 0.02 }}
                  />
                )}
                {(on && any) || (note && note.key === r.key) ? (
                  <motion.span
                    className="absolute inset-x-0 text-center text-[11px] font-semibold tabular-nums text-ink"
                    style={{ bottom: `calc(${pct(Math.max(r.value ?? 0, r.high ?? 0))} + 4px)` }}
                    initial={{ opacity: 0, y: 4 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: T.focus }}
                  >
                    {r.display ?? compact(r.value ?? 0)}
                  </motion.span>
                ) : null}
              </span>
              <span className={cn("mt-1 truncate text-center text-[11px]", on ? "font-semibold text-ink" : "text-ink-subtle")}>{r.label}</span>
              <span className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-1 hidden -translate-x-1/2 whitespace-nowrap rounded-lg border border-hairline bg-surface px-3 py-2 text-[12px] text-ink-2 shadow-lg group-hover:block">
                <b className="text-ink">{r.label}</b> · {r.display ?? compact(r.value ?? 0)}
                {r.usual_display && <> against usual {r.usual_display}</>}
                {r.gap_display && <> ({r.gap_display})</>}
                {r.partial && <> · still running</>}
              </span>
            </button>
          );
        })}
      </div>
      {note && (
        <div className="mt-2">
          <Note text={note.text} />
        </div>
      )}
    </div>
  );
}

// ── trend: today against a normal day, hour by hour ───────────────────

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [w, setW] = useState(640);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(280, Math.round(e.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

const hourLabel = (h: number) => {
  const hh = Math.round(h) % 24;
  return hh === 0 ? "12 am" : hh === 12 ? "noon" : hh < 12 ? `${hh} am` : `${hh - 12} pm`;
};

export function TrendScene({ scene, focus }: { scene: Scene; focus: string[] | null }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const typical = scene.data.typical ?? [];
  const today = scene.data.today ?? [];
  const H = 260;
  const pad = { l: 8, r: 64, t: 12, b: 26 };
  const { x, y, band, median, line } = useMemo(() => {
    const hi = Math.max(...typical.flatMap((t) => [t[1], t[3]]), ...today.map((t) => t[1]), 1e-9);
    const x = scaleLinear().domain([0, 24]).range([pad.l, width - pad.r]);
    const y = scaleLinear().domain([0, hi * 1.08]).range([H - pad.b, pad.t]);
    return {
      x,
      y,
      band: d3area<[number, number, number, number]>().x((d) => x(d[0])).y0((d) => y(d[2])).y1((d) => y(d[3])).curve(curveMonotoneX)(typical) ?? "",
      median: d3line<[number, number, number, number]>().x((d) => x(d[0])).y((d) => y(d[1])).curve(curveMonotoneX)(typical) ?? "",
      line: d3line<[number, number]>().x((d) => x(d[0])).y((d) => y(d[1])).curve(curveMonotoneX)(today) ?? "",
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [typical, today, width]);
  const now = today[today.length - 1];
  const nowLit = (focus ?? []).includes("now");
  const at = hover === null ? null : typical.reduce((b, t) => (Math.abs(t[0] - hover) < Math.abs(b[0] - hover) ? t : b), typical[0]);
  const atToday = hover === null ? null : today.filter((t) => t[0] <= hover + 0.5).pop() ?? null;
  return (
    <div ref={ref} className="relative">
      <div className="mb-2 flex items-center gap-4 text-[11px] text-ink-muted">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-[2px] w-4 rounded" style={{ background: FOCUS }} /> today
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-3 w-4 rounded-sm bg-brand-soft" /> normal range
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="w-4 border-t-2 border-dashed border-ink-subtle" /> usual
        </span>
      </div>
      <svg
        width={width}
        height={H}
        className="block overflow-visible"
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => {
          const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
          setHover(Math.max(0, Math.min(24, x.invert(e.clientX - r.left))));
        }}
      >
        {[0, 6, 12, 18, 24].map((h, i) => (
          <motion.g key={h} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: T.frame + i * 0.03 }}>
            <line x1={x(h)} x2={x(h)} y1={pad.t} y2={H - pad.b} stroke="var(--hairline)" />
            <text x={x(h)} y={H - 8} textAnchor="middle" className="fill-[var(--ink-subtle)] text-[11px]">
              {hourLabel(h)}
            </text>
          </motion.g>
        ))}
        <motion.path d={band} fill="var(--brand-soft)" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: T.normal, duration: 0.3 }} />
        <motion.path
          d={median}
          fill="none"
          stroke="var(--ink-subtle)"
          strokeWidth={1.5}
          strokeDasharray="4 4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: T.normal + 0.1, duration: 0.3 }}
        />
        <motion.path
          d={line}
          fill="none"
          stroke={FOCUS}
          strokeWidth={2.5}
          strokeLinecap="round"
          initial={{ pathLength: 0 }}
          animate={{ pathLength: 1 }}
          transition={{ delay: T.values, duration: 0.9, ease: EASE }}
        />
        {now && (
          <motion.g initial={{ opacity: 0, scale: 0.6 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: T.values + 0.85 }}>
            <motion.circle
              cx={x(now[0])}
              cy={y(now[1])}
              r={nowLit ? 11 : 8}
              fill={FOCUS}
              opacity={0.18}
              animate={{ r: nowLit ? [9, 14, 9] : [7, 10, 7] }}
              transition={{ repeat: Infinity, duration: 1.8 }}
            />
            <circle cx={x(now[0])} cy={y(now[1])} r={4.5} fill={FOCUS} stroke="var(--surface)" strokeWidth={2} />
            <text x={x(now[0]) + 10} y={y(now[1]) + 4} className="fill-[var(--ink)] text-[12px] font-semibold">
              {scene.data.actual_display}
            </text>
            {scene.data.expected_display && (
              <text x={x(now[0]) + 10} y={y(now[1]) + 19} className="fill-[var(--ink-muted)] text-[11px]">
                usual {scene.data.expected_display}
              </text>
            )}
          </motion.g>
        )}
        {at && (
          <g>
            <line x1={x(at[0])} x2={x(at[0])} y1={pad.t} y2={H - pad.b} stroke="var(--ink-subtle)" strokeDasharray="2 3" />
            <circle cx={x(at[0])} cy={y(at[1])} r={3} fill="var(--ink-subtle)" />
          </g>
        )}
      </svg>
      {at && (
        <div
          className="pointer-events-none absolute top-8 z-10 rounded-lg border border-hairline bg-surface px-3 py-2 text-[12px] text-ink-2 shadow-lg"
          style={{ left: Math.min(width - 180, Math.max(0, x(at[0]) + 10)) }}
        >
          <b className="text-ink">{hourLabel(at[0])}</b>
          {atToday && <> · today {compact(atToday[1])}</>} · usual {compact(at[1])}
          <span className="block text-[11px] text-ink-subtle">
            normal {compact(at[2])}–{compact(at[3])}
          </span>
        </div>
      )}
    </div>
  );
}

// ── one figure, and two side by side ──────────────────────────────────

const STATUS = { above: "above normal", below: "below normal", normal: "within normal" } as const;

function Figure({
  label,
  display,
  usual,
  status,
  extra,
  delay = 0,
}: {
  label?: string;
  display?: string;
  usual?: string;
  status?: string;
  extra?: string | null;
  delay?: number;
}) {
  const s = (status as keyof typeof STATUS) || "normal";
  return (
    <div className="flex flex-col items-start gap-2">
      {label && <p className="text-k-caption text-ink-muted">{label}</p>}
      <motion.p
        initial={{ opacity: 0, y: 10, scale: 0.96 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ delay: T.values + delay, duration: 0.5, ease: EASE }}
        className="text-[56px] font-bold leading-none tracking-tight text-ink tabular-nums"
      >
        {display}
      </motion.p>
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: T.focus + delay }} className="flex flex-wrap items-center gap-2">
        <StatusPill tone={s === "normal" ? "neutral" : "warn"}>{STATUS[s] ?? s}</StatusPill>
        {usual && <span className="text-k-body text-ink-muted">usual by now {usual}</span>}
        {extra && <span className="text-k-body text-ink-muted">· {extra}</span>}
      </motion.div>
    </div>
  );
}

export function NumberScene({ scene }: { scene: Scene }) {
  const d = scene.data;
  return (
    <div className="py-4">
      <Figure
        display={d.display}
        usual={d.usual_display}
        status={d.status}
        extra={d.projection_display ? `heading for about ${d.projection_display} today` : d.low_display ? `normal ${d.low_display}–${d.high_display}` : null}
      />
    </div>
  );
}

export function CompareScene({ scene, focus }: { scene: Scene; focus: string[] | null }) {
  const items = scene.data.items ?? [];
  const lit = new Set(focus ?? []);
  return (
    <div className="grid gap-6 py-4 sm:grid-cols-2">
      {items.map((it, i) => (
        <div key={it.key} className={cn("rounded-xl p-4 transition-opacity duration-300", lit.size && !lit.has(it.key) && "opacity-50")}>
          <Figure label={it.label} display={it.display} usual={it.usual_display} status={it.status} delay={i * 0.15} />
        </div>
      ))}
    </div>
  );
}
