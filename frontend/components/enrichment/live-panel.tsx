"use client";

import { useEffect, useRef, useState } from "react";
import { CheckCircle2, CircleSlash, Clock, Coins, XCircle } from "lucide-react";

import { Spinner } from "@/components/kairos/ds";

import type { EnrichmentRun, RunItem } from "@/lib/enrichment";
import { cn } from "@/lib/utils";

// ── time and numbers ─────────────────────────────────────────────────

/**
 * "Now" on the server's clock, ticking every second. The offset comes from
 * the last poll's server_now, so a viewer's wrong system clock cannot make
 * a timer run fast, slow or negative.
 */
export function useServerNow(serverNow: string | undefined, live: boolean): number {
  const offset = useRef(0);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (serverNow) offset.current = Date.parse(serverNow) - Date.now();
  }, [serverNow]);
  useEffect(() => {
    if (!live) return;
    const tick = () => setNow(Date.now() + offset.current);
    const h = window.setInterval(tick, 1000);
    return () => window.clearInterval(h);
  }, [live]);
  return now;
}

export function seconds(from: string | null | undefined, to: number | string | null | undefined): number {
  if (!from) return 0;
  const end = typeof to === "string" ? Date.parse(to) : to ?? Date.now();
  return Math.max(0, (end - Date.parse(from)) / 1000);
}

export function formatDuration(total: number): string {
  const s = Math.floor(total);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
}

