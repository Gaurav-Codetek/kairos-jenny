"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ChevronRight,
  Columns3,
  Database,
  FolderTree,
  GitBranch,
  Key,
  Search,
  Table2,
} from "lucide-react";

import { EmptyState, Spinner, StatusPill } from "@/components/kairos/ds";
import { PageHeader } from "@/components/shell/app-shell";
import { fetchApi } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Catalog {
  id: string;
  entity_id: string;
  name: string;
  comment: string | null;
  owner: string | null;
}
interface Schema {
  id: string;
  entity_id: string;
  name: string;
  full_name: string;
  comment: string | null;
}
interface Column {
  name: string;
  data_type: string;
  is_nullable: boolean;
  is_partition_column: boolean;
  comment: string | null;
  ordinal_position: number;
}
interface Table {
  id: string;
  entity_id: string;
  name: string;
  full_name: string;
  table_type: string;
  data_source_format: string | null;
  owner: string | null;
  comment: string | null;
  row_count: number | null;
  columns?: Column[];
}

/** A drill-down column in the browser: catalogs → schemas → tables. */
function Pane({
  title,
  count,
  children,
  width,
}: {
  title: string;
  count?: number;
  children: React.ReactNode;
  width: string;
}) {
  return (
    <div className={cn("flex min-h-0 shrink-0 flex-col border-r border-hairline", width)}>
      <div className="flex h-11 items-center gap-2 border-b border-hairline px-4">
        <span className="text-k-caption font-semibold text-ink-2">{title}</span>
        {count !== undefined && (
          <span className="rounded-full bg-neutral-soft px-1.5 text-[11px] font-semibold tabular-nums text-ink-muted">
            {count}
          </span>
        )}
      </div>
      <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto p-2">{children}</div>
    </div>
  );
}

function Row({
  active,
  onClick,
  icon: Icon,
  label,
  detail,
  tint,
}: {
  active: boolean;
  onClick: () => void;
  icon: typeof Database;
  label: string;
  detail?: string;
  tint: string;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors duration-200",
        active ? "bg-brand-soft" : "hover:bg-sunken"
      )}
    >
      <Icon className="h-4 w-4 shrink-0" style={{ color: active ? "var(--brand)" : tint }} />
      <span className="min-w-0 flex-1">
        <span className={cn("block truncate text-k-body", active ? "font-semibold text-brand-strong" : "text-ink")}>{label}</span>
        {detail && <span className="block truncate text-k-caption text-ink-subtle">{detail}</span>}
      </span>
      <ChevronRight
        className={cn("h-3.5 w-3.5 shrink-0 transition-opacity", active ? "text-brand opacity-100" : "opacity-0")}
      />
    </button>
  );
}

