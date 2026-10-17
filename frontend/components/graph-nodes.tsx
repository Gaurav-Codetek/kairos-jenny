"use client";

import { Handle, Position } from "@xyflow/react";
import { Database, Table } from "lucide-react";

export function CatalogGroupNode({ data }: { data: any }) {
  // We use a glassmorphism bubble-like effect for the catalog group
  return (
    <div className="relative min-w-[300px] min-h-[300px] rounded-[40px] border border-white/20 bg-gradient-to-br from-orange-400/10 to-purple-400/10 backdrop-blur-md shadow-2xl p-6 pointer-events-none">
      <div className="absolute top-4 left-6 text-xs font-bold tracking-wider text-muted-foreground/80 uppercase">
        {data.label}
      </div>
      {/* Group nodes don't typically need handles if edges connect to children, but we'll add invisible ones just in case */}
      <Handle type="target" position={Position.Top} className="opacity-0" />
      <Handle type="source" position={Position.Bottom} className="opacity-0" />
    </div>
  );
}

export function TableNode({ data }: { data: any }) {
  return (
    <div className="flex items-center gap-3 px-4 py-2 bg-background/90 backdrop-blur-sm border shadow-sm rounded-lg min-w-[200px]">
      <Handle type="target" position={Position.Left} className="w-2 h-2 rounded-full bg-muted-foreground" />
      
      <div className="p-2 bg-muted rounded-md">
        {data.table_type === "VIEW" ? (
          <Database className="w-4 h-4 text-blue-500" />
        ) : (
          <Table className="w-4 h-4 text-green-500" />
        )}
      </div>
      
      <div className="flex flex-col">
        <span className="text-sm font-semibold">{data.label}</span>
        <span className="text-xs text-muted-foreground">{data.full_name}</span>
      </div>
      
      <Handle type="source" position={Position.Right} className="w-2 h-2 rounded-full bg-muted-foreground" />
    </div>
  );
}

export const nodeTypes = {
  catalogGroup: CatalogGroupNode,
  tableNode: TableNode,
};
