"use client";

/**
 * Create a data product from a business concept. Kairos reads the connection's
 * enriched map, picks the tables that belong to the concept, defines the semantic
 * model and checks it on the platform. Tables can be pinned when a person knows
 * one must be in.
 */

import { useEffect, useMemo, useState } from "react";
import { Check, ChevronDown, Layers, Sparkles, X } from "lucide-react";

import { Callout, Field, Spinner, StatusPill } from "@/components/kairos/ds";
import { cn } from "@/lib/utils";
import { LANE_LABEL, listEnrichedTables, trustTone, type Build, type Lane } from "@/lib/products";

const STEP_KEYS = ["map", "inputs", "model", "verify", "supply"];
const STEP_LABEL: Record<string, string> = {
  map: "Reading the connection's enriched map",
  inputs: "Picking the tables that belong to the concept",
  model: "Defining metrics, dimensions and tools",
  verify: "Compiling every metric and join on the platform",
  repair: "Repairing what the platform rejected",
  supply: "Tracing the supply chain and writing contracts",
};

export function CreateDialog({
  workspaceId,
  workspaceName,
  onStart,
  onClose,
}: {
  workspaceId: string;
  workspaceName: string;
  onStart: (body: { concept: string; intent: string; pins: string[] }) => Promise<void>;
  onClose: () => void;
}) {
  const [concept, setConcept] = useState("");
  const [intent, setIntent] = useState("");
  const [pins, setPins] = useState<string[]>([]);
  const [showPins, setShowPins] = useState(false);
  const [tables, setTables] = useState<{ entity_id: string; full_name: string; lane: Lane; role: string | null; trust: string }[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (showPins && tables === null) listEnrichedTables(workspaceId).then((r) => setTables(r.tables)).catch(() => setTables([]));
  }, [showPins, tables, workspaceId]);

  const grouped = useMemo(() => {
    const order: Lane[] = ["mart", "core", "staging", "raw"];
    return order.map((l) => ({ lane: l, rows: (tables ?? []).filter((t) => t.lane === l) })).filter((g) => g.rows.length);
  }, [tables]);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      await onStart({ concept: concept.trim(), intent: intent.trim(), pins });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start the build.");
      setBusy(false);
    }
  }

  return (
    <div className="absolute inset-0 z-30 flex items-start justify-center bg-[rgb(26_29_36/0.18)] px-4 pt-16 backdrop-blur-[2px]">
      <div className="kairos-panel k-pop w-full max-w-xl overflow-hidden">
        <header className="flex items-center gap-3 border-b border-hairline px-5 py-3.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-soft text-brand">
            <Sparkles className="h-4 w-4" />
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="text-k-title font-semibold text-ink">New data product</h2>
            <p className="text-k-caption text-ink-muted">on {workspaceName}</p>
          </div>
          <button onClick={onClose} className="k-btn k-btn-ghost k-btn-sm" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </header>
        <div className="space-y-4 px-5 py-4">
          <Field label="Business concept" hint="One concept per product: Sales, Delivery performance, Customer…">
            <input
              autoFocus
              value={concept}
              onChange={(e) => setConcept(e.target.value)}
              placeholder="e.g. Sales"
              className="k-input w-full"
            />
          </Field>
          <Field label="What it should cover" hint="Optional. Measures that do not fit are left to other products.">
            <textarea
              value={intent}
              onChange={(e) => setIntent(e.target.value)}
              rows={3}
              placeholder="e.g. Orders, revenue, GMV, AOV and cancellations by city, date, restaurant and cuisine"
              className="k-input h-auto w-full py-2"
            />
          </Field>
          <div>
            <button type="button" onClick={() => setShowPins((s) => !s)} className="flex items-center gap-1.5 text-k-caption font-medium text-brand">
              <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", !showPins && "-rotate-90")} />
              Pin tables that must be in {pins.length > 0 && `(${pins.length})`}
            </button>
            {showPins && (
              <div className="mt-2 max-h-56 overflow-y-auto rounded-lg border border-hairline">
                {tables === null ? (
                  <p className="flex items-center gap-2 px-3 py-3 text-k-caption text-ink-muted">
                    <Spinner /> Loading enriched tables…
                  </p>
                ) : (
                  grouped.map((g) => (
                    <div key={g.lane}>
                      <p className="k-label sticky top-0 bg-sunken px-3 py-1">{LANE_LABEL[g.lane]}</p>
                      {g.rows.map((t) => {
                        const on = pins.includes(t.entity_id);
                        return (
                          <button
                            key={t.entity_id}
                            type="button"
                            onClick={() => setPins((p) => (on ? p.filter((x) => x !== t.entity_id) : [...p, t.entity_id]))}
                            className={cn("flex w-full items-center gap-2 px-3 py-1.5 text-left", on ? "bg-brand-soft" : "hover:bg-sunken")}
                          >
                            <span
                              className={cn(
                                "flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded border",
                                on ? "border-brand bg-brand text-white" : "border-hairline-strong"
                              )}
                            >
                              {on && <Check className="h-2.5 w-2.5" strokeWidth={3} />}
                            </span>
                            <span className="truncate font-mono text-[11.5px] text-ink">{t.full_name}</span>
                            <StatusPill tone={trustTone(t.trust as never)} size="sm" className="ml-auto">
                              {t.trust}
                            </StatusPill>
                          </button>
                        );
                      })}
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
          {error && <Callout tone="danger">{error}</Callout>}
          <button onClick={start} disabled={!concept.trim() || busy} className="k-btn k-btn-primary w-full justify-center">
            {busy ? <Spinner className="border-white/30" /> : <Layers className="h-4 w-4" />}
            Build data product
          </button>
          <p className="text-k-caption text-ink-subtle">
            Kairos picks the inputs, defines each metric once, compiles everything on the platform and writes the
            contracts. It takes one to two minutes and never changes the warehouse.
          </p>
        </div>
      </div>
    </div>
  );
}

/** A running build's steps, floating over the graph. */
export function BuildProgress({ build }: { build: Build }) {
  const done = new Set(build.steps.map((s) => s.key));
  const current = build.steps[build.steps.length - 1]?.key;
  const keys = done.has("repair") ? ["map", "inputs", "model", "verify", "repair", "supply"] : STEP_KEYS;
  return (
    <div className="kairos-panel k-pop absolute left-1/2 top-5 z-30 w-[440px] -translate-x-1/2 px-5 py-4">
      <p className="text-k-title font-semibold text-ink">
        {build.status === "failed" ? "Build failed" : `Building ${build.concept}…`}
      </p>
      {build.status === "failed" ? (
        <Callout tone="danger" className="mt-2">
          {build.error}
        </Callout>
      ) : (
        <ol className="mt-3 space-y-2">
          {keys.map((k) => {
            const isCurrent = k === current && build.status === "running";
            const isDone = done.has(k) && !isCurrent;
            return (
              <li key={k} className="flex items-center gap-2.5">
                <span
                  className={cn(
                    "flex h-5 w-5 shrink-0 items-center justify-center rounded-full",
                    isDone ? "bg-ok-soft text-ok" : isCurrent ? "bg-brand-soft" : "bg-neutral-soft"
                  )}
                >
                  {isDone ? <Check className="h-3 w-3" /> : isCurrent ? <Spinner className="h-3 w-3" /> : null}
                </span>
                <span className={cn("text-k-body", isDone || isCurrent ? "text-ink" : "text-ink-subtle")}>{STEP_LABEL[k]}</span>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
