"use client";

/**
 * The companion's live view: its headline, each vital today against a normal day at this
 * time, and the moments it noticed — drawn from the snapshot its heartbeat keeps current.
 */

import { useMemo } from "react";
import { CheckCircle2, ChevronRight, Radar, Sunrise, TrendingDown, TrendingUp, Unplug, Zap } from "lucide-react";

import { EmptyState, KairosMark, Spinner, StatusPill, Switch, type Tone } from "@/components/kairos/ds";
import { PaceChart } from "@/components/living/pace-chart";
import { timeAgo } from "@/components/agents/bits";
import { offsetLabel, type CompanionState, type Moment, type Vital } from "@/lib/companion";
import { fmt, sendFeedback } from "@/lib/living";
import { cn } from "@/lib/utils";

const VALENCE_TONE: Record<string, Tone> = { bad: "danger", good: "ok", neutral: "brand" };

function valueFormat(v: Pick<Vital, "unit" | "metric">) {
  const u = (v.unit || "").toLowerCase();
  if (["ratio", "rate", "share", "fraction"].includes(u) || /rate|share|ratio/.test(v.metric)) return (x: number) => `${(x * 100).toFixed(1)}%`;
  if (["minutes", "minute", "min"].includes(u) || /time_min|minutes|_min$/.test(v.metric)) return (x: number) => `${x.toFixed(1)} min`;
  return fmt;
}

function statusPill(v: Vital) {
  if (v.status === "above" || v.status === "below") {
    const pct = v.dev_pct != null ? `${Math.abs(v.dev_pct).toFixed(1)}% ` : "";
    return (
      <StatusPill tone={VALENCE_TONE[v.valence ?? "neutral"]} size="sm">
        {pct}
        {v.status} normal
      </StatusPill>
    );
  }
  const label: Record<string, [Tone, string]> = {
    normal: ["ok", "on track"],
    early: ["neutral", "early in the day"],
    stale: ["neutral", "not live"],
    learning: ["neutral", "learning normal"],
    error: ["danger", "can't read"],
  };
  const [tone, text] = label[v.status] ?? ["neutral", v.status];
  return (
    <StatusPill tone={tone} size="sm">
      {text}
    </StatusPill>
  );
}

export function VitalCard({ v, index, localTime }: { v: Vital; index: number; localTime: string | null }) {
  const format = valueFormat(v);
  const tone = v.status === "above" || v.status === "below" ? (v.valence === "bad" ? "var(--danger-dot)" : v.valence === "good" ? "var(--ok-dot)" : "var(--brand)") : "var(--brand)";
  return (
    <article className="kairos-panel k-rise flex flex-col px-4 pb-3 pt-3.5" style={{ ["--i" as string]: index }} title={v.why}>
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <p className="truncate text-k-body font-semibold text-ink">{v.label}</p>
          <p className="truncate text-[11px] text-ink-subtle">{v.product}</p>
        </div>
        {statusPill(v)}
      </div>
      {v.actual_display ? (
        <>
          <p className="mt-2 flex items-baseline gap-2">
            <span className="text-[26px] font-semibold leading-none tabular-nums text-ink">{v.actual_display}</span>
            <span className="text-k-caption text-ink-muted">{v.additive ? "so far today" : "today so far"}</span>
          </p>
          <p className="mt-1 text-[12px] text-ink-muted">
            Normal by {localTime ?? "now"}: <span className="font-medium text-ink-2 tabular-nums">{v.expected_display}</span>
            {v.low_display && v.high_display && v.low_display !== v.high_display && (
              <span className="text-ink-subtle"> ({v.low_display}–{v.high_display})</span>
            )}
          </p>
          {v.projection_display && v.expected_full_display && (
            <p className="text-[12px] text-ink-muted">
              Heading for <span className="font-medium text-ink-2 tabular-nums">{v.projection_display}</span> · a normal day closes at{" "}
              <span className="tabular-nums">{v.expected_full_display}</span>
            </p>
          )}
          {v.curve && (
            <div className="mt-2.5">
              <PaceChart typical={v.curve.typical} today={v.curve.today} tone={tone} format={format} width={320} height={88} />
            </div>
          )}
          <p className="mt-1.5 flex flex-wrap gap-x-3 text-[10.5px] text-ink-subtle">
            {v.basis && <span>vs {v.basis}</span>}
            {v.hour?.actual_display && (
              <span>
                {String(v.hour.hour).padStart(2, "0")}:00 hour {v.hour.actual_display} (normal {v.hour.expected_display})
              </span>
            )}
          </p>
        </>
      ) : (
        <p className="mt-3 text-k-caption text-ink-muted">
          {v.status === "stale" ? `No live data — the newest event is ${v.data_until ?? "unknown"}.` : v.note ?? v.error ?? "Nothing to show yet."}
        </p>
      )}
    </article>
  );
}

