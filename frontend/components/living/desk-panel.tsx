"use client";

// Jenny's desk: what she has committed to keep an eye on. Each item is a real spec the server runs on every pulse —
// a watch (a metric against a line, read all day: crossings, coming back, a summary at the close) or a check (a
// question she looks into at a set time) — so what she promised in conversation is visible here and can be taken off.

import { useCallback, useEffect, useState } from "react";
import { CalendarClock, Eye, NotebookPen, X } from "lucide-react";

import { Panel, StatusPill, type Tone } from "@/components/kairos/ds";
import { timeAgo } from "@/components/agents/bits";
import { dropDeskItem, getDesk, type DeskItem } from "@/lib/companion";

const FOCUS = "#5148E0";

function status(i: DeskItem): { label: string; tone: Tone } {
  if (i.type === "watch" && i.status === "open") {
    return i.state === "crossed" ? { label: "Over the line now", tone: "warn" } : { label: "Watching", tone: "brand" };
  }
  const other: Record<string, { label: string; tone: Tone }> = {
    open: { label: "Watching", tone: "brand" },
    running: { label: "Looking into it", tone: "warn" },
    tripped: { label: "Crossed · told you", tone: "warn" },
    done: { label: "Checked · told you", tone: "ok" },
    expired: { label: "Ended · summary left", tone: "neutral" },
    cancelled: { label: "Taken off", tone: "neutral" },
  };
  return other[i.status] ?? { label: i.status, tone: "neutral" };
}

/** The threshold as the metric shows its values: "8.0%" for a rate shown in percent, else the number. */
function lineLabel(t: number, sample?: string | null): string {
  if (sample?.trim().endsWith("%") && Math.abs(t) <= 1.5) return `${(t * 100).toFixed(1)}%`;
  return Math.abs(t) >= 1000 ? t.toLocaleString(undefined, { maximumFractionDigits: 0 }) : `${+t.toFixed(2)}`;
}

const mins = (t: string) => {
  const [h, m] = t.split(":").map(Number);
  return h * 60 + m;
};

/** Today's readings against the line: crossings shaded, the line dashed, the latest reading a dot. */
function DayChart({ item }: { item: DeskItem }) {
  const pts = item.readings ?? [];
  const spec = item.spec;
  if (!spec || pts.length < 2) return null;
  const W = 300;
  const H = 54;
  const PLOT = W - 58; // the right end holds the line's label
  const eps = item.episodes ?? [];
  // The day runs from whichever came first, a reading or a crossing (one carried over from before), to now.
  const t0 = Math.min(mins(pts[0][0]), ...eps.map((e) => mins(e.from)));
  const t1 = Math.max(mins(pts[pts.length - 1][0]), t0 + 30);
  const vals = [...pts.map((p) => p[1]), spec.threshold];
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const pad = (hi - lo) * 0.15 || Math.abs(hi) * 0.1 || 1;
  const x = (t: string) => Math.min(PLOT, Math.max(4, ((mins(t) - t0) / (t1 - t0)) * (PLOT - 8) + 4));
  const y = (v: number) => H - 6 - ((v - (lo - pad)) / (hi + pad - (lo - pad))) * (H - 12);
  const path = pts.map((p, i) => `${i ? "L" : "M"} ${x(p[0]).toFixed(1)} ${y(p[1]).toFixed(1)}`).join(" ");
  const last = pts[pts.length - 1];
  return (
    <svg width={W} height={H + 12} className="mt-2 block max-w-full overflow-visible" role="img" aria-label={`Today's readings against the line ${spec.condition} ${spec.threshold}`}>
      {eps.map((e, i) => (
        <rect
          key={i}
          x={x(e.from)}
          width={Math.max(2, x(e.to ?? last[0]) - x(e.from))}
          y={0}
          height={H}
          rx={3}
          fill="var(--warn-soft)"
        />
      ))}
      <line x1={4} x2={PLOT} y1={y(spec.threshold)} y2={y(spec.threshold)} stroke="var(--ink-muted)" strokeDasharray="4 3" />
      <text x={W} y={y(spec.threshold) + 3} textAnchor="end" className="fill-[var(--ink-muted)] text-[10px]">
        line {lineLabel(spec.threshold, item.last?.display)}
      </text>
      <path d={path} fill="none" stroke={FOCUS} strokeWidth={2} strokeLinejoin="round" />
      <circle cx={x(last[0])} cy={y(last[1])} r={3.5} fill={FOCUS} stroke="var(--surface)" strokeWidth={1.5} />
      <text x={4} y={H + 10} className="fill-[var(--ink-subtle)] text-[10px]">
        {`${String(Math.floor(t0 / 60)).padStart(2, "0")}:${String(t0 % 60).padStart(2, "0")}`}
      </text>
      <text x={PLOT} y={H + 10} textAnchor="end" className="fill-[var(--ink-subtle)] text-[10px]">
        {last[0]}
      </text>
    </svg>
  );
}

