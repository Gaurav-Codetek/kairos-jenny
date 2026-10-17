"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertCircle, Check, ChevronRight, Plug, Plus, Radio, RefreshCw, Trash2, Zap } from "lucide-react";

import {
  Callout,
  EmptyState,
  Field,
  Panel,
  Spinner,
  StatusPill,
  stagger,
  useCountUp,
} from "@/components/kairos/ds";

import { PageHeader } from "@/components/shell/app-shell";
import { AddConnectionDialog } from "@/components/connections/add-connection";
import { DeleteConnectionDialog } from "@/components/connections/delete-connection";
import { SyncLivePanel } from "@/components/connections/sync-live-panel";
import {
  DOMAIN_META,
  PLATFORM_META,
  getSyncLive,
  getWorkspaceStatus,
  listWorkspaces,
  relativeTime,
  testConnection,
  triggerSync,
  type Platform,
  type TestResult,
  type SyncLive,
  type Workspace,
  type WorkspaceStatus,
} from "@/lib/connections";
import { cn } from "@/lib/utils";
import { CopyButton } from "@/components/agents/bits";

/** "a, b ,c" → ["a", "b", "c"]; blank → null, meaning everything. */
function splitList(value: string): string[] | null {
  const items = value.split(",").map((v) => v.trim()).filter(Boolean);
  return items.length ? items : null;
}