const SIGNAL_ICON: Record<string, typeof Radar> = {
  pace_below: TrendingDown,
  pace_above: TrendingUp,
  hour_break: Zap,
  recovered: CheckCircle2,
  stalled: Unplug,
  flowing: CheckCircle2,
  day_close: Sunrise,
};

export function MomentCard({ m, index, onChanged }: { m: Moment; index: number; onChanged?: (m: Moment) => void }) {
  const f = m.facts ?? {};
  const Icon = SIGNAL_ICON[m.signal ?? ""] ?? Radar;
  const val = f.valence as string | undefined;
  const tone =
    m.kind === "data_issue" && m.signal === "stalled" ? "warn" : m.signal === "recovered" || m.signal === "flowing" ? "ok" : val === "bad" ? "danger" : val === "good" ? "ok" : "brand";
  const t = (({ ok: ["var(--ok-soft)", "var(--ok)"], warn: ["var(--warn-soft)", "var(--warn)"], danger: ["var(--danger-soft)", "var(--danger)"], brand: ["var(--brand-soft)", "var(--brand-strong)"] }) as Record<string, string[]>)[tone];
  const when = new Date(m.created_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  const where = (f.where as { dimension: string; top: { slice: string; delta: number; delta_display?: string; share_of_gap_pct?: number | null }[] }[] | undefined) ?? [];
  const latest = f.latest as { local_time?: string; actual_display?: string; expected_display?: string; dev_pct?: number } | undefined;
  return (
    <article className={cn("kairos-panel k-rise overflow-hidden", m.status === "resolved" && "opacity-70")} style={{ ["--i" as string]: index }}>
      <div className="flex gap-3 px-4 py-3">
        <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full" style={{ background: t[0], color: t[1] }}>
          <Icon className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <h3 className="text-k-body font-semibold text-ink">{m.title}</h3>
          </div>
          <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-ink-subtle">
            <span>{m.kind === "daily_briefing" ? "Morning briefing" : when}</span>
            {f.product && <span>· {f.product as string}</span>}
            {m.status === "resolved" && <StatusPill tone="ok" size="sm">resolved</StatusPill>}
            {m.status === "open" && m.kind !== "daily_briefing" && m.signal?.startsWith("pace") && <StatusPill tone={tone as Tone} size="sm">still open</StatusPill>}
          </p>
          {m.body && <p className="mt-1.5 whitespace-pre-line text-k-body leading-relaxed text-ink-2">{m.body}</p>}
          {latest?.actual_display && m.status === "open" && (
            <p className="mt-1.5 text-[11.5px] text-ink-muted">
              Latest at {latest.local_time}: {latest.actual_display} vs normal {latest.expected_display}
              {latest.dev_pct != null && ` (${latest.dev_pct > 0 ? "+" : ""}${latest.dev_pct.toFixed(1)}%)`}
            </p>
          )}
          {where.length > 0 && (
            <div className="mt-2.5 grid gap-3 sm:grid-cols-2">
              {where.map((d) => {
                const max = Math.max(...d.top.map((x) => Math.abs(x.delta)), 1);
                return (
                  <div key={d.dimension}>
                    <p className="k-label mb-1">where it sits · {d.dimension.replace(/_/g, " ")}</p>
                    {d.top.slice(0, 4).map((x, i) => (
                      <div key={`${x.slice}-${i}`} className="flex items-center gap-2 text-[11px]">
                        <span className="w-24 truncate text-ink-2" title={x.slice}>
                          {x.slice}
                        </span>
                        <span className="h-1.5 flex-1 rounded-full bg-sunken">
                          <span className="block h-full rounded-full" style={{ width: `${(Math.abs(x.delta) / max) * 100}%`, background: x.delta < 0 ? "var(--danger-dot)" : "var(--ok-dot)" }} />
                        </span>
                        <span className="w-16 text-right tabular-nums text-ink-muted">{x.delta_display}</span>
                      </div>
                    ))}
                  </div>
                );
              })}
            </div>
          )}
          {m.kind !== "daily_briefing" && m.signal !== "recovered" && m.signal !== "flowing" && (
            <div className="mt-2 flex items-center gap-1">
              {m.feedback ? (
                <span className="text-[11px] text-ink-muted">{m.feedback === "useful" ? "Marked useful" : "Noted — I'll be stricter here"}</span>
              ) : (
                <>
                  <button className="k-btn k-btn-ghost k-btn-sm" onClick={async () => onChanged?.({ ...m, ...((await sendFeedback(m.id, { feedback: "useful" })) as unknown as Partial<Moment>) })}>
                    Useful
                  </button>
                  <button className="k-btn k-btn-ghost k-btn-sm" onClick={async () => onChanged?.({ ...m, ...((await sendFeedback(m.id, { feedback: "not_useful" })) as unknown as Partial<Moment>) })}>
                    Not useful
                  </button>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </article>
  );
}

export function PulseView({
  state,
  onPulse,
  onToggle,
  onMomentChanged,
}: {
  state: CompanionState | null;
  onPulse: () => void;
  onToggle: (on: boolean) => void;
  onMomentChanged: (m: Moment) => void;
}) {
  const snap = state?.snapshot ?? null;
  const today = snap?.today ?? null;
  const briefing = state?.notes.find((n) => n.kind === "daily_briefing");
  const moments = useMemo(
    () => (state?.notes ?? []).filter((n) => n.kind !== "daily_briefing" && (!today || n.period === today || n.period === null)),
    [state, today]
  );
  const earlier = useMemo(() => {
    // How the day went: each change of headline, newest first.
    const seen: { at: string; text: string }[] = [];
    for (const p of state?.timeline ?? []) {
      if (p.headline && !seen.some((s) => s.text === p.headline) && (!today || p.as_of.slice(0, 10) >= today.slice(0, 10))) {
        seen.push({ at: p.local_time ?? new Date(p.as_of).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }), text: p.headline });
      }
    }
    return seen.slice(1, 6);
  }, [state, today]);

  if (!state) {
    return (
      <p className="flex items-center gap-2 text-k-body text-ink-muted">
        <Spinner /> Loading…
      </p>
    );
  }
  const running = state.status === "running";
  const nextIn = state.next_pulse_in_seconds != null ? Math.round(state.next_pulse_in_seconds / 60) : null;
  return (
    <div className="space-y-4">
      <section data-guide="jenny:headline" className="kairos-panel k-rise overflow-hidden">
        <div className="flex gap-3.5 px-5 pb-3 pt-4">
          <span className="mt-1 shrink-0">
            <KairosMark size={32} />
          </span>
          <div className="min-w-0 flex-1">
            <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-k-caption text-ink-muted">
              {snap?.live ? (
                <StatusPill tone="ok" size="sm">
                  Live
                </StatusPill>
              ) : (
                <StatusPill tone="neutral" size="sm">
                  Not live
                </StatusPill>
              )}
              {snap?.local_time && (
                <span>
                  {snap.weekday} {snap.local_time} <span className="text-ink-subtle">{offsetLabel(snap.offset_minutes)}</span>
                </span>
              )}
              {snap?.lag_minutes != null && <span>· data {snap.lag_minutes < 1 ? "under a minute" : `${Math.round(snap.lag_minutes)} min`} behind</span>}
              {state.last_pulse_at && <span>· looked {timeAgo(state.last_pulse_at)}</span>}
              {state.enabled && nextIn !== null && !running && <span>· next look in {nextIn < 1 ? "under a minute" : `${nextIn} min`}</span>}
            </p>
            <p className="mt-1 text-k-caption font-semibold text-brand-strong">Jenny</p>
            <p className="mt-0.5 text-[17px] font-medium leading-snug text-ink">
              {state.headline ?? (running ? "Taking my first look…" : "I haven't looked yet.")}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3 border-t border-hairline bg-sunken/40 px-5 py-2">
          <button onClick={onPulse} disabled={running} className="k-btn k-btn-sm">
            {running ? <Spinner /> : <Radar className="h-3.5 w-3.5" />}
            {running ? "Looking…" : "Look now"}
          </button>
          <label className="flex items-center gap-2 text-k-caption text-ink-2">
            <Switch checked={state.enabled} onChange={onToggle} label={state.enabled ? "Stop watching" : "Watch"} />
            {state.enabled ? `Watching every ${Math.round(state.interval_seconds / 60)} min` : "Paused"}
          </label>
          {state.tz_source === "inferred" && state.tz_offset_minutes !== null && (
            <span className="text-[11px] text-ink-subtle">Clock read from the data: {offsetLabel(state.tz_offset_minutes)}</span>
          )}
          {state.error && <span className="text-[11px] text-danger">Last look failed: {state.error.slice(0, 120)}</span>}
        </div>
      </section>

      {snap && snap.vitals.length === 0 && (
        <section className="kairos-panel">
          <EmptyState icon={Radar} title="Nothing I can watch live here">
            None of this connection&apos;s data products record when each event happened, only the day. The Notebook tab has my monthly reading.
          </EmptyState>
        </section>
      )}

      {snap && snap.vitals.length > 0 && (
        <div data-guide="jenny:vitals" className="grid gap-3 lg:grid-cols-2">
          {snap.vitals.map((v, i) => (
            <VitalCard key={v.key} v={v} index={i} localTime={snap.local_time} />
          ))}
        </div>
      )}

      {briefing && <MomentCard m={briefing} index={0} onChanged={onMomentChanged} />}

      <div>
        <p className="k-label mb-2 px-1">Today&apos;s moments</p>
        {moments.length === 0 ? (
          <p className="px-1 text-k-body text-ink-muted">
            {snap?.live ? "Nothing has needed you today — every vital has stayed within its normal range." : "No live moments — the data isn't live."}
          </p>
        ) : (
          <div className="space-y-3">
            {moments.map((m, i) => (
              <MomentCard key={m.id} m={m} index={i % 8} onChanged={onMomentChanged} />
            ))}
          </div>
        )}
      </div>

      {earlier.length > 0 && (
        <details className="group px-1">
          <summary className="flex cursor-pointer list-none items-center gap-1 text-k-caption font-medium text-ink-muted">
            <ChevronRight className="h-3 w-3 transition-transform group-open:rotate-90" /> How the day went
          </summary>
          <ol className="mt-2 space-y-1.5 border-l border-hairline pl-3">
            {earlier.map((e) => (
              <li key={e.at + e.text} className="text-[12px] text-ink-2">
                <span className="mr-2 tabular-nums text-ink-subtle">{e.at}</span>
                {e.text}
              </li>
            ))}
          </ol>
        </details>
      )}
    </div>
  );
}
