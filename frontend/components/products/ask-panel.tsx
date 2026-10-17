"use client";

/**
 * Ask a data product: pick metrics and dimensions (no tables), run it on the query
 * port, and see the answer with the SQL Kairos compiled and the table it used.
 */

import { useState } from "react";
import { Play, Plus, Wrench, X, Zap } from "lucide-react";

import { Callout, Chip, Spinner, StatusPill } from "@/components/kairos/ds";
import { cn } from "@/lib/utils";
import { queryProduct, tail, type Product, type QueryResult } from "@/lib/products";

const GRAINS = ["", "hour", "day", "week", "month", "quarter", "year"];
const OPS = ["=", "!=", ">", ">=", "<", "<=", "in", "like"];

type Filter = { dimension: string; op: string; value: string };

export function AskPanel({ product }: { product: Product }) {
  const model = product.spec.model;
  const [metrics, setMetrics] = useState<string[]>(model.metrics.slice(0, 1).map((m) => m.name));
  const [by, setBy] = useState<Record<string, string>>({});
  const [filters, setFilters] = useState<Filter[]>([]);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [busy, setBusy] = useState(false);

  const toggle = <T,>(list: T[], v: T) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

  async function run(body: Parameters<typeof queryProduct>[1]) {
    setBusy(true);
    setResult(null);
    try {
      setResult(await queryProduct(product.id, { limit: 50, ...body }));
    } catch (e) {
      setResult({ error: e instanceof Error ? e.message : "The query failed." });
    } finally {
      setBusy(false);
    }
  }

  const byList = Object.entries(by).map(([d, g]) => (g ? `${d}:${g}` : d));
  const filterList = filters
    .filter((f) => f.dimension && f.value !== "")
    .map((f) => ({ dimension: f.dimension, op: f.op, value: f.op === "in" ? f.value.split(",").map((v) => v.trim()) : f.value }));

  const cols = (result?.columns ?? []).map((c) => (typeof c === "string" ? c : c.name));

  return (
    <div className="space-y-4">
      <div>
        <p className="k-label mb-1.5">Metrics</p>
        <div className="flex flex-wrap gap-1.5">
          {model.metrics.map((m) => (
            <Chip key={m.name} on={metrics.includes(m.name)} onClick={() => setMetrics((x) => toggle(x, m.name))}>
              {m.label || m.name}
            </Chip>
          ))}
        </div>
      </div>
      <div>
        <p className="k-label mb-1.5">By</p>
        <div className="flex flex-wrap gap-1.5">
          {model.dimensions.map((d) => {
            const on = d.name in by;
            return (
              <span key={d.name} className="inline-flex items-center">
                <Chip
                  on={on}
                  onClick={() =>
                    setBy((x) => {
                      const next = { ...x };
                      if (on) delete next[d.name];
                      else next[d.name] = d.type === "time" ? "month" : "";
                      return next;
                    })
                  }
                >
                  {d.label || d.name}
                </Chip>
                {on && d.type === "time" && (
                  <select
                    value={by[d.name]}
                    onChange={(e) => setBy((x) => ({ ...x, [d.name]: e.target.value }))}
                    className="k-input ml-1 h-7 w-[92px] px-1.5 text-k-caption"
                  >
                    {GRAINS.map((g) => (
                      <option key={g} value={g}>
                        {g || "as is"}
                      </option>
                    ))}
                  </select>
                )}
              </span>
            );
          })}
        </div>
      </div>
      <div>
        <div className="mb-1.5 flex items-center gap-2">
          <p className="k-label">Filters</p>
          <button
            className="k-btn k-btn-ghost k-btn-sm"
            onClick={() => setFilters((f) => [...f, { dimension: model.dimensions[0]?.name ?? "", op: "=", value: "" }])}
          >
            <Plus className="h-3.5 w-3.5" /> Add
          </button>
        </div>
        <div className="space-y-1.5">
          {filters.map((f, i) => (
            <div key={i} className="flex items-center gap-1.5">
              <select
                value={f.dimension}
                onChange={(e) => setFilters((x) => x.map((y, j) => (j === i ? { ...y, dimension: e.target.value } : y)))}
                className="k-input h-8 w-36 px-2"
              >
                {model.dimensions.map((d) => (
                  <option key={d.name} value={d.name}>
                    {d.label || d.name}
                  </option>
                ))}
              </select>
              <select
                value={f.op}
                onChange={(e) => setFilters((x) => x.map((y, j) => (j === i ? { ...y, op: e.target.value } : y)))}
                className="k-input h-8 w-16 px-1.5"
              >
                {OPS.map((o) => (
                  <option key={o}>{o}</option>
                ))}
              </select>
              <input
                value={f.value}
                onChange={(e) => setFilters((x) => x.map((y, j) => (j === i ? { ...y, value: e.target.value } : y)))}
                placeholder={f.op === "in" ? "a, b, c" : "value"}
                className="k-input h-8 min-w-0 flex-1"
              />
              <button className="k-btn k-btn-ghost k-btn-sm" onClick={() => setFilters((x) => x.filter((_, j) => j !== i))}>
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>
      </div>
      <button
        disabled={busy || !metrics.length}
        onClick={() => run({ metrics, by: byList, filters: filterList })}
        className="k-btn k-btn-primary w-full justify-center"
      >
        {busy ? <Spinner className="border-white/30" /> : <Play className="h-4 w-4" />}
        Ask {product.name}
      </button>
      {model.tools.length > 0 && (
        <div>
          <p className="k-label mb-1.5">Or run a domain tool</p>
          <div className="flex flex-wrap gap-1.5">
            {model.tools.map((t) => (
              <button
                key={t.name}
                title={t.description}
                onClick={() => run({ tool: t.name })}
                disabled={busy}
                className="inline-flex h-7 items-center gap-1.5 rounded-full border border-hairline px-2.5 font-mono text-[11px] text-ink-2 hover:border-brand-border hover:text-brand-strong"
              >
                <Wrench className="h-3 w-3" />
                {t.name}
              </button>
            ))}
          </div>
        </div>
      )}

      {result && (
        <div className="k-rise space-y-2.5 border-t border-hairline pt-4">
          {result.error ? (
            <Callout tone="danger">{result.error}</Callout>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <StatusPill tone={result.source === "shortcut" ? "ok" : "brand"} size="sm">
                  {result.source === "shortcut" ? (
                    <>
                      <Zap className="h-3 w-3" /> pre-aggregated
                    </>
                  ) : (
                    "computed from base"
                  )}
                </StatusPill>
                <span className="font-mono text-[11px] text-ink-muted">{result.table && tail(result.table)}</span>
                <span className="ml-auto text-k-caption text-ink-subtle">
                  {result.row_count} rows · {result.duration_ms} ms
                </span>
              </div>
              <div className="max-h-[300px] overflow-auto rounded-lg border border-hairline">
                <table className="w-full text-k-caption">
                  <thead className="sticky top-0 bg-sunken">
                    <tr>
                      {cols.map((c) => (
                        <th key={c} className="k-label whitespace-nowrap px-3 py-1.5 text-left">
                          {c}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(result.rows ?? []).map((r, i) => (
                      <tr key={i} className="border-t border-hairline">
                        {r.map((v, j) => (
                          <td key={j} className={cn("whitespace-nowrap px-3 py-1.5", typeof v === "number" || /^-?\d+(\.\d+)?$/.test(String(v)) ? "text-right tabular-nums" : "")}>
                            {v === null ? <span className="text-ink-subtle">null</span> : String(v)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {result.notes?.map((n) => (
                <p key={n} className="text-k-caption text-ink-muted">
                  {n}
                </p>
              ))}
              <details>
                <summary className="cursor-pointer text-k-caption font-medium text-brand">SQL Kairos compiled</summary>
                <pre className="mt-1.5 whitespace-pre-wrap break-words rounded-lg bg-[#0F172A] p-3 font-mono text-[11px] leading-relaxed text-[#E2E8F0]">
                  {result.sql}
                </pre>
              </details>
            </>
          )}
        </div>
      )}
    </div>
  );
}