export function compact(n: number): string {
  if (n < 1000) return String(Math.round(n));
  if (n < 1_000_000) return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0)}K`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}

/**
 * Counts toward the latest value instead of jumping to it. Polls arrive every
 * couple of seconds; an eased count between them reads as a live meter.
 */
export function useCountUp(target: number, durationMs = 900): number {
  const [shown, setShown] = useState(target);
  const from = useRef(target);
  useEffect(() => {
    const start = performance.now();
    const origin = from.current;
    if (origin === target) return;
    let raf = 0;
    const step = (t: number) => {
      const p = Math.min(1, (t - start) / durationMs);
      const eased = 1 - Math.pow(1 - p, 3);
      const value = origin + (target - origin) * eased;
      from.current = value;
      setShown(value);
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target, durationMs]);
  return shown;
}

// ── pieces ───────────────────────────────────────────────────────────

export function StatTile({ label, value, detail, icon }: { label: string; value: string; detail?: string; icon?: React.ReactNode }) {
  return (
    <div className="kairos-panel k-rise min-w-0 px-4 py-3">
      <p className="flex items-center gap-1.5 text-k-caption font-medium text-ink-muted">
        {icon}
        {label}
      </p>
      {/* Fixed-width digits: these values change every second, and
          proportional digits would make them jitter as they tick. */}
      <p className="mt-1 truncate text-[22px] font-bold leading-7 tabular-nums text-ink">{value}</p>
      {detail && <p className="truncate text-k-caption tabular-nums text-ink-subtle">{detail}</p>}
    </div>
  );
}

const KIND_LABEL: Record<string, string> = {
  catalog: "Catalog", schema: "Schema", table: "Table", job: "Pipeline", task: "Task",
};

function StatusIcon({ status }: { status: string }) {
  if (status === "completed") return <CheckCircle2 className="h-4 w-4 shrink-0" style={{ color: "var(--ok-dot)" }} />;
  if (status === "failed") return <XCircle className="h-4 w-4 shrink-0" style={{ color: "var(--danger-dot)" }} />;
  return <CircleSlash className="h-4 w-4 shrink-0 text-ink-subtle" />;
}

// ── the panel ────────────────────────────────────────────────────────

export function LivePanel({ run, live }: { run: EnrichmentRun; live: boolean }) {
  const now = useServerNow(run.server_now, live);
  const usage = run.usage ?? { input_tokens: 0, output_tokens: 0, total_tokens: 0, llm_calls: 0, tool_calls: 0 };

  const runElapsed = seconds(run.started_at, run.finished_at ?? (live ? now : run.heartbeat_at));
  const tokens = useCountUp(usage.total_tokens);
  const current = live ? run.current ?? null : null;
  const entityElapsed = current ? seconds(current.started_at, now) : 0;
  const entityTokens = useCountUp(current?.total_tokens ?? 0);
  const activityFor = run.activity_at ? seconds(run.activity_at, now) : 0;

  // ETA from the entities finished so far — shown only once there is a basis.
  const finished = (run.recent_items ?? []).filter((i) => i.status === "completed" && i.duration_s);
  const avg = finished.length >= 2 ? finished.reduce((a, i) => a + (i.duration_s ?? 0), 0) / finished.length : null;
  const eta = live && avg !== null ? Math.max(0, avg * run.totals.remaining - entityElapsed) : null;
  const done = run.totals.completed + run.totals.failed + run.totals.skipped;

  return (
    <div className="space-y-3 border-b border-hairline bg-sunken px-5 py-4">
      <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
        <StatTile
          label="Elapsed"
          icon={<Clock className="h-3 w-3" />}
          value={formatDuration(runElapsed)}
          detail={eta !== null ? `about ${formatDuration(eta)} left` : live ? "estimating…" : run.status}
        />
        <StatTile
          label="Tokens used"
          icon={<Coins className="h-3 w-3" />}
          value={compact(tokens)}
          detail={`${compact(usage.input_tokens)} in · ${compact(usage.output_tokens)} out`}
        />
        <StatTile
          label="Entities"
          value={`${done} of ${run.totals.total}`}
          detail={avg !== null ? `${formatDuration(avg)} each on average` : `${run.totals.remaining} to go`}
        />
        <StatTile
          label="Agent calls"
          value={compact(usage.llm_calls + usage.tool_calls)}
          detail={`${usage.llm_calls} model · ${usage.tool_calls} tool`}
        />
      </div>

      <div className="grid gap-2 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        {/* What is happening right now */}
        <div className={cn("kairos-panel min-w-0 px-4 py-3.5 transition-[border-color,box-shadow] duration-300", current && "border-brand-border shadow-[0_0_0_3px_var(--brand-soft)]")}>
          <p className="text-k-caption font-medium text-ink-muted">Now enriching</p>
          {current ? (
            <>
              <div className="mt-1 flex items-center gap-2">
                <span className="rounded-full bg-brand-soft px-2 py-0.5 text-[11px] font-semibold text-brand-strong">
                  {KIND_LABEL[current.kind] ?? current.kind}
                </span>
                <span className="min-w-0 truncate text-k-title font-semibold text-ink" title={current.entity_id}>
                  {current.name}
                </span>
                <span className="ml-auto shrink-0 text-k-body font-medium tabular-nums text-ink">
                  {formatDuration(entityElapsed)}
                </span>
              </div>
              <p className="mt-0.5 truncate text-k-caption text-ink-subtle" title={current.parent_entity_id ?? ""}>
                {current.via_relation && current.parent_name
                  ? <>Reached via {current.via_relation} from <span className="text-ink-muted">{current.parent_name}</span></>
                  : "Seed"}
              </p>
              <div className="mt-2.5 flex items-center gap-2 rounded-lg border border-hairline bg-sunken px-3 py-2">
                <span className="relative flex h-2 w-2 shrink-0">
                  <span className="k-pulse absolute inline-flex h-full w-full rounded-full bg-brand" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-brand" />
                </span>
                <span className="min-w-0 flex-1 truncate text-k-caption text-ink" title={run.activity ?? ""}>
                  {run.activity ?? "Starting…"}
                </span>
                <span className="shrink-0 text-k-caption tabular-nums text-ink-subtle">{Math.floor(activityFor)}s</span>
              </div>
              <p className="mt-1.5 text-k-caption tabular-nums text-ink-subtle">
                {compact(entityTokens)} tokens · {current.llm_calls} model calls · {current.tool_calls} tool calls on this entity
              </p>
            </>
          ) : (
            <p className="mt-1 text-k-body text-ink-subtle">
              {live ? (
                <span className="flex items-center gap-1.5">
                  <Spinner /> Picking the next entity…
                </span>
              ) : (
                "Nothing running."
              )}
            </p>
          )}
        </div>

        {/* What just finished */}
        <div className="kairos-panel min-w-0 px-4 py-3.5">
          <p className="text-k-caption font-medium text-ink-muted">Recently finished</p>
          {(run.recent_items ?? []).length === 0 ? (
            <p className="mt-1 text-k-body text-ink-subtle">Nothing finished yet.</p>
          ) : (
            <table className="mt-1 w-full text-k-caption">
              <thead className="sr-only">
                <tr><th>Status</th><th>Entity</th><th>Time</th><th>Tokens</th></tr>
              </thead>
              <tbody>
                {(run.recent_items ?? []).slice(0, 5).map((i: RunItem) => (
                  <tr key={i.entity_id + (i.finished_at ?? "")} className="k-rise border-t border-hairline first:border-0">
                    <td className="w-6 py-1.5"><StatusIcon status={i.status} /></td>
                    <td className="max-w-0 truncate py-1.5 pr-2 font-mono text-ink" title={i.entity_id}>{i.name}</td>
                    <td className="w-12 py-1 text-right tabular-nums text-ink-muted">
                      {i.duration_s !== null ? formatDuration(i.duration_s) : "—"}
                    </td>
                    <td className={cn("w-14 py-1 text-right tabular-nums", i.total_tokens ? "text-ink-muted" : "text-ink-subtle")}>
                      {i.total_tokens ? compact(i.total_tokens) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
