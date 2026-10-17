"use client";

import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, ChevronDown, Play, RefreshCw, XCircle } from "lucide-react";

import {
  getContextHealth,
  getEval,
  listEvals,
  reindexWorkspace,
  runEval,
  type ContextHealth,
  type EvalReport,
  type EvalSummary,
} from "@/lib/agents";
import { Spinner } from "@/components/kairos/ds";
import { cn } from "@/lib/utils";
import { Empty, timeAgo } from "./bits";
import { DemandPanel } from "./demand-panel";

function Funnel({ ws, onReindex }: { ws: ContextHealth["workspaces"][number]; onReindex: () => void }) {
  const steps = [
    { label: "Synced", n: ws.tables, color: "var(--neutral-dot)" },
    { label: "Searchable", n: ws.tables_indexed, color: "var(--brand)" },
    { label: "Profiled", n: ws.tables_profiled, color: "var(--warn-dot)" },
    { label: "Verified", n: ws.tables_verified, color: "var(--ok-dot)" },
  ];
  return (
    <div className="kairos-panel k-rise p-4">
      <div className="flex items-center gap-2">
        <p className="text-k-title font-semibold text-ink">{ws.name}</p>
        <span className="text-k-caption text-ink-subtle">tables · synced {timeAgo(ws.last_synced_at)}</span>
        <button
          onClick={onReindex}
          disabled={ws.indexing}
          className="k-btn k-btn-sm ml-auto"
        >
          {ws.indexing ? <Spinner /> : <RefreshCw className="h-3.5 w-3.5" />}
          {ws.indexing ? "Indexing…" : "Rebuild index"}
        </button>
      </div>
      <div className="mt-4 space-y-2.5">
        {steps.map((s) => (
          <div key={s.label} className="grid grid-cols-[84px_1fr_64px] items-center gap-2">
            <span className="text-k-caption text-ink-muted">{s.label}</span>
            <div className="h-2 overflow-hidden rounded-full bg-neutral-soft">
              <div className="k-grow h-full rounded-full" style={{ width: `${ws.tables ? (s.n / ws.tables) * 100 : 0}%`, background: s.color }} />
            </div>
            <span className="text-right text-k-caption tabular-nums text-ink">
              {s.n} <span className="text-ink-subtle">({ws.tables ? Math.round((s.n / ws.tables) * 100) : 0}%)</span>
            </span>
          </div>
        ))}
      </div>
      <p className="mt-3 border-t border-hairline pt-3 text-k-caption text-ink-subtle">
        {ws.documents} entities searchable · {ws.documents_embedded} with meaning vectors · {ws.open_feedback} open report(s)
      </p>
    </div>
  );
}

