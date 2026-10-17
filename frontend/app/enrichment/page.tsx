"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  FileCode2,
  Link2,
  Play,
  RotateCcw,
  Square,
  Sparkles,
  X,
} from "lucide-react";

import { Callout, EmptyState, Spinner, StatusPill, Switch, stagger } from "@/components/kairos/ds";
import { PageHeader } from "@/components/shell/app-shell";
import { ScopePicker } from "@/components/enrichment/scope-picker";
import { LivePanel } from "@/components/enrichment/live-panel";
import {
  cancelRun,
  getDiscovered,
  getEvents,
  getProfileYaml,
  getRun,
  isTerminal,
  listProfiles,
  listRuns,
  resumeRun,
  startRun,
  type DiscoveredSummary,
  type EnrichmentEvent,
  type EnrichmentRun,
  type ProfileIndexEntry,
  type RunEstimate,
} from "@/lib/enrichment";
import { cn } from "@/lib/utils";

const POLL_MS = 1500;
const MAX_FEED = 400;

/** Feed rows are typed so the eye can scan for discoveries, not read every line. */
const EVENT_STYLE: Record<string, { dot: string; label: string; strong?: boolean }> = {
  run_started: { dot: "var(--brand)", label: "Started", strong: true },
  entity_started: { dot: "var(--neutral-dot)", label: "Profiling", strong: true },
  facts: { dot: "var(--neutral-dot)", label: "Facts" },
  classified: { dot: "var(--brand)", label: "Classified" },
  verified: { dot: "var(--ok-dot)", label: "Verified" },
  tool_call: { dot: "var(--hairline-strong)", label: "Tool" },
  relation_found: { dot: "var(--ok-dot)", label: "Link", strong: true },
  entity_discovered: { dot: "var(--warn-dot)", label: "New entity", strong: true },
  frontier_expanded: { dot: "var(--brand)", label: "Frontier" },
  frontier_stopped: { dot: "var(--neutral-dot)", label: "Boundary" },
  profile_written: { dot: "var(--brand)", label: "Profiled", strong: true },
  entity_skipped: { dot: "var(--neutral-dot)", label: "Skipped" },
  entity_failed: { dot: "var(--danger-dot)", label: "Failed", strong: true },
  run_finished: { dot: "var(--brand)", label: "Finished", strong: true },
};

