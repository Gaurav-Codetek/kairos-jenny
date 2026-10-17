"use client";

import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { AlertTriangle, CheckCircle2, ChevronRight, Wrench, XCircle } from "lucide-react";

import { Callout, Spinner, StatusPill } from "@/components/kairos/ds";

import { argLine, getThread, isActive, type ThreadDetail, type TranscriptItem } from "@/lib/evals";
import { cn } from "@/lib/utils";

type ToolItem = Extract<TranscriptItem, { type: "tool_call" }>;
type Block = { kind: "tools"; calls: ToolItem[] } | { kind: "text"; text: string } | { kind: "answer"; text: string };

/** Consecutive tool calls become one "Used N tools" block, the way a chat client shows them. */
function blocks(items: TranscriptItem[]): Block[] {
  const out: Block[] = [];
  for (const it of items) {
    if (it.type === "tool_call") {
      const last = out[out.length - 1];
      if (last?.kind === "tools") last.calls.push(it);
      else out.push({ kind: "tools", calls: [it] });
    } else out.push({ kind: it.type, text: it.text });
  }
  return out;
}

/** One evaluation thread, replayed like a chat: outcome, the agent's tool use, its answer, then the grading. */
export function ThreadView({ id, label }: { id: string; label?: string }) {
  const [t, setT] = useState<ThreadDetail | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    let timer: number | undefined;
    const load = () =>
      getThread(id)
        .then((d) => {
          if (!alive) return;
          setT(d);
          if (isActive(d.status)) timer = window.setTimeout(load, 3000);
        })
        .catch(() => alive && setFailed(true));
    // A new thread id means a new question: the parent remounts this view, so no reset is needed.
    load();
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [id]);

  if (failed) return <p className="text-k-caption text-ink-muted">Could not load this thread.</p>;
  if (!t) return <Spinner />;

  return (
    <div className="flex min-w-0 flex-col gap-3.5">
      <Outcome t={t} label={label} />

      {blocks(t.transcript).map((b, i) =>
        b.kind === "tools" ? (
          <ToolBlock key={i} calls={b.calls} />
        ) : b.kind === "text" ? (
          <div key={i} className="eval-md text-k-body text-ink-muted">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{b.text}</ReactMarkdown>
          </div>
        ) : (
          <div key={i} className="kairos-panel k-rise px-4 py-3.5" style={{ borderColor: "var(--brand-border)" }}>
            <p className="mb-2 flex items-center gap-1.5 text-k-caption font-semibold text-brand">
              <span className="h-1.5 w-1.5 rounded-full bg-brand" /> Answer
            </p>
            <div className="eval-md text-k-body leading-relaxed text-ink">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{b.text || "_(empty answer)_"}</ReactMarkdown>
            </div>
          </div>
        )
      )}

      {isActive(t.status) && (
        <div className="flex items-center gap-2 text-k-caption text-ink-muted">
          <Spinner />
          {t.status === "answered" ? "Grading the answer…" : t.status === "queued" ? "Waiting to start…" : "Working…"}
        </div>
      )}
      {t.error && <Callout tone="danger" icon={XCircle}>{t.error}</Callout>}

      <Grading t={t} />
    </div>
  );
}

function Outcome({ t, label }: { t: ThreadDetail; label?: string }) {
  const scored = t.status === "scored";
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-hairline pb-3 text-k-caption">
      {label && <span className="text-k-title font-bold text-ink">{label}</span>}
      {scored ? (
        <StatusPill tone={t.passed ? "ok" : "danger"} className="k-pop tabular-nums">
          {t.passed ? "Passed" : "Failed"} · {Math.round((t.judge_score ?? 0) * 100)}
        </StatusPill>
      ) : (
        <StatusPill tone="neutral" className="capitalize">{t.status}</StatusPill>
      )}
      <span className="tabular-nums text-ink-muted">
        {t.tool_calls} tool{t.tool_calls === 1 ? "" : "s"} · {(t.input_tokens + t.output_tokens).toLocaleString()} tokens ·{" "}
        {(t.duration_ms / 1000).toFixed(0)} s
      </span>
      {t.tool_errors > 0 && <span className="text-danger">{t.tool_errors} tool error{t.tool_errors === 1 ? "" : "s"}</span>}
      {t.step_limit_hit && (
        <span className="inline-flex items-center gap-1 font-medium text-warn">
          <AlertTriangle className="h-3.5 w-3.5" /> step limit
        </span>
      )}
    </div>
  );
}

