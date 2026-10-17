"use client";

/**
 * A small line of a metric's monthly series, drawn by the screen (not the model):
 * the flagged period is ringed, the normal range is a soft band, and periods that may
 * still change are dashed. Hovering a point shows its month and value.
 */

import { useState } from "react";

import { fmt, monthLabel } from "@/lib/living";

export function Sparkline({
  points,
  highlight,
  band,
  provisionalFrom,
  width = 240,
  height = 56,
  tone = "var(--brand)",
}: {
  points: [string, number][];
  highlight?: string | null;
  band?: [number, number] | null;
  provisionalFrom?: number;
  width?: number;
  height?: number;
  tone?: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  if (points.length < 2) return <div style={{ width, height }} className="rounded bg-sunken" />;
  const vals = points.map((p) => p[1]);
  const lo = Math.min(...vals, ...(band ?? []));
  const hi = Math.max(...vals, ...(band ?? []));
  const pad = 4;
  const x = (i: number) => pad + (i * (width - 2 * pad)) / (points.length - 1);
  const y = (v: number) => (hi === lo ? height / 2 : height - pad - ((v - lo) * (height - 2 * pad)) / (hi - lo));
  const cut = provisionalFrom ?? points.length;
  const path = (from: number, to: number) =>
    points
      .slice(from, to)
      .map((p, i) => `${i ? "L" : "M"} ${x(from + i).toFixed(1)} ${y(p[1]).toFixed(1)}`)
      .join(" ");
  const hi_i = highlight ? points.findIndex((p) => p[0].slice(0, 7) === highlight.slice(0, 7)) : -1;
  return (
    <svg
      width={width}
      height={height}
      className="overflow-visible"
      onMouseLeave={() => setHover(null)}
      onMouseMove={(e) => {
        const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
        const i = Math.round(((e.clientX - r.left - pad) / (width - 2 * pad)) * (points.length - 1));
        setHover(Math.max(0, Math.min(points.length - 1, i)));
      }}
    >
      {band && (
        <rect x={pad} width={width - 2 * pad} y={y(band[1])} height={Math.max(1, y(band[0]) - y(band[1]))} fill="var(--brand-soft)" opacity={0.7} />
      )}
      <path d={path(0, Math.min(cut, points.length))} fill="none" stroke={tone} strokeWidth={1.8} strokeLinejoin="round" />
      {cut < points.length && (
        <path d={path(Math.max(0, cut - 1), points.length)} fill="none" stroke={tone} strokeWidth={1.8} strokeDasharray="3 3" opacity={0.7} />
      )}
      {hi_i >= 0 && (
        <circle cx={x(hi_i)} cy={y(points[hi_i][1])} r={4.5} fill="var(--surface)" stroke="var(--warn-dot)" strokeWidth={2} />
      )}
      <circle cx={x(points.length - 1)} cy={y(points[points.length - 1][1])} r={2.2} fill={tone} />
      {hover !== null && (
        <g>
          <line x1={x(hover)} x2={x(hover)} y1={0} y2={height} stroke="var(--hairline-strong)" />
          <circle cx={x(hover)} cy={y(points[hover][1])} r={3} fill={tone} />
          <text
            x={Math.min(Math.max(x(hover), 40), width - 40)}
            y={-4}
            textAnchor="middle"
            className="fill-ink-2 text-[10px] font-medium"
          >
            {monthLabel(points[hover][0])} · {fmt(points[hover][1])}
          </text>
        </g>
      )}
    </svg>
  );
}
