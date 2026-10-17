"use client";

/**
 * One thing the agent noticed: what it is, why it matters, where it moved, and the numbers.
 * The person's reaction (useful / not useful / dismiss) tunes how sensitive the agent is.
 */

import { useState } from "react";
import { AlertTriangle, ArrowDownRight, ArrowUpRight, Check, ChevronRight, Clock, Database, RotateCcw, ThumbsDown, ThumbsUp, X } from "lucide-react";

import { StatusPill, type Tone } from "@/components/kairos/ds";
import { Sparkline } from "@/components/living/sparkline";
import { cn } from "@/lib/utils";
import { fmt, monthLabel, sendFeedback, type AgentNote } from "@/lib/living";

const STATUS: Record<string, { tone: Tone; label: string }> = {
  open: { tone: "brand", label: "new" },
  provisional: { tone: "warn", label: "waiting for the data to settle" },
  confirmed: { tone: "ok", label: "confirmed" },
  withdrawn: { tone: "neutral", label: "withdrawn" },
  resolved: { tone: "ok", label: "resolved" },
  dismissed: { tone: "neutral", label: "dismissed" },
};

export function NoteCard({ note, onChanged, index = 0 }: { note: AgentNote; onChanged?: (n: AgentNote) => void; index?: number }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const f = note.facts ?? {};
  const s = f.signal;
  const isIssue = note.kind === "data_issue";
  const isCorrection = note.kind === "correction";
  const status = STATUS[note.status] ?? STATUS.open;
  const Arrow = s?.direction === "down" ? ArrowDownRight : ArrowUpRight;
  const moodTone = f.valence === "bad" ? "var(--danger-dot)" : f.valence === "good" ? "var(--ok-dot)" : "var(--brand)";

  async function react(body: Parameters<typeof sendFeedback>[1]) {
    setBusy(true);
    try {
      const n = await sendFeedback(note.id, body);
      onChanged?.(n);
    } finally {
      setBusy(false);
    }
  }

  return (
    <article
      className={cn(
        "kairos-panel k-rise overflow-hidden",
        isIssue && "border-warn-dot/50",
        (note.status === "withdrawn" || note.status === "dismissed") && "opacity-60"
      )}
      style={{ ["--i" as string]: index }}
    >
      <div className="flex gap-3 px-4 pt-3.5">
        <span
          className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full"
          style={{
            background: isIssue ? "var(--warn-soft)" : isCorrection ? "var(--neutral-soft)" : f.valence === "bad" ? "var(--danger-soft)" : f.valence === "good" ? "var(--ok-soft)" : "var(--brand-soft)",
            color: isIssue ? "var(--warn)" : isCorrection ? "var(--neutral)" : moodTone,
          }}
        >
          {isIssue ? <Database className="h-4 w-4" /> : isCorrection ? <RotateCcw className="h-4 w-4" /> : <Arrow className="h-4 w-4" />}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <h3 className="text-k-body font-semibold text-ink">{note.title}</h3>
          </div>
          <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-ink-subtle">
            {f.product && <span>{f.product}</span>}
            {note.period && <span>· {monthLabel(note.period)}</span>}
            {isIssue ? (
              <StatusPill tone="warn" size="sm">
                data issue
              </StatusPill>
            ) : (
              <StatusPill tone={status.tone} size="sm">
                {note.status === "provisional" ? <Clock className="h-2.5 w-2.5" /> : null}
                {f.held_for_data && note.status === "provisional" ? "held: loads failing" : status.label}
              </StatusPill>
            )}
            {f.valence && f.valence !== "neutral" && !isIssue && (
              <StatusPill tone={f.valence === "good" ? "ok" : "danger"} size="sm" dot={false}>
                {f.valence === "good" ? "good for the business" : "bad for the business"}
              </StatusPill>
            )}
          </p>
        </div>
      </div>

      {note.body && (
        <p className="whitespace-pre-line px-4 pt-2 text-k-body leading-relaxed text-ink-2 [padding-left:60px]">
          {f.members ? note.body.split("\n\n")[0] : note.body}
        </p>
      )}
      {f.members && (
        <div className="px-4 pt-2 [padding-left:60px]">
          <div className="divide-y divide-hairline rounded-lg border border-hairline">
            {f.members.map((m) => (
              <div key={m.label + m.product} className="flex items-center gap-2 px-3 py-1.5 text-[12px]">
                <span className="min-w-0 flex-1 truncate text-ink">{m.label}</span>
                <span className="truncate text-[11px] text-ink-subtle">{m.product}</span>
                <span className="w-28 text-right tabular-nums text-ink-muted">
                  {m.baseline_display} → <span className="font-semibold text-ink">{m.value_display}</span>
                </span>
                <span className={cn("w-14 text-right text-[11px] font-semibold tabular-nums", m.valence === "bad" ? "text-danger" : m.valence === "good" ? "text-ok" : "text-ink-2")}>
                  {typeof m.impact_pct === "number" ? `${m.impact_pct > 0 ? "+" : ""}${m.impact_pct.toFixed(1)}%` : ""}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {!f.members && (f.series_tail?.length ?? 0) > 2 && (
        <div className="flex flex-wrap items-end gap-6 px-4 pt-3 [padding-left:60px]">
          <Sparkline
            points={f.series_tail!}
            highlight={note.period}
            band={s?.normal_range ?? null}
            tone={moodTone}
            width={280}
            height={60}
          />
          {s && (
            <div className="space-y-0.5 text-[11px] text-ink-muted">
              <p>
                now <span className="font-semibold tabular-nums text-ink">{s.value_display ?? fmt(s.value)}</span>
              </p>
              {s.baseline != null && (
                <p>
                  usual <span className="tabular-nums text-ink-2">{s.baseline_display ?? fmt(s.baseline)}</span>
                </p>
              )}
              {s.impact_pct != null && (
                <p className={cn("font-semibold tabular-nums", (f.valence === "bad" && "text-danger") || (f.valence === "good" && "text-ok") || "text-ink-2")}>
                  {s.impact_pct > 0 ? "+" : ""}
                  {s.impact_pct.toFixed(1)}%
                </p>
              )}
            </div>
          )}
        </div>
      )}

      {!f.members && (f.where?.length ?? 0) > 0 && (
        <div className="grid gap-3 px-4 pt-3 [padding-left:60px] sm:grid-cols-2">
          {f.where!.map((d) => {
            const max = Math.max(...d.top.map((t) => Math.abs(t.delta)), 1);
            return (
              <div key={d.dimension}>
                <p className="k-label mb-1">where it moved · {d.dimension.replace(/_/g, " ")}</p>
                {d.top.slice(0, 3).map((t, i) => (
                  <div key={`${t.slice}-${i}`} className="flex items-center gap-2 text-[11px]">
                    <span className="w-24 truncate text-ink-2" title={t.slice}>
                      {t.slice}
                    </span>
                    <span className="h-1.5 flex-1 rounded-full bg-sunken">
                      <span
                        className="block h-full rounded-full"
                        style={{ width: `${(Math.abs(t.delta) / max) * 100}%`, background: t.delta < 0 ? "var(--danger-dot)" : "var(--ok-dot)" }}
                      />
                    </span>
                    <span className="w-16 text-right tabular-nums text-ink-muted">
                      {t.delta > 0 ? "+" : ""}
                      {fmt(t.delta)}
                    </span>
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      )}

      {isIssue && (f.problems?.length ?? 0) > 0 && (
        <ul className="space-y-0.5 px-4 pt-2 [padding-left:60px]">
          {f.problems!.slice(0, 4).map((p) => (
            <li key={p} className="flex gap-1.5 text-[11px] text-warn">
              <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
              {p}
            </li>
          ))}
        </ul>
      )}

      <footer className="mt-3 flex flex-wrap items-center gap-2 border-t border-hairline px-4 py-2 [padding-left:60px]">
        {note.kind !== "briefing" && (
          <button onClick={() => setOpen((o) => !o)} className="flex items-center gap-1 text-[11px] font-medium text-brand">
            <ChevronRight className={cn("h-3 w-3 transition-transform", open && "rotate-90")} />
            the numbers behind it
          </button>
        )}
        <span className="text-[11px] text-ink-subtle">confidence {(note.confidence * 100).toFixed(0)}%</span>
        <span className="ml-auto flex items-center gap-1">
          {note.feedback ? (
            <span className="flex items-center gap-1 text-[11px] text-ink-muted">
              <Check className="h-3 w-3" /> {note.feedback === "useful" ? "marked useful" : "marked not useful — I'll be stricter here"}
            </span>
          ) : (
            <>
              <button disabled={busy} onClick={() => react({ feedback: "useful" })} className="k-btn k-btn-ghost k-btn-sm" title="Useful">
                <ThumbsUp className="h-3.5 w-3.5" /> Useful
              </button>
              <button disabled={busy} onClick={() => react({ feedback: "not_useful" })} className="k-btn k-btn-ghost k-btn-sm" title="Not useful: ask for stronger evidence on this metric">
                <ThumbsDown className="h-3.5 w-3.5" /> Not useful
              </button>
            </>
          )}
          {note.status !== "dismissed" && (
            <button disabled={busy} onClick={() => react({ status: "dismissed" })} className="k-btn k-btn-ghost k-btn-sm" title="Dismiss">
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </span>
      </footer>
      {open && (
        <div className="k-rise space-y-2 border-t border-hairline bg-sunken/50 px-4 py-3 [padding-left:60px]">
          {f.maturity && (
            <p className="text-[11px] text-ink-muted">
              <span className="font-semibold text-ink-2">How long I wait: </span>
              {f.maturity.settle_periods} month(s) · {f.maturity.measured ? "measured from my own looks" : "my judgment of this kind of data, until I've measured it"} —{" "}
              {f.maturity.reason}
            </p>
          )}
          {f.partial && (
            <p className="text-[11px] text-ink-muted">
              <span className="font-semibold text-ink-2">Left out: </span>
              {monthLabel(f.partial.period)} — the data only reaches {f.partial.data_until}, so it isn&apos;t compared with full months.
            </p>
          )}
          {s && <pre className="overflow-auto rounded-md bg-surface p-2 font-mono text-[10.5px] text-ink-2">{JSON.stringify(s, null, 2)}</pre>}
          {f.query?.sql && (
            <pre className="overflow-auto whitespace-pre-wrap break-words rounded-md bg-[#0F172A] p-2 font-mono text-[10.5px] text-[#E2E8F0]">{f.query.sql}</pre>
          )}
          {f.written_by && <p className="text-[11px] text-ink-subtle">Words by the language model; every number in them was checked against these facts.</p>}
        </div>
      )}
    </article>
  );
}
