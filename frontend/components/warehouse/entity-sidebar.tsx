"use client";

import { useEffect, useMemo, useState } from "react";
import { Building2, Layers, Loader2, Search, Sparkles } from "lucide-react";

import {
  fetchEntityMap,
  fetchRoots,
  kindStyle,
  searchEntities,
  type EntityMapDocument,
  type SearchResponse,
  type WarehouseRoot,
} from "@/lib/warehouse";
import { cn } from "@/lib/utils";

interface EntitySidebarProps {
  selectedId: string | null;
  onSelect: (entityId: string) => void;
}

type Tab = "browse" | "map";

export function EntitySidebar({ selectedId, onSelect }: EntitySidebarProps) {
  const [tab, setTab] = useState<Tab>("browse");
  const [roots, setRoots] = useState<WarehouseRoot[]>([]);
  const [entityMap, setEntityMap] = useState<EntityMapDocument | null>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResponse["results"]>([]);
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    fetchRoots().then(({ roots: r }) => setRoots(r)).catch(() => undefined);
    fetchEntityMap().then(setEntityMap).catch(() => undefined);
  }, []);

  // Debounced cross-grain search — this is the main way in.
  useEffect(() => {
    const needle = query.trim();
    if (needle.length < 2) {
      setResults([]);
      return;
    }
    setSearching(true);
    const handle = window.setTimeout(() => {
      searchEntities(needle, 40)
        .then((response) => setResults(response.results))
        .catch(() => setResults([]))
        .finally(() => setSearching(false));
    }, 250);
    return () => {
      window.clearTimeout(handle);
      setSearching(false);
    };
  }, [query]);

  const grouped = useMemo(() => {
    const byKind = new Map<string, SearchResponse["results"]>();
    results.forEach((result) => {
      const list = byKind.get(result.kind) ?? [];
      list.push(result);
      byKind.set(result.kind, list);
    });
    return Array.from(byKind.entries());
  }, [results]);

  return (
    <aside className="flex h-full w-[300px] shrink-0 flex-col border-r border-border bg-card/40">
      <div className="border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <Layers className="h-4 w-4 text-primary" />
          <h2 className="text-sm font-semibold tracking-tight">Entity Map</h2>
        </div>
        {entityMap && (
          <p className="mt-1 text-k-caption text-ink-muted">
            {entityMap.totals.entities.toLocaleString()} entities · {entityMap.kinds.length} kinds
          </p>
        )}
      </div>

      <div className="flex gap-1 border-b border-border p-2">
        {(["browse", "map"] as Tab[]).map((id) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={cn(
              "flex-1 rounded-md px-2 py-1.5 text-k-caption font-medium capitalize transition-colors",
              tab === id ? "bg-primary text-primary-foreground" : "text-ink-muted hover:bg-muted"
            )}
          >
            {id === "browse" ? "Browse" : "Schema"}
          </button>
        ))}
      </div>

      {tab === "browse" && (
        <>
          <div className="border-b border-border p-2">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-muted" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search any grain…"
                className="w-full rounded-md border border-border bg-background py-1.5 pl-8 pr-2 text-xs outline-none placeholder:text-ink-muted focus:border-primary/60"
              />
              {searching && (
                <Loader2 className="absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 animate-spin text-ink-muted" />
              )}
            </div>
            <p className="mt-1 px-0.5 text-[10.5px] text-ink-muted">
              Tables, columns, jobs, tasks, runs — anything.
            </p>
          </div>

          <div className="flex-1 overflow-y-auto p-2">
            {query.trim().length >= 2 ? (
              <>
                {results.length === 0 && !searching && (
                  <p className="px-2 py-4 text-xs text-ink-muted">No matches.</p>
                )}
                {grouped.map(([kind, items]) => {
                  const style = kindStyle(kind);
                  return (
                    <div key={kind} className="mb-2">
                      <p className="k-label px-2 py-1">
                        {style.label} ({items.length})
                      </p>
                      {items.map((item) => (
                        <button
                          key={item.id}
                          type="button"
                          onClick={() => onSelect(item.id)}
                          title={item.sublabel || item.id}
                          className={cn(
                            "flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-left transition-colors",
                            selectedId === item.id ? "bg-primary/15" : "hover:bg-muted"
                          )}
                        >
                          <span
                            className="h-2 w-2 shrink-0 rounded-full"
                            style={{ backgroundColor: style.dot }}
                          />
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-xs">{item.label}</span>
                            <span className="block truncate font-mono text-[10.5px] text-ink-muted">
                              {item.sublabel}
                            </span>
                          </span>
                        </button>
                      ))}
                    </div>
                  );
                })}
              </>
            ) : (
              <>
                <p className="k-label px-2 py-1">
                  Start here
                </p>
                {roots.map((root) => (
                  <button
                    key={root.id}
                    type="button"
                    onClick={() => onSelect(root.id)}
                    className={cn(
                      "mb-1 flex w-full items-start gap-2 rounded-md border border-border p-2 text-left transition-colors",
                      selectedId === root.id ? "bg-primary/15" : "hover:bg-muted/50"
                    )}
                  >
                    <Building2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-xs font-semibold">{root.label}</span>
                      <span className="mt-0.5 flex flex-wrap gap-1.5 text-[10.5px] text-ink-muted">
                        <span>{root.catalogs} catalogs</span>
                        <span>{root.jobs} jobs</span>
                        {root.failed_runs > 0 && (
                          <span className="text-red-300">{root.failed_runs} failed runs</span>
                        )}
                      </span>
                    </span>
                  </button>
                ))}
              </>
            )}
          </div>
        </>
      )}

      {tab === "map" && (
        <div className="flex-1 overflow-y-auto p-3">
          <p className="mb-2 text-[11px] leading-relaxed text-ink-muted">
            The grains in the warehouse and the relationships that connect them. Counts are live.
          </p>

          <p className="k-label mb-1 mt-3">
            Kinds
          </p>
          <div className="space-y-0.5">
            {entityMap?.kinds.map((kind) => {
              const style = kindStyle(kind.kind);
              return (
                <div
                  key={kind.kind}
                  className="flex items-center gap-2 rounded px-1.5 py-1"
                  title={kind.grain}
                >
                  <span
                    className="h-2 w-2 shrink-0 rounded-full"
                    style={{ backgroundColor: style.dot }}
                  />
                  <span className="flex-1 truncate text-k-caption">{style.label}</span>
                  <span className="font-mono text-[11px] text-ink-muted">
                    {kind.count.toLocaleString()}
                  </span>
                </div>
              );
            })}
          </div>

          <p className="k-label mb-1 mt-4">
            Relationships
          </p>
          <div className="space-y-1">
            {entityMap?.relations.map((relation, index) => (
              <div
                key={`${relation.name}-${index}`}
                className="rounded border border-border bg-muted/20 px-1.5 py-1"
                title={relation.description}
              >
                <p className="font-mono text-[11px]">
                  <span className="text-ink-muted">{relation.source}</span>
                  <span className="mx-1 text-primary">{relation.name}</span>
                  <span className="text-ink-muted">{relation.target}</span>
                </p>
              </div>
            ))}
          </div>

          {entityMap && (
            <p className="mt-3 flex items-start gap-1 rounded border border-cyan-500/20 bg-cyan-500/5 p-2 text-[10.5px] leading-relaxed text-cyan-200/80">
              <Sparkles className="mt-px h-3 w-3 shrink-0" />
              <span>
                DISCOVERED is open vocabulary — the enrichment agent adds relation types and entity
                kinds that are not in this list.
              </span>
            </p>
          )}
        </div>
      )}
    </aside>
  );
}
