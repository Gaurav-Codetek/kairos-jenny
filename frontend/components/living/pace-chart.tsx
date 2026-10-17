"use client";

/**
 * Today against a normal day, hour by hour. For a number that adds up (orders, revenue) the
 * lines are cumulative: the soft band is where normal days stood at each hour (10th–90th
 * percentile), the dashed line their median, the solid line today up to now. For a rate or an
 * average the points are each hour's value. Hovering shows the hour and both values.
 */

import { useState } from "react";

export function PaceChart({
  typical,
  today,
  tone = "var(--brand)",
  format,
  width = 300,
  height = 92,
}: {
  typical: [number, number, number, number][];
  today: [number, number][];
  tone?: string;
  format: (v: number) => string;
  width?: number;
  height?: number;
}) {
  const [hover, setHover] = useState<number | null>(null);
  if (typical.length < 2) return <div style={{ width, height }} className="rounded-lg bg-sunken" />;
  const padX = 4;
  const padTop = 6;
  const padBottom = 14;
  const all = [...typical.flatMap((t) => [t[1], t[2], t[3]]), ...today.map((t) => t[1])];
  const lo = Math.min(0, ...all);
  const hi = Math.max(...all, 1e-9);
  const x = (h: number) => padX + (h / 24) * (width - 2 * padX);
  const y = (v: number) => height - padBottom - ((v - lo) / (hi - lo || 1)) * (height - padTop - padBottom);
  const line = (pts: [number, number][]) => pts.map((p, i) => `${i ? "L" : "M"} ${x(p[0]).toFixed(1)} ${y(p[1]).toFixed(1)}`).join(" ");
  const band =
    typical.map((t, i) => `${i ? "L" : "M"} ${x(t[0]).toFixed(1)} ${y(t[3]).toFixed(1)}`).join(" ") +
    " " +
    [...typical].reverse().map((t) => `L ${x(t[0]).toFixed(1)} ${y(t[2]).toFixed(1)}`).join(" ") +
    " Z";
  const now = today[today.length - 1];
  const hoverT = hover === null ? null : typical.reduce((best, t) => (Math.abs(t[0] - hover) < Math.abs(best[0] - hover) ? t : best), typical[0]);
  const hoverToday = hover === null ? null : today.filter((t) => t[0] <= hover + 0.5).pop() ?? null;
  return (
    <div className="relative">
      <svg
        width={width}
        height={height}
        className="block overflow-visible"
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => {
          const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
          setHover(Math.max(0, Math.min(24, ((e.clientX - r.left - padX) / (width - 2 * padX)) * 24)));
        }}
      >
        {[0, 6, 12, 18, 24].map((h) => (
          <g key={h}>
            <line x1={x(h)} x2={x(h)} y1={padTop} y2={height - padBottom} stroke="var(--hairline)" strokeWidth={1} />
            <text x={x(h)} y={height - 2} textAnchor={h === 0 ? "start" : h === 24 ? "end" : "middle"} className="fill-ink-subtle text-[9px]">
              {String(h).padStart(2, "0")}
            </text>
          </g>
        ))}
        <path d={band} fill="var(--brand-soft)" opacity={0.75} />
        <path d={line(typical.map((t) => [t[0], t[1]]))} fill="none" stroke="var(--ink-subtle)" strokeWidth={1.2} strokeDasharray="3 3" />
        {today.length > 1 && <path d={line(today)} pathLength={1} fill="none" stroke={tone} strokeWidth={2} strokeLinejoin="round" className="k-draw" />}
        {now && (
          <>
            <circle cx={x(now[0])} cy={y(now[1])} r={5.5} fill={tone} opacity={0.18} className="k-pulse" style={{ transformBox: "fill-box", transformOrigin: "center" }} />
            <circle cx={x(now[0])} cy={y(now[1])} r={3} fill={tone} />
          </>
        )}
        {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={padTop} y2={height - padBottom} stroke="var(--hairline-strong)" />}
      </svg>
      {hover !== null && hoverT && (
        <div className="pointer-events-none absolute -top-1 right-0 rounded-md border border-hairline bg-surface px-2 py-1 text-[10.5px] shadow-sm">
          <span className="text-ink-subtle">{String(Math.floor(hoverT[0])).padStart(2, "0")}:00 · </span>
          {hoverToday && <span className="font-semibold text-ink">today {format(hoverToday[1])} · </span>}
          <span className="text-ink-muted">normal {format(hoverT[1])}</span>
        </div>
      )}
    </div>
  );
}
