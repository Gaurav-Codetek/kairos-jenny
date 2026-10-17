"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ArrowLeft, CircleDashed, FlaskConical, Play, Search, Square, Trash2, XCircle } from "lucide-react";

import { EmptyState, Segmented, SectionIntro, Spinner, StatusPill, stagger } from "@/components/kairos/ds";

import { PageHeader } from "@/components/shell/app-shell";
import { timeAgo } from "@/components/agents/bits";
import { NewRun } from "@/components/evals/new-run";
import { ThreadView } from "@/components/evals/thread-view";
import {
  CONNECTOR_LABEL,
  cancelRun,
  deleteRun,
  getRun,
  isActive,
  listRuns,
  pct,
  type Connector,
  type EvalRun,
  type ThreadRow,
} from "@/lib/evals";
import { cn } from "@/lib/utils";

/** Selection lives in the URL (?run=…&q=…), updated without a navigation, so links can be shared. */
function writeUrl(run: string | null, q: string | null) {
  const sp = new URLSearchParams();
  if (run) sp.set("run", run);
  if (q) sp.set("q", q);
  window.history.replaceState(null, "", `/evals${sp.toString() ? `?${sp}` : ""}`);
}

export default function EvalsPage() {
  return (
    <Suspense>
      <EvalsScreen />
    </Suspense>
  );
}

function EvalsScreen() {
  const params = useSearchParams();
  const [runs, setRuns] = useState<EvalRun[] | null>(null);
  const [runId, setRunId] = useState<string | null>(() => params.get("run"));
  const [caseId, setCaseId] = useState<string | null>(() => params.get("q"));
  const [creating, setCreating] = useState(false);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    let timer: number | undefined;
    const load = () =>
      listRuns()
        .then((r) => {
          setRuns(r.runs);
          if (r.runs.some((x) => isActive(x.status))) timer = window.setTimeout(load, 5000);
        })
        .catch(() => setRuns([]));
    load();
    return () => window.clearTimeout(timer);
  }, [refresh]);

  const current = runId ?? runs?.[0]?.id ?? null;
  const selectRun = (id: string | null) => {
    setRunId(id);
    setCaseId(null);
    writeUrl(id, null);
  };
  const selectCase = (q: string | null) => {
    setCaseId(q);
    writeUrl(current, q);
  };

  return (
    <>
      <PageHeader
        title="Evaluations"
        description="The same questions through each connector, answered by one model, every step kept"
        actions={
          <div className="flex items-center gap-2">
            {runs && runs.length > 0 && (
              <select
                value={current ?? ""}
                onChange={(e) => selectRun(e.target.value)}
                className="k-input max-w-[360px] !w-auto !text-k-caption"
                aria-label="Evaluation run"
              >
                {runs.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name} · {r.status === "completed" ? timeAgo(r.created_at) : r.status} ·{" "}
                    {r.connectors.map((c) => `${c} ${pct(r.summary?.[c]?.pass_rate)}`).join(" / ")}
                  </option>
                ))}
              </select>
            )}
            <button onClick={() => setCreating(true)} className="k-btn k-btn-primary">
              <Play className="h-4 w-4" /> New run
            </button>
          </div>
        }
      />

      {runs === null ? (
        <div className="flex flex-1 items-center justify-center">
          <Spinner />
        </div>
      ) : !current ? (
        <div className="flex flex-1 items-center justify-center">
          <EmptyState
            icon={FlaskConical}
            title="No evaluation runs yet"
            action={
              <button onClick={() => setCreating(true)} className="k-btn k-btn-primary">
                <Play className="h-4 w-4" /> New run
              </button>
            }
          >
            A run asks each question through each connector in a fresh conversation, keeps every step, and grades the
            answer.
          </EmptyState>
        </div>
      ) : (
        <RunView
          key={current}
          id={current}
          caseId={caseId}
          onCase={selectCase}
          onDeleted={() => {
            selectRun(null);
            setRefresh((n) => n + 1);
          }}
        />
      )}

      {creating && (
        <NewRun
          onClose={() => setCreating(false)}
          onStarted={(id) => {
            setCreating(false);
            selectRun(id);
            setRefresh((n) => n + 1);
          }}
        />
      )}
    </>
  );
}

// ── One run: summary bar, then questions and transcripts side by side ──

interface CaseRow {
  case_id: string;
  category: string;
  question: string;
  threads: Partial<Record<Connector, ThreadRow>>;
}

const OUTCOMES = [
  { id: "all", label: "All" },
  { id: "differ", label: "Disagree" },
  { id: "failed", label: "Any failed" },
  { id: "both-failed", label: "Both failed" },
] as const;
type Outcome = (typeof OUTCOMES)[number]["id"];

