"use client";

import { useEffect, useState } from "react";
import { Check, Play, X } from "lucide-react";

import { Callout, Chip, Field, Spinner } from "@/components/kairos/ds";
import { CONNECTOR_LABEL, getQuestionBank, startRun, type Connector, type QuestionBank } from "@/lib/evals";
import { cn } from "@/lib/utils";

/** Start an evaluation: which connectors, which questions. */
export function NewRun({ onClose, onStarted }: { onClose: () => void; onStarted: (id: string) => void }) {
  const [bank, setBank] = useState<QuestionBank | null>(null);
  const [connectors, setConnectors] = useState<Connector[]>(["v1", "v2"]);
  const [cats, setCats] = useState<string[]>([]);
  const [limit, setLimit] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getQuestionBank().then(setBank).catch(() => setError("Could not load the question bank."));
  }, []);

  const available = bank ? (cats.length ? bank.questions.filter((q) => cats.includes(q.category)).length : bank.total) : 0;
  const count = Math.min(available, Number(limit) || available);
  const options = bank?.connector_options ?? [
    { id: "v1", label: CONNECTOR_LABEL.v1 },
    { id: "v2", label: CONNECTOR_LABEL.v2 },
  ];

  return (
    <div
      className="k-page fixed inset-0 z-50 flex items-center justify-center bg-[rgb(26_29_36/0.28)] p-4 backdrop-blur-[3px]"
      onClick={onClose}
    >
      <div
        className="kairos-panel k-pop flex max-h-[90vh] w-full max-w-xl flex-col shadow-[0_24px_60px_-20px_rgb(26_29_36/0.35)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-3 border-b border-hairline px-5 py-4">
          <span aria-hidden className="mt-0.5 h-6 w-1 rounded-full bg-brand" />
          <div className="flex-1">
            <h3 className="text-[17px] font-bold text-ink">New evaluation run</h3>
            <p className="mt-0.5 text-k-caption text-ink-muted">
              Each question is asked in a fresh conversation through each connector by {bank?.default_model ?? "the model"},
              then graded.
            </p>
          </div>
          <button onClick={onClose} className="k-btn k-btn-ghost k-btn-sm !px-1.5" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-5 overflow-y-auto px-5 py-5">
          <div>
            <p className="mb-2 text-k-caption font-semibold text-ink-2">Connectors</p>
            <div className="grid gap-2 sm:grid-cols-2">
              {options.map((o) => {
                const on = connectors.includes(o.id);
                return (
                  <button
                    key={o.id}
                    type="button"
                    onClick={() => setConnectors((cs) => (on ? cs.filter((x) => x !== o.id) : [...cs, o.id]))}
                    className={cn(
                      "flex items-center gap-2.5 rounded-lg border px-3 py-2.5 text-left text-k-body transition-all duration-200",
                      on
                        ? "border-brand bg-brand-soft/60 font-semibold text-brand-strong shadow-[0_0_0_3px_var(--brand-soft)]"
                        : "border-hairline text-ink hover:border-brand-border hover:bg-sunken"
                    )}
                  >
                    <span
                      className={cn(
                        "flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-[5px] border-[1.5px]",
                        on ? "border-brand bg-brand" : "border-hairline-strong bg-surface"
                      )}
                    >
                      {on && <Check className="k-pop h-3 w-3 text-white" strokeWidth={3} />}
                    </span>
                    <span className="truncate">{o.label}</span>
                  </button>
                );
              })}
            </div>
          </div>

          <div>
            <p className="mb-2 text-k-caption font-semibold text-ink-2">
              Categories <span className="font-normal text-ink-subtle">(none selected: all)</span>
            </p>
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(bank?.categories ?? {}).map(([c, n]) => (
                <Chip
                  key={c}
                  on={cats.includes(c)}
                  count={n}
                  onClick={() => setCats((cs) => (cs.includes(c) ? cs.filter((x) => x !== c) : [...cs, c]))}
                >
                  {c}
                </Chip>
              ))}
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Max questions">
              <input
                value={limit}
                onChange={(e) => setLimit(e.target.value.replace(/\D/g, ""))}
                placeholder={`all ${available}`}
                className="k-input tabular-nums"
              />
            </Field>
            <Field label="Name (optional)">
              <input value={name} onChange={(e) => setName(e.target.value)} className="k-input" />
            </Field>
          </div>

          {error && <Callout tone="danger">{error}</Callout>}
        </div>

        <div className="flex items-center gap-2 border-t border-hairline bg-sunken px-5 py-3.5">
          <p className="text-k-caption text-ink-muted">
            {count} question{count === 1 ? "" : "s"} × {connectors.length} connector{connectors.length === 1 ? "" : "s"} ={" "}
            <span className="font-bold tabular-nums text-ink">{count * connectors.length}</span> threads
          </p>
          <span className="flex-1" />
          <button onClick={onClose} className="k-btn">
            Cancel
          </button>
          <button
            disabled={busy || !connectors.length || !count}
            onClick={async () => {
              setBusy(true);
              setError(null);
              try {
                const run = await startRun({
                  name: name || undefined,
                  connectors,
                  categories: cats.length ? cats : undefined,
                  limit: Number(limit) || undefined,
                });
                onStarted(run.id);
              } catch {
                setError("Could not start the run.");
                setBusy(false);
              }
            }}
            className="k-btn k-btn-primary"
          >
            {busy ? <Spinner className="border-white/30" /> : <Play className="h-4 w-4" />} Start
          </button>
        </div>
      </div>
    </div>
  );
}