export default function ConnectionsPage() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [status, setStatus] = useState<WorkspaceStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<boolean | null>(null);
  const [testAccess, setTestAccess] = useState<TestResult | null>(null);

  // Sync options — the controls that were previously API-only.
  const [starting, setStarting] = useState(false);
  const [live, setLive] = useState<SyncLive | null>(null);
  const syncing = starting || live?.status === "running";
  const [runLimit, setRunLimit] = useState(25);
  const [skipLineage, setSkipLineage] = useState(false);
  const [catalogFilter, setCatalogFilter] = useState("");
  const [pipelineFilter, setPipelineFilter] = useState("");
  const [syncError, setSyncError] = useState<string | null>(null);

  const reload = useCallback(() => {
    listWorkspaces()
      .then((w) => {
        setWorkspaces(w);
        setSelected((cur) => cur ?? (w.length ? w[0].id : null));
      })
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const refreshStatus = useCallback((id: string) => {
    getWorkspaceStatus(id).then(setStatus).catch(() => setStatus(null));
  }, []);

  useEffect(() => {
    if (selected) {
      setStatus(null);
      setTestResult(null);
      setLive(null);
      refreshStatus(selected);
      // Pick up a sync already running — started in another tab, or before a reload.
      getSyncLive(selected)
        .then((s) => setLive(s.status === "none" ? null : (s as SyncLive)))
        .catch(() => undefined);
    }
  }, [selected, refreshStatus]);

  // Poll once a second while a sync runs; when it ends, reload the counts.
  const liveRunning = live?.status === "running";
  useEffect(() => {
    if (!selected || !liveRunning) return;
    let stopped = false;
    const h = window.setInterval(() => {
      getSyncLive(selected)
        .then((s) => {
          if (stopped || s.status === "none") return;
          const next = s as SyncLive;
          setLive(next);
          if (next.status !== "running") {
            refreshStatus(selected);
            reload();
          }
        })
        .catch(() => undefined);
    }, 1000);
    return () => {
      stopped = true;
      window.clearInterval(h);
    };
  }, [selected, liveRunning, refreshStatus, reload]);

  // The domain rows and totals only change when a domain commits; refresh
  // them as each phase finishes rather than only at the end.
  const phasesDone = live
    ? Object.values(live.phases).filter((p) => p.status === "completed" || p.status === "failed").length
    : 0;
  useEffect(() => {
    if (selected && phasesDone) refreshStatus(selected);
  }, [selected, phasesDone, refreshStatus]);

  async function handleTest() {
    if (!selected) return;
    setTesting(true);
    setTestResult(null);
    setTestAccess(null);
    try {
      const r = await testConnection(selected);
      setTestResult(r.connected);
      setTestAccess(r);
    } catch {
      setTestResult(false);
    } finally {
      setTesting(false);
    }
  }

  async function handleSync() {
    if (!selected) return;
    setStarting(true);
    setSyncError(null);
    try {
      // Returns at once with the first snapshot; the panel polls from there.
      const first = await triggerSync(selected, {
        run_limit: runLimit,
        skip_lineage: skipLineage,
        catalog_filter: splitList(catalogFilter),
        job_filter: splitList(pipelineFilter),
      });
      setLive(first);
      refreshStatus(selected);
    } catch (err) {
      setSyncError(err instanceof Error ? err.message : "Sync failed to start");
    } finally {
      setStarting(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Connections"
        description="Platforms Kairos mirrors into the Synthetic Warehouse"
        actions={
          <button onClick={() => setAdding(true)} className="k-btn k-btn-primary">
            <Plus className="h-4 w-4" /> Add connection
          </button>
        }
      />

      <div className="flex min-h-0 flex-1">
        {/* Connection list */}
        <div className="w-[300px] shrink-0 overflow-y-auto border-r border-hairline bg-surface">
          <p className="k-label px-5 pb-2 pt-4">Connected</p>

          {loading && (
            <div className="flex justify-center px-4 py-6">
              <Spinner />
            </div>
          )}

          <div className="space-y-1 px-3">
            {!loading &&
              workspaces.map((w, i) => {
                const meta = PLATFORM_META[w.platform] ?? PLATFORM_META.databricks;
                const active = selected === w.id;
                return (
                  <button
                    key={w.id}
                    onClick={() => setSelected(w.id)}
                    className={cn(
                      "k-rise flex w-full items-center gap-3 rounded-lg px-2.5 py-2.5 text-left transition-colors duration-200",
                      active ? "bg-brand-soft" : "hover:bg-sunken"
                    )}
                    style={stagger(i)}
                  >
                    <PlatformBadge platform={w.platform} />
                    <span className="min-w-0 flex-1">
                      <span className={cn("block truncate text-k-body font-semibold", active ? "text-brand-strong" : "text-ink")}>
                        {w.name}
                      </span>
                      <span className="block truncate text-k-caption text-ink-muted">
                        {meta.label} · {w.last_synced_at ? `synced ${relativeTime(w.last_synced_at)}` : "never synced"}
                      </span>
                    </span>
                    <ChevronRight className={cn("h-4 w-4 shrink-0", active ? "text-brand" : "text-ink-subtle")} />
                  </button>
                );
              })}
          </div>

          {/* Platform availability */}
          <div className="mt-5 border-t border-hairline px-5 py-4">
            <p className="k-label mb-3">Available platforms</p>
            <div className="space-y-3">
              {(Object.keys(PLATFORM_META) as Platform[]).map((p) => {
                const meta = PLATFORM_META[p];
                return (
                  <div key={p} className="flex items-start gap-3">
                    <PlatformBadge platform={p} small />
                    <span className="min-w-0">
                      <span className="block text-k-caption font-semibold text-ink">{meta.label}</span>
                      <span className="block text-k-caption leading-snug text-ink-muted">{meta.blurb}</span>
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Detail */}
        <div className="min-w-0 flex-1 overflow-y-auto">
          {!loading && workspaces.length === 0 && (
            <div className="flex h-full items-center justify-center">
              <EmptyState
                icon={Plug}
                title="Connect your first platform"
                action={
                  <button onClick={() => setAdding(true)} className="k-btn k-btn-primary">
                    <Plus className="h-4 w-4" /> Add connection
                  </button>
                }
              >
                Kairos mirrors your catalogs, pipelines and lineage into a Synthetic Warehouse. Nothing is written back to
                your platform.
              </EmptyState>
            </div>
          )}

          {!status && selected && (
            <div className="flex h-40 items-center justify-center">
              <Spinner />
            </div>
          )}

          {status && (
            <div key={status.name} className="mx-auto max-w-3xl space-y-5 px-7 py-6">
              {/* Connection summary */}
              <section className="kairos-panel k-rise p-5">
                <div className="flex items-start gap-3.5">
                  <PlatformBadge platform={status.platform} large />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <h2 className="truncate text-[17px] font-bold text-ink">{status.name}</h2>
                      <StatusPill tone="neutral" size="sm" dot={false}>
                        {(PLATFORM_META[status.platform] ?? PLATFORM_META.databricks).label}
                      </StatusPill>
                    </div>
                    <p className="mt-0.5 truncate font-mono text-k-caption text-ink-muted">{status.host}</p>
                  </div>
                  <button onClick={handleTest} disabled={testing} className="k-btn">
                    {testing ? <Spinner /> : <Plug className="h-4 w-4" />}
                    Test
                  </button>
                  <button
                    onClick={() => setDeleting(true)}
                    disabled={syncing}
                    title={syncing ? "Wait for the sync to finish" : "Delete this connection"}
                    className="k-btn hover:!border-danger-dot hover:!bg-danger-soft hover:!text-danger"
                  >
                    <Trash2 className="h-4 w-4" />
                    Delete
                  </button>
                </div>

                {testResult !== null && (
                  <Callout tone={testResult ? "ok" : "danger"} icon={testResult ? Check : AlertCircle} className="k-pop mt-4">
                    {testResult ? "Connection healthy" : "Could not reach the platform"}
                  </Callout>
                )}
                {testResult && testAccess?.access && (
                  <div className="k-rise mt-3 rounded-lg border border-hairline px-3.5 py-3 text-k-caption text-ink-muted">
                    <p>
                      Connected as <span className="font-mono text-ink">{testAccess.access.user_name}</span> with role{" "}
                      <span className="font-mono text-ink">{testAccess.access.role}</span>
                      {testAccess.access.warehouse ? (
                        <>
                          {" "}on <span className="font-mono text-ink">{testAccess.access.warehouse}</span>
                        </>
                      ) : null}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {Object.entries(testAccess.access.can_read ?? {}).map(([what, r]) => (
                        <StatusPill key={what} title={r.error ?? ""} tone={r.ok ? "ok" : "danger"} size="sm">
                          {what.replace(/_/g, " ")}
                          {r.rows != null ? ` · ${r.rows}` : ""}
                        </StatusPill>
                      ))}
                    </div>
                  </div>
                )}

                <dl className="mt-5 grid grid-cols-4 gap-3 border-t border-hairline pt-4">
                  {[
                    ["Tables", status.counts.tables],
                    ["Columns", status.counts.columns],
                    ["Jobs", status.counts.jobs],
                    ["Runs", status.counts.runs],
                  ].map(([label, value]) => (
                    <div key={String(label)}>
                      <dt className="text-k-caption font-medium text-ink-muted">{label}</dt>
                      <dd className="mt-0.5 text-[22px] font-bold tabular-nums text-ink">
                        <CountUp value={Number(value ?? 0)} />
                      </dd>
                    </div>
                  ))}
                </dl>
              </section>

              {status.mcp_url && (
                <section className="kairos-panel k-rise p-5" style={stagger(1)}>
                  <div className="flex items-center gap-3">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand">
                      <Radio className="h-4 w-4" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-k-title font-semibold text-ink">Agent endpoint for this connection</p>
                      <code className="block truncate font-mono text-k-caption text-ink-2">{status.mcp_url}</code>
                    </div>
                    <CopyButton text={status.mcp_url} />
                  </div>
                  <p className="mt-3 text-k-caption text-ink-muted">
                    An agent connected here sees only {status.name}, with{" "}
                    {(PLATFORM_META[status.platform] ?? PLATFORM_META.databricks).label} tools:
                  </p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {(status.mcp_tools ?? []).map((t) => (
                      <span
                        key={t}
                        className="rounded-full border border-hairline bg-sunken px-2.5 py-0.5 font-mono text-[11.5px] text-ink-2"
                      >
                        {t}
                      </span>
                    ))}
                  </div>
                </section>
              )}

              {/* Per-domain sync state, drawn as the chain they run in */}
              <Panel
                title="Sync domains"
                meta="Each runs in order; a failure in one does not stop the others"
                className="k-rise"
                style={stagger(2)}
                bodyClassName="px-5 py-4"
              >
                <ol className="relative">
                  {status.domains.map((d, i) => {
                    const meta = DOMAIN_META[d.domain];
                    const last = i === status.domains.length - 1;
                    const done = d.status === "idle";
                    const tone = d.status === "error" ? "danger" : d.status === "running" ? "brand" : done ? "ok" : "neutral";
                    return (
                      <li key={d.domain} className="relative flex gap-4 pb-5 last:pb-0">
                        {!last && (
                          <span
                            aria-hidden
                            className={cn(
                              "absolute bottom-1 left-[11px] top-7",
                              done ? "w-0.5 rounded-full bg-brand-border" : "w-0 border-l-2 border-dashed border-hairline-strong"
                            )}
                          />
                        )}
                        <span
                          className={cn(
                            "relative z-10 mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full",
                            done ? "bg-brand text-white" : "border-2 border-hairline-strong bg-surface text-ink-subtle"
                          )}
                        >
                          {done ? (
                            <Check className="h-3.5 w-3.5" strokeWidth={3} />
                          ) : d.status === "running" ? (
                            <Spinner className="h-3 w-3" />
                          ) : (
                            <span className="text-[11px] font-bold">{i + 1}</span>
                          )}
                        </span>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <p className="text-k-body font-semibold text-ink">{meta.label}</p>
                            {d.status !== "idle" && (
                              <StatusPill tone={tone} size="sm">
                                {d.status === "never_run" ? "Not run" : d.status === "running" ? "Running" : "Error"}
                              </StatusPill>
                            )}
                          </div>
                          <p className="text-k-caption text-ink-muted">{meta.description}</p>
                          {d.error_message && <p className="mt-1 line-clamp-2 text-k-caption text-danger">{d.error_message}</p>}
                        </div>
                        <div className="shrink-0 text-right">
                          <p className="text-k-title font-bold tabular-nums text-ink">{d.entities_in_warehouse.toLocaleString()}</p>
                          <p className="text-k-caption text-ink-subtle">{relativeTime(d.last_sync_at)}</p>
                        </div>
                      </li>
                    );
                  })}
                </ol>
              </Panel>

              {/* Sync controls */}
              <Panel title="Run a sync" className="k-rise" style={stagger(3)} bodyClassName="p-5">
                <p className="text-k-body text-ink-muted">
                  Mirrors the platform into the Synthetic Warehouse. Safe to re-run: unchanged entities are updated in
                  place, not duplicated.
                </p>

                <div className="mt-5 grid grid-cols-2 gap-4">
                  <Field label="Catalogs" hint="Comma-separated. Leave blank to sync everything.">
                    <input
                      value={catalogFilter}
                      onChange={(e) => setCatalogFilter(e.target.value)}
                      placeholder="All catalogs"
                      className="k-input"
                    />
                  </Field>
                  <Field label="Pipelines" hint="Job names or ids, comma-separated. Blank syncs every pipeline.">
                    <input
                      value={pipelineFilter}
                      onChange={(e) => setPipelineFilter(e.target.value)}
                      placeholder="All pipelines"
                      className="k-input"
                    />
                  </Field>
                  <Field label="Run history per job" hint="Higher values take longer and hit the platform API harder.">
                    <input
                      type="number"
                      min={1}
                      max={200}
                      value={runLimit}
                      onChange={(e) => setRunLimit(Number(e.target.value))}
                      className="k-input tabular-nums"
                    />
                  </Field>
                </div>

                <label className="mt-4 flex cursor-pointer items-center gap-2 text-k-body text-ink-2">
                  <input
                    type="checkbox"
                    checked={skipLineage}
                    onChange={(e) => setSkipLineage(e.target.checked)}
                    className="h-4 w-4 accent-[var(--brand)]"
                  />
                  Skip lineage
                  <span className="text-k-caption text-ink-subtle">(lineage queries system tables and is the slowest step)</span>
                </label>

                {syncError && (
                  <Callout tone="danger" icon={AlertCircle} className="mt-4">
                    {syncError}
                  </Callout>
                )}

                <div className="mt-5 flex items-center gap-2 border-t border-hairline pt-4">
                  <button onClick={handleSync} disabled={syncing} className="k-btn k-btn-primary">
                    {syncing ? <Spinner className="border-white/30" /> : <Zap className="h-4 w-4" />}
                    {syncing ? "Syncing…" : "Start sync"}
                  </button>
                  <button onClick={() => selected && refreshStatus(selected)} className="k-btn">
                    <RefreshCw className="h-4 w-4" />
                    Refresh
                  </button>
                  {syncing && (
                    <span className="text-k-caption text-ink-subtle">Runs in the background; you can leave this page and come back.</span>
                  )}
                </div>
              </Panel>

              {live && <SyncLivePanel sync={live} />}
            </div>
          )}
        </div>
      </div>

      {deleting && selected && status && (
        <DeleteConnectionDialog
          id={selected}
          status={status}
          onClose={() => setDeleting(false)}
          onDeleted={() => {
            setDeleting(false);
            setStatus(null);
            setLive(null);
            setSelected(null);
            reload();
          }}
        />
      )}

      {adding && (
        <AddConnectionDialog
          onClose={() => setAdding(false)}
          onCreated={(id) => {
            setAdding(false);
            setSelected(id);
            reload();
          }}
        />
      )}
    </>
  );
}

function PlatformBadge({ platform, small, large }: { platform: string; small?: boolean; large?: boolean }) {
  const meta = PLATFORM_META[platform as Platform] ?? PLATFORM_META.databricks;
  return (
    <span
      className={cn(
        "flex shrink-0 items-center justify-center rounded-full font-bold",
        large ? "h-11 w-11 text-[16px]" : small ? "h-7 w-7 text-[11px]" : "h-9 w-9 text-[13px]"
      )}
      style={{ background: meta.tint, color: meta.accent }}
    >
      {meta.label[0]}
    </span>
  );
}

function CountUp({ value }: { value: number }) {
  const n = useCountUp(value);
  return <>{(n ?? 0).toLocaleString()}</>;
}
