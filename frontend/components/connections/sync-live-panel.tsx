"use client";

import { AlertTriangle, CheckCircle2, CircleDashed, CircleSlash, Clock, XCircle } from "lucide-react";

import { Callout, Spinner } from "@/components/kairos/ds";

import {
  StatTile,
  formatDuration,
  seconds,
  useCountUp,
  useServerNow,
} from "@/components/enrichment/live-panel";
import type { SyncLive, SyncPhase, SyncPhaseState } from "@/lib/connections";
import { cn } from "@/lib/utils";

const PHASES: SyncPhase[] = ["catalog", "jobs", "objects", "lineage", "index"];

/** The fourth phase is Kairos's own: making what was mirrored searchable by agents. */
const PHASE_LABEL: Record<SyncPhase, string> = {
  catalog: "Catalog",
  jobs: "Pipelines",
  objects: "Objects",
  lineage: "Lineage",
  index: "Agent index",
};

/** The counters shown under each phase, in the order the sync produces them. */
const COUNTERS: { key: string; label: string; phase: SyncPhase }[] = [
  { key: "catalogs", label: "Catalogs", phase: "catalog" },
  { key: "schemas", label: "Schemas", phase: "catalog" },
  { key: "tables", label: "Tables", phase: "catalog" },
  { key: "columns", label: "Columns", phase: "catalog" },
  { key: "jobs", label: "Jobs", phase: "jobs" },
  { key: "tasks", label: "Tasks", phase: "jobs" },
  { key: "runs", label: "Runs", phase: "jobs" },
  { key: "task_runs", label: "Task runs", phase: "jobs" },
  { key: "objects", label: "Objects", phase: "objects" },
  { key: "table_edges", label: "Table edges", phase: "lineage" },
  { key: "column_edges", label: "Column edges", phase: "lineage" },
  { key: "documents", label: "Searchable", phase: "index" },
];

function PhaseIcon({ status }: { status: SyncPhaseState["status"] }) {
  if (status === "running") return <Spinner />;
  if (status === "completed") return <CheckCircle2 className="h-4 w-4 shrink-0" style={{ color: "var(--ok-dot)" }} />;
  if (status === "failed") return <XCircle className="h-4 w-4 shrink-0" style={{ color: "var(--danger-dot)" }} />;
  if (status === "skipped") return <CircleSlash className="h-4 w-4 shrink-0 text-ink-subtle" />;
  return <CircleDashed className="h-4 w-4 shrink-0 text-ink-subtle" />;
}

function Counter({ label, value, active }: { label: string; value: number; active: boolean }) {
  const shown = useCountUp(value);
  return (
    <div className="min-w-0">
      <p className={cn("text-[11.5px]", active ? "text-ink-muted" : "text-ink-subtle")}>{label}</p>
      <p className={cn("text-[17px] font-bold leading-6 tabular-nums", value ? "text-ink" : "text-ink-subtle")}>
        {Math.round(shown).toLocaleString()}
      </p>
    </div>
  );
}

