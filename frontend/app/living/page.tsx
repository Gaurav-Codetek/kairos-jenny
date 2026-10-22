"use client";

/**
 * Jenny, the business's companion (the Living Agent). Pulse is its live view — every vital today against
 * a normal day at this time, the moments it noticed, and a conversation grounded in live data.
 * Notebook is its slower monthly reading: it waits for numbers to settle and remembers.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { Activity, BookOpen, Clock, EyeOff, History, Play, Presentation, Radar } from "lucide-react";

import { Callout, Chip, EmptyState, KairosMark, Segmented, Spinner, StatusPill, Switch, Tabs } from "@/components/kairos/ds";
import { PageHeader } from "@/components/shell/app-shell";
import { NoteCard } from "@/components/living/note-card";
import { CompanionChat } from "@/components/living/companion-chat";
import { PulseView } from "@/components/living/pulse-view";
import { DeskButton } from "@/components/living/desk-panel";
import { Stage } from "@/components/stage/stage";
import { useStage } from "@/lib/stage";
import { Sparkline } from "@/components/living/sparkline";
import { timeAgo } from "@/components/agents/bits";
import { getCompanion, pulseNow, updateCompanion, type CompanionState } from "@/lib/companion";
import { listWorkspaces, type Workspace } from "@/lib/connections";
import { fmt, getReplay, getRun, getState, monthLabel, startRun, updateWatch, type AgentNote, type AgentRunView, type LivingState, type WatchView } from "@/lib/living";
import { cn } from "@/lib/utils";

const FILTERS = [
  { id: "attention", label: "Needs attention" },
  { id: "waiting", label: "Waiting" },
  { id: "issues", label: "Data issues" },
  { id: "all", label: "Everything" },
] as const;
type Filter = (typeof FILTERS)[number]["id"];

export default function LivingPage() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [state, setState] = useState<LivingState | null>(null);
  const [tab, setTab] = useState<"pulse" | "now" | "replay">("pulse");
  // Inside Pulse: the live view, or Jenny's stage. Something new on her stage brings it forward by itself — the
  // owner never has to go looking for it while she talks.
  const [pulseView, setPulseView] = useState<"live" | "stage">("live");
  const stageState = useStage();
  const [seenReveal, setSeenReveal] = useState(stageState.reveal);
  if (stageState.reveal !== seenReveal) {
    setSeenReveal(stageState.reveal);
    setTab("pulse");
    setPulseView("stage");
  }
  const [companion, setCompanion] = useState<CompanionState | null>(null);
  const [filter, setFilter] = useState<Filter>("attention");
  const [run, setRun] = useState<AgentRunView | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listWorkspaces()
      .then((ws) => {
        setWorkspaces(ws);
        // A link can open a workspace and a tab: /living?workspace=<id>&tab=stage
        const q = new URLSearchParams(window.location.search);
        setWorkspaceId((c) => c ?? ws.find((w) => w.id === q.get("workspace"))?.id ?? ws[0]?.id ?? null);
        const t = q.get("tab");
        if (t === "now" || t === "replay" || t === "pulse") setTab(t);
        if (t === "stage") setPulseView("stage");
      })
      .catch(() => setWorkspaces([]));
  }, []);

  // "Can't reach the API" only when it's really away: after two missed reads in a row (a restart takes ~15 s), and
  // gone again as soon as a read succeeds.
  const missed = useRef(0);
  const UNREACHABLE = "Could not reach the companion — is the API running?";
  const reached = useCallback(() => {
    missed.current = 0;
    setError((e) => (e === UNREACHABLE ? null : e));
  }, []);
  const unreached = useCallback(() => {
    missed.current += 1;
    if (missed.current >= 2) setError(UNREACHABLE);
  }, []);

  const load = useCallback(() => {
    if (!workspaceId) return;
    getState(workspaceId)
      .then((s) => {
        reached();
        setState(s);
        const running = s.runs.find((r) => r.status === "running" && r.step);
        if (running) setRun(running);
      })
      .catch(unreached);
  }, [workspaceId, reached, unreached]);

  useEffect(() => {
    load();
  }, [load]);

  // The companion's live view: refreshed often, faster while it is looking.
  const loadCompanion = useCallback(() => {
    if (!workspaceId) return;
    getCompanion(workspaceId)
      .then((c) => {
        reached();
        setCompanion(c);
      })
      .catch(unreached);
  }, [workspaceId, reached, unreached]);
  useEffect(() => {
    loadCompanion();
  }, [loadCompanion]);
  useEffect(() => {
    if (tab !== "pulse") return;
    const t = window.setInterval(loadCompanion, companion?.status === "running" ? 2500 : 15000);
    return () => window.clearInterval(t);
  }, [tab, loadCompanion, companion?.status]);

  // Follow a look while it runs.
  useEffect(() => {
    if (!run || run.status !== "running") return;
    const t = window.setInterval(async () => {
      const r = await getRun(run.id).catch(() => null);
      if (!r) return;
      setRun(r);
      if (r.status !== "running") load();
    }, 2000);
    return () => window.clearInterval(t);
  }, [run, load]);

  async function lookNow() {
    if (!workspaceId) return;
    setError(null);
    try {
      setRun(await startRun({ workspace_id: workspaceId, mode: "live" }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start.");
    }
  }

  const ws = workspaces.find((w) => w.id === workspaceId);
  const briefing = state?.notes.find((n) => n.kind === "briefing");
  const notes = useMemo(() => {
    // Members of a group story live on in memory; the feed shows the story.
    const list = (state?.notes ?? []).filter((n) => n.kind !== "briefing" && n.status !== "grouped");
    const active = (n: AgentNote) => !["dismissed", "withdrawn"].includes(n.status);
    const pick =
      filter === "attention"
        ? list.filter((n) => active(n) && ((n.kind === "finding" && n.status !== "provisional") || n.kind === "correction"))
        : filter === "waiting"
          ? list.filter((n) => n.status === "provisional")
          : filter === "issues"
            ? list.filter((n) => n.kind === "data_issue" && active(n))
            : list;
    return [...pick].sort((a, b) => b.importance - a.importance || b.created_at.localeCompare(a.created_at));
  }, [state, filter]);
  const counts = useMemo(() => {
    const list = (state?.notes ?? []).filter((n) => n.kind !== "briefing" && n.status !== "grouped");
    const active = (n: AgentNote) => !["dismissed", "withdrawn"].includes(n.status);
    return {
      attention: list.filter((n) => active(n) && ((n.kind === "finding" && n.status !== "provisional") || n.kind === "correction")).length,
      waiting: list.filter((n) => n.status === "provisional").length,
      issues: list.filter((n) => n.kind === "data_issue" && active(n)).length,
      all: list.length,
    };
  }, [state]);

  const running = run?.status === "running";
  const lastLive = state?.runs.find((r) => r.mode === "live" && r.status === "completed");

  return (
    <>
      <PageHeader
        title="Jenny"
        description="Jenny, your business companion: watches the live numbers all day, tells you what matters, and talks it through with you"
        actions={
          <div className="flex items-center gap-3">
            {workspaces.length > 1 && (
              <Segmented items={workspaces.map((w) => ({ id: w.id, label: w.name }))} value={workspaceId ?? ""} onChange={(id) => { if (id === workspaceId) return; setState(null); setCompanion(null); setRun(null); setWorkspaceId(id); }} />
            )}
            {tab !== "pulse" && <button onClick={lookNow} disabled={!workspaceId || running} className="k-btn k-btn-primary">
              {running && run?.mode === "live" ? <Spinner className="border-white/30" /> : <Radar className="h-4 w-4" />}
              {running && run?.mode === "live" ? "Looking…" : "Monthly look"}
            </button>}
          </div>
        }
      />
      <div data-guide="jenny:tabs">
      <Tabs
        items={[
          { id: "pulse", label: "Pulse", icon: Activity },
          { id: "now", label: "Notebook", icon: BookOpen },
          { id: "replay", label: "Replay history", icon: History },
        ]}
        value={tab}
        onChange={setTab}
      />
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_400px] overflow-hidden">
        <div className="min-h-0 overflow-y-auto">
          <div className="mx-auto max-w-4xl space-y-4 px-6 py-5">
            {error && <Callout tone="danger">{error}</Callout>}
            {running && (
              <Callout tone="brand" icon={Radar}>
                {run?.step ?? "Starting"}…
              </Callout>
            )}
            {tab === "pulse" && (
              <div className="flex items-center gap-3">
                <span data-guide="jenny:views">
                <Segmented
                  size="sm"
                  items={[
                    { id: "live", label: "Live pulse" },
                    {
                      id: "stage",
                      label: (
                        <span className="inline-flex items-center gap-1.5">
                          <Presentation className="h-3.5 w-3.5" /> Jenny&apos;s stage
                        </span>
                      ),
                      count: stageState.scenes.length || undefined,
                    },
                  ]}
                  value={pulseView}
                  onChange={setPulseView}
                />
                </span>
                {pulseView === "stage" && (
                  <span className="text-k-caption text-ink-muted">What Jenny is showing you as she talks</span>
                )}
                <div data-guide="jenny:desk" className="ml-auto">
                  <DeskButton workspaceId={workspaceId} />
                </div>
              </div>
            )}
            {tab === "pulse" && pulseView === "stage" ? (
              <Stage />
            ) : tab === "pulse" ? (
              <PulseView
                state={companion}
                onPulse={async () => {
                  if (!workspaceId) return;
                  await pulseNow(workspaceId).catch(() => null);
                  loadCompanion();
                }}
                onToggle={async (on) => {
                  if (!workspaceId) return;
                  await updateCompanion(workspaceId, { enabled: on });
                  loadCompanion();
                }}
                onMomentChanged={(m) => setCompanion((c) => (c ? { ...c, notes: c.notes.map((x) => (x.id === m.id ? m : x)) } : c))}
              />
            ) : null}
            {tab === "pulse" ? null : tab === "now" ? (
              state === null ? (
                <p className="flex items-center gap-2 text-k-body text-ink-muted">
                  <Spinner /> Loading…
                </p>
              ) : state.products === 0 ? (
                <section className="kairos-panel">
                  <EmptyState icon={Radar} title="Nothing to watch yet">
                    The agent watches data products. Build some on the Data Products screen first.
                  </EmptyState>
                </section>
              ) : state.notes.length === 0 && !running ? (
                <section className="kairos-panel">
                  <EmptyState icon={Radar} title={`I haven't looked at ${ws?.name ?? "this connection"} yet`} action={<button onClick={lookNow} className="k-btn k-btn-primary"><Radar className="h-4 w-4" /> Look now</button>}>
                    I&apos;ll build a watch list from its data products, read each metric month by month, and tell you what
                    has really changed — and what I&apos;m still waiting on.
                  </EmptyState>
                </section>
              ) : (
                <>
                  {briefing && (
                    <section className="kairos-panel k-rise overflow-hidden">
                      <div className="flex gap-3 px-5 py-4">
                        <span className="mt-0.5 shrink-0">
                          <KairosMark size={30} />
                        </span>
                        <div className="min-w-0">
                          <p className="text-k-caption text-ink-muted">
                            {briefing.title} {lastLive?.finished_at && <>· looked {timeAgo(lastLive.finished_at)}</>}
                          </p>
                          <div className="eval-md mt-1 text-[15px] leading-relaxed text-ink">
                            <ReactMarkdown>{briefing.body ?? ""}</ReactMarkdown>
                          </div>
                        </div>
                      </div>
                    </section>
                  )}
                  <div className="flex flex-wrap items-center gap-1.5">
                    {FILTERS.map((f) => (
                      <Chip key={f.id} on={filter === f.id} onClick={() => setFilter(f.id)} count={counts[f.id]}>
                        {f.label}
                      </Chip>
                    ))}
                  </div>
                  {notes.length === 0 ? (
                    <p className="px-1 text-k-body text-ink-muted">Nothing here right now.</p>
                  ) : (
                    notes.map((n, i) => (
                      <NoteCard
                        key={n.id}
                        note={n}
                        index={i % 8}
                        onChanged={(u) => setState((s) => (s ? { ...s, notes: s.notes.map((x) => (x.id === u.id ? u : x)) } : s))}
                      />
                    ))
                  )}
                </>
              )
            ) : (
              <Replay workspaceId={workspaceId} watches={state?.watches ?? []} onRun={setRun} running={running} />
            )}
          </div>
        </div>
        {/* Jenny stays beside the pulse and her stage: the stage is fed by this conversation, and switching to it mid-call must not hang up. */}
        {tab === "pulse" ? <CompanionChat key={workspaceId ?? "none"} workspaceId={workspaceId} headline={companion?.headline} /> : <WatchPanel watches={state?.watches ?? []} onChanged={load} />}
      </div>
    </>
  );
}

