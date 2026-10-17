"use client";

/**
 * The data product engine on screen: start it, then watch it read the flow,
 * propose the products the data supports, and build each one.
 */

import { useState } from "react";
import { Check, ChevronDown, Cpu, Layers, Workflow, X } from "lucide-react";

import { Callout, Spinner, StatusPill, Switch } from "@/components/kairos/ds";
import { cn } from "@/lib/utils";
import { tail, type EngineProposal, type EngineRun } from "@/lib/products";

export function EngineStart({
  workspaceName,
  existing,
  onRun,
  onClose,
}: {
  workspaceName: string;
  existing: number;
  onRun: (rebuild: boolean) => Promise<void>;
  onClose: () => void;
}) {
  const [rebuild, setRebuild] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="absolute inset-0 z-30 flex items-start justify-center bg-[rgb(26_29_36/0.18)] px-4 pt-16 backdrop-blur-[2px]">
      <div className="kairos-panel k-pop w-full max-w-lg overflow-hidden">
        <header className="flex items-center gap-3 border-b border-hairline px-5 py-3.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-brand text-white">
            <Cpu className="h-4 w-4" />
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="text-k-title font-semibold text-ink">Data product engine</h2>
            <p className="text-k-caption text-ink-muted">on {workspaceName}</p>
          </div>
          <button onClick={onClose} className="k-btn k-btn-ghost k-btn-sm" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </header>
        <div className="space-y-4 px-5 py-4">
          <ol className="space-y-2.5 text-k-body text-ink-2">
            {[
              ["Read the flow", "which curated facts feed which marts, and the dimensions they join"],
              ["Propose products", "every business concept the data supports, each measure owned by one product"],
              ["Build each one", "inputs, semantic model, checks on the platform, contracts"],
            ].map(([t, d], i) => (
              <li key={t} className="flex gap-2.5">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-brand-soft text-[11px] font-semibold text-brand">
                  {i + 1}
                </span>
                <span>
                  <span className="font-semibold text-ink">{t}</span> — {d}
                </span>
              </li>
            ))}
          </ol>
          {existing > 0 && (
            <div className="flex items-center gap-3 rounded-lg bg-sunken px-3 py-2.5">
              <Switch checked={rebuild} onChange={setRebuild} label="Rebuild existing products" />
              <p className="text-k-caption text-ink-2">
                {rebuild
                  ? `Rebuild the ${existing} existing product${existing === 1 ? "" : "s"} too, so every metric has one owner`
                  : `Keep the ${existing} existing product${existing === 1 ? "" : "s"} as they are; build only new ones`}
              </p>
            </div>
          )}
          {error && <Callout tone="danger">{error}</Callout>}
          <button
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await onRun(rebuild);
              } catch (e) {
                setError(e instanceof Error ? e.message : "Could not start the engine.");
                setBusy(false);
              }
            }}
            className="k-btn k-btn-primary w-full justify-center"
          >
            {busy ? <Spinner className="border-white/30" /> : <Cpu className="h-4 w-4" />}
            Run the engine
          </button>
          <p className="text-k-caption text-ink-subtle">
            Takes a few minutes per product. Kairos never changes the warehouse; every product starts as a draft.
          </p>
        </div>
      </div>
    </div>
  );
}

const STATUS: Record<EngineProposal["status"], { tone: "ok" | "warn" | "danger" | "neutral" | "brand"; label: string }> = {
  queued: { tone: "neutral", label: "queued" },
  building: { tone: "brand", label: "building" },
  built: { tone: "ok", label: "built" },
  kept: { tone: "neutral", label: "kept as is" },
  failed: { tone: "danger", label: "failed" },
};