function RunView({ id, caseId, onCase, onDeleted }: { id: string; caseId: string | null; onCase: (q: string | null) => void; onDeleted: () => void }) {
  const [run, setRun] = useState<EvalRun | null>(null);
  const [threads, setThreads] = useState<ThreadRow[]>([]);
  const [category, setCategory] = useState("");
  const [outcome, setOutcome] = useState<Outcome>("all");
  const [search, setSearch] = useState("");

  useEffect(() => {
    let alive = true;
    let timer: number | undefined;
    const load = () =>
      getRun(id)
        .then((d) => {
          if (!alive) return;
          setRun(d.run);
          setThreads(d.threads);
          if (isActive(d.run.status)) timer = window.setTimeout(load, 4000);
        })
        .catch(() => undefined);
    load();
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [id]);

  const cases = useMemo(() => {
    const map = new Map<string, CaseRow>();
    for (const t of threads) {
      const row = map.get(t.case_id) ?? { case_id: t.case_id, category: t.category ?? "general", question: t.question, threads: {} };
      row.threads[t.connector] = t;
      map.set(t.case_id, row);
    }
    return [...map.values()];
  }, [threads]);

  const categoryCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const c of cases) m.set(c.category, (m.get(c.category) ?? 0) + 1);
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [cases]);

  const matches = useCallback(
    (c: CaseRow, conns: Connector[]) => {
      if (category && c.category !== category) return false;
      if (search && !`${c.question} ${c.case_id}`.toLowerCase().includes(search.toLowerCase())) return false;
      const v = conns.map((k) => c.threads[k]?.passed);
      if (outcome === "differ") return v.length === 2 && v[0] != null && v[1] != null && v[0] !== v[1];
      if (outcome === "failed") return v.some((x) => x === false);
      if (outcome === "both-failed") return v.length > 0 && v.every((x) => x === false);
      return true;
    },
    [category, search, outcome]
  );

  if (!run) return <p className="p-6 text-k-body text-ink-muted">Loading run…</p>;
  const visible = cases.filter((c) => matches(c, run.connectors));
  const selected = caseId ? cases.find((c) => c.case_id === caseId) ?? null : null;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <RunBar run={run} onDeleted={onDeleted} />

      <div className="flex min-h-0 flex-1">
        {/* Questions */}
        <aside className={cn("min-h-0 w-full flex-col border-r border-hairline bg-surface lg:flex lg:w-[400px] lg:shrink-0", selected ? "hidden" : "flex")}>
          <div className="space-y-2.5 border-b border-hairline p-4">
            <label className="relative block">
              <Search className="absolute left-3 top-[9px] h-4 w-4 text-ink-subtle" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search questions"
                className="k-input !pl-9"
              />
            </label>
            <div className="flex items-center gap-2">
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                className="k-input !h-8 min-w-0 flex-1 !px-2.5 !text-k-caption"
                aria-label="Category"
              >
                <option value="">All categories ({cases.length})</option>
                {categoryCounts.map(([c, n]) => (
                  <option key={c} value={c}>
                    {c} ({n})
                  </option>
                ))}
              </select>
              <span className="shrink-0 text-k-caption tabular-nums text-ink-subtle">{visible.length} shown</span>
            </div>
            <Segmented items={OUTCOMES} value={outcome} onChange={setOutcome} size="sm" className="flex w-full [&>button]:flex-1 [&>button]:justify-center" />
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {visible.length === 0 && <p className="p-8 text-center text-k-body text-ink-muted">No questions match.</p>}
            {visible.map((c) => (
              <button
                key={c.case_id}
                onClick={() => onCase(c.case_id)}
                className={cn(
                  "block w-full border-b border-hairline px-4 py-3 text-left transition-colors duration-200",
                  c.case_id === caseId ? "bg-brand-soft/60 shadow-[inset_3px_0_0_var(--brand)]" : "hover:bg-sunken"
                )}
              >
                <p className="line-clamp-2 text-k-body leading-snug text-ink">{c.question}</p>
                <div className="mt-1 flex items-center gap-1.5">
                  <span className="min-w-0 flex-1 truncate text-k-caption text-ink-subtle">{c.category}</span>
                  {run.connectors.map((k) => (
                    <ResultPill key={k} label={k} t={c.threads[k]} />
                  ))}
                </div>
              </button>
            ))}
          </div>
        </aside>

        {/* Transcripts, or the category breakdown when nothing is selected */}
        <section className={cn("min-h-0 min-w-0 flex-1 flex-col", selected ? "flex" : "hidden lg:flex")}>
          {selected ? (
            <CaseDetail key={selected.case_id} row={selected} connectors={run.connectors} onBack={() => onCase(null)} />
          ) : (
            <Breakdown cases={cases} connectors={run.connectors} onCategory={setCategory} />
          )}
        </section>
      </div>
    </div>
  );
}

