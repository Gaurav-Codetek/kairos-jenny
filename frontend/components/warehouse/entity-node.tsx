"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import {
  Activity,
  AlertTriangle,
  Boxes,
  Building2,
  Columns3,
  Database,
  FileSearch,
  FolderTree,
  History,
  ListChecks,
  Play,
  Plus,
  RefreshCw,
  FileCode2,
  FileText,
  Globe,
  HardDrive,
  LayoutDashboard,
  Server,
  Sparkles,
  Table2,
} from "lucide-react";

import { isFailureStatus, kindStyle, type EntityNode } from "@/lib/warehouse";
import { cn } from "@/lib/utils";

const KIND_ICON: Record<string, typeof Database> = {
  workspace: Building2,
  catalog: Database,
  schema: FolderTree,
  table: Table2,
  column: Columns3,
  job: Boxes,
  task: ListChecks,
  run: Play,
  taskrun: Activity,
  evidence: FileSearch,
  change: History,
  syncstate: RefreshCw,
  // Kinds the enrichment agent registers.
  volume: HardDrive,
  file: FileText,
  notebook: FileCode2,
  cluster: Server,
  genie_space: Sparkles,
  external_connection: Globe,
  dashboard: LayoutDashboard,
};

export interface EntityNodeCallbacks {
  onExpand: (id: string) => void;
  expandingId: string | null;
}

export type EntityNodeData = EntityNode & EntityNodeCallbacks;

export function WarehouseEntityNode({ data, selected }: NodeProps) {
  const node = data as unknown as EntityNodeData;
  const style = kindStyle(node.kind);
  const Icon = KIND_ICON[node.kind] ?? Database;
  const failed = isFailureStatus(node.status);
  const isExpanding = node.expandingId === node.id;

  return (
    <div
      className={cn(
        "relative w-[250px] rounded-xl border bg-card/95 shadow-lg backdrop-blur-sm transition-all",
        style.border,
        node.is_root && "ring-2 ring-primary/70",
        selected && "ring-2 ring-primary/50",
        failed && "border-red-500/70 bg-red-950/30",
        !node.known && "border-dashed opacity-70"
      )}
    >
      <Handle type="target" position={Position.Left} className="!h-2 !w-2 !border-0 !bg-muted-foreground/60" />

      <div className="flex items-start gap-2.5 p-2.5">
        <div className={cn("mt-0.5 rounded-md p-1.5", failed ? "bg-red-500/20" : "bg-muted")}>
          {failed ? (
            <AlertTriangle className="h-3.5 w-3.5 text-red-400" />
          ) : (
            <Icon className="h-3.5 w-3.5" style={{ color: style.dot }} />
          )}
        </div>

        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold" title={node.label}>
            {node.label}
          </div>
          <div className="truncate font-mono text-[10px] text-muted-foreground" title={node.sublabel}>
            {node.sublabel || node.id}
          </div>

          <div className="mt-1 flex flex-wrap items-center gap-1">
            <span
              className={cn(
                "rounded border px-1.5 py-px text-[9px] font-semibold tracking-wide",
                style.chip
              )}
            >
              {style.label}
            </span>
            {!node.is_root && (
              <span className="rounded border border-border bg-muted/50 px-1.5 py-px text-[9px] text-muted-foreground">
                d{node.depth}
              </span>
            )}
            {failed && (
              <span className="rounded border border-red-500/40 bg-red-500/15 px-1.5 py-px text-[9px] font-semibold text-red-300">
                {node.status}
              </span>
            )}
            {node.discovered && (
              <span
                className="rounded border border-cyan-500/25 bg-cyan-500/10 px-1.5 py-px text-[9px] text-cyan-300"
                title="Registered by the enrichment agent, not by the connector"
              >
                found
              </span>
            )}
            {!node.known && (
              <span
                className="rounded border border-orange-500/25 bg-orange-500/10 px-1.5 py-px text-[9px] text-orange-300"
                title="Referenced by other records but never synced"
              >
                unsynced
              </span>
            )}
          </div>
        </div>
      </div>

      {node.expandable && (
        <button
          type="button"
          title="Expand this entity"
          onClick={(event) => {
            event.stopPropagation();
            node.onExpand(node.id);
          }}
          disabled={isExpanding}
          className="absolute -right-3 top-1/2 z-10 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-full border border-primary/50 bg-primary/25 text-primary-foreground shadow transition-colors hover:bg-primary/50 disabled:opacity-50"
        >
          <Plus className={cn("h-3.5 w-3.5", isExpanding && "animate-spin")} />
        </button>
      )}

      <Handle type="source" position={Position.Right} className="!h-2 !w-2 !border-0 !bg-muted-foreground/60" />
    </div>
  );
}

export const entityNodeTypes = {
  entityNode: WarehouseEntityNode,
};