// ── what I'm watching: the agent's own dashboard ─────────────────────

function WatchPanel({ watches, onChanged }: { watches: WatchView[]; onChanged: () => void }) {
  const groups = useMemo(() => {
    const m = new Map<string, WatchView[]>();
    watches.forEach((w) => m.set(w.product ?? "—", [...(m.get(w.product ?? "—") ?? []), w]));
    return [...m.entries()];
  }, [watches]);
  return (
    <aside className="min-h-0 overflow-y-auto border-l border-hairline bg-surface">
      <div className="sticky top-0 z-10 border-b border-hairline bg-surface px-4 py-3">
        <p className="text-k-title font-semibold text-ink">What I&apos;m watching</p>
        <p className="text-k-caption text-ink-muted">{watches.filter((w) => w.status === "active").length} metrics across {groups.length} data products</p>
      </div>
      {groups.length === 0 && <p className="px-4 py-4 text-k-body text-ink-muted">My watch list is built on my first look.</p>}
      {groups.map(([product, ws]) => (
        <section key={product} className="border-b border-hairline px-4 py-3">
          <p className="text-k-body font-semibold text-ink">{product}</p>
          <p className="mt-0.5 flex gap-1.5 text-[11px] text-ink-muted" title={ws[0].settle_reason ?? undefined}>
            <Clock className="mt-0.5 h-3 w-3 shrink-0 text-warn" />
            <span className="line-clamp-2">
              I wait {ws[0].settle_periods} month{ws[0].settle_periods === 1 ? "" : "s"} before trusting a new month
              {ws[0].settle_measured ? " (measured)" : ""}: {ws[0].settle_reason}
            </span>
          </p>
          <div className="mt-2 space-y-1">
            {ws.map((w) => {
              const last = w.series[w.series.length - 1];
              const attention = w.attention.includes("open") || w.attention.includes("confirmed") ? "brand" : w.attention.includes("provisional") ? "warn" : null;
              return (
                <div key={w.id} className={cn("flex items-center gap-2 rounded-lg px-1.5 py-1", w.status === "muted" && "opacity-45")}>
                  <span
                    className="h-1.5 w-1.5 shrink-0 rounded-full"
                    style={{ background: attention === "brand" ? "var(--brand)" : attention === "warn" ? "var(--warn-dot)" : "var(--hairline-strong)" }}
                    title={attention ? "I noted something here" : "steady"}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[12px] text-ink" title={w.why ?? undefined}>
                      {w.label ?? w.metric}
                    </span>
                    <span className="text-[10.5px] text-ink-subtle">
                      {w.series.length < 7
                        ? "too little history yet"
                        : w.good_direction === "up" ? "higher is better" : w.good_direction === "down" ? "lower is better" : "watching"}
                    </span>
                  </span>
                  <Sparkline points={w.series.slice(-18)} width={96} height={26} provisionalFrom={Math.max(0, Math.min(18, w.series.length) - w.settle_periods)} tone={attention === "warn" ? "var(--warn-dot)" : "var(--brand)"} />
                  <span className="w-14 text-right text-[11px] tabular-nums text-ink-2">{last ? fmt(last[1]) : "–"}</span>
                  <Switch
                    checked={w.status === "active"}
                    label={w.status === "active" ? "Stop watching" : "Watch"}
                    onChange={async (on) => {
                      await updateWatch(w.id, { status: on ? "active" : "muted" });
                      onChanged();
                    }}
                  />
                </div>
              );
            })}
          </div>
        </section>
      ))}
    </aside>
  );
}

