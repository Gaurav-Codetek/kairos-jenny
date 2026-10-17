"use client";

/**
 * The Test screen's side panel: what the agent did and what Kairos recorded.
 *
 *  Trace      the agent's own steps, live: connecting, each model step with tokens and time,
 *             each tool call with its arguments and result, the answer
 *  Audit      Kairos's audit log for the console's agent: tool, channel, latency, tokens, cost,
 *             the entities each call touched
 *  Behaviour  the session summed up: tools used, errors, latency, tokens and cost, entities and
 *             data products touched, queries run, and anything that looks off
 */

import { useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowRightLeft,
  Bot,
  Braces,
  Check,
  ChevronRight,
  Clock,
  Coins,
  Cpu,
  Database,
  Layers,
  Plug,
  ShieldCheck,
  Wrench,
  X,
} from "lucide-react";

import { Meter, StatusPill, Tabs } from "@/components/kairos/ds";
import { cn } from "@/lib/utils";
import type { AuditRow, ConsoleSession, TraceEvent } from "@/lib/test-console";

const TABS = [
  { id: "trace", label: "Trace" },
  { id: "audit", label: "Audit trail" },
  { id: "behaviour", label: "Behaviour" },
] as const;
type Tab = (typeof TABS)[number]["id"];

const fmtMs = (ms: number) => (ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`);
const fmtTok = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));
const time = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const tail = (id: string) => id.split(":").pop()!.split(".").pop()!;

export function MonitorPanel({ session, trace, audit }: { session: ConsoleSession | null; trace: TraceEvent[]; audit: AuditRow[] }) {
  const [tab, setTab] = useState<Tab>("trace");
  return (
    <aside className="flex min-h-0 flex-col border-l border-hairline bg-surface">
      <Tabs
        size="panel"
        items={TABS.map((t) => ({ ...t, count: t.id === "trace" ? trace.filter((e) => e.type === "tool_call").length : t.id === "audit" ? audit.length : undefined }))}
        value={tab}
        onChange={setTab}
      />
      <div className="min-h-0 flex-1 overflow-y-auto">
        {tab === "trace" && <Trace trace={trace} running={session?.status === "running"} />}
        {tab === "audit" && <Audit audit={audit} />}
        {tab === "behaviour" && <Behaviour session={session} trace={trace} audit={audit} />}
      </div>
    </aside>
  );
}

// ── trace ──────────────────────────────────────────────────────────────

function Trace({ trace, running }: { trace: TraceEvent[]; running: boolean }) {
  const turns = useMemo(() => {
    const m = new Map<number, TraceEvent[]>();
    trace.forEach((e) => m.set(e.turn, [...(m.get(e.turn) ?? []), e]));
    return [...m.entries()];
  }, [trace]);
  if (!trace.length)
    return <p className="px-4 py-6 text-k-body text-ink-muted">Ask something: every step the agent takes appears here as it happens.</p>;
  return (
    <div className="space-y-4 px-4 py-4">
      {turns.map(([turn, events]) => (
        <section key={turn}>
          <p className="k-label mb-2">{turn ? `Turn ${turn}` : "Session"}</p>
          <ol className="relative space-y-1.5 border-l border-hairline pl-4">
            {events.map((e, i) => (
              <TraceItem key={i} e={e} />
            ))}
            {running && turn === turns[turns.length - 1][0] && (
              <li className="flex items-center gap-2 text-k-caption text-brand">
                <span className="k-spin inline-block h-3 w-3 rounded-full border-2 border-brand-soft" style={{ borderTopColor: "var(--brand)" }} />
                working…
              </li>
            )}
          </ol>
        </section>
      ))}
    </div>
  );
}

function Dot({ tone }: { tone: string }) {
  return <span className="absolute -left-[21px] top-1.5 h-2.5 w-2.5 rounded-full ring-2 ring-surface" style={{ background: tone }} />;
}

function TraceItem({ e }: { e: TraceEvent }) {
  const [open, setOpen] = useState(false);
  if (e.type === "connect")
    return (
      <li className="relative text-k-caption text-ink-muted">
        <Dot tone="var(--neutral-dot)" />
        <Plug className="mr-1 inline h-3 w-3" /> Connected to <span className="font-mono text-ink-2">{e.connector}</span> · {e.tools.length} tools ·{" "}
        {fmtMs(e.ms)}
      </li>
    );
  if (e.type === "switch")
    return (
      <li className="relative text-k-caption text-ink-muted">
        <Dot tone="var(--warn-dot)" />
        <ArrowRightLeft className="mr-1 inline h-3 w-3" /> Switched {e.from} → {e.to}
      </li>
    );
  if (e.type === "llm")
    return (
      <li className="relative">
        <Dot tone="var(--brand)" />
        <p className="text-k-caption text-ink-2">
          <Cpu className="mr-1 inline h-3 w-3 text-brand" />
          Model step {e.step} · {fmtMs(e.ms)} · {fmtTok(e.input_tokens)} in / {fmtTok(e.output_tokens)} out
        </p>
        <p className="text-[11px] text-ink-muted">{e.tool_calls.length ? `decided to call ${e.tool_calls.join(", ")}` : "wrote the answer"}</p>
        {e.thought && <p className="mt-0.5 line-clamp-2 text-[11px] italic text-ink-subtle">“{e.thought}”</p>}
      </li>
    );
  if (e.type === "tool_call")
    return (
      <li className="relative">
        <Dot tone={e.ok ? "var(--ok-dot)" : "var(--danger-dot)"} />
        <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-1.5 text-left">
          <ChevronRight className={cn("h-3 w-3 shrink-0 text-ink-subtle transition-transform", open && "rotate-90")} />
          <span className="font-mono text-[12px] font-semibold text-ink">{e.tool}</span>
          <StatusPill tone={e.ok ? "ok" : "danger"} size="sm">
            {e.ok ? "ok" : "error"}
          </StatusPill>
          <span className="ml-auto text-[11px] tabular-nums text-ink-muted">
            {fmtMs(e.ms)} · {fmtTok(e.result_chars)} chars
          </span>
        </button>
        <p className="ml-[18px] truncate font-mono text-[10.5px] text-ink-subtle">{JSON.stringify(e.args)}</p>
        {open && (
          <div className="k-rise ml-[18px] mt-1.5 space-y-1.5">
            <pre className="max-h-40 overflow-auto rounded-md bg-sunken p-2 font-mono text-[10.5px] text-ink-2">{JSON.stringify(e.args, null, 2)}</pre>
            <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-md bg-[#0F172A] p-2 font-mono text-[10.5px] leading-relaxed text-[#E2E8F0]">
              {e.result}
              {e.truncated ? "\n…" : ""}
            </pre>
          </div>
        )}
      </li>
    );
  if (e.type === "answer")
    return (
      <li className="relative text-k-caption text-ink-2">
        <Dot tone="var(--ok-dot)" />
        <Check className="mr-1 inline h-3 w-3 text-ok" />
        Answered in {fmtMs(e.ms)} · {fmtTok(e.input_tokens + e.output_tokens)} tokens · {e.tools.length} tool call{e.tools.length === 1 ? "" : "s"}
        {e.step_limit && <span className="ml-1 text-warn">· hit the step limit</span>}
      </li>
    );
  return (
    <li className="relative text-k-caption text-danger">
      <Dot tone="var(--danger-dot)" />
      <X className="mr-1 inline h-3 w-3" />
      {e.error}
    </li>
  );
}

// ── audit ──────────────────────────────────────────────────────────────

function Audit({ audit }: { audit: AuditRow[] }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!audit.length)
    return (
      <p className="px-4 py-6 text-k-body text-ink-muted">
        Nothing recorded yet. Every call the agent makes to Kairos is written to the audit log as the{" "}
        <span className="font-mono">test-console</span> agent and appears here.
      </p>
    );
  return (
    <div className="divide-y divide-hairline">
      {[...audit].reverse().map((a) => (
        <div key={a.id} className="px-4 py-2.5">
          <button onClick={() => setOpen(open === a.id ? null : a.id)} className="flex w-full items-center gap-2 text-left">
            <span className="text-[11px] tabular-nums text-ink-subtle">{time(a.at)}</span>
            <span className="truncate font-mono text-[12px] font-semibold text-ink">{a.tool}</span>
            <StatusPill tone={a.ok ? "ok" : "danger"} size="sm" className="ml-auto">
              {a.ok ? "ok" : "error"}
            </StatusPill>
          </button>
          <p className="mt-0.5 flex flex-wrap gap-x-2.5 text-[11px] text-ink-muted">
            <span className="font-mono">{a.channel}</span>
            <span>{fmtMs(a.duration_ms)}</span>
            {a.result_tokens != null && <span>~{fmtTok(a.result_tokens)} result tokens</span>}
            {a.est_cost_usd != null && <span>${a.est_cost_usd.toFixed(5)}</span>}
          </p>
          {a.entities.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1">
              {a.entities.slice(0, 6).map((e) => (
                <span key={e} className="rounded bg-sunken px-1.5 py-0.5 font-mono text-[10px] text-ink-2" title={e}>
                  {tail(e)}
                </span>
              ))}
              {a.entities.length > 6 && <span className="text-[10px] text-ink-subtle">+{a.entities.length - 6}</span>}
            </div>
          )}
          {a.error && <p className="mt-1 text-[11px] text-danger">{a.error}</p>}
          {open === a.id && (
            <pre className="k-rise mt-1.5 max-h-40 overflow-auto rounded-md bg-sunken p-2 font-mono text-[10.5px] text-ink-2">
              {JSON.stringify(a.arguments, null, 2)}
            </pre>
          )}
        </div>
      ))}
    </div>
  );
}

// ── behaviour ──────────────────────────────────────────────────────────

function Behaviour({ session, trace, audit }: { session: ConsoleSession | null; trace: TraceEvent[]; audit: AuditRow[] }) {
  const b = useMemo(() => {
    const calls = trace.filter((e): e is Extract<TraceEvent, { type: "tool_call" }> => e.type === "tool_call");
    const answers = trace.filter((e): e is Extract<TraceEvent, { type: "answer" }> => e.type === "answer");
    const byTool = new Map<string, { n: number; ms: number; errors: number }>();
    calls.forEach((c) => {
      const t = byTool.get(c.tool) ?? { n: 0, ms: 0, errors: 0 };
      t.n += 1;
      t.ms += c.ms;
      t.errors += c.ok ? 0 : 1;
      byTool.set(c.tool, t);
    });
    const entities = new Map<string, number>();
    audit.forEach((a) => a.entities.forEach((e) => entities.set(e, (entities.get(e) ?? 0) + 1)));
    const products = new Map<string, number>();
    calls.forEach((c) => {
      const p = c.args.product;
      if (typeof p === "string") products.set(p, (products.get(p) ?? 0) + 1);
    });
    const queries = calls
      .filter((c) => c.tool === "run_sql" || c.tool === "query_data_product")
      .map((c) => (c.tool === "run_sql" ? String(c.args.sql ?? "") : `${c.args.product}: ${JSON.stringify({ metrics: c.args.metrics, by: c.args.by, tool: c.args.tool })}`));
    const flags: string[] = [];
    calls.filter((c) => !c.ok).forEach((c) => flags.push(`${c.tool} returned an error`));
    calls.filter((c) => c.ms > 5000).forEach((c) => flags.push(`${c.tool} took ${fmtMs(c.ms)}`));
    calls.filter((c) => c.result_chars > 20000).forEach((c) => flags.push(`${c.tool} returned ${fmtTok(c.result_chars)} chars — heavy for the agent's context`));
    answers.filter((a) => a.step_limit).forEach(() => flags.push("an answer hit the step limit"));
    const toolMs = calls.reduce((s, c) => s + c.ms, 0);
    const answerMs = answers.reduce((s, a) => s + a.ms, 0);
    const cost = audit.reduce((s, a) => s + (a.est_cost_usd ?? 0), 0);
    return { calls, answers, byTool, entities, products, queries, flags, toolMs, answerMs, cost };
  }, [trace, audit]);
  const t = session?.totals;
  const maxTool = Math.max(1, ...[...b.byTool.values()].map((x) => x.n));
  const stats: [string, string, typeof Bot][] = [
    ["Turns", String(session?.turns ?? 0), Bot],
    ["Tool calls", `${t?.tool_calls ?? 0}${t?.tool_errors ? ` · ${t.tool_errors} failed` : ""}`, Wrench],
    ["Model steps", String(t?.llm_steps ?? 0), Cpu],
    ["Tokens", `${fmtTok(t?.input_tokens ?? 0)} in · ${fmtTok(t?.output_tokens ?? 0)} out`, Coins],
    ["Time in tools", b.answerMs ? `${fmtMs(b.toolMs)} of ${fmtMs(b.answerMs)}` : "–", Clock],
    ["Kairos cost (audit)", `$${b.cost.toFixed(4)}`, ShieldCheck],
  ];
  return (
    <div className="space-y-5 px-4 py-4">
      <div className="grid grid-cols-2 gap-2">
        {stats.map(([l, v, Icon]) => (
          <div key={l} className="rounded-lg bg-sunken px-3 py-2">
            <p className="flex items-center gap-1 text-[11px] text-ink-muted">
              <Icon className="h-3 w-3" /> {l}
            </p>
            <p className="mt-0.5 text-k-body font-semibold tabular-nums text-ink">{v}</p>
          </div>
        ))}
      </div>
      {b.flags.length > 0 && (
        <section>
          <p className="k-label mb-1.5">Worth a look</p>
          <ul className="space-y-1">
            {b.flags.map((f, i) => (
              <li key={i} className="flex gap-1.5 text-k-caption text-warn">
                <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" /> {f}
              </li>
            ))}
          </ul>
        </section>
      )}
      <section>
        <p className="k-label mb-1.5">Tools used</p>
        {b.byTool.size === 0 ? (
          <p className="text-k-caption text-ink-subtle">None yet.</p>
        ) : (
          <div className="space-y-1.5">
            {[...b.byTool.entries()].sort((a, c) => c[1].n - a[1].n).map(([tool, x], i) => (
              <div key={tool}>
                <div className="flex items-center gap-2 text-k-caption">
                  <span className="font-mono text-ink-2">{tool}</span>
                  <span className="ml-auto tabular-nums text-ink-muted">
                    {x.n}× · avg {fmtMs(Math.round(x.ms / x.n))}
                    {x.errors ? ` · ${x.errors} failed` : ""}
                  </span>
                </div>
                <Meter value={x.n} max={maxTool} index={i} tone={x.errors ? "danger" : "brand"} />
              </div>
            ))}
          </div>
        )}
      </section>
      {b.products.size > 0 && (
        <section>
          <p className="k-label mb-1.5">Data products used</p>
          <div className="flex flex-wrap gap-1.5">
            {[...b.products.entries()].map(([p, n]) => (
              <StatusPill key={p} tone="brand" size="sm" dot={false}>
                <Layers className="h-3 w-3" /> {p} · {n}
              </StatusPill>
            ))}
          </div>
        </section>
      )}
      {b.entities.size > 0 && (
        <section>
          <p className="k-label mb-1.5">Entities touched (from the audit log)</p>
          <div className="flex flex-wrap gap-1">
            {[...b.entities.entries()].sort((a, c) => c[1] - a[1]).slice(0, 24).map(([e, n]) => (
              <span key={e} title={e} className="inline-flex items-center gap-1 rounded bg-sunken px-1.5 py-0.5 font-mono text-[10.5px] text-ink-2">
                <Database className="h-2.5 w-2.5 text-ink-subtle" />
                {tail(e)}
                {n > 1 && <span className="text-ink-subtle">×{n}</span>}
              </span>
            ))}
          </div>
        </section>
      )}
      {b.queries.length > 0 && (
        <section>
          <p className="k-label mb-1.5">Queries run on the platform</p>
          <div className="space-y-1.5">
            {b.queries.map((q, i) => (
              <pre key={i} className="whitespace-pre-wrap break-words rounded-md bg-sunken px-2 py-1.5 font-mono text-[10.5px] text-ink-2">
                <Braces className="mr-1 inline h-3 w-3 text-brand" />
                {q}
              </pre>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
