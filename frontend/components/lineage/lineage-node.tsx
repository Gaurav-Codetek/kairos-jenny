"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import { ChevronLeft, ChevronRight, Database, Eye, EyeOff, Table2 } from "lucide-react";

import type { LineageDirection, LineageNode } from "@/lib/lineage";
import { cn } from "@/lib/utils";

/** Colour encodes which side of the selected table a node sits on. */
const DIRECTION_STYLES: Record<LineageDirection, { ring: string; chip: string; label: string }> = {
  root: {
    ring: "border-amber-400/70 ring-2 ring-amber-400/30",
    chip: "bg-amber-400/15 text-amber-300 border-amber-400/30",
    label: "SELECTED",
  },
  upstream: {
    ring: "border-sky-500/50",
    chip: "bg-sky-500/15 text-sky-300 border-sky-500/30",
    label: "UPSTREAM",
  },
  downstream: {
    ring: "border-violet-500/50",
    chip: "bg-violet-500/15 text-violet-300 border-violet-500/30",
    label: "DOWNSTREAM",
  },
  both: {
    ring: "border-emerald-500/50",
    chip: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
    label: "CYCLE",
  },
};

export interface LineageNodeCallbacks {
  onExpand: (entityId: string, side: "upstream" | "downstream") => void;
  expandingId: string | null;
}

/**
 * Expand handlers are passed through the node data rather than context so
 * that React Flow's shallow node-data comparison still re-renders them.
 */
export type LineageNodeData = LineageNode & LineageNodeCallbacks;

export function LineageTableNode({ data, selected }: NodeProps) {
  const node = data as unknown as LineageNodeData;
  const style = DIRECTION_STYLES[node.direction] ?? DIRECTION_STYLES.upstream;
  const isExpanding = node.expandingId === node.entity_id;

  return (
    <div
      className={cn(
        "group relative w-[268px] rounded-xl border bg-card/95 shadow-lg backdrop-blur-sm transition-all",
        style.ring,
        selected && "ring-2 ring-primary/60",
        // Tables referenced by lineage but absent from the catalog.
        !node.known && "border-dashed opacity-70"
      )}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!h-2 !w-2 !border-0 !bg-muted-foreground/60"
      />

      {/* Upstream expander */}
      {node.hidden_upstream > 0 && (
        <button
          type="button"
          title={`Expand ${node.hidden_upstream} more upstream`}
          onClick={(event) => {
            event.stopPropagation();
            node.onExpand(node.entity_id, "upstream");
          }}
          className="absolute -left-3 top-1/2 z-10 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-full border border-sky-500/40 bg-sky-500/20 text-sky-200 shadow transition-colors hover:bg-sky-500/40 disabled:opacity-50"
          disabled={isExpanding}
        >
          <ChevronLeft className="h-3.5 w-3.5" />
        </button>
      )}

      <div className="flex items-start gap-2.5 p-3">
        <div
          className={cn(
            "mt-0.5 rounded-md p-1.5",
            node.known ? "bg-muted" : "bg-muted/40"
          )}
        >
          {node.table_type === "VIEW" ? (
            <Database className="h-3.5 w-3.5 text-sky-400" />
          ) : (
            <Table2 className={cn("h-3.5 w-3.5", node.known ? "text-emerald-400" : "text-muted-foreground")} />
          )}
        </div>

        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold" title={node.full_name}>
            {node.label}
          </div>
          <div className="truncate font-mono text-[10px] text-muted-foreground" title={node.full_name}>
            {node.catalog}.{node.schema}
          </div>

          <div className="mt-1.5 flex flex-wrap items-center gap-1">
            <span className={cn("rounded border px-1.5 py-px text-[9px] font-semibold tracking-wide", style.chip)}>
              {style.label}
            </span>
            {node.direction !== "root" && (
              <span className="rounded border border-border bg-muted/50 px-1.5 py-px text-[9px] font-medium text-muted-foreground">
                {node.depth} hop{node.depth === 1 ? "" : "s"}
              </span>
            )}
            {node.known ? (
              <span
                className="flex items-center gap-0.5 rounded border border-emerald-500/25 bg-emerald-500/10 px-1.5 py-px text-[9px] font-medium text-emerald-300"
                title="Present in the Synthetic Warehouse"
              >
                <Eye className="h-2.5 w-2.5" /> synced
              </span>
            ) : (
              <span
                className="flex items-center gap-0.5 rounded border border-orange-500/25 bg-orange-500/10 px-1.5 py-px text-[9px] font-medium text-orange-300"
                title="Referenced by lineage but never synced into the catalog"
              >
                <EyeOff className="h-2.5 w-2.5" /> external
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Downstream expander */}
      {node.hidden_downstream > 0 && (
        <button
          type="button"
          title={`Expand ${node.hidden_downstream} more downstream`}
          onClick={(event) => {
            event.stopPropagation();
            node.onExpand(node.entity_id, "downstream");
          }}
          className="absolute -right-3 top-1/2 z-10 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-full border border-violet-500/40 bg-violet-500/20 text-violet-200 shadow transition-colors hover:bg-violet-500/40 disabled:opacity-50"
          disabled={isExpanding}
        >
          <ChevronRight className="h-3.5 w-3.5" />
        </button>
      )}

      <Handle
        type="source"
        position={Position.Right}
        className="!h-2 !w-2 !border-0 !bg-muted-foreground/60"
      />
    </div>
  );
}

export const lineageNodeTypes = {
  lineageTable: LineageTableNode,
};
