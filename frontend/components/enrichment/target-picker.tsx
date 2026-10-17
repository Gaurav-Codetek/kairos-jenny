"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Boxes, Check, Database, FolderTree, Search, Table2 } from "lucide-react";

import {
  estimateRun,
  formatDuration,
  listTargets,
  type EnrichmentTarget,
  type RunEstimate,
  type TargetKind,
} from "@/lib/enrichment";
import { cn } from "@/lib/utils";

const KIND_TABS: Array<{ id: TargetKind; label: string; icon: typeof Boxes }> = [
  { id: "job", label: "Pipelines", icon: Boxes },
  { id: "catalog", label: "Catalogs", icon: Database },
  { id: "schema", label: "Schemas", icon: FolderTree },
  { id: "table", label: "Tables", icon: Table2 },
];

interface TargetPickerProps {
  selected: string[];
  onChange: (entityIds: string[]) => void;
  includeDescendants: boolean;
  onIncludeDescendantsChange: (value: boolean) => void;
  force: boolean;
  onEstimate: (estimate: RunEstimate | null) => void;
}

export function TargetPicker({
  selected,
  onChange,
  includeDescendants,
  onIncludeDescendantsChange,
  force,
  onEstimate,
}: TargetPickerProps) {
  const [kind, setKind] = useState<TargetKind>("job");
  const [targets, setTargets] = useState<EnrichmentTarget[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [estimate, setEstimate] = useState<RunEstimate | null>(null);
  const [estimating, setEstimating] = useState(false);

  useEffect(() => {
    setLoading(true);
    listTargets(kind)
      .then(({ targets: t }) => setTargets(t))
      .catch(() => setTargets([]))
      .finally(() => setLoading(false));
  }, [kind]);

  // Re-price whenever the selection or its expansion rule changes.
  useEffect(() => {
    if (selected.length === 0) {
      setEstimate(null);
      onEstimate(null);
      return;
    }
    setEstimating(true);
    let cancelled = false;
    estimateRun(selected, includeDescendants, force)
      .then((result) => {
        if (cancelled) return;
        setEstimate(result);
        onEstimate(result);
      })
      .catch(() => undefined)
      .finally(() => !cancelled && setEstimating(false));
    return () => {
      cancelled = true;
    };
  }, [selected, includeDescendants, force, onEstimate]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return targets;
    return targets.filter((t) => t.name.toLowerCase().includes(needle));
  }, [targets, query]);

  const toggle = (entityId: string) => {
    onChange(
      selected.includes(entityId)
        ? selected.filter((id) => id !== entityId)
        : [...selected, entityId]
    );
  };

  return (
    <div className="space-y-3">
      {/* Kind tabs */}
      <div className="flex gap-1">
        {KIND_TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => setKind(id)}
            className={cn(
              "flex items-center gap-1.5 rounded-md px-2.5 py-1 text-k-caption font-medium transition-colors",
              kind === id
                ? "bg-primary text-primary-foreground"
                : "text-ink-muted hover:bg-muted"
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            {label}
          </button>
        ))}
      </div>

      {/* Search */}
      <div className="relative">
        <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-muted" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={`Search ${kind}s…`}
          className="w-full rounded-md border border-border bg-background py-1.5 pl-8 pr-2 text-xs outline-none placeholder:text-ink-muted focus:border-primary/60"
        />
      </div>

      {/* Target list */}
      <div className="max-h-64 overflow-y-auto rounded-md border border-border">
        {loading && <p className="p-3 text-center text-k-caption text-ink-muted">Loading…</p>}
        {!loading && filtered.length === 0 && (
          <p className="p-3 text-center text-k-caption text-ink-muted">No matches.</p>
        )}
        {!loading &&
          filtered.map((target) => {
            const isSelected = selected.includes(target.entity_id);
            return (
              <button
                key={target.entity_id}
                type="button"
                onClick={() => toggle(target.entity_id)}
                className={cn(
                  "flex w-full items-center gap-2 border-b border-border/50 px-2.5 py-2 text-left transition-colors last:border-0",
                  isSelected ? "bg-primary/10" : "hover:bg-muted/50"
                )}
              >
                <span
                  className={cn(
                    "flex h-4 w-4 shrink-0 items-center justify-center rounded border",
                    isSelected ? "border-primary bg-primary" : "border-border"
                  )}
                >
                  {isSelected && <Check className="h-3 w-3 text-primary-foreground" />}
                </span>

                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-1.5">
                    <span className="truncate text-xs font-medium" title={target.name}>
                      {target.name}
                    </span>
                    {target.profiled && (
                      <span className="shrink-0 rounded bg-violet-500/15 px-1 py-px text-[10.5px] text-violet-300">
                        profiled
                      </span>
                    )}
                    {target.failed_runs > 0 && (
                      <span
                        className="flex shrink-0 items-center gap-0.5 rounded bg-red-500/15 px-1 py-px text-[10.5px] text-red-300"
                        title={`${target.failed_runs} failed runs`}
                      >
                        <AlertTriangle className="h-2.5 w-2.5" />
                        {target.failed_runs}
                      </span>
                    )}
                  </span>
                  <span className="mt-0.5 flex gap-2 text-[10.5px] text-ink-muted">
                    {target.detail && <span className="truncate">{target.detail}</span>}
                    {target.child_count > 0 && (
                      <span className="shrink-0 text-sky-400">+{target.child_count} children</span>
                    )}
                  </span>
                </span>

                <span className="shrink-0 font-mono text-[11px] text-ink-muted">
                  {includeDescendants ? target.entity_count : 1}
                </span>
              </button>
            );
          })}
      </div>

      <label className="flex cursor-pointer items-center gap-2 text-k-caption text-ink-muted">
        <input
          type="checkbox"
          checked={includeDescendants}
          onChange={(e) => onIncludeDescendantsChange(e.target.checked)}
          className="h-3 w-3 accent-primary"
        />
        Include what it contains
        <span className="text-[11px] opacity-70">
          (a pipeline pulls in its tasks — that is where the code and links are)
        </span>
      </label>

      {/* Estimate */}
      {selected.length > 0 && (
        <div className="rounded-md border border-border bg-muted/20 p-3">
          <div className="flex items-center gap-2">
            <span className="text-k-caption font-semibold">
              {selected.length} target{selected.length === 1 ? "" : "s"} selected
            </span>
            {estimating && (
              <span className="text-[11px] text-ink-muted">estimating…</span>
            )}
          </div>

          {estimate && (
            <>
              <div className="mt-2 grid grid-cols-3 gap-2">
                <Metric label="Entities" value={String(estimate.to_process)} />
                <Metric label="Est. time" value={formatDuration(estimate.estimated_minutes)} />
                <Metric label="LLM calls" value={`~${estimate.estimated_llm_calls}`} />
              </div>

              <div className="mt-2 flex flex-wrap gap-1">
                {Object.entries(estimate.by_kind).map(([k, count]) => (
                  <span
                    key={k}
                    className="rounded border border-border bg-background px-1.5 py-px text-[10.5px] text-ink-muted"
                  >
                    {count} {k}
                    {count === 1 ? "" : "s"}
                  </span>
                ))}
              </div>

              {estimate.already_profiled > 0 && !force && (
                <p className="mt-2 text-[11px] text-ink-muted">
                  {estimate.already_profiled} already profiled and unchanged — these will be
                  skipped. Tick &ldquo;re-profile unchanged&rdquo; to redo them.
                </p>
              )}

              <p className="mt-1.5 text-[10.5px] text-ink-muted">
                {estimate.basis === "measured"
                  ? "Timing averaged from this deployment's completed runs."
                  : "Timing from defaults — will sharpen once runs complete."}
              </p>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-border bg-background px-2 py-1.5">
      <p className="k-label">{label}</p>
      <p className="font-mono text-sm font-bold text-primary">{value}</p>
    </div>
  );
}
