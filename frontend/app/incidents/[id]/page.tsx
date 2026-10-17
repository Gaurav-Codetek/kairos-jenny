"use client";

import { useEffect, useState, useRef } from "react";
import { useParams } from "next/navigation";
import { fetchApi } from "@/lib/api";
import { describeIncident } from "@/lib/incidents";
import Link from "next/link";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Activity, ArrowLeft, Bot, ExternalLink, Sparkles, ServerCrash, Wrench, Zap } from "lucide-react";

import { EmptyState, Panel, Spinner, StatusPill, stagger } from "@/components/kairos/ds";
import { PageHeader } from "@/components/shell/app-shell";
import ReactMarkdown from "react-markdown";

/** Jev's schema-drift hypothesis, as returned by POST /agent/rca/{id}/jev. */
interface JevResult {
  status: "ok" | "not_configured" | "error";
  reason?: string;
  hypothesis?: string;
  confidence?: number;
  probabilities?: Record<string, number>;
  signals?: Record<string, number>;
  model?: string;
  latency_ms?: number;
  threshold?: number;
  used_as_hint?: boolean;
}

interface VariantSummary {
  id: string;
  class: string;
  variant: string;
  status: "draft" | "proven" | "retired";
  trusted: boolean;
  stats?: { successes?: number; failures?: number; consecutive_failures?: number };
  plan: { id: string; type: string; name: string }[];
}

interface PlanStep {
  id: string;
  type: string;
  name: string;
  ok: boolean;
  ms: number;
  summary: string;
}

interface JevRun {
  jev: JevResult | null;
  agent_classification?: string | null;
  agreement?: boolean | null;
  total_ms?: number;
  mode?: "fast" | "learn" | "fast_fallback_learn" | "open";
  variant_match?: { choice?: string; confidence?: number; reason?: string } | null;
  variant_used?: VariantSummary | null;
  agent_b?: { success: boolean; failure: string | null; steps: PlanStep[]; ms: number; tool_calls: number } | null;
  agent_a?: { tool_calls: number; ms: number } | null;
  variant_learned?: VariantSummary | null;
  compile?: {
    saved: boolean;
    attempts: { attempt?: number; problem: string | null; details?: string[] }[];
    dry_run_steps?: PlanStep[] | null;
  } | null;
}

const MODE_LABEL: Record<string, string> = {
  fast: "Fast · Agent B ran a learned variant",
  learn: "Learn · Agent A investigated and compiled a variant",
  fast_fallback_learn: "Agent B failed → Agent A investigated",
  open: "Open-ended · no confident class",
};

function StepList({ steps }: { steps: PlanStep[] }) {
  return (
    <ol className="mt-1 space-y-0.5 font-mono">
      {steps.map((s) => (
        <li key={s.id} className={s.ok ? "" : "text-danger"}>
          {s.ok ? "✓" : "✗"} {s.id} <span className="opacity-70">[{s.type}:{s.name}]</span> {(s.ms / 1000).toFixed(1)}s
          <div className="pl-4 opacity-70 break-all">{s.summary}</div>
        </li>
      ))}
    </ol>
  );
}

function VariantLine({ title, v }: { title: string; v: VariantSummary }) {
  return (
    <details className="text-k-caption text-ink-muted">
      <summary className="cursor-pointer">
        {title}: <span className="font-mono">{v.id}</span> · {v.trusted ? "trusted" : v.status} ·{" "}
        {v.stats?.successes ?? 0} wins / {v.stats?.failures ?? 0} fails · {v.plan.length} nodes
      </summary>
      <p className="mt-1 italic">{v.variant}</p>
      <p className="mt-1 font-mono">{v.plan.map((n) => `${n.id}[${n.type}]`).join(" → ")}</p>
    </details>
  );
}

const pct = (n: number) => `${Math.round(n * 100)}%`;