function ToolBlock({ calls }: { calls: ToolItem[] }) {
  const [open, setOpen] = useState(false);
  const errors = calls.filter((c) => !c.ok).length;
  return (
    <div className="rounded-lg border border-hairline bg-sunken">
      <button onClick={() => setOpen((o) => !o)} className="flex w-full min-w-0 items-center gap-2 rounded-lg px-3 py-2.5 text-left transition-colors hover:bg-neutral-soft">
        <ChevronRight className={cn("h-3.5 w-3.5 shrink-0 text-ink-subtle transition-transform", open && "rotate-90")} />
        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand">
          <Wrench className="h-3 w-3" />
        </span>
        <span className="shrink-0 text-k-caption font-semibold text-ink">
          Used {calls.length} tool{calls.length === 1 ? "" : "s"}
        </span>
        <span className="min-w-0 flex-1 truncate font-mono text-k-caption text-ink-muted">{calls.map((c) => c.tool).join(", ")}</span>
        {errors > 0 && <StatusPill tone="danger" size="sm">{errors} failed</StatusPill>}
      </button>
      {open && (
        <div className="k-rise space-y-1.5 border-t border-hairline p-2">
          {calls.map((c, i) => (
            <ToolCall key={i} item={c} />
          ))}
        </div>
      )}
    </div>
  );
}

function pretty(text: string): string {
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}

function ToolCall({ item }: { item: ToolItem }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="min-w-0 rounded-lg border border-hairline bg-surface">
      <button onClick={() => setOpen((o) => !o)} className="flex w-full min-w-0 items-center gap-2 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-sunken">
        <ChevronRight className={cn("h-3 w-3 shrink-0 text-ink-subtle transition-transform", open && "rotate-90")} />
        <span className="shrink-0 font-mono text-k-caption font-semibold text-brand-strong">{item.tool}</span>
        <span className="min-w-0 flex-1 truncate text-k-caption text-ink-muted" title={argLine(item.args)}>
          {argLine(item.args)}
        </span>
        {item.ok ? (
          <CheckCircle2 className="h-4 w-4 shrink-0" style={{ color: "var(--ok-dot)" }} />
        ) : (
          <XCircle className="h-4 w-4 shrink-0" style={{ color: "var(--danger-dot)" }} />
        )}
        <span className="hidden shrink-0 text-[11px] tabular-nums text-ink-subtle md:inline">
          {(item.result_chars / 1000).toFixed(1)}k chars
        </span>
      </button>
      {open && (
        <div className="space-y-2 border-t border-hairline px-2.5 py-2">
          {item.local && <p className="text-k-caption text-ink-subtle">Answered locally — evaluations never write to Kairos.</p>}
          <div>
            <p className="k-label">Arguments</p>
            <pre className="mt-1.5 max-h-48 overflow-auto rounded-lg border border-hairline bg-sunken px-3 py-2.5 font-mono text-k-caption leading-relaxed text-ink-2">
              {JSON.stringify(item.args, null, 2)}
            </pre>
          </div>
          <div>
            <p className="k-label">
              Result · {item.ms} ms
              {item.result_truncated ? ` · first ${item.result.length.toLocaleString()} of ${item.result_chars.toLocaleString()} chars` : ""}
            </p>
            <pre className="mt-1.5 max-h-96 overflow-auto rounded-lg border border-hairline bg-sunken px-3 py-2.5 font-mono text-k-caption leading-relaxed text-ink-2">
              {pretty(item.result)}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}

function Grading({ t }: { t: ThreadDetail }) {
  const [showRef, setShowRef] = useState(false);
  if (t.status !== "scored") return null;
  return (
    <div className="space-y-2 rounded-lg border border-dashed border-hairline-strong bg-sunken px-4 py-3 text-k-caption">
      <p className="k-label">
        Grading · judge {Math.round((t.judge_score ?? 0) * 100)}% · mentions {Math.round((t.mention_score ?? 0) * 100)}%
      </p>
      {t.verdict && <p className="text-ink">{t.verdict}</p>}
      {t.mentions_missing.length > 0 && (
        <p className="text-ink-muted">
          Did not mention: <span className="font-mono text-k-caption">{t.mentions_missing.join("  ·  ")}</span>
        </p>
      )}
      {t.missing_context && (
        <p className="text-ink-muted">
          <span className="font-medium text-ink-subtle">Missing context: </span>
          {t.missing_context}
        </p>
      )}
      {t.reference &&
        (showRef ? (
          <p className="border-t border-hairline pt-1.5 text-ink-muted">
            <span className="font-medium text-ink-subtle">Reference: </span>
            {t.reference}
          </p>
        ) : (
          <button onClick={() => setShowRef(true)} className="text-k-caption font-semibold text-brand hover:text-brand-strong">
            Show the reference answer
          </button>
        ))}
    </div>
  );
}