export function EnginePanel({ run, onClose, onOpen }: { run: EngineRun; onClose: () => void; onOpen: (id: string) => void }) {
  const [open, setOpen] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const done = run.proposals.filter((p) => ["built", "kept"].includes(p.status)).length;
  const phases = [
    { key: "flow", label: "Flow" },
    { key: "plan", label: "Plan" },
    { key: "build", label: run.proposals.length ? `Build ${done}/${run.proposals.length}` : "Build" },
  ];
  const order = ["flow", "plan", "build", "done"];
  const at = order.indexOf(run.phase);

  return (
    <div className="kairos-panel k-pop absolute left-4 top-4 z-30 flex max-h-[calc(100%-2rem)] w-[400px] flex-col overflow-hidden">
      <header className="flex items-center gap-2.5 border-b border-hairline px-4 py-3">
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-brand text-white">
          {run.status === "running" ? <Spinner className="border-white/30" /> : <Cpu className="h-3.5 w-3.5" />}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-k-body font-semibold text-ink">Data product engine</p>
          <p className="text-k-caption text-ink-muted">
            {run.status === "running" ? "running" : run.status === "failed" ? "failed" : `done · ${done} product${done === 1 ? "" : "s"}`}
          </p>
        </div>
        <button onClick={() => setCollapsed((c) => !c)} className="k-btn k-btn-ghost k-btn-sm" aria-label="Collapse">
          <ChevronDown className={cn("h-4 w-4 transition-transform", collapsed && "-rotate-90")} />
        </button>
        {run.status !== "running" && (
          <button onClick={onClose} className="k-btn k-btn-ghost k-btn-sm" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        )}
      </header>
      {!collapsed && (
        <div className="min-h-0 overflow-y-auto">
          <ol className="flex gap-3 border-b border-hairline px-4 py-2.5">
            {phases.map((p, i) => {
              const state = at > i || run.phase === "done" ? "done" : at === i && run.status === "running" ? "now" : "todo";
              return (
                <li key={p.key} className="flex items-center gap-1.5 whitespace-nowrap text-k-caption">
                  <span
                    className={cn(
                      "flex h-4 w-4 items-center justify-center rounded-full",
                      state === "done" ? "bg-ok-soft text-ok" : state === "now" ? "bg-brand-soft" : "bg-neutral-soft"
                    )}
                  >
                    {state === "done" ? <Check className="h-2.5 w-2.5" /> : state === "now" ? <Spinner className="h-2.5 w-2.5" /> : null}
                  </span>
                  <span className={state === "todo" ? "text-ink-subtle" : "text-ink-2"}>{p.label}</span>
                </li>
              );
            })}
          </ol>
          {run.error && (
            <div className="px-4 py-3">
              <Callout tone="danger">{run.error}</Callout>
            </div>
          )}
          {run.flow && (
            <div className="flex items-start gap-2 border-b border-hairline px-4 py-2.5 text-k-caption text-ink-muted">
              <Workflow className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand" />
              <span>
                {run.flow.facts.length} facts → {run.flow.marts.length} marts, {run.flow.dimensions.length} dimensions
                {run.flow.operational.length > 0 && `, ${run.flow.operational.length} operational tables set aside`}
              </span>
            </div>
          )}
          <div className="divide-y divide-hairline">
            {run.proposals.map((p) => {
              const s = STATUS[p.status];
              const expanded = open === p.concept;
              return (
                <div key={p.concept} className="px-4 py-2.5">
                  <div className="flex items-center gap-2">
                    <Layers className={cn("h-4 w-4 shrink-0", p.status === "built" ? "text-brand" : "text-ink-subtle")} />
                    <button
                      onClick={() => setOpen(expanded ? null : p.concept)}
                      className="min-w-0 flex-1 truncate text-left text-k-body font-semibold text-ink hover:text-brand"
                    >
                      {p.concept}
                    </button>
                    <StatusPill tone={s.tone} size="sm">
                      {p.status === "building" && <Spinner className="h-2.5 w-2.5" />}
                      {s.label}
                    </StatusPill>
                  </div>
                  {p.status === "building" && p.steps.length > 0 && (
                    <p className="ml-6 mt-0.5 text-[11px] text-brand">{p.steps[p.steps.length - 1].label}…</p>
                  )}
                  {p.error && <p className="ml-6 mt-0.5 line-clamp-2 text-[11px] text-danger">{p.error}</p>}
                  {expanded && (
                    <div className="k-rise ml-6 mt-1.5 space-y-1.5">
                      <p className="text-k-caption text-ink-2">{p.intent}</p>
                      <p className="text-[11px] text-ink-muted">{p.rationale}</p>
                      <p className="text-[11px] text-ink-subtle">
                        on <span className="font-mono">{p.tables.map(tail).join(", ")}</span>
                      </p>
                      {p.product_id && (
                        <button onClick={() => onOpen(p.product_id!)} className="k-btn k-btn-sm">
                          Open product
                        </button>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          {run.not_covered.length > 0 && (
            <details className="border-t border-hairline px-4 py-2.5">
              <summary className="cursor-pointer text-k-caption text-ink-muted">
                {run.not_covered.length} table{run.not_covered.length === 1 ? "" : "s"} not made into a product, and why
              </summary>
              <ul className="mt-1.5 space-y-1">
                {run.not_covered.map((n) => (
                  <li key={n.table} className="text-[11px] text-ink-muted">
                    <span className="font-mono text-ink-2">{tail(n.table)}</span> — {n.why}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
