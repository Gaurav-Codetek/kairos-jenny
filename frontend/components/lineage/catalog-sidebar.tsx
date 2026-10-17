"use client";

import { useMemo, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Database,
  FolderTree,
  GitBranch,
  Search,
  Table2,
  Workflow,
} from "lucide-react";

import type { CatalogTreeResponse } from "@/lib/lineage";
import { cn } from "@/lib/utils";

interface CatalogSidebarProps {
  tree: CatalogTreeResponse | null;
  loading: boolean;
  selectedEntityId: string | null;
  onSelect: (entityId: string) => void;
}

type SidebarTab = "catalog" | "lineage";

export function CatalogSidebar({ tree, loading, selectedEntityId, onSelect }: CatalogSidebarProps) {
  const [tab, setTab] = useState<SidebarTab>("catalog");
  const [query, setQuery] = useState("");
  const [lineageOnly, setLineageOnly] = useState(false);
  const [openCatalogs, setOpenCatalogs] = useState<Set<string>>(new Set());
  const [openSchemas, setOpenSchemas] = useState<Set<string>>(new Set());

  const search = query.trim().toLowerCase();

  // Searching auto-expands, otherwise the match is buried in a collapsed node.
  const catalogs = useMemo(() => {
    if (!tree) return [];
    return tree.catalogs
      .map((catalog) => ({
        ...catalog,
        schemas: catalog.schemas
          .map((schema) => ({
            ...schema,
            tables: schema.tables.filter((table) => {
              if (lineageOnly && !table.has_lineage) return false;
              if (!search) return true;
              return table.full_name.toLowerCase().includes(search);
            }),
          }))
          .filter((schema) => schema.tables.length > 0),
      }))
      .filter((catalog) => catalog.schemas.length > 0);
  }, [tree, search, lineageOnly]);

  const lineageGroups = useMemo(() => {
    if (!tree) return [];
    return tree.lineage_roots
      .map((group) => ({
        ...group,
        entities: group.entities.filter((entity) =>
          search ? entity.full_name.toLowerCase().includes(search) : true
        ),
      }))
      .filter((group) => group.entities.length > 0);
  }, [tree, search]);

  const toggle = (set: Set<string>, key: string, update: (next: Set<string>) => void) => {
    const next = new Set(set);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    update(next);
  };

  const isCatalogOpen = (id: string) => Boolean(search) || openCatalogs.has(id);
  const isSchemaOpen = (id: string) => Boolean(search) || openSchemas.has(id);

  return (
    <aside className="flex h-full w-[320px] shrink-0 flex-col border-r border-border bg-card/40">
      <div className="border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <FolderTree className="h-4 w-4 text-primary" />
          <h2 className="text-sm font-semibold tracking-tight">Knowledge Catalog</h2>
        </div>
        {tree && (
          <p className="mt-1 text-k-caption text-ink-muted">
            {tree.stats.tables.toLocaleString()} tables · {tree.stats.lineage_edges} lineage edges ·{" "}
            {tree.stats.external_lineage_nodes} external
          </p>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-border p-2">
        <button
          type="button"
          onClick={() => setTab("catalog")}
          className={cn(
            "flex flex-1 items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium transition-colors",
            tab === "catalog" ? "bg-primary text-primary-foreground" : "text-ink-muted hover:bg-muted"
          )}
        >
          <Database className="h-3.5 w-3.5" /> Catalog
        </button>
        <button
          type="button"
          onClick={() => setTab("lineage")}
          className={cn(
            "flex flex-1 items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium transition-colors",
            tab === "lineage" ? "bg-primary text-primary-foreground" : "text-ink-muted hover:bg-muted"
          )}
        >
          <Workflow className="h-3.5 w-3.5" /> Lineage roots
        </button>
      </div>

      {/* Search */}
      <div className="border-b border-border p-2">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-muted" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search tables…"
            className="w-full rounded-md border border-border bg-background py-1.5 pl-8 pr-2 text-xs outline-none placeholder:text-ink-muted focus:border-primary/60"
          />
        </div>
        {tab === "catalog" && (
          <label className="mt-2 flex cursor-pointer items-center gap-2 px-0.5 text-k-caption text-ink-muted">
            <input
              type="checkbox"
              checked={lineageOnly}
              onChange={(event) => setLineageOnly(event.target.checked)}
              className="h-3 w-3 accent-primary"
            />
            Only tables with lineage
            {tree && (
              <span className="ml-auto font-mono text-[11px]">
                {tree.stats.tables_with_lineage}/{tree.stats.tables}
              </span>
            )}
          </label>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-2">
        {loading && <p className="px-2 py-4 text-xs text-ink-muted">Loading catalog…</p>}

        {!loading && tab === "catalog" && catalogs.length === 0 && (
          <p className="px-2 py-4 text-xs text-ink-muted">
            {lineageOnly
              ? "No catalog tables have lineage edges. Try the Lineage roots tab."
              : "No tables match this search."}
          </p>
        )}

        {!loading &&
          tab === "catalog" &&
          catalogs.map((catalog) => (
            <div key={catalog.id} className="mb-0.5">
              <button
                type="button"
                onClick={() => toggle(openCatalogs, catalog.id, setOpenCatalogs)}
                className="flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-xs font-semibold hover:bg-muted"
              >
                {isCatalogOpen(catalog.id) ? (
                  <ChevronDown className="h-3.5 w-3.5 shrink-0 text-ink-muted" />
                ) : (
                  <ChevronRight className="h-3.5 w-3.5 shrink-0 text-ink-muted" />
                )}
                <Database className="h-3.5 w-3.5 shrink-0 text-amber-400" />
                <span className="truncate">{catalog.name}</span>
                <span className="ml-auto shrink-0 font-mono text-[11px] text-ink-muted">
                  {catalog.lineage_table_count > 0 && (
                    <span className="mr-1 text-sky-400">{catalog.lineage_table_count}⇄</span>
                  )}
                  {catalog.table_count}
                </span>
              </button>

              {isCatalogOpen(catalog.id) &&
                catalog.schemas.map((schema) => (
                  <div key={schema.id} className="ml-3 border-l border-border/60 pl-1">
                    <button
                      type="button"
                      onClick={() => toggle(openSchemas, schema.id, setOpenSchemas)}
                      className="flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-left text-xs hover:bg-muted"
                    >
                      {isSchemaOpen(schema.id) ? (
                        <ChevronDown className="h-3 w-3 shrink-0 text-ink-muted" />
                      ) : (
                        <ChevronRight className="h-3 w-3 shrink-0 text-ink-muted" />
                      )}
                      <span className="truncate text-ink-muted">{schema.name}</span>
                      <span className="ml-auto shrink-0 font-mono text-[11px] text-ink-muted">
                        {schema.table_count}
                      </span>
                    </button>

                    {isSchemaOpen(schema.id) && (
                      <div className="ml-3 border-l border-border/60 pl-1">
                        {schema.tables.map((table) => (
                          <button
                            key={table.id}
                            type="button"
                            onClick={() => onSelect(table.entity_id)}
                            title={table.full_name}
                            className={cn(
                              "flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-left text-xs transition-colors",
                              selectedEntityId === table.entity_id
                                ? "bg-primary/15 text-primary"
                                : "hover:bg-muted",
                              !table.has_lineage && "opacity-55"
                            )}
                          >
                            <Table2 className="h-3 w-3 shrink-0 text-emerald-400/80" />
                            <span className="truncate">{table.name}</span>
                            {table.has_lineage && (
                              <span
                                className="ml-auto shrink-0 font-mono text-[10.5px] text-sky-400"
                                title={`${table.upstream_count} upstream, ${table.downstream_count} downstream`}
                              >
                                {table.upstream_count}↑{table.downstream_count}↓
                              </span>
                            )}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
            </div>
          ))}

        {!loading && tab === "lineage" && (
          <>
            <p className="mb-2 rounded-md border border-orange-500/20 bg-orange-500/5 px-2 py-1.5 text-[11px] leading-relaxed text-orange-200/80">
              <GitBranch className="mr-1 inline h-3 w-3" />
              Every entity appearing in lineage. Ones marked <strong>external</strong> come from
              <code className="mx-1 rounded bg-muted px-1">system.access.*</code>
              but were never synced into the catalog.
            </p>

            {lineageGroups.length === 0 && (
              <p className="px-2 py-4 text-xs text-ink-muted">No lineage entities match.</p>
            )}

            {lineageGroups.map((group) => (
              <div key={group.catalog} className="mb-2">
                <div className="flex items-center gap-1.5 px-2 py-1 text-xs font-semibold">
                  <Database className="h-3.5 w-3.5 shrink-0 text-amber-400" />
                  <span className="truncate">{group.catalog}</span>
                  <span className="ml-auto shrink-0 font-mono text-[11px] text-ink-muted">
                    {group.known_count}/{group.entity_count} synced
                  </span>
                </div>
                <div className="ml-3 border-l border-border/60 pl-1">
                  {group.entities.map((entity) => (
                    <button
                      key={entity.entity_id}
                      type="button"
                      onClick={() => onSelect(entity.entity_id)}
                      title={entity.full_name}
                      className={cn(
                        "flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-left text-xs transition-colors",
                        selectedEntityId === entity.entity_id
                          ? "bg-primary/15 text-primary"
                          : "hover:bg-muted"
                      )}
                    >
                      <Table2
                        className={cn(
                          "h-3 w-3 shrink-0",
                          entity.known ? "text-emerald-400/80" : "text-orange-400/70"
                        )}
                      />
                      <span className={cn("truncate", !entity.known && "italic text-ink-muted")}>
                        {entity.schema}.{entity.name}
                      </span>
                      <span className="ml-auto shrink-0 font-mono text-[10.5px] text-sky-400">
                        {entity.upstream_count}↑{entity.downstream_count}↓
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </>
        )}
      </div>
    </aside>
  );
}
