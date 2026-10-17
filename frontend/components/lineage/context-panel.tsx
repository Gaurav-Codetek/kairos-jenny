"use client";

import { useState } from "react";
import {
  Activity,
  Columns3,
  FileSearch,
  GitBranch,
  History,
  Info,
  Loader2,
  X,
} from "lucide-react";

import { formatBytes, formatCount, type NodeContext } from "@/lib/lineage";
import { cn } from "@/lib/utils";

interface ContextPanelProps {
  context: NodeContext | null;
  loading: boolean;
  onClose: () => void;
}

type PanelTab = "overview" | "columns" | "lineage" | "changes" | "evidence";

const TABS: Array<{ id: PanelTab; label: string; icon: typeof Info }> = [
  { id: "overview", label: "Overview", icon: Info },
  { id: "columns", label: "Columns", icon: Columns3 },
  { id: "lineage", label: "Columns flow", icon: GitBranch },
  { id: "changes", label: "Changes", icon: History },
  { id: "evidence", label: "Evidence", icon: FileSearch },
];

export function ContextPanel({ context, loading, onClose }: ContextPanelProps) {
  const [tab, setTab] = useState<PanelTab>("overview");

  if (loading) {
    return (
      <aside className="flex h-full w-[380px] shrink-0 items-center justify-center border-l border-border bg-card/40">
        <Loader2 className="h-5 w-5 animate-spin text-ink-muted" />
      </aside>
    );
  }

  if (!context) return null;

  const { table } = context;
  const counts: Record<PanelTab, number | null> = {
    overview: null,
    columns: context.column_count,
    lineage: context.column_lineage.length,
    changes: context.changes.length,
    evidence: context.evidence.length,
  };

  return (
    <aside className="flex h-full w-[380px] shrink-0 flex-col border-l border-border bg-card/40">
      <div className="flex items-start gap-2 border-b border-border px-4 py-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h2 className="truncate text-sm font-semibold" title={table.full_name}>
              {table.name}
            </h2>
            {context.known ? (
              <span className="shrink-0 rounded border border-emerald-500/25 bg-emerald-500/10 px-1.5 py-px text-[10.5px] font-medium text-emerald-300">
                synced
              </span>
            ) : (
              <span className="shrink-0 rounded border border-orange-500/25 bg-orange-500/10 px-1.5 py-px text-[10.5px] font-medium text-orange-300">
                external
              </span>
            )}
          </div>
          <p className="truncate font-mono text-[11px] text-ink-muted" title={table.full_name}>
            {table.full_name}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md p-1 text-ink-muted transition-colors hover:bg-muted hover:text-foreground"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {!context.known && (
        <p className="border-b border-border bg-orange-500/5 px-4 py-2 text-k-caption leading-relaxed text-orange-200/80">
          This table appears in lineage but was never synced into the catalog, so only its graph
          position is known — no columns, changes, or evidence.
        </p>
      )}

      <div className="flex gap-0.5 overflow-x-auto border-b border-border px-2 py-1.5">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={cn(
              "flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-k-caption font-medium transition-colors",
              tab === id ? "bg-primary text-primary-foreground" : "text-ink-muted hover:bg-muted"
            )}
          >
            <Icon className="h-3 w-3" />
            {label}
            {counts[id] !== null && counts[id]! > 0 && (
              <span className="font-mono text-[10.5px] opacity-70">{counts[id]}</span>
            )}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        {tab === "overview" && (
          <dl className="space-y-2 text-xs">
            <Row label="Catalog" value={table.catalog} mono />
            <Row label="Schema" value={table.schema} mono />
            <Row label="Type" value={table.table_type ?? "—"} />
            <Row label="Format" value={table.data_source_format ?? "—"} />
            <Row label="Owner" value={table.owner ?? "—"} />
            <Row label="Rows" value={formatCount(table.row_count)} />
            <Row label="Size" value={formatBytes(table.size_bytes)} />
            <Row
              label="First seen"
              value={table.first_seen_at ? new Date(table.first_seen_at).toLocaleString() : "—"}
            />
            <Row
              label="Last seen"
              value={table.last_seen_at ? new Date(table.last_seen_at).toLocaleString() : "—"}
            />
            {table.comment && (
              <div className="pt-2">
                <dt className="k-label mb-1">
                  Comment
                </dt>
                <dd className="rounded-md border border-border bg-muted/30 p-2 text-k-caption leading-relaxed">
                  {table.comment}
                </dd>
              </div>
            )}
            {table.storage_location && (
              <div className="pt-2">
                <dt className="k-label mb-1">
                  Storage location
                </dt>
                <dd className="break-all rounded-md border border-border bg-muted/30 p-2 font-mono text-[11px]">
                  {table.storage_location}
                </dd>
              </div>
            )}
          </dl>
        )}

        {tab === "columns" && (
          <div className="space-y-1">
            {context.columns.length === 0 && <Empty text="No columns recorded." />}
            {context.columns.map((column) => (
              <div
                key={column.name}
                className="rounded-md border border-border bg-muted/20 px-2 py-1.5"
              >
                <div className="flex items-baseline gap-2">
                  <span className="truncate font-mono text-k-caption font-medium">{column.name}</span>
                  <span className="ml-auto shrink-0 font-mono text-[11px] text-sky-300">
                    {column.data_type}
                  </span>
                </div>
                <div className="mt-0.5 flex gap-1.5 text-[10.5px] text-ink-muted">
                  <span>#{column.ordinal_position}</span>
                  {!column.is_nullable && <span className="text-amber-400">NOT NULL</span>}
                  {column.is_partition_column && <span className="text-violet-400">PARTITION</span>}
                </div>
                {column.comment && (
                  <p className="mt-1 text-[11px] leading-snug text-ink-muted">
                    {column.comment}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}

        {tab === "lineage" && (
          <div className="space-y-1">
            {context.column_lineage.length === 0 && (
              <Empty text="No column-level lineage recorded for this table." />
            )}
            {context.column_lineage.map((flow, index) => (
              <div
                key={`${flow.column}-${flow.remote_entity_id}-${index}`}
                className="rounded-md border border-border bg-muted/20 px-2 py-1.5"
              >
                <div className="flex items-center gap-1.5">
                  <span
                    className={cn(
                      "shrink-0 rounded px-1 py-px text-[10.5px] font-semibold",
                      flow.direction === "upstream"
                        ? "bg-sky-500/15 text-sky-300"
                        : "bg-violet-500/15 text-violet-300"
                    )}
                  >
                    {flow.direction === "upstream" ? "IN" : "OUT"}
                  </span>
                  <span className="truncate font-mono text-k-caption font-medium">{flow.column}</span>
                </div>
                <p
                  className="mt-1 truncate font-mono text-[10.5px] text-ink-muted"
                  title={flow.remote_full_name}
                >
                  {flow.direction === "upstream" ? "← " : "→ "}
                  {flow.remote_full_name}
                </p>
              </div>
            ))}
          </div>
        )}

        {tab === "changes" && (
          <div className="space-y-1">
            {context.changes.length === 0 && <Empty text="No change events recorded." />}
            {context.changes.map((change, index) => (
              <div
                key={`${change.detected_at}-${index}`}
                className="rounded-md border border-border bg-muted/20 px-2 py-1.5"
              >
                <div className="flex items-center gap-1.5">
                  <Activity className="h-3 w-3 shrink-0 text-emerald-400" />
                  <span className="text-k-caption font-medium">{change.change_type}</span>
                  {change.field_name && (
                    <span className="font-mono text-[11px] text-ink-muted">
                      {change.field_name}
                    </span>
                  )}
                  <span className="ml-auto shrink-0 text-[10.5px] text-ink-muted">
                    {new Date(change.detected_at).toLocaleDateString()}
                  </span>
                </div>
                {(change.old_value || change.new_value) && (
                  <div className="mt-1 space-y-0.5 font-mono text-[10.5px]">
                    {change.old_value && (
                      <p className="truncate text-red-300/80">− {change.old_value}</p>
                    )}
                    {change.new_value && (
                      <p className="truncate text-emerald-300/80">+ {change.new_value}</p>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {tab === "evidence" && (
          <div className="space-y-1">
            {context.evidence.length === 0 && <Empty text="No evidence recorded." />}
            {context.evidence.map((item) => (
              <div
                key={item.content_hash + item.observed_at}
                className="rounded-md border border-border bg-muted/20 px-2 py-1.5"
              >
                <div className="flex items-center gap-1.5">
                  <FileSearch className="h-3 w-3 shrink-0 text-amber-400" />
                  <span className="text-k-caption font-medium">{item.source_type}</span>
                  <span className="ml-auto shrink-0 font-mono text-[10.5px] text-ink-muted">
                    {item.content_hash}
                  </span>
                </div>
                <p className="mt-0.5 text-[10.5px] text-ink-muted">
                  {new Date(item.observed_at).toLocaleString()}
                </p>
                <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap break-all rounded bg-background/60 p-1.5 font-mono text-[10.5px] leading-snug text-ink-muted">
                  {item.content_preview}
                </pre>
              </div>
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-baseline gap-2">
      <dt className="k-label w-24 shrink-0">
        {label}
      </dt>
      <dd className={cn("min-w-0 flex-1 truncate text-k-caption", mono && "font-mono")} title={value}>
        {value}
      </dd>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <p className="px-1 py-4 text-center text-k-caption text-ink-muted">{text}</p>;
}
