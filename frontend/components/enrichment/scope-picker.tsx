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
import { Spinner, StatusPill, Tabs } from "@/components/kairos/ds";
import { cn } from "@/lib/utils";

const TABS: Array<{ id: TargetKind; label: string; icon: typeof Boxes }> = [
  { id: "job", label: "Pipelines", icon: Boxes },
  { id: "catalog", label: "Catalogs", icon: Database },
  { id: "schema", label: "Schemas", icon: FolderTree },
  { id: "table", label: "Tables", icon: Table2 },
];

interface Props {
  selected: string[];
  onChange: (ids: string[]) => void;
  force: boolean;
  onEstimate: (e: RunEstimate | null) => void;
}

export function ScopePicker({ selected, onChange, force, onEstimate }: Props) {
  const [kind, setKind] = useState<TargetKind>("job");
  const [targets, setTargets] = useState<EnrichmentTarget[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [estimate, setEstimate] = useState<RunEstimate | null>(null);

  useEffect(() => {
    setLoading(true);
    listTargets(kind)
      .then((r) => setTargets(r.targets))
      .catch(() => setTargets([]))
      .finally(() => setLoading(false));
  }, [kind]);

  useEffect(() => {
    if (!selected.length) {
      setEstimate(null);
      onEstimate(null);
      return;
    }
    let cancelled = false;
    estimateRun(selected, true, force)
      .then((r) => {
        if (cancelled) return;
        setEstimate(r);
        onEstimate(r);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [selected, force, onEstimate]);

  const filtered = useMemo(() => {
    const n = query.trim().toLowerCase();
    return n ? targets.filter((t) => t.name.toLowerCase().includes(n)) : targets;
  }, [targets, query]);

  return (
    <div className="flex min-h-0 flex-col">
      <Tabs size="panel" items={TABS.map(({ id, label }) => ({ id, label }))} value={kind} onChange={setKind} className="gap-0" />

      <div className="border-b border-hairline p-3">
        <div className="relative">
          <Search className="absolute left-3 top-[9px] h-4 w-4 text-ink-subtle" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={`Search ${kind}s…`}
            className="k-input !pl-9"
          />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {loading && (
          <div className="flex justify-center py-6"><Spinner /></div>
        )}
        {!loading && filtered.length === 0 && (
          <p className="px-3 py-6 text-center text-k-caption text-ink-subtle">No matches.</p>
        )}
        {!loading &&
          filtered.map((t) => {
            const isSelected = selected.includes(t.entity_id);
            return (
              <button
                key={t.entity_id}
                onClick={() =>
                  onChange(
                    isSelected
                      ? selected.filter((id) => id !== t.entity_id)
                      : [...selected, t.entity_id]
                  )
                }
                className={cn(
                  "flex w-full items-center gap-3 border-b border-hairline px-4 py-2.5 text-left transition-colors duration-200",
                  isSelected ? "bg-brand-soft/60 shadow-[inset_3px_0_0_var(--brand)]" : "hover:bg-sunken"
                )}
              >
                <span
                  className={cn(
                    "flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-[5px] border-[1.5px] transition-colors duration-200",
                    isSelected ? "border-brand bg-brand" : "border-hairline-strong bg-surface"
                  )}
                >
                  {isSelected && <Check className="k-pop h-3 w-3 text-white" strokeWidth={3} />}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-1.5">
                    <span className={cn("truncate text-k-body", isSelected ? "font-semibold text-brand-strong" : "text-ink")}>{t.name}</span>
                    {t.profiled && (
                      <StatusPill tone="warn" size="sm">
                        profiled
                      </StatusPill>
                    )}
                    {t.failed_runs > 0 && (
                      <StatusPill tone="danger" size="sm" dot={false} title={`${t.failed_runs} failed runs`}>
                        <AlertTriangle className="h-3 w-3" />
                        {t.failed_runs}
                      </StatusPill>
                    )}
                  </span>
                  {t.child_count > 0 && (
                    <span className="block text-k-caption text-ink-subtle">
                      +{t.child_count} child entities
                    </span>
                  )}
                </span>
              </button>
            );
          })}
      </div>

      {estimate && selected.length > 0 && (
        <div className="k-rise border-t border-hairline bg-sunken p-4">
          <p className="mb-2.5 text-k-caption font-semibold text-ink-2">
            {selected.length} selected · frontier will follow their relationships
          </p>
          <div className="grid grid-cols-3 gap-2">
            {[
              ["Entities", String(estimate.to_process)],
              ["Est. time", formatDuration(estimate.estimated_minutes)],
              ["LLM calls", `~${estimate.estimated_llm_calls}`],
            ].map(([label, value]) => (
              <div key={label} className="kairos-panel px-2.5 py-2">
                <p className="text-[11px] font-medium text-ink-muted">{label}</p>
                <p className="text-[17px] font-bold tabular-nums text-ink">{value}</p>
              </div>
            ))}
          </div>
          <p className="mt-2.5 text-k-caption leading-snug text-ink-subtle">
            {estimate.basis === "measured"
              ? "Timing averaged from this deployment's completed runs."
              : "Timing from defaults — sharpens once runs complete."}
            {" Bounded by the run budget, so the walk cannot exceed it."}
          </p>
        </div>
      )}
    </div>
  );
}