export default function EnrichmentPage() {
  const [run, setRun] = useState<EnrichmentRun | null>(null);
  // The feed carries the run it belongs to; another run reads as an empty feed until its events arrive.
  const [feed, setFeed] = useState<{ runId: string | null; events: EnrichmentEvent[] }>({ runId: null, events: [] });
  const [discovered, setDiscovered] = useState<DiscoveredSummary | null>(null);
  const [profiles, setProfiles] = useState<ProfileIndexEntry[]>([]);

  const [selected, setSelected] = useState<string[]>([]);
  const [estimate, setEstimate] = useState<RunEstimate | null>(null);
  const [force, setForce] = useState(false);
  // Entity cap: on by default (30, the server's default), so one seed cannot walk the whole warehouse.
  const [capOn, setCapOn] = useState(true);
  const [capLimit, setCapLimit] = useState(30);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openProfile, setOpenProfile] = useState<{ entity_id: string; yaml: string } | null>(null);
  // Stopping lets the current entity finish, which can take a while: say so, and do not ask twice.
  const [stopping, setStopping] = useState<string | null>(null);

  const cursor = useRef(0);
  const feedRef = useRef<HTMLDivElement | null>(null);
  const autoScroll = useRef(true);

  const refreshPanels = useCallback(() => {
    getDiscovered().then(setDiscovered).catch(() => undefined);
    listProfiles().then((r) => setProfiles(r.profiles)).catch(() => undefined);
  }, []);

  useEffect(() => {
    listRuns().then(({ runs }) => runs.length && setRun(runs[0])).catch(() => undefined);
    refreshPanels();
  }, [refreshPanels]);

  // The feed belongs to one run: a different run starts from an empty feed and cursor.
  const feedRun = useRef<string | null>(null);
  // One poll at a time: two overlapping polls read the same cursor and append the same events twice.
  const polling = useRef(false);

  useEffect(() => {
    if (!run) return;
    if (feedRun.current !== run.id) {
      feedRun.current = run.id;
      cursor.current = 0;
    }
    const runId = run.id;
    let cancelled = false;
    async function tick() {
      if (cancelled || !run || polling.current) return;
      polling.current = true;
      try {
        const [status, batch] = await Promise.all([getRun(run.id), getEvents(run.id, cursor.current)]);
        if (cancelled || feedRun.current !== run.id) return;
        setRun(status);
        if (batch.events.length) {
          cursor.current = Math.max(cursor.current, batch.last_sequence);
          setFeed((f) => {
            const current = f.runId === runId ? f.events : [];
            const seen = new Set(current.map((e) => e.sequence));
            return {
              runId,
              events: [...current, ...batch.events.filter((e) => !seen.has(e.sequence))].slice(-MAX_FEED),
            };
          });
          if (batch.events.some((e) => ["relation_found", "profile_written"].includes(e.event_type))) {
            refreshPanels();
          }
        }
      } catch {
        /* transient — next tick retries */
      } finally {
        polling.current = false;
      }
    }
    tick();
    const h = window.setInterval(() => {
      if (run && !isTerminal(run.status)) tick();
    }, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(h);
    };
  }, [run?.id, run?.status, refreshPanels]);

  useEffect(() => {
    if (autoScroll.current && feedRef.current) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight;
    }
  }, [feed]);

  const events = feed.runId === run?.id ? feed.events : [];
  const live = run ? !isTerminal(run.status) : false;

  async function handleStart() {
    setStarting(true);
    setError(null);
    try {
      const created = await startRun({
        entity_ids: selected,
        include_descendants: true,
        follow_graph: true,
        force,
        entity_cap: capOn,
        max_entities: capOn ? capLimit : null,
      });
      setRun(created);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start run");
    } finally {
      setStarting(false);
    }
  }

  const relationTypes = useMemo(() => discovered?.relation_types ?? [], [discovered]);

  return (
    <>
      <PageHeader
        title="Enrichment"
        description="Agents read your pipelines and build the semantic layer"
        actions={
          <>
            {live && (
              <StatusPill tone="brand" className="k-pop">
                Running
              </StatusPill>
            )}
            {live ? (
              <button
                onClick={() => {
                  if (!run || stopping === run.id) return;
                  setStopping(run.id);
                  cancelRun(run.id).catch(() => setStopping(null));
                }}
                disabled={stopping === run?.id}
                title={stopping === run?.id ? "Finishing the entity in progress, then stopping" : "Stop this run"}
                className="k-btn"
              >
                {stopping === run?.id ? (
                  <>
                    <Spinner /> Stopping…
                  </>
                ) : (
                  <>
                    <Square className="h-3.5 w-3.5" /> Stop
                  </>
                )}
              </button>
            ) : (
              <button
                onClick={handleStart}
                disabled={starting || !selected.length}
                className="k-btn k-btn-primary"
              >
                {starting ? <Spinner className="border-white/30" /> : <Play className="h-4 w-4" />}
                {estimate ? `Enrich ${capOn ? Math.min(estimate.to_process, capLimit) : estimate.to_process}` : "Start"}
              </button>
            )}
          </>
        }
      />

      <div className="flex min-h-0 flex-1">
        {/* Scope */}
        <aside className="flex w-[320px] shrink-0 flex-col border-r border-hairline bg-surface">
          <div className="border-b border-hairline px-4 py-3.5">
            <p className="text-k-title font-semibold text-ink">Scope</p>
            <p className="text-k-caption text-ink-muted">
              Pick a seed. The agent follows its relationships outward.
            </p>
          </div>
          <ScopePicker
            selected={selected}
            onChange={setSelected}
            force={force}
            onEstimate={setEstimate}
          />
          <div className="space-y-3 border-t border-hairline bg-sunken px-4 py-3">
            <div className="flex items-center gap-2.5">
              <Switch checked={capOn} onChange={setCapOn} label="Entity cap" />
              <span className="text-k-body font-medium text-ink-2">Entity cap</span>
              {capOn ? (
                <span className="ml-auto flex items-center gap-1.5 text-k-caption text-ink-muted">
                  up to
                  <input
                    type="number"
                    min={1}
                    max={5000}
                    value={capLimit}
                    onChange={(e) => setCapLimit(Math.max(1, Math.min(5000, Number(e.target.value) || 1)))}
                    aria-label="Maximum entities per run"
                    className="k-input !h-7 !w-16 !px-2 text-right !text-k-caption tabular-nums"
                  />
                </span>
              ) : (
                <span className="ml-auto text-k-caption font-medium text-warn">Off</span>
              )}
            </div>
            <p className="text-k-caption leading-snug text-ink-subtle">
              {capOn
                ? estimate && estimate.to_process > capLimit
                  ? `This selection reaches about ${estimate.to_process}; the run stops at ${capLimit}.`
                  : "The run stops after this many entities, even if the seeds reach more."
                : "No ceiling: everything the seeds reach within 3 hops is profiled. Large selections take long and use more tokens."}
            </p>
            <label className="flex cursor-pointer items-center gap-2 text-k-body text-ink-2">
              <input
                type="checkbox"
                checked={force}
                onChange={(e) => setForce(e.target.checked)}
                className="h-4 w-4 accent-[var(--brand)]"
              />
              Re-profile unchanged entities
            </label>
          </div>
        </aside>

        {/* Live feed */}
        <div className="flex min-w-0 flex-1 flex-col">
          {run && (
            <div className="border-b border-hairline bg-surface px-5 py-3.5">
              <div className="flex items-center gap-3">
                <StatusPill
                  tone={run.status === "completed" ? "ok" : run.status === "failed" ? "danger" : live ? "brand" : "neutral"}
                  size="sm"
                  className="capitalize"
                >
                  {run.status}
                </StatusPill>
                <span className="font-mono text-k-caption text-ink-subtle">{run.id.slice(0, 8)}</span>
                <div className="ml-auto flex items-center gap-3 text-k-caption tabular-nums">
                  <span className="font-semibold text-ok">{run.totals.completed} done</span>
                  {run.totals.skipped > 0 && (
                    <span className="text-ink-subtle">{run.totals.skipped} skipped</span>
                  )}
                  {run.totals.failed > 0 && (
                    <span className="font-semibold text-danger">{run.totals.failed} failed</span>
                  )}
                  <span className="text-ink-muted">{run.totals.remaining} left</span>
                  <span className="font-semibold text-brand">{run.discovered.relations} links</span>
                </div>
              </div>
              <div className="mt-2.5 h-1.5 overflow-hidden rounded-full bg-neutral-soft">
                <div
                  className="h-full rounded-full transition-all duration-700 ease-out"
                  style={{ width: `${run.totals.percent}%`, background: "var(--brand)" }}
                />
              </div>
              {(run.status === "paused" || (live && !run.active_in_process)) && (
                <div className="mt-3 flex items-center gap-2 rounded-lg bg-warn-soft px-3 py-2 text-warn">
                  <AlertTriangle className="h-4 w-4" />
                  <span className="text-k-caption font-medium">
                    Interrupted by a restart · {run.totals.remaining} pending
                  </span>
                  <button
                    onClick={async () => {
                      await resumeRun(run.id).catch(() => undefined);
                      setRun((r) => (r ? { ...r, status: "running" } : r));
                    }}
                    className="k-btn k-btn-primary k-btn-sm ml-auto"
                  >
                    Resume
                  </button>
                </div>
              )}
            </div>
          )}

          {run && <LivePanel run={run} live={live && run.active_in_process} />}

          {error && (
            <div className="border-b border-hairline px-5 py-2.5">
              <Callout tone="danger" icon={AlertTriangle}>
                {error}
              </Callout>
            </div>
          )}

          <div
            ref={feedRef}
            onScroll={(e) => {
              const el = e.currentTarget;
              autoScroll.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
            }}
            className="min-h-0 flex-1 overflow-y-auto bg-surface px-5 py-3"
          >
            {events.length === 0 && (
              <div className="flex h-full items-center justify-center">
                <EmptyState icon={Sparkles} title={run ? "Waiting for activity" : "No run yet"}>
                  Choose a pipeline on the left. The agent reads its code, writes a profile, and links what it finds
                  into the graph.
                </EmptyState>
              </div>
            )}

            {events.map((e) => {
              const style = EVENT_STYLE[e.event_type] ?? {
                dot: "var(--ink-subtle)",
                label: e.event_type,
              };
              return (
                <div
                  key={`${run?.id}:${e.sequence}`}
                  className={cn("k-rise flex items-start gap-3 py-1", style.strong && "mt-1")}
                >
                  <span className="mt-[7px] h-2 w-2 shrink-0 rounded-full" style={{ background: style.dot }} />
                  <span className={cn("w-[78px] shrink-0 text-k-caption leading-[22px]", style.strong ? "font-semibold text-ink-2" : "text-ink-subtle")}>
                    {style.label}
                  </span>
                  <span
                    className={cn(
                      "min-w-0 break-words text-k-body leading-[22px]",
                      e.level === "error" ? "text-danger" : style.strong ? "text-ink" : "text-ink-muted"
                    )}
                  >
                    {e.message}
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Discoveries */}
        <aside className="w-[300px] shrink-0 overflow-y-auto border-l border-hairline bg-surface">
          <section className="border-b border-hairline p-4">
            <h3 className="mb-3 flex items-center gap-2 text-k-title font-semibold text-ink">
              <Link2 className="h-4 w-4 text-ink-subtle" />
              Relation vocabulary
            </h3>
            {relationTypes.length === 0 ? (
              <p className="text-k-caption text-ink-subtle">Nothing discovered yet.</p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {relationTypes.map((r, i) => (
                  <span
                    key={r.relation_type}
                    className="k-pop inline-flex h-6 items-center gap-1.5 rounded-full bg-brand-soft px-2.5 font-mono text-[11px] font-semibold text-brand-strong"
                    style={stagger(Math.min(i, 10))}
                  >
                    {r.relation_type} <span className="font-sans tabular-nums text-brand opacity-70">{r.count}</span>
                  </span>
                ))}
              </div>
            )}
            <p className="mt-3 text-k-caption leading-snug text-ink-subtle">
              Invented by the agent as it reads code — not a fixed schema.
            </p>
          </section>

          <section className="p-4">
            <h3 className="mb-3 flex items-center gap-2 text-k-title font-semibold text-ink">
              <FileCode2 className="h-4 w-4 text-ink-subtle" />
              Profiles
              <span className="rounded-full bg-neutral-soft px-1.5 text-[11px] font-semibold tabular-nums text-ink-muted">
                {profiles.length}
              </span>
            </h3>
            <div className="space-y-2">
              {profiles.slice(0, 30).map((p) => (
                <button
                  key={p.entity_id}
                  onClick={() =>
                    getProfileYaml(p.entity_id)
                      .then(setOpenProfile)
                      // Gone since the list was loaded (e.g. profiles were cleared): refresh the list.
                      .catch(() => {
                        setError("That profile no longer exists — the list has been refreshed.");
                        refreshPanels();
                      })
                  }
                  className="kairos-panel k-hover w-full p-3 text-left"
                >
                  <span className="flex items-center gap-1.5">
                    <StatusPill tone="neutral" size="sm" dot={false}>
                      {p.kind}
                    </StatusPill>
                    <span className="truncate font-mono text-k-caption font-semibold text-ink">
                      {p.entity_id.split(":").slice(-1)[0]}
                    </span>
                  </span>
                  {p.summary && (
                    <span className="mt-1.5 line-clamp-3 block text-k-caption leading-snug text-ink-muted">
                      {p.summary}
                    </span>
                  )}
                </button>
              ))}
              {profiles.length === 0 && (
                <p className="text-k-caption text-ink-subtle">No profiles generated yet.</p>
              )}
            </div>
          </section>
        </aside>
      </div>

      {openProfile && (
        <div
          className="k-page fixed inset-0 z-50 flex items-center justify-center bg-[rgb(26_29_36/0.28)] p-10 backdrop-blur-[3px]"
          onClick={() => setOpenProfile(null)}
        >
          <div
            className="kairos-panel k-pop flex max-h-full w-full max-w-3xl flex-col shadow-[0_24px_60px_-20px_rgb(26_29_36/0.35)]"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-2.5 border-b border-hairline px-5 py-3.5">
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-soft text-brand">
                <FileCode2 className="h-4 w-4" />
              </span>
              <span className="truncate font-mono text-k-body font-semibold text-ink">{openProfile.entity_id}</span>
              <button onClick={() => setOpenProfile(null)} className="k-btn k-btn-ghost k-btn-sm ml-auto !px-1.5">
                <X className="h-4 w-4" />
              </button>
            </div>
            <pre className="flex-1 overflow-auto whitespace-pre-wrap break-words bg-sunken p-5 font-mono text-k-caption leading-relaxed text-ink-2">
              {openProfile.yaml}
            </pre>
          </div>
        </div>
      )}
    </>
  );
}