export function DeskPanel({ workspaceId }: { workspaceId: string | null }) {
  const [items, setItems] = useState<DeskItem[]>([]);

  const load = useCallback(() => {
    if (!workspaceId) return;
    getDesk(workspaceId)
      .then((r) => setItems(r.items))
      .catch(() => undefined);
  }, [workspaceId]);

  useEffect(() => {
    load();
    const t = window.setInterval(load, 30_000);
    return () => window.clearInterval(t);
  }, [load]);

  const open = items.filter((i) => i.status === "open" || i.status === "running");
  const closed = items.filter((i) => !(i.status === "open" || i.status === "running"));

  return (
    <Panel title="Jenny's desk" icon={NotebookPen} meta={open.length ? `${open.length} kept alive` : "nothing promised right now"}>
      {items.length === 0 ? (
        <p className="px-4 py-4 text-k-body text-ink-muted">
          When Jenny says she&apos;ll keep an eye on something or come back to it, it lands here — and she only says so
          once it&apos;s really set up. A watch keeps reading all day and leaves you a summary at the close.
        </p>
      ) : (
        <ul className="divide-y divide-hairline">
          {[...open, ...closed].map((i) => {
            const s = status(i);
            const Icon = i.type === "check" ? CalendarClock : Eye;
            const eps = i.episodes ?? [];
            const summary = (i.summaries ?? []).slice(-1)[0];
            return (
              <li key={i.id} className="flex gap-3 px-4 py-3">
                <Icon className="mt-0.5 h-4 w-4 shrink-0 text-brand" strokeWidth={2} />
                <div className="min-w-0 flex-1">
                  <p className="text-k-body font-medium text-ink">{i.title}</p>
                  <p className="mt-0.5 text-k-caption text-ink-muted">
                    {i.type === "check" ? `Looks into it ${i.at}` : `Until ${i.until}`}
                    {i.last?.display && <> · now {i.last.display}</>}
                    {i.last?.error && <> · couldn&apos;t read: {i.last.error}</>}
                    {i.origin?.question && <> · you asked: “{i.origin.question}”</>}
                    {" · "}set {timeAgo(i.created_at)}
                  </p>
                  {i.type === "watch" && i.status === "open" && (
                    <>
                      <DayChart item={i} />
                      <p className="mt-1 text-[12px] text-ink-2">
                        {eps.length
                          ? `Crossed ${eps.length} time${eps.length === 1 ? "" : "s"} today: ${eps
                              .map((e) => `${e.from}–${e.to ?? "now"}${e.peak_d ? ` (peak ${e.peak_d})` : ""}`)
                              .join(", ")}`
                          : "Hasn't crossed today."}
                      </p>
                    </>
                  )}
                  {summary && (
                    <p className="mt-1.5 border-l-2 border-brand-soft pl-2.5 text-[12px] leading-snug text-ink-2">{summary.text}</p>
                  )}
                  {!summary && i.outcome && i.status !== "cancelled" && (
                    <p className="mt-1.5 border-l-2 border-brand-soft pl-2.5 text-[12px] leading-snug text-ink-2">{i.outcome}</p>
                  )}
                </div>
                <div className="flex shrink-0 items-start gap-1.5">
                  <StatusPill tone={s.tone}>{s.label}</StatusPill>
                  {i.status === "open" && workspaceId && (
                    <button
                      onClick={() => dropDeskItem(workspaceId, i.id).then(load).catch(() => undefined)}
                      className="flex h-6 w-6 items-center justify-center rounded-full text-ink-subtle hover:bg-sunken hover:text-ink"
                      aria-label="Take off Jenny's desk"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