function ResultPill({ label, t }: { label: string; t: ThreadRow | undefined }) {
  if (!t) return null;
  if (t.status !== "scored") {
    return (
      <span className="inline-flex h-5 shrink-0 items-center gap-1 rounded-full bg-neutral-soft px-2 text-[11px] font-semibold text-neutral" title={`${label}: ${t.status}`}>
        {label}
        {isActive(t.status) ? <Spinner className="h-3 w-3" /> : t.status === "failed" ? <XCircle className="h-3 w-3" /> : <CircleDashed className="h-3 w-3" />}
      </span>
    );
  }
  return (
    <StatusPill tone={t.passed ? "ok" : "danger"} size="sm" title={`${label}: ${t.passed ? "passed" : "failed"} · ${t.verdict ?? ""}`} className="tabular-nums">
      {label} {Math.round((t.judge_score ?? 0) * 100)}
    </StatusPill>
  );
}

const METRICS: { key: string; label: string; fmt: (v: number | null | undefined) => string; better: "high" | "low" }[] = [
  { key: "pass_rate", label: "Pass rate", fmt: pct, better: "high" },
  { key: "avg_score", label: "Avg score", fmt: pct, better: "high" },
  { key: "invented", label: "Invented facts", fmt: (v) => (v == null ? "—" : String(v)), better: "low" },
  { key: "avg_tool_calls", label: "Tools / question", fmt: (v) => (v == null ? "—" : v.toFixed(1)), better: "low" },
  { key: "avg_tokens", label: "Tokens / question", fmt: (v) => (v == null ? "—" : v >= 1000 ? `${(v / 1000).toFixed(1)}k` : String(v)), better: "low" },
  { key: "avg_seconds", label: "Seconds / question", fmt: (v) => (v == null ? "—" : v.toFixed(0)), better: "low" },
];

