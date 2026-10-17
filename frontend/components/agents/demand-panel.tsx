"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Sparkles } from "lucide-react";

import { Spinner, StatusPill } from "@/components/kairos/ds";

import { getDemand, type DemandItem } from "@/lib/agents";
import { startRun } from "@/lib/enrichment";
import { Empty, TrustBadge, timeAgo } from "./bits";

/** What agents rely on that Kairos has not profiled or verified — where enrichment pays off first. */
export function DemandPanel() {
  const [items, setItems] = useState<DemandItem[] | null>(null);
  const [starting, setStarting] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getDemand(14).then((d) => setItems(d.needs_enrichment)).catch(() => setItems([]));
  }, []);

  const enrichable = (items ?? []).filter((i) => i.kind === "table" || i.kind === "job" || i.kind === "task").slice(0, 15);

  async function enrich() {
    setStarting(true);
    setError(null);
    try {
      const run = await startRun({
        entity_ids: enrichable.map((i) => i.entity_id),
        follow_graph: false,
        include_descendants: false,
        max_entities: enrichable.length,
      });
      setRunId(run.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start enrichment");
    } finally {
      setStarting(false);
    }
  }

  return (
    <section className="kairos-panel overflow-hidden">
      <div className="flex flex-wrap items-center gap-3 border-b border-hairline px-5 py-3.5">
        <div className="min-w-0 flex-1">
          <p className="text-k-title font-semibold text-ink">What agents use that Kairos hasn&apos;t verified</p>
          <p className="text-k-caption text-ink-muted">
            Entities agents asked about or queried in the last 14 days, most used first. Enriching these improves the
            answers agents are already giving.
          </p>
        </div>
        {enrichable.length > 0 && !runId && (
          <button
            onClick={enrich}
            disabled={starting}
            className="k-btn k-btn-primary"
          >
            {starting ? <Spinner className="border-white/30" /> : <Sparkles className="h-3.5 w-3.5" />}
            Enrich these {enrichable.length}
          </button>
        )}
        {runId && (
          <Link href="/enrichment" className="shrink-0 text-k-caption font-semibold text-brand hover:text-brand-strong">
            Enrichment started — watch it live →
          </Link>
        )}
      </div>
      {error && <p className="px-4 py-2 text-k-caption text-danger">{error}</p>}
      {items === null && <Spinner className="m-5" />}
      {items !== null && items.length === 0 && <Empty>Everything agents used recently is verified.</Empty>}
      {(items ?? []).slice(0, 15).map((i) => (
        <div key={i.entity_id} className="k-row flex items-center gap-3 border-b border-hairline px-5 py-2.5 last:border-b-0">
          <span className="flex w-14 shrink-0"><StatusPill tone="neutral" size="sm" dot={false}>{i.kind}</StatusPill></span>
          <span className="min-w-0 flex-1 truncate text-k-body text-ink" title={i.entity_id}>{i.name}</span>
          <TrustBadge level={i.trust_level} />
          <span className="w-36 shrink-0 text-right text-k-caption tabular-nums text-ink-muted">
            {i.calls} use{i.calls === 1 ? "" : "s"}{i.queried_with_sql ? ` · ${i.queried_with_sql} via SQL` : ""}
          </span>
          <span className="w-16 shrink-0 text-right text-k-caption text-ink-subtle">{timeAgo(i.last_used)}</span>
        </div>
      ))}
    </section>
  );
}