// ── replay: what I would have said, month by month ───────────────────

function Replay({ workspaceId, watches, onRun, running }: { workspaceId: string | null; watches: WatchView[]; onRun: (r: AgentRunView) => void; running: boolean }) {
  const [data, setData] = useState<{ run: AgentRunView | null; notes: AgentNote[] } | null>(null);
  const [step, setStep] = useState<string | null>(null);
  const [startM, setStartM] = useState("");
  const [endM, setEndM] = useState("");

  const load = useCallback(() => {
    if (workspaceId) getReplay(workspaceId).then(setData).catch(() => setData({ run: null, notes: [] }));
  }, [workspaceId]);
  useEffect(() => {
    load();
  }, [load, running]);

  // Default range: the last 12 months the watched series cover.
  const span = useMemo(() => {
    const all = watches.flatMap((w) => w.series.map((p) => p[0].slice(0, 7))).sort();
    return all.length ? { first: all[0], last: all[all.length - 1] } : null;
  }, [watches]);
  const start = startM || (span ? shiftMonth(span.last, -11) : "");
  const end = endM || span?.last || "";

  const steps = ((data?.run?.stats?.steps as { as_of: string; new: number; provisional: number; confirmed: number; withdrawn: number; data_issues: number }[]) ?? []);
  const totals = data?.run?.stats?.totals as Record<string, number> | undefined;
  const selected = step ?? steps[steps.length - 1]?.as_of ?? null;
  const shown = (data?.notes ?? []).filter((n) => n.status !== "grouped" && (!selected || (n.as_of ?? "").slice(0, 10) === selected));

  return (
    <div className="space-y-4">
      <section className="kairos-panel px-5 py-4">
        <p className="text-k-title font-semibold text-ink">Replay the history</p>
        <p className="mt-1 text-k-body text-ink-muted">
          I walk through past months as if each month-end were today, with only the data up to then, and show what I would have
          told you. It shows how I wait and what I would have caught. It can&apos;t show restatements that already happened — those
          I learn from my own looks going forward.
        </p>
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <label className="text-k-caption text-ink-2">
            From
            <input type="month" value={start} onChange={(e) => setStartM(e.target.value)} className="k-input mt-1 block h-8 w-40" />
          </label>
          <label className="text-k-caption text-ink-2">
            To
            <input type="month" value={end} onChange={(e) => setEndM(e.target.value)} className="k-input mt-1 block h-8 w-40" />
          </label>
          <button
            disabled={!workspaceId || running || !start || !end}
            onClick={async () => onRun(await startRun({ workspace_id: workspaceId!, mode: "replay", start: `${start}-01`, end: `${end}-01` }))}
            className="k-btn k-btn-primary"
          >
            <Play className="h-4 w-4" /> Replay
          </button>
        </div>
      </section>
      {data?.run && steps.length > 0 && (
        <>
          {totals && (
            <p className="text-k-caption text-ink-muted">
              Over {steps.length} months I would have raised {totals.new} findings, held {totals.provisional} as provisional while the
              data settled, confirmed {totals.confirmed} of those, withdrawn {totals.withdrawn}, and flagged {totals.data_issues} data issues.
            </p>
          )}
          <div className="flex gap-1 overflow-x-auto pb-1">
            {steps.map((s) => {
              const n = s.new + s.provisional + s.data_issues;
              return (
                <button
                  key={s.as_of}
                  onClick={() => setStep(s.as_of)}
                  className={cn(
                    "flex min-w-[64px] flex-col items-center rounded-lg border px-2 py-1.5 text-[11px]",
                    selected === s.as_of ? "border-brand bg-brand-soft text-brand-strong" : "border-hairline bg-surface text-ink-2 hover:bg-sunken"
                  )}
                >
                  <span className="font-semibold">{monthLabel(s.as_of)}</span>
                  <span className="mt-0.5 flex gap-1">
                    {s.new > 0 && <StatusPill tone="brand" size="sm" dot={false}>{s.new}</StatusPill>}
                    {s.provisional > 0 && <StatusPill tone="warn" size="sm" dot={false}>{s.provisional}</StatusPill>}
                    {n === 0 && <span className="text-ink-subtle">quiet</span>}
                  </span>
                </button>
              );
            })}
          </div>
          {selected && <p className="k-label">As of {monthLabel(selected)} · {shown.length} note{shown.length === 1 ? "" : "s"}</p>}
          {shown.length === 0 ? (
            <p className="text-k-body text-ink-muted">Nothing worth telling you that month.</p>
          ) : (
            shown.map((n, i) => <NoteCard key={n.id} note={n} index={i % 8} />)
          )}
        </>
      )}
      {data?.run?.status === "running" && <p className="flex items-center gap-2 text-k-body text-ink-muted"><Spinner /> Replaying…</p>}
      {!data?.run && <p className="flex items-center gap-1.5 text-k-caption text-ink-subtle"><EyeOff className="h-3.5 w-3.5" /> No replay yet.</p>}
    </div>
  );
}

function shiftMonth(ym: string, n: number): string {
  const [y, m] = ym.split("-").map(Number);
  const d = new Date(y, m - 1 + n, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}
