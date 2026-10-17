"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import {
  Boxes,
  Columns3,
  Database,
  FileCode2,
  FileText,
  FolderTree,
  Globe,
  HardDrive,
  Layers,
  ListChecks,
  Loader2,
  Play,
  Server,
  Table2,
  type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * Visual identity per entity kind: a three-letter code and a tint, the way
 * dbt separates SRC from MDL at a glance. Codes are short so the badge stays
 * a fixed size no matter how long the entity name is.
 */
export const KIND_VISUAL: Record<
  string,
  { code: string; icon: LucideIcon; bg: string; fg: string }
> = {
  workspace: { code: "WS", icon: Layers, bg: "var(--k-container-bg)", fg: "var(--k-container-fg)" },
  catalog: { code: "CAT", icon: Database, bg: "var(--k-container-bg)", fg: "var(--k-container-fg)" },
  schema: { code: "SCH", icon: FolderTree, bg: "var(--k-container-bg)", fg: "var(--k-container-fg)" },
  table: { code: "TBL", icon: Table2, bg: "var(--k-table-bg)", fg: "var(--k-table-fg)" },
  column: { code: "COL", icon: Columns3, bg: "var(--k-table-bg)", fg: "var(--k-table-fg)" },
  job: { code: "JOB", icon: Boxes, bg: "var(--k-job-bg)", fg: "var(--k-job-fg)" },
  pipeline: { code: "PIPE", icon: Boxes, bg: "var(--k-job-bg)", fg: "var(--k-job-fg)" },
  task: { code: "TSK", icon: ListChecks, bg: "var(--k-task-bg)", fg: "var(--k-task-fg)" },
  run: { code: "RUN", icon: Play, bg: "var(--k-run-bg)", fg: "var(--k-run-fg)" },
  taskrun: { code: "TRN", icon: Play, bg: "var(--k-run-bg)", fg: "var(--k-run-fg)" },
  // dbt-native kinds
  source: { code: "SRC", icon: Database, bg: "var(--k-source-bg)", fg: "var(--k-source-fg)" },
  model: { code: "MDL", icon: Boxes, bg: "var(--k-model-bg)", fg: "var(--k-model-fg)" },
  // Kinds the enrichment agent registers at runtime
  volume: { code: "VOL", icon: HardDrive, bg: "var(--k-external-bg)", fg: "var(--k-external-fg)" },
  // Data products: business concepts defined in Kairos, downstream of the tables they read
  product: { code: "DP", icon: Layers, bg: "var(--brand-soft)", fg: "var(--brand)" },
  file: { code: "FILE", icon: FileText, bg: "var(--k-external-bg)", fg: "var(--k-external-fg)" },
  notebook: { code: "NB", icon: FileCode2, bg: "var(--k-task-bg)", fg: "var(--k-task-fg)" },
  cluster: { code: "CLS", icon: Server, bg: "var(--k-external-bg)", fg: "var(--k-external-fg)" },
  external_connection: {
    code: "EXT",
    icon: Globe,
    bg: "var(--k-external-bg)",
    fg: "var(--k-external-fg)",
  },
};

export function kindVisual(kind: string) {
  return (
    KIND_VISUAL[kind] ?? {
      code: (kind || "ENT").slice(0, 4).toUpperCase(),
      icon: Layers,
      bg: "var(--k-neutral-bg)",
      fg: "var(--k-neutral-fg)",
    }
  );
}

export interface LineageCardData {
  entity_id: string;
  kind: string;
  label: string;
  sublabel?: string;
  known?: boolean;
  discovered?: boolean;
  failed?: boolean;
  /** Focus flow: this node is on the selected node's path. */
  focused?: boolean;
  /** Focus flow: a selection exists and this node is not on its path. */
  dimmed?: boolean;
  isRoot?: boolean;
  /** Not yet expanded — clicking pulls in its next hop. */
  canExpand?: boolean;
  expanding?: boolean;
}

export function LineageCard({ data, selected }: NodeProps) {
  const node = data as unknown as LineageCardData;
  const visual = kindVisual(node.kind);

  return (
    <div
      className={cn(
        "group relative flex w-[210px] items-center gap-2.5 rounded-[10px] border bg-surface px-2.5 py-2 transition-all duration-200 ease-out",
        // Selection reads through the border and a soft ring, never a fill —
        // a filled card would fight the kind badge for attention.
        selected || node.isRoot
          ? "border-brand shadow-[0_0_0_3px_var(--brand-soft)]"
          : "border-hairline hover:-translate-y-px hover:border-brand-border hover:shadow-[0_6px_18px_-12px_rgb(81_72_224/0.4)]",
        node.failed && "border-danger-dot/60",
        !node.known && "border-dashed",
        // Dimming is what makes focus flow legible in a dense graph.
        node.dimmed && "opacity-25",
        node.focused && !node.isRoot && "border-brand-border"
      )}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!h-1.5 !w-1.5 !border-0 !bg-transparent"
      />

      <span
        className="flex h-8 w-8 shrink-0 flex-col items-center justify-center rounded-full"
        style={{ background: visual.bg, color: visual.fg }}
      >
        <visual.icon className="h-3 w-3" strokeWidth={2.25} />
        <span className="text-[7px] font-bold leading-none tracking-tight">{visual.code}</span>
      </span>

      <span className="min-w-0 flex-1">
        <span
          className="block truncate text-k-body font-semibold leading-tight text-ink"
          title={node.sublabel || node.label}
        >
          {node.label}
        </span>
        {node.sublabel && (
          <span className="block truncate text-[11px] leading-tight text-ink-muted">
            {node.sublabel}
          </span>
        )}
      </span>

      {node.discovered && (
        <span
          className="absolute -right-1 -top-1 h-2 w-2 rounded-full ring-2 ring-surface"
          style={{ background: "var(--brand)" }}
          title="Discovered by the enrichment agent"
        />
      )}

      {/* Expansion affordance. The graph opens at one hop; this signals there
          is more behind a node without pre-loading the whole warehouse. */}
      {node.canExpand && !node.dimmed && (
        <span
          className={cn(
            "absolute -right-2 top-1/2 flex h-4 w-4 -translate-y-1/2 items-center justify-center",
            "rounded-full border bg-surface text-[11px] font-semibold leading-none",
            "border-hairline text-ink-subtle transition-colors",
            "group-hover:border-brand group-hover:text-brand"
          )}
          title="Click the card to expand one more hop"
        >
          {node.expanding ? (
            <Loader2 className="h-2.5 w-2.5 animate-spin" />
          ) : (
            "+"
          )}
        </span>
      )}

      <Handle
        type="source"
        position={Position.Right}
        className="!h-1.5 !w-1.5 !border-0 !bg-transparent"
      />
    </div>
  );
}

export const lineageNodeTypes = { lineageCard: LineageCard };