export default function CatalogPage() {
  const [catalogs, setCatalogs] = useState<Catalog[]>([]);
  const [schemas, setSchemas] = useState<Schema[]>([]);
  const [tables, setTables] = useState<Table[]>([]);
  const [detail, setDetail] = useState<Table | null>(null);

  const [catalogId, setCatalogId] = useState<string | null>(null);
  const [schemaId, setSchemaId] = useState<string | null>(null);
  const [tableId, setTableId] = useState<string | null>(null);

  const [loading, setLoading] = useState<string | null>("catalogs");
  const [filter, setFilter] = useState("");

  useEffect(() => {
    fetchApi("/catalog/catalogs")
      .then((c: Catalog[]) => setCatalogs(c))
      .catch(() => undefined)
      .finally(() => setLoading(null));
  }, []);

  useEffect(() => {
    if (!catalogId) return;
    setLoading("schemas");
    setSchemas([]);
    setTables([]);
    setDetail(null);
    setSchemaId(null);
    setTableId(null);
    fetchApi(`/catalog/catalogs/${catalogId}/schemas`)
      .then(setSchemas)
      .catch(() => undefined)
      .finally(() => setLoading(null));
  }, [catalogId]);

  useEffect(() => {
    if (!schemaId) return;
    setLoading("tables");
    setTables([]);
    setDetail(null);
    setTableId(null);
    fetchApi(`/catalog/schemas/${schemaId}/tables`)
      .then(setTables)
      .catch(() => undefined)
      .finally(() => setLoading(null));
  }, [schemaId]);

  useEffect(() => {
    if (!tableId) return;
    setLoading("detail");
    fetchApi(`/catalog/tables/${tableId}`)
      .then(setDetail)
      .catch(() => undefined)
      .finally(() => setLoading(null));
  }, [tableId]);

  const visibleTables = filter.trim()
    ? tables.filter((t) => t.name.toLowerCase().includes(filter.trim().toLowerCase()))
    : tables;

  return (
    <>
      <PageHeader
        title="Catalog"
        description="Structural metadata mirrored from the connected platform"
      />

      <div className="flex min-h-0 flex-1 bg-surface">
        <Pane title="Catalogs" count={catalogs.length} width="w-[220px]">
          {loading === "catalogs" && (
            <div className="flex justify-center py-6">
              <Spinner />
            </div>
          )}
          {catalogs.map((c) => (
            <Row
              key={c.id}
              active={catalogId === c.id}
              onClick={() => setCatalogId(c.id)}
              icon={Database}
              label={c.name}
              detail={c.owner ?? undefined}
              tint="var(--k-container-fg)"
            />
          ))}
          {!loading && catalogs.length === 0 && (
            <p className="px-3 py-6 text-center text-k-caption text-ink-subtle">
              Nothing synced yet.{" "}
              <Link href="/connections" className="text-brand hover:underline">
                Run a sync
              </Link>
            </p>
          )}
        </Pane>

        <Pane title="Schemas" count={schemas.length} width="w-[220px]">
          {loading === "schemas" && (
            <div className="flex justify-center py-6">
              <Spinner />
            </div>
          )}
          {schemas.map((s) => (
            <Row
              key={s.id}
              active={schemaId === s.id}
              onClick={() => setSchemaId(s.id)}
              icon={FolderTree}
              label={s.name}
              tint="var(--k-container-fg)"
            />
          ))}
          {!loading && catalogId && schemas.length === 0 && (
            <p className="px-3 py-6 text-center text-k-caption text-ink-subtle">No schemas.</p>
          )}
        </Pane>

        <Pane title="Tables" count={tables.length} width="w-[260px]">
          {tables.length > 6 && (
            <div className="relative mb-1.5">
              <Search className="absolute left-2.5 top-[9px] h-3.5 w-3.5 text-ink-subtle" />
              <input
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Filter tables"
                className="k-input !h-8 !pl-8 !text-k-caption"
              />
            </div>
          )}
          {loading === "tables" && (
            <div className="flex justify-center py-6">
              <Spinner />
            </div>
          )}
          {visibleTables.map((t) => (
            <Row
              key={t.id}
              active={tableId === t.id}
              onClick={() => setTableId(t.id)}
              icon={Table2}
              label={t.name}
              detail={t.table_type}
              tint="var(--k-table-fg)"
            />
          ))}
          {!loading && schemaId && tables.length === 0 && (
            <p className="px-3 py-6 text-center text-k-caption text-ink-subtle">No tables.</p>
          )}
        </Pane>

        {/* Table detail */}
        <div className="min-w-0 flex-1 overflow-y-auto bg-sunken">
          {!detail && (
            <div className="flex h-full items-center justify-center">
              <EmptyState icon={Table2} title="Select a table">
                Drill down from a catalog to a schema to a table to see its columns.
              </EmptyState>
            </div>
          )}

          {detail && (
            <div key={detail.id} className="k-rise p-6">
              <div className="flex items-start gap-3.5">
                <span className="flex h-11 w-11 items-center justify-center rounded-full bg-brand-soft text-brand">
                  <Table2 className="h-5 w-5" />
                </span>
                <div className="min-w-0 flex-1">
                  <h2 className="font-mono text-[18px] font-bold text-ink">{detail.name}</h2>
                  <p className="truncate font-mono text-k-caption text-ink-muted">
                    {detail.full_name}
                  </p>
                </div>
                <Link
                  href="/graph"
                  className="k-btn"
                >
                  <GitBranch className="h-4 w-4" />
                  Lineage
                </Link>
              </div>

              {detail.comment && (
                <p className="mt-4 rounded-lg border border-hairline bg-surface px-4 py-3 text-k-body leading-relaxed text-ink-2">
                  {detail.comment}
                </p>
              )}

              <dl className="mt-4 grid grid-cols-4 gap-3">
                {[
                  ["Type", detail.table_type],
                  ["Format", detail.data_source_format ?? "—"],
                  ["Owner", detail.owner ?? "—"],
                  ["Rows", detail.row_count?.toLocaleString() ?? "—"],
                ].map(([k, v]) => (
                  <div key={k} className="kairos-panel px-4 py-3">
                    <dt className="text-k-caption font-medium text-ink-muted">{k}</dt>
                    <dd className="mt-0.5 truncate text-k-title font-semibold text-ink">{v}</dd>
                  </div>
                ))}
              </dl>

              <section className="kairos-panel mt-4 overflow-hidden">
                <div className="flex min-h-[48px] items-center gap-2.5 border-b border-hairline px-4">
                  <Columns3 className="h-4 w-4 text-ink-subtle" />
                  <h3 className="text-k-title font-semibold text-ink">Columns</h3>
                  <span className="rounded-full bg-neutral-soft px-1.5 text-[11px] font-semibold tabular-nums text-ink-muted">
                    {detail.columns?.length ?? 0}
                  </span>
                </div>
                <table className="w-full">
                  <thead>
                    <tr>
                      <th className="kairos-th w-8">#</th>
                      <th className="kairos-th">Name</th>
                      <th className="kairos-th">Type</th>
                      <th className="kairos-th">Nullable</th>
                      <th className="kairos-th">Comment</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(detail.columns ?? []).map((c) => (
                      <tr key={c.name} className="k-row">
                        <td className="kairos-td tabular-nums text-ink-subtle">
                          {c.ordinal_position}
                        </td>
                        <td className="kairos-td">
                          <span className="flex items-center gap-1.5">
                            <span className="font-mono font-medium text-ink">{c.name}</span>
                            {c.is_partition_column && (
                              <StatusPill tone="brand" size="sm" dot={false} title="Partition column">
                                <Key className="h-3 w-3" /> partition
                              </StatusPill>
                            )}
                          </span>
                        </td>
                        <td className="kairos-td font-mono text-k-caption text-ink-muted">
                          {c.data_type}
                        </td>
                        <td className="kairos-td">
                          {c.is_nullable ? <span className="text-ink-muted">yes</span> : <StatusPill tone="neutral" size="sm" dot={false}>not null</StatusPill>}
                        </td>
                        <td className="kairos-td max-w-[280px] truncate text-ink-muted">
                          {c.comment ?? "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {(detail.columns ?? []).length === 0 && (
                  <p className="px-4 py-8 text-center text-k-body text-ink-muted">
                    No columns recorded.
                  </p>
                )}
              </section>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
