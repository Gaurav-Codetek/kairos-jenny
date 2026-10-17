"use client";

/**
 * Test: chat with an agent that reaches Kairos through an MCP connector, exactly as an
 * outside agent would, and watch every step it takes and every call Kairos records.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ArrowUp, Bot, Check, ChevronDown, Plug, Plus, Wrench } from "lucide-react";

import { Callout, KairosMark, Spinner } from "@/components/kairos/ds";
import { PageHeader } from "@/components/shell/app-shell";
import { MonitorPanel } from "@/components/test/monitor-panel";
import { cn } from "@/lib/utils";
import {
  createSession,
  getAudit,
  getSession,
  listConnectors,
  sendMessage,
  switchConnector,
  type AuditRow,
  type ConsoleConnector,
  type ConsoleSession,
  type TraceEvent,
} from "@/lib/test-console";

const STORE = "kairos.test.session";
const SUGGESTIONS = [
  "What data products exist, and what does each one answer?",
  "What was GMV by city for the top 5 cities?",
  "Which pipelines failed recently, and why?",
  "Which table should I use for daily revenue, and how is it built?",
];

const fmtMs = (ms: number) => (ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`);

function remember(id: string | null) {
  try {
    if (id) localStorage.setItem(STORE, id);
    else localStorage.removeItem(STORE);
  } catch {
    /* storage unavailable: the session just is not remembered */
  }
}

function recall(): string | null {
  try {
    return localStorage.getItem(STORE);
  } catch {
    return null;
  }
}