function RunBar({ run, onDeleted }: { run: EvalRun; onDeleted: () => void }) {
  const active = isActive(run.status);
  return (
    <div className="border-b border-hairline bg-surface px-4 py-4 lg:px-6">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="text-[16px] font-bold text-ink">{run.name}</span>
        <StatusPill tone={active ? "brand" : run.status === "completed" ? "ok" : "danger"} size="sm" className="capitalize">
          {run.status}
        </StatusPill>
        <span className="text-k-caption text-ink-muted">
          {run.finished_threads}/{run.total_threads} threads · agent {run.model} · judge {run.judge_model}
        </span>
        <span className="flex-1" />
        {active ? (
          <button onClick={() => cancelRun(run.id)} className="k-btn k-btn-sm">
            <Square className="h-3.5 w-3.5" /> Stop
          </button>
        ) : (
          <button
            onClick={async () => {
              if (window.confirm("Delete this run and all its threads?")) {
                await deleteRun(run.id);
                onDeleted();
              }
            }}
            className="k-btn k-btn-sm hover:!text-danger"
          >
            <Trash2 className="h-3.5 w-3.5" /> Delete
          </button>
        )}
      </div>
      {active && (
        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-neutral-soft">
          <div
            className="h-full rounded-full bg-brand transition-all duration-700 ease-out"
            style={{ width: `${run.total_threads ? (run.finished_threads / run.total_threads) * 100 : 0}%` }}
          />
        </div>
      )}
      {run.error && <p className="mt-1 text-k-caption text-danger">{run.error}</p>}

      <div className="mt-3.5 grid grid-cols-2 gap-2.5 sm:grid-cols-3 xl:grid-cols-6">
        {METRICS.map((m) => {
          const vals = run.connectors.map((c) => (run.summary?.[c] as unknown as Record<string, number | null> | undefined)?.[m.key] ?? null);
          const nums = vals.filter((v): v is number => v != null);
          const best =
            nums.length === run.connectors.length && nums.length > 1 && new Set(nums).size > 1
              ? m.better === "high" ? Math.max(...nums) : Math.min(...nums)
              : null;
          return (
            <div key={m.key} className="k-rise rounded-lg border border-hairline bg-sunken px-3 py-2.5" style={stagger(METRICS.indexOf(m))}>
              <p className="text-k-caption font-medium text-ink-muted">{m.label}</p>
              <div className="mt-1 flex items-baseline gap-3">
                {run.connectors.map((c, i) => (
                  <span key={c} className="tabular-nums">
                    <span className="text-[11px] text-ink-subtle">{c} </span>
                    <span className={cn("text-[17px] font-bold", vals[i] != null && vals[i] === best ? "text-ok" : "text-ink")}>
                      {m.fmt(vals[i])}
                    </span>
                  </span>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function CaseDetail({ row, connectors, onBack }: { row: CaseRow; connectors: Connector[]; onBack: () => void }) {
  const both = connectors.length > 1;
  const [view, setView] = useState<"side" | Connector>(both ? "side" : connectors[0]);
  const shown = view === "side" ? connectors : [view];

  return (
    <>
      <div className="flex items-start gap-3 border-b border-hairline bg-surface px-4 py-4 lg:px-6">
        <button onClick={onBack} className="k-btn k-btn-ghost k-btn-sm !px-1.5 lg:hidden" aria-label="Back to questions">
          <ArrowLeft className="h-4 w-4" />
        </button>
        <div className="min-w-0 flex-1">
          <p className="text-k-caption text-ink-subtle">
            {row.category} · {row.case_id}
          </p>
          <p className="mt-0.5 text-[16px] font-semibold leading-snug text-ink">{row.question}</p>
        </div>
        {both && (
          <Segmented
            items={(["side", ...connectors] as const).map((v) => ({ id: v, label: v === "side" ? "Side by side" : v }))}
            value={view}
            onChange={(v) => setView(v as "side" | Connector)}
          />
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className={cn("grid gap-0", shown.length > 1 && "xl:grid-cols-2 xl:divide-x xl:divide-hairline")}>
          {shown.map((k) =>
            row.threads[k] ? (
              <div key={k} className="k-rise min-w-0 p-4 lg:p-6">
                <ThreadView id={row.threads[k]!.id} label={CONNECTOR_LABEL[k]} />
              </div>
            ) : null
          )}
        </div>
      </div>
    </>
  );
}

function Breakdown({ cases, connectors, onCategory }: { cases: CaseRow[]; connectors: Connector[]; onCategory: (c: string) => void }) {
  const rows = useMemo(() => {
    const out = new Map<string, Partial<Record<Connector, { passed: number; scored: number; score: number }>>>();
    for (const c of cases) {
      const entry = out.get(c.category) ?? {};
      for (const [conn, t] of Object.entries(c.threads) as [Connector, ThreadRow][]) {
        if (t.status !== "scored") continue;
        const s = entry[conn] ?? { passed: 0, scored: 0, score: 0 };
        s.scored += 1;
        s.passed += t.passed ? 1 : 0;
        s.score += t.judge_score ?? 0;
        entry[conn] = s;
      }
      out.set(c.category, entry);
    }
    return [...out.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [cases]);

  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-4 lg:p-6">
      <div className="mb-4">
        <SectionIntro title="By category">Pick a question on the left to replay its conversations, or a category to filter.</SectionIntro>
      </div>
      <div className="kairos-panel k-rise overflow-x-auto">
        <table className="w-full min-w-[440px] text-k-caption">
          <thead>
            <tr className="k-label border-b border-hairline">
              <th className="px-4 py-2.5 text-left font-semibold">Category</th>
              {connectors.map((c) => (
                <th key={c} className="px-4 py-2.5 text-left font-semibold">
                  {CONNECTOR_LABEL[c]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(([cat, by]) => (
              <tr key={cat} onClick={() => onCategory(cat)} className="k-row cursor-pointer border-b border-hairline last:border-b-0">
                <td className="px-4 py-3 text-k-body font-medium text-ink">{cat}</td>
                {connectors.map((c) => {
                  const s = by[c];
                  const rate = s && s.scored ? s.passed / s.scored : null;
                  return (
                    <td key={c} className="px-4 py-3">
                      {s && s.scored ? (
                        <div className="flex items-center gap-2">
                          <div className="h-1.5 w-24 overflow-hidden rounded-full bg-neutral-soft">
                            <div
                              className="k-grow h-full rounded-full"
                              style={{ width: `${(rate ?? 0) * 100}%`, background: rate! >= 0.8 ? "var(--ok-dot)" : rate! >= 0.5 ? "var(--warn-dot)" : "var(--danger-dot)" }}
                            />
                          </div>
                          <span className="font-semibold tabular-nums text-ink">
                            {s.passed}/{s.scored}
                          </span>
                          <span className="tabular-nums text-ink-subtle">avg {Math.round((s.score / s.scored) * 100)}</span>
                        </div>
                      ) : (
                        <span className="text-ink-subtle">—</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