function JevPanel({ run }: { run: JevRun }) {
  const jev = run.jev;
  return (
    <div className="not-prose mb-4 space-y-3 border-b border-hairline pb-4">
      <span className="k-label flex items-center gap-1">
        <Zap className="h-3 w-3" /> Jev Triage
      </span>

      {!jev || jev.status !== "ok" ? (
        <p className="text-xs text-ink-muted">
          Jev did not run{jev?.reason ? `: ${jev.reason}` : "."} The agent investigated without a hypothesis.
        </p>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-ink-muted">Hypothesis</span>
            <StatusPill tone="brand" size="sm" dot={false} className="font-mono">{jev.hypothesis}</StatusPill>
            <span className="text-ink-muted">confidence {pct(jev.confidence ?? 0)}</span>
            <StatusPill tone="neutral" size="sm" dot={false}>
              {jev.used_as_hint ? "given to agent" : `not used (below ${pct(jev.threshold ?? 0)} or not schema)`}
            </StatusPill>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-ink-muted">Agent final</span>
            <StatusPill tone="brand" size="sm" dot={false} className="font-mono">{run.agent_classification ?? "not stated"}</StatusPill>
            {run.agreement != null && (
              <StatusPill tone={run.agreement ? "ok" : "danger"} size="sm">
                {run.agreement ? "agrees" : "disagrees"}
              </StatusPill>
            )}
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-k-caption font-mono text-ink-muted">
            {Object.entries(jev.probabilities ?? {}).map(([label, p]) => (
              <div key={label} className="flex justify-between"><span>{label}</span><span>{pct(p)}</span></div>
            ))}
            {Object.entries(jev.signals ?? {}).map(([name, p]) => (
              <div key={name} className="flex justify-between"><span>{name}</span><span>{pct(p)}</span></div>
            ))}
          </div>
          {run.mode && (
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="text-ink-muted">Mode</span>
              <StatusPill tone="neutral" size="sm" dot={false}>{MODE_LABEL[run.mode] ?? run.mode}</StatusPill>
              {run.variant_match && (
                <span className="text-k-caption text-ink-muted">
                  variant pick: {run.variant_match.choice ?? run.variant_match.reason}
                  {run.variant_match.confidence != null && ` (${pct(run.variant_match.confidence)})`}
                </span>
              )}
            </div>
          )}
          {run.variant_used && <VariantLine title="Variant used" v={run.variant_used} />}
          {run.agent_b && (
            <details className="text-k-caption text-ink-muted" open={!run.agent_b.success}>
              <summary className="cursor-pointer">
                Agent B: {run.agent_b.success ? "diagnosed" : `failed — ${run.agent_b.failure}`} ·{" "}
                {run.agent_b.tool_calls} tool calls · {(run.agent_b.ms / 1000).toFixed(1)} s
              </summary>
              <StepList steps={run.agent_b.steps} />
            </details>
          )}
          {run.agent_a && (
            <p className="text-k-caption text-ink-muted">
              Agent A: {run.agent_a.tool_calls} tool calls · {(run.agent_a.ms / 1000).toFixed(1)} s
            </p>
          )}
          {run.variant_learned && <VariantLine title="Variant learned" v={run.variant_learned} />}
          {run.compile && !run.compile.saved && (
            <details className="text-k-caption text-danger">
              <summary className="cursor-pointer">No variant saved after {run.compile.attempts.length} compile attempts</summary>
              <ul className="mt-1 list-disc pl-5">
                {run.compile.attempts.map((a, i) => (
                  <li key={i}>{a.problem}{a.details ? `: ${a.details.join("; ")}` : ""}</li>
                ))}
              </ul>
            </details>
          )}
          {run.compile?.saved && run.compile.dry_run_steps && (
            <details className="text-k-caption text-ink-muted">
              <summary className="cursor-pointer">
                Dry run of the new variant on this incident ({run.compile.attempts.length} compile attempt
                {run.compile.attempts.length === 1 ? "" : "s"})
              </summary>
              <StepList steps={run.compile.dry_run_steps} />
            </details>
          )}
          <p className="text-k-caption text-ink-muted">
            {jev.model} · Jev {jev.latency_ms} ms · total {((run.total_ms ?? 0) / 1000).toFixed(1)} s
          </p>
        </>
      )}
    </div>
  );
}