export function SyncLivePanel({ sync }: { sync: SyncLive }) {
  const live = sync.status === "running";
  const now = useServerNow(sync.server_now, live);
  const elapsed = seconds(sync.started_at, sync.finished_at ?? now);
  const stepFor = live ? seconds(sync.step_at, now) : 0;
  const total = Object.values(sync.counts).reduce((a, b) => a + b, 0);
  const pos = live ? sync.position : null;
  const totalShown = useCountUp(total);

  return (
    <section className="kairos-panel k-rise overflow-hidden">
      <div className="flex min-h-[48px] items-center gap-2.5 border-b border-hairline px-5 py-3">
        {live ? (
          <span className="relative flex h-2 w-2 shrink-0">
            <span className="k-pulse absolute inline-flex h-full w-full rounded-full bg-brand" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-brand" />
          </span>
        ) : sync.status === "completed" ? (
          <CheckCircle2 className="h-4 w-4" style={{ color: "var(--ok-dot)" }} />
        ) : (
          <XCircle className="h-4 w-4" style={{ color: "var(--danger-dot)" }} />
        )}
        <h3 className="text-k-title font-semibold text-ink">
          {live ? "Sync in progress" : sync.status === "completed" ? "Last sync complete" : "Last sync failed"}
        </h3>
        <span className="ml-auto text-k-caption text-ink-subtle">
          {sync.options.catalog_filter?.length ? sync.options.catalog_filter.join(", ") : "All catalogs"}
          {" · "}
          {sync.options.job_filter?.length ? sync.options.job_filter.join(", ") : "all pipelines"}
          {" · "}
          {sync.options.run_limit ?? 25} runs per job
          {sync.options.skip_lineage ? " · no lineage" : ""}
        </span>
      </div>

      <div className="space-y-3 bg-sunken px-5 py-4">
        <div className="grid grid-cols-2 gap-2">
          <StatTile
            label="Elapsed"
            icon={<Clock className="h-3 w-3" />}
            value={formatDuration(elapsed)}
            detail={live ? `started ${new Date(sync.started_at).toLocaleTimeString()}` : sync.status}
          />
          <StatTile
            label="Entities mirrored"
            value={Math.round(totalShown).toLocaleString()}
            detail={sync.phase ? `now: ${PHASE_LABEL[sync.phase].toLowerCase()}` : "across all domains"}
          />
        </div>

        {/* What it is doing right now */}
        {live && (
          <div className="kairos-panel px-3.5 py-3">
            <p className="text-k-caption text-ink-muted">Now syncing</p>
            <div className="mt-1.5 flex items-center gap-2">
              <span className="min-w-0 flex-1 truncate text-k-body font-medium text-ink" title={sync.step}>
                {sync.step}
              </span>
              <span className="shrink-0 text-k-caption tabular-nums text-ink-subtle">{Math.floor(stepFor)}s</span>
            </div>
            {pos && (
              <div className="mt-2">
                <div className="h-1.5 overflow-hidden rounded-full bg-neutral-soft">
                  <div
                    className="h-full rounded-full bg-brand transition-[width] duration-500 ease-out"
                    style={{ width: `${Math.min(100, (pos.index / pos.total) * 100)}%` }}
                  />
                </div>
                <p className="mt-1 text-[11px] tabular-nums text-ink-subtle">
                  {pos.unit} {pos.index} of {pos.total}
                </p>
              </div>
            )}
          </div>
        )}

        {sync.error && (
          <Callout tone="danger" icon={AlertTriangle}>
            {sync.error}
          </Callout>
        )}

        {/* The three domains, each with its timer and what it has produced */}
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
          {PHASES.map((p) => {
            // A sync started before the index phase existed has no entry for it.
            const state = sync.phases[p] ?? { status: "pending", started_at: null, finished_at: null, items: 0, error: null };
            const took =
              state.started_at && (state.finished_at || state.status === "running")
                ? seconds(state.started_at, state.finished_at ?? now)
                : null;
            return (
              <div
                key={p}
                className={cn(
                  "kairos-panel min-w-0 px-3.5 py-3 transition-[border-color,box-shadow] duration-300",
                  state.status === "running" && "border-brand-border shadow-[0_0_0_3px_var(--brand-soft)]"
                )}
              >
                <div className="flex items-center gap-1.5">
                  <PhaseIcon status={state.status} />
                  <span className="text-k-body font-semibold text-ink">{PHASE_LABEL[p]}</span>
                  <span className="ml-auto text-k-caption tabular-nums text-ink-subtle">
                    {took !== null ? formatDuration(took) : state.status === "skipped" ? "skipped" : "waiting"}
                  </span>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1.5">
                  {COUNTERS.filter((c) => c.phase === p).map((c) => (
                    <Counter
                      key={c.key}
                      label={c.label}
                      value={sync.counts[c.key] ?? 0}
                      active={state.status === "running"}
                    />
                  ))}
                </div>
                {state.error && (
                  <p className="mt-1.5 truncate text-k-caption text-danger" title={state.error}>
                    {state.error}
                  </p>
                )}
              </div>
            );
          })}
        </div>

        {/* Activity, newest first */}
        <div className="kairos-panel overflow-hidden">
          <p className="border-b border-hairline px-3.5 py-2.5 text-k-caption font-semibold text-ink-2">Activity</p>
          <ol className="max-h-56 overflow-y-auto">
            {sync.log.map((line, i) => (
              <li
                key={`${line.at}-${i}`}
                className="flex gap-3 border-b border-hairline px-3.5 py-1.5 text-k-caption last:border-b-0"
              >
                <span className="w-11 shrink-0 text-right tabular-nums text-ink-subtle">
                  {formatDuration(seconds(sync.started_at, line.at))}
                </span>
                <span
                  className={cn(
                    "min-w-0 flex-1 break-words",
                    line.level === "error" && "text-danger",
                    line.level === "warning" && "text-warn",
                    line.level === "info" && "text-ink"
                  )}
                >
                  {line.message}
                </span>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </section>
  );
}
