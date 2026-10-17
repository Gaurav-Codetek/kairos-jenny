"use client";

import { memo } from "react";
import { Handle, Position, useStore, type NodeProps } from "@xyflow/react";
import { ChevronRight, X } from "lucide-react";

import { kindVisual } from "@/components/graph/lineage-card";
import { useMeshHighlight } from "@/components/mesh/highlight";
import { FAILED, LEAF_HEIGHT, LEAF_WIDTH, bundleSummary, type Bundle, type ResourceType } from "@/lib/mesh";
import { cn } from "@/lib/utils";

/** One accent per kind — a thin bar, not a filled badge, so colour guides without shouting. */
export const ACCENT: Record<ResourceType, string> = {
  catalog: "var(--k-container-fg)",
  schema: "var(--k-container-fg)",
  table: "var(--k-table-fg)",
  volume: "var(--k-external-fg)",
  pipeline: "var(--k-job-fg)",
  task: "var(--k-task-fg)",
  product: "var(--brand)",
};

export const KIND_LABEL: Record<ResourceType, string> = {
  catalog: "Catalog",
  schema: "Schema",
  table: "Table",
  volume: "Volume",
  pipeline: "Pipeline",
  task: "Task",
  product: "Data product",
};

export interface MeshNodeData {
  bundle: Bundle;
  /** The open bundle this card came from — shown as a chip that closes it. */
  openParent: Bundle | null;
  childCount: number;
  onToggle: (uid: string) => void;
}

const handle = "!h-2 !w-2 !min-h-0 !min-w-0 !border-0 !bg-transparent";

/** Below this zoom a card shows its name only: detail you cannot read is just noise. */
const useCompact = () => useStore((s) => s.transform[2] < 0.5);

function StatusDot({ bundle }: { bundle: Bundle }) {
  const runs = bundle.inherited.runs ?? bundle.inherited.task_runs ?? 0;
  if (!runs || !bundle.status) return null;
  const failed = FAILED.has(String(bundle.status).toUpperCase());
  return (
    <span
      className={cn("h-2 w-2 shrink-0 rounded-full ring-2", failed ? "bg-danger-dot ring-danger-soft" : "bg-ok-dot ring-ok-soft")}
      title={`Last run ${String(bundle.status).toLowerCase()}${
        bundle.inherited.failed_runs ? ` · ${bundle.inherited.failed_runs} of ${runs} failed` : ""
      }`}
    />
  );
}

function BundleNodeImpl({ id, data }: NodeProps) {
  const d = data as unknown as MeshNodeData;
  const b = d.bundle;
  // Highlight comes from context, not node data — see highlight.ts.
  const h = useMeshHighlight();
  const selected = h.selected === id;
  const onPath = h.pathNodes.has(id);
  const dimmed = h.focusId !== null && !onPath && h.focusId !== id;
  const Icon = kindVisual(b.resource_type).icon;
  const compact = useCompact();

  return (
    <div
      style={{ width: LEAF_WIDTH, height: LEAF_HEIGHT }}
      className={cn(
        "group relative flex items-stretch overflow-hidden rounded-[10px] border bg-surface transition-[opacity,box-shadow,border-color,transform] duration-200 ease-out",
        selected
          ? "border-brand shadow-[0_0_0_3px_var(--brand-soft)]"
          : onPath
            ? "border-brand-border shadow-[0_4px_14px_-8px_rgb(81_72_224/0.45)]"
            : "border-hairline hover:-translate-y-px hover:border-brand-border hover:shadow-[0_6px_18px_-12px_rgb(81_72_224/0.4)]",
        dimmed && "opacity-30"
      )}
    >
      <Handle type="target" position={Position.Left} className={handle} />

      {!compact && (
        <span className="flex w-11 shrink-0 items-center justify-center">
          <span
            className="flex h-7 w-7 items-center justify-center rounded-full"
            style={{ background: kindVisual(b.resource_type).bg, color: ACCENT[b.resource_type] }}
          >
            <Icon className="h-3.5 w-3.5" strokeWidth={2.2} />
          </span>
        </span>
      )}

      <div className={cn("flex min-w-0 flex-1 flex-col justify-center gap-1 pr-3", compact && "pl-3")}>
        {!compact && d.openParent && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              d.onToggle(d.openParent!.unique_id);
            }}
            className="nodrag group/chip -ml-0.5 flex max-w-full items-center gap-1 self-start rounded-full px-1 text-[10.5px] leading-none text-ink-subtle hover:bg-brand-soft hover:text-brand-strong"
            title={`In ${KIND_LABEL[d.openParent.resource_type].toLowerCase()} ${d.openParent.name} — click to close it`}
          >
            <span className="truncate">{d.openParent.name}</span>
            <X className="h-2.5 w-2.5 shrink-0 opacity-0 group-hover/chip:opacity-100" />
          </button>
        )}
        <div className="flex items-center gap-1.5">
          {compact && <Icon className="h-4 w-4 shrink-0" style={{ color: ACCENT[b.resource_type] }} strokeWidth={2} />}
          <span
            className={cn("truncate font-semibold leading-tight", selected ? "text-brand-strong" : "text-ink", compact ? "text-[17px]" : "text-[12.5px]")}
            title={b.fqn.join(".")}
          >
            {b.name}
          </span>
          <span className="ml-auto" />
          <StatusDot bundle={b} />
        </div>
        {!compact && (
          <span className="truncate text-[10.5px] leading-none text-ink-muted">
            {KIND_LABEL[b.resource_type]} · {bundleSummary(b)}
          </span>
        )}
      </div>

      {d.childCount > 0 && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            d.onToggle(b.unique_id);
          }}
          className="nodrag flex w-8 shrink-0 items-center justify-center border-l border-hairline text-ink-subtle transition-colors hover:bg-brand-soft hover:text-brand"
          title={`Open ${b.name}: show what inside it carries lineage`}
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      )}
      <Handle type="source" position={Position.Right} className={handle} />
    </div>
  );
}

export const BundleNode = memo(BundleNodeImpl);
export const meshNodeTypes = { bundle: BundleNode };