export default function IncidentDetail() {
  const params = useParams();
  const id = params.id as string;
  
  const [run, setRun] = useState<any>(null);
  const [loadingAgent, setLoadingAgent] = useState(false);
  const [rcaReport, setRcaReport] = useState<string | null>(null);
  const [toolsUsed, setToolsUsed] = useState<string[]>([]);
  const [jevRun, setJevRun] = useState<JevRun | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    async function loadRun() {
      try {
        const data = await fetchApi(`/incidents/${id}`);
        setRun(data);
      } catch (err) {
        console.error(err);
      }
    }
    loadRun();
  }, [id]);

  const generateRCA = async () => {
    setLoadingAgent(true);
    setRcaReport(null);
    setToolsUsed([]);
    setJevRun(null);
    try {
      const data = await fetchApi(`/agent/rca/${id}`, { method: "POST" });
      setRcaReport(data.response);
      setToolsUsed(data.tools_used || []);
    } catch (err) {
      setRcaReport("Error generating RCA. Please check logs.");
    } finally {
      setLoadingAgent(false);
    }
  };

  // Experimental: Jev classifies the schema-drift subtype, the agent verifies it.
  const generateJevRCA = async () => {
    setLoadingAgent(true);
    setRcaReport(null);
    setToolsUsed([]);
    setJevRun(null);
    try {
      const data = await fetchApi(`/agent/rca/${id}/jev`, { method: "POST" });
      setJevRun(data);
      setRcaReport(data.response);
      setToolsUsed(data.tools_used || []);
    } catch (err) {
      setRcaReport("Error generating Jev RCA. Please check logs.");
    } finally {
      setLoadingAgent(false);
    }
  };

  const runButtons = (
    <div className="flex flex-wrap justify-center gap-2">
      <button onClick={generateRCA} disabled={loadingAgent} className="k-btn k-btn-primary">
        <Sparkles className="h-4 w-4" /> Generate root cause analysis
      </button>
      <button onClick={generateJevRCA} disabled={loadingAgent} className="k-btn">
        <Zap className="h-4 w-4" /> Run JEV RCA
      </button>
    </div>
  );

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [rcaReport]);

  if (!run)
    return (
      <div className="flex flex-1 items-center justify-center">
        <Spinner />
      </div>
    );

  const d = describeIncident(run);

  return (
    <>
      <PageHeader
        title={run.run_name || d.title}
        description={`${d.workspace ?? "Failed run"} · run ${run.source_native_id ?? ""}`}
        actions={
          <Link href="/incidents" className="k-btn">
            <ArrowLeft className="h-4 w-4" /> All incidents
          </Link>
        }
      />

      <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-7 py-6 md:flex-row md:overflow-hidden">
        {/* Incident context */}
        <div className="flex min-h-0 flex-1 flex-col gap-4 md:overflow-y-auto">
          <Panel
            title="What failed"
            icon={ServerCrash}
            action={<StatusPill tone="danger">{run.result_state}</StatusPill>}
            className="k-rise"
            bodyClassName="space-y-4 p-5"
          >
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-lg border border-hairline bg-sunken px-4 py-3">
                <p className="text-k-caption font-medium text-ink-muted">Started</p>
                <p className="mt-0.5 text-k-title font-semibold tabular-nums text-ink">
                  {new Date(run.start_time).toLocaleString()}
                </p>
              </div>
              <div className="rounded-lg border border-hairline bg-sunken px-4 py-3">
                <p className="text-k-caption font-medium text-ink-muted">Ran for</p>
                <p className="mt-0.5 text-k-title font-semibold tabular-nums text-ink">
                  {run.execution_duration_ms ? `${(run.execution_duration_ms / 1000).toFixed(1)}s` : d.duration ?? "Unknown"}
                </p>
              </div>
            </div>

            {run.error_message && (
              <div>
                <p className="mb-2 flex items-center gap-1.5 text-k-caption font-semibold text-danger">
                  <Activity className="h-4 w-4" /> Top-level error
                </p>
                <pre className="overflow-x-auto whitespace-pre-wrap rounded-lg border border-hairline bg-danger-soft/50 px-3.5 py-3 font-mono text-k-caption leading-relaxed text-ink-2">
                  {run.error_message}
                </pre>
              </div>
            )}

            {run.failed_tasks && run.failed_tasks.length > 0 && (
              <div>
                <p className="mb-2 text-k-caption font-semibold text-ink-2">Failed tasks</p>
                <div className="space-y-2.5">
                  {run.failed_tasks.map((task: any, idx: number) => (
                    <div key={idx} className="kairos-panel k-rise p-3.5" style={stagger(idx)}>
                      <div className="mb-2 flex items-center justify-between gap-2">
                        <span className="truncate font-mono text-k-body font-semibold text-ink">{task.task_key}</span>
                        <StatusPill tone="danger" size="sm">
                          Failed
                        </StatusPill>
                      </div>
                      <p className="overflow-x-auto rounded-md bg-sunken px-2.5 py-2 text-k-caption text-ink-muted">
                        {task.error_message || "No specific task error available."}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {run.run_page_url && (
              <a href={run.run_page_url} target="_blank" rel="noreferrer" className="k-btn k-btn-sm">
                Open in platform <ExternalLink className="h-3.5 w-3.5" />
              </a>
            )}
          </Panel>
        </div>

        {/* AI copilot */}
        <section className="kairos-panel k-rise flex min-h-[480px] flex-1 flex-col overflow-hidden md:min-h-0" style={stagger(1)}>
          <header className="flex min-h-[48px] items-center gap-2.5 border-b border-hairline px-4 py-2.5">
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-brand-soft text-brand">
              <Bot className="h-4 w-4" />
            </span>
            <h2 className="text-k-title font-semibold text-ink">AI data engineer copilot</h2>
            <StatusPill tone="brand" size="sm" className="ml-auto">
              LangGraph ready
            </StatusPill>
          </header>

          <ScrollArea className="min-h-0 flex-1">
            <div className="flex flex-col gap-6 p-6">
              {!rcaReport && !loadingAgent && (
                <EmptyState icon={Sparkles} title="Ready to investigate this failed pipeline" action={runButtons}>
                  I will read the error logs, trace the table lineage, and check for recent schema or configuration
                  changes in the Synthetic Warehouse.
                </EmptyState>
              )}

              {loadingAgent && (
                <div className="flex items-start gap-3">
                  <span className="relative flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand">
                    <span className="k-pulse absolute inset-0 rounded-full bg-brand/30" />
                    <Bot className="relative h-4 w-4" />
                  </span>
                  <div className="flex-1 space-y-2.5 pt-1">
                    <div className="h-3.5 w-3/4 animate-pulse rounded-full bg-neutral-soft" />
                    <div className="h-3.5 w-1/2 animate-pulse rounded-full bg-neutral-soft" />
                    <div className="h-3.5 w-5/6 animate-pulse rounded-full bg-neutral-soft" />
                    <span className="mt-2 flex items-center gap-2 text-k-caption text-ink-muted">
                      <Spinner /> Querying Synthetic Warehouse tools…
                    </span>
                  </div>
                </div>
              )}

              {rcaReport && (
                <div ref={scrollRef} className="k-rise flex items-start gap-3">
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand text-white">
                    <Bot className="h-4 w-4" />
                  </span>
                  <div className="prose prose-sm max-w-none flex-1 rounded-lg border border-hairline bg-sunken p-5 prose-headings:text-ink prose-p:text-ink-2 prose-a:text-brand">
                    {jevRun && <JevPanel run={jevRun} />}
                    {toolsUsed.length > 0 && (
                      <div className="not-prose mb-4 border-b border-hairline pb-4">
                        <span className="mb-2 flex items-center gap-1.5 text-k-caption font-semibold text-ink-2">
                          <Wrench className="h-3.5 w-3.5" /> Tools used
                        </span>
                        <div className="flex flex-wrap gap-1.5">
                          {toolsUsed.map((tool, idx) => (
                            <span
                              key={idx}
                              className="rounded-full bg-brand-soft px-2.5 py-0.5 font-mono text-[11px] font-semibold text-brand-strong"
                            >
                              {tool}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                    <ReactMarkdown>{rcaReport}</ReactMarkdown>
                  </div>
                </div>
              )}
            </div>
          </ScrollArea>

          {rcaReport && (
            <div className="space-y-3 border-t border-hairline bg-sunken px-4 py-3.5 text-center text-k-caption text-ink-muted">
              <p>Analysis complete. Check LangSmith for the detailed trace.</p>
              {runButtons}
            </div>
          )}
        </section>
      </div>
    </>
  );
}
