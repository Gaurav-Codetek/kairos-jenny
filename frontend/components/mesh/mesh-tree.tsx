"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronRight, Search, X } from "lucide-react";

import { kindVisual } from "@/components/graph/lineage-card";
import { ACCENT } from "@/components/mesh/bundle-card";
import type { Bundle, MeshIndex } from "@/lib/mesh";
import { cn } from "@/lib/utils";

interface MeshTreeProps {
  index: MeshIndex;
  /** Bundles with lineage, plus every ancestor of one. */
  withLineage: Set<string>;
  selected: string | null;
  /** A bundle whose children should be shown open in the tree. */
  browse?: string | null;
  onPick: (uid: string) => void;
}

/**
 * The inventory beside the canvas (Dagster's asset sidebar, dbt's file tree):
 * every bundle is findable here, so the canvas only has to show lineage.
 */
export function MeshTree({ index, withLineage, selected, browse, onPick }: MeshTreeProps) {
  const [query, setQuery] = useState("");
  const [lineageOnly, setLineageOnly] = useState(false);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const list = useRef<HTMLDivElement>(null);

  // Reveal a bundle in the tree when it changes: open its ancestors (and
  // itself, when browsing). Adjusting state on a prop change, during render.
  const target = browse ?? selected;
  const [revealed, setRevealed] = useState<string | null>(null);
  if (target && target !== revealed) {
    setRevealed(target);
    setOpen((current) => {
      const next = new Set(current);
      index.ancestors(target).forEach((a) => next.add(a));
      if (browse) next.add(browse);
      return next;
    });
  }
  useEffect(() => {
    if (!target) return;
    const h = window.setTimeout(() => {
      list.current?.querySelector(`[data-uid="${CSS.escape(target)}"]`)?.scrollIntoView({ block: "nearest" });
    }, 50);
    return () => window.clearTimeout(h);
  }, [target]);

  const roots = useMemo(() => {
    const all = index.roots().map((id) => index.byId.get(id)!);
    const byName = (a: Bundle, b: Bundle) => a.name.localeCompare(b.name);
    return {
      data: all.filter((b) => !["pipeline", "task", "product"].includes(b.resource_type)).sort(byName),
      pipelines: all.filter((b) => b.resource_type === "pipeline").sort(byName),
      products: all.filter((b) => b.resource_type === "product").sort(byName),
    };
  }, [index]);

  const results = useMemo(() => index.search(query, 60), [index, query]);

  const toggle = (uid: string) =>
    setOpen((s) => {
      const next = new Set(s);
      if (next.has(uid)) next.delete(uid);
      else next.add(uid);
      return next;
    });

  const renderRow = (b: Bundle, depth: number): React.ReactNode => {
    if (lineageOnly && !withLineage.has(b.unique_id)) return null;
    const kids = (index.childrenOf.get(b.unique_id) ?? [])
      .map((id) => index.byId.get(id)!)
      .sort((a, c) => a.resource_type.localeCompare(c.resource_type) || a.name.localeCompare(c.name));
    const isOpen = open.has(b.unique_id);
    return (
      <div key={b.unique_id}>
        <Row
          bundle={b}
          depth={depth}
          hasChildren={kids.length > 0}
          open={isOpen}
          active={selected === b.unique_id}
          lineage={withLineage.has(b.unique_id)}
          onToggle={() => toggle(b.unique_id)}
          onPick={() => onPick(b.unique_id)}
        />
        {isOpen && kids.map((k) => renderRow(k, depth + 1))}
      </div>
    );
  };

  return (
    <aside className="flex h-full w-[272px] shrink-0 flex-col border-r border-hairline bg-surface">
      <div className="space-y-2.5 border-b border-hairline p-3">
        <div className="relative">
          <Search className="absolute left-3 top-[9px] h-4 w-4 text-ink-subtle" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Find a bundle…"
            className="k-input !pl-9 !pr-8"
          />
          {query && (
            <button onClick={() => setQuery("")} className="absolute right-2.5 top-[9px] text-ink-subtle hover:text-ink">
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
        {!query && (
          <label className="flex cursor-pointer items-center gap-2 text-k-caption text-ink-muted">
            <input
              type="checkbox"
              checked={lineageOnly}
              onChange={(e) => setLineageOnly(e.target.checked)}
              className="h-3.5 w-3.5 accent-[var(--brand)]"
            />
            Only bundles with lineage
          </label>
        )}
      </div>

      <div ref={list} className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
        {query ? (
          results.length ? (
            results.map((b) => (
              <Row
                key={b.unique_id}
                bundle={b}
                depth={0}
                hasChildren={false}
                open={false}
                active={selected === b.unique_id}
                lineage={withLineage.has(b.unique_id)}
                path={b.fqn.slice(0, -1).join(" / ")}
                onToggle={() => undefined}
                onPick={() => {
                  onPick(b.unique_id);
                  setQuery("");
                }}
              />
            ))
          ) : (
            <p className="px-4 py-6 text-center text-k-caption text-ink-subtle">No bundle matches “{query}”.</p>
          )
        ) : (
          <>
            <Section title="Data" count={roots.data.length}>{roots.data.map((b) => renderRow(b, 0))}</Section>
            {roots.products.length > 0 && (
              <Section title="Data products" count={roots.products.length}>{roots.products.map((b) => renderRow(b, 0))}</Section>
            )}
            <Section title="Pipelines" count={roots.pipelines.length}>{roots.pipelines.map((b) => renderRow(b, 0))}</Section>
          </>
        )}
      </div>
    </aside>
  );
}

function Section({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  return (
    <div className="mb-2">
      <p className="k-label flex items-center gap-1.5 px-2 pb-1.5 pt-2">
        {title} <span className="rounded-full bg-neutral-soft px-1.5 font-semibold normal-case tracking-normal text-ink-muted">{count}</span>
      </p>
      {children}
    </div>
  );
}

function Row(props: {
  bundle: Bundle;
  depth: number;
  hasChildren: boolean;
  open: boolean;
  active: boolean;
  lineage: boolean;
  path?: string;
  onToggle: () => void;
  onPick: () => void;
}) {
  const { bundle: b, depth } = props;
  const Icon = kindVisual(b.resource_type).icon;
  const count = Object.values(b.children).reduce((a, n) => a + (n ?? 0), 0);
  return (
    <button
      data-uid={b.unique_id}
      onClick={props.onPick}
      className={cn(
        "group flex w-full items-center gap-1.5 rounded-lg py-[6px] pr-2.5 text-left transition-colors duration-200",
        props.active ? "bg-brand-soft" : "hover:bg-sunken"
      )}
      style={{ paddingLeft: 6 + depth * 14 }}
      title={b.fqn.join(".")}
    >
      <span
        onClick={(e) => {
          e.stopPropagation();
          if (props.hasChildren) props.onToggle();
        }}
        className={cn("flex h-4 w-4 shrink-0 items-center justify-center rounded text-ink-subtle", props.hasChildren && "hover:bg-hairline")}
      >
        {props.hasChildren && <ChevronRight className={cn("h-3 w-3 transition-transform", props.open && "rotate-90")} />}
      </span>
      <Icon className="h-3.5 w-3.5 shrink-0" style={{ color: ACCENT[b.resource_type] }} strokeWidth={2} />
      <span className="min-w-0 flex-1">
        <span className={cn("block truncate text-k-body", props.active ? "font-semibold text-brand-strong" : "text-ink")}>
          {b.name}
        </span>
        {props.path && <span className="block truncate text-[11px] text-ink-subtle">{props.path}</span>}
      </span>
      {props.lineage && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-brand" title="Has lineage" />}
      {count > 0 && <span className="shrink-0 text-[11px] tabular-nums text-ink-subtle">{count}</span>}
    </button>
  );
}