function ReportDetail({ file }: { file: string }) {
  const [report, setReport] = useState<EvalReport | null>(null);
  const [openCase, setOpenCase] = useState<string | null>(null);
  useEffect(() => {
    getEval(file).then(setReport).catch(() => setReport(null));
  }, [file]);
  if (!report) return <Spinner className="m-4" />;
  return (
    <div className="space-y-3 border-t border-hairline bg-sunken/50 px-4 py-3">
      {report.context_gaps.length > 0 && (
        <div>
          <p className="text-k-caption font-medium text-ink-muted">Context gaps this run found</p>
          <ul className="mt-1 space-y-1 text-k-caption text-ink">
            {report.context_gaps.map((g) => (
              <li key={g.case}>
                <span className="font-mono text-k-caption text-ink-subtle">{g.case}</span> — {g.gap}
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="overflow-hidden rounded-lg border border-hairline bg-surface">
        {report.results.map((r) => (
          <div key={r.id} className="border-b border-hairline last:border-b-0">
            <button onClick={() => setOpenCase(openCase === r.id ? null : r.id)} className="k-row flex w-full items-center gap-2 px-3 py-2.5 text-left">
              {r.passed ? (
                <CheckCircle2 className="h-4 w-4 shrink-0" style={{ color: "var(--ok-dot)" }} />
              ) : (
                <XCircle className="h-4 w-4 shrink-0" style={{ color: "var(--danger-dot)" }} />
              )}
              <span className="w-28 shrink-0 text-k-caption text-ink-subtle">{r.role}</span>
              <span className="min-w-0 flex-1 truncate text-k-caption text-ink">{r.question}</span>
              <span className="shrink-0 text-k-caption tabular-nums text-ink-muted">
                judge {r.judge_score.toFixed(2)} · {r.tool_calls} calls · {r.seconds}s
              </span>
              <ChevronDown className={cn("h-3.5 w-3.5 shrink-0 text-ink-subtle transition-transform", openCase === r.id && "rotate-180")} />
            </button>
            {openCase === r.id && (
              <div className="space-y-1.5 px-9 pb-3 text-k-caption">
                {r.verdict && <p className="text-ink-muted">Judge: {r.verdict}</p>}
                {r.mentions_missing.length > 0 && <p className="text-danger">Missing: {r.mentions_missing.join("; ")}</p>}
                <p className="text-k-caption text-ink-subtle">Tools: {r.tools_used.join(" → ") || "none"}</p>
                <pre className="max-h-64 overflow-y-auto whitespace-pre-wrap rounded-lg border border-hairline bg-sunken px-3 py-2 text-k-caption text-ink-2">{r.answer}</pre>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export function ReadinessPanel() {
  const [health, setHealth] = useState<ContextHealth | null>(null);
  const [evals, setEvals] = useState<{ running: string[]; reports: EvalSummary[] }>({ running: [], reports: [] });
  const [openFile, setOpenFile] = useState<string | null>(null);

  const reload = useCallback(() => {
    getContextHealth().then(setHealth).catch(() => undefined);
    listEvals().then(setEvals).catch(() => undefined);
  }, []);

  useEffect(() => {
    reload();
    const h = window.setInterval(reload, 6000);
    return () => window.clearInterval(h);
  }, [reload]);

  const latest = (toolset: string) => evals.reports.find((r) => r.toolset === toolset);
  const full = latest("full");
  const legacy = latest("legacy");

  return (
    <div className="space-y-4">
      <section className="kairos-panel p-5">
        <div className="flex flex-wrap items-start gap-4">
          <div className="max-w-xl">
            <h3 className="text-k-title font-semibold text-ink">Could a brand-new agent use this platform?</h3>
            <p className="mt-1 text-k-body leading-relaxed text-ink-muted">
              The cold-agent test gives a generic agent nothing but its Kairos connection and asks it questions an
              analyst, a pipeline engineer, a governance reviewer and an incident responder would ask. Every failure names
              the context the agent was missing — that is the backlog for making the map better.
            </p>
          </div>
          <div className="ml-auto flex gap-3">
            {[
              { label: "With Kairos context", r: full },
              { label: "Graph tools only", r: legacy },
            ].map(({ label, r }) => (
              <div key={label} className="min-w-[170px] rounded-lg border border-hairline bg-sunken px-4 py-3">
                <p className="text-k-caption font-medium text-ink-muted">{label}</p>
                <p className="mt-1 text-k-stat font-bold tabular-nums text-ink">{r ? `${Math.round(r.readiness * 100)}%` : "—"}</p>
                <p className="text-k-caption tabular-nums text-ink-subtle">
                  {r ? `${r.passed}/${r.cases} passed · ${timeAgo(r.ran_at)}` : "not run yet"}
                </p>
              </div>
            ))}
          </div>
        </div>
        <div className="mt-4 flex gap-2">
          {(["full", "legacy"] as const).map((t) => (
            <button
              key={t}
              disabled={evals.running.includes(t)}
              onClick={async () => {
                await runEval(t);
                reload();
              }}
              className={cn("k-btn", t === "full" && "k-btn-primary")}
            >
              {evals.running.includes(t) ? <Spinner className={t === "full" ? "border-white/30" : ""} /> : <Play className="h-3.5 w-3.5" />}
              {evals.running.includes(t) ? "Running…" : t === "full" ? "Run the test" : "Run with graph tools only"}
            </button>
          ))}
          <span className="self-center text-k-caption text-ink-subtle">A few minutes; uses LLM budget.</span>
        </div>
      </section>

      <DemandPanel />

      <div className="grid gap-4 lg:grid-cols-2">
        {(health?.workspaces ?? []).filter((w) => w.tables > 0).map((w) => (
          <Funnel
            key={w.workspace_id}
            ws={w}
            onReindex={async () => {
              await reindexWorkspace(w.workspace_id);
              reload();
            }}
          />
        ))}
      </div>

      <section className="kairos-panel overflow-hidden">
        <p className="flex min-h-[48px] items-center border-b border-hairline px-4 text-k-title font-semibold text-ink">Test history</p>
        {evals.reports.length === 0 && <Empty>No runs yet.</Empty>}
        {evals.reports.map((r) => (
          <div key={r.file} className="border-b border-hairline last:border-b-0">
            <button onClick={() => setOpenFile(openFile === r.file ? null : r.file)} className="k-row flex w-full items-center gap-3 px-4 py-3 text-left">
              <span className="w-24 text-k-caption text-ink-muted">{r.toolset === "full" ? "Kairos context" : "graph only"}</span>
              <span className="w-14 text-k-body font-semibold tabular-nums text-ink">{Math.round(r.readiness * 100)}%</span>
              <span className="text-k-caption tabular-nums text-ink-muted">
                {r.passed}/{r.cases} · judge {r.mean_judge_score.toFixed(2)} · {r.tool_calls} calls · {r.tokens.toLocaleString()} tokens
              </span>
              <span className="ml-auto text-k-caption text-ink-subtle">{timeAgo(r.ran_at)}</span>
              <ChevronDown className={cn("h-3.5 w-3.5 text-ink-subtle transition-transform", openFile === r.file && "rotate-180")} />
            </button>
            {openFile === r.file && <ReportDetail file={r.file} />}
          </div>
        ))}
      </section>
    </div>
  );
}