export default function TestPage() {
  const [connectors, setConnectors] = useState<ConsoleConnector[]>([]);
  const [session, setSession] = useState<ConsoleSession | null>(null);
  const [trace, setTrace] = useState<TraceEvent[]>([]);
  const [audit, setAudit] = useState<AuditRow[]>([]);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [picker, setPicker] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);
  const traceCount = useRef(0);

  // A response carries the trace from index `from` on: place it there, never append blindly, so
  // overlapping polls and full responses cannot duplicate events.
  const adopt = useCallback((s: ConsoleSession, from = 0) => {
    setSession(s);
    setTrace((t) => [...t.slice(0, from), ...s.trace]);
    traceCount.current = Math.max(traceCount.current, s.trace_total);
  }, []);

  const start = useCallback(
    async (connector: string) => {
      const s = await createSession(connector);
      remember(s.id);
      traceCount.current = 0;
      adopt(s, 0);
      setAudit([]);
    },
    [adopt]
  );

  // Connectors, then the remembered session (or a new one on Kairos v2, which sees every connection).
  useEffect(() => {
    (async () => {
      const list = (await listConnectors().catch(() => ({ connectors: [] }))).connectors;
      setConnectors(list);
      const id = recall();
      const old = id ? await getSession(id).catch(() => null) : null;
      if (old) {
        adopt(old, 0);
        getAudit(old.id).then((r) => setAudit(r.audit)).catch(() => undefined);
      } else {
        await start("v2").catch(() => setError("Could not start a session — is the API running?"));
      }
    })();
  }, [adopt, start]);

  // While the agent works: new trace events and the audit log, about twice a second.
  useEffect(() => {
    if (!session || session.status !== "running") return;
    const t = window.setInterval(async () => {
      const from = traceCount.current;
      const s = await getSession(session.id, from).catch(() => null);
      if (s) adopt(s, from);
      getAudit(session.id).then((r) => setAudit(r.audit)).catch(() => undefined);
    }, 600);
    return () => window.clearInterval(t);
  }, [session, adopt]);

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [session?.messages.length, trace.length]);

  async function send(text: string) {
    if (!session || !text.trim() || session.status === "running") return;
    setError(null);
    setDraft("");
    try {
      adopt(await sendMessage(session.id, text.trim()));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not send.");
    }
  }

  async function changeConnector(id: string) {
    setPicker(false);
    if (!session || id === session.connector) return;
    try {
      adopt(await switchConnector(session.id, id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not switch.");
    }
  }

  const current = connectors.find((c) => c.id === session?.connector);
  const running = session?.status === "running";
  const liveStep = running ? [...trace].reverse().find((e) => e.turn === session?.turns) : undefined;

  return (
    <>
      <PageHeader
        title="Test"
        description="Chat with an agent through a Kairos MCP connector and watch every call it makes"
        actions={
          <div className="flex items-center gap-2">
            <div className="relative">
              <button onClick={() => setPicker((p) => !p)} disabled={running} className="k-btn min-w-[260px] justify-between">
                <span className="flex min-w-0 items-center gap-2">
                  <Plug className="h-4 w-4 shrink-0 text-brand" />
                  <span className="truncate">{current ? current.label : "Connector"}</span>
                  {current && <span className="truncate font-mono text-[11px] text-ink-subtle">{current.path}</span>}
                </span>
                <ChevronDown className="h-4 w-4 shrink-0 text-ink-subtle" />
              </button>
              {picker && (
                <div className="kairos-panel k-pop absolute right-0 top-11 z-40 w-[340px] overflow-hidden p-1">
                  {connectors.map((c) => (
                    <button
                      key={c.id}
                      onClick={() => changeConnector(c.id)}
                      className={cn("flex w-full items-start gap-2.5 rounded-lg px-3 py-2 text-left hover:bg-sunken", c.id === session?.connector && "bg-brand-soft")}
                    >
                      <Plug className="mt-0.5 h-4 w-4 shrink-0 text-brand" />
                      <span className="min-w-0 flex-1">
                        <span className="block text-k-body font-semibold text-ink">{c.label}</span>
                        <span className="block text-k-caption text-ink-muted">
                          {c.detail} · {c.tools} tools
                        </span>
                        <span className="block font-mono text-[11px] text-ink-subtle">{c.path}</span>
                      </span>
                      {c.id === session?.connector && <Check className="mt-0.5 h-4 w-4 text-brand" />}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <button onClick={() => start(session?.connector ?? "v2")} disabled={running} className="k-btn">
              <Plus className="h-4 w-4" /> New chat
            </button>
          </div>
        }
      />

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_440px] overflow-hidden">
        {/* ── chat ── */}
        <div className="flex min-h-0 flex-col bg-canvas">
          <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto">
            <div className="mx-auto max-w-3xl space-y-4 px-6 py-6">
              {session && session.messages.length === 0 && (
                <div className="k-rise pt-10 text-center">
                  <span className="inline-flex"><KairosMark size={40} /></span>
                  <p className="mt-3 text-k-h1 font-bold text-ink">Ask your data platform</p>
                  <p className="mt-1 text-k-body text-ink-muted">
                    The agent knows nothing but what <span className="font-semibold text-ink-2">{current?.label ?? "the connector"}</span> serves it.
                  </p>
                  <div className="mx-auto mt-6 grid max-w-2xl grid-cols-2 gap-2">
                    {SUGGESTIONS.map((s) => (
                      <button key={s} onClick={() => send(s)} className="kairos-panel k-hover px-3.5 py-3 text-left text-k-body text-ink-2">
                        {s}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {session?.messages.map((m) =>
                m.role === "system" ? (
                  <p key={m.id} className="text-center">
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-warn-soft px-3 py-1 text-k-caption text-warn">
                      <Plug className="h-3 w-3" /> {m.text}
                    </span>
                  </p>
                ) : m.role === "user" ? (
                  <div key={m.id} className="k-rise flex justify-end">
                    <div className="max-w-[80%] rounded-2xl rounded-br-md bg-brand px-4 py-2.5 text-k-body text-white">{m.text}</div>
                  </div>
                ) : (
                  <div key={m.id} className="k-rise flex gap-3">
                    <span className="mt-1 shrink-0"><KairosMark size={26} /></span>
                    <div className="min-w-0 flex-1">
                      <div className={cn("kairos-panel px-4 py-3", m.error && "border-danger-dot")}>
                        <div className="eval-md text-k-body text-ink">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.text}</ReactMarkdown>
                        </div>
                      </div>
                      <p className="mt-1 flex flex-wrap items-center gap-x-2 text-[11px] text-ink-subtle">
                        <span className="font-mono">{m.connector}</span>
                        {m.ms != null && <span>· {fmtMs(m.ms)}</span>}
                        {m.tokens != null && <span>· {(m.tokens / 1000).toFixed(1)}k tokens</span>}
                        {(m.tools ?? []).map((t, i) => (
                          <span key={i} className="inline-flex items-center gap-1 rounded bg-sunken px-1.5 py-0.5 font-mono text-[10.5px] text-ink-2">
                            <Wrench className="h-2.5 w-2.5" /> {t}
                          </span>
                        ))}
                      </p>
                    </div>
                  </div>
                )
              )}
              {running && (
                <div className="flex gap-3">
                  <span className="mt-1 shrink-0"><KairosMark size={26} /></span>
                  <div className="kairos-panel flex items-center gap-2.5 px-4 py-3 text-k-body text-ink-muted">
                    <Spinner />
                    {liveStep?.type === "tool_call"
                      ? `Called ${liveStep.tool} — reading the result…`
                      : liveStep?.type === "llm" && liveStep.tool_calls.length
                        ? `Calling ${liveStep.tool_calls.join(", ")}…`
                        : liveStep?.type === "connect"
                          ? "Connected — thinking…"
                          : "Connecting to Kairos…"}
                  </div>
                </div>
              )}
            </div>
          </div>
          <div className="border-t border-hairline bg-surface px-6 py-3.5">
            <div className="mx-auto max-w-3xl">
              {error && (
                <Callout tone="danger" className="mb-2">
                  {error}
                </Callout>
              )}
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  send(draft);
                }}
                className="flex items-end gap-2 rounded-2xl border border-hairline-strong bg-surface px-3 py-2 focus-within:border-brand focus-within:shadow-[0_0_0_3px_var(--brand-soft)]"
              >
                <Bot className="mb-1.5 h-4 w-4 shrink-0 text-ink-subtle" />
                <textarea
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      send(draft);
                    }
                  }}
                  rows={Math.min(6, Math.max(1, draft.split("\n").length))}
                  placeholder={running ? "The agent is answering…" : `Ask through ${current?.label ?? "Kairos"}…`}
                  disabled={!session || running}
                  className="min-h-[28px] flex-1 resize-none bg-transparent py-1 text-k-body text-ink outline-none placeholder:text-ink-subtle"
                />
                <button
                  type="submit"
                  disabled={!draft.trim() || running}
                  className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand text-white disabled:opacity-40"
                  aria-label="Send"
                >
                  {running ? <Spinner className="border-white/30" /> : <ArrowUp className="h-4 w-4" />}
                </button>
              </form>
              <p className="mt-1.5 text-center text-[11px] text-ink-subtle">
                Calls are made as the <span className="font-mono">test-console</span> agent and land in the audit log like any other agent&apos;s.
              </p>
            </div>
          </div>
        </div>

        {/* ── monitor ── */}
        <MonitorPanel session={session} trace={trace} audit={audit} />
      </div>
    </>
  );
}
