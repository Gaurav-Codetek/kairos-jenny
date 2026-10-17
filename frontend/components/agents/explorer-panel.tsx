"use client";

import { useEffect, useRef, useState } from "react";
import { AlertTriangle, ArrowRight, Flag, Loader2, Search } from "lucide-react";

import {
  getContextCard,
  postFeedback,
  searchContext,
  type ContextCard,
  type FlowEntry,
  type SearchResult,
} from "@/lib/agents";
import { Callout, Chip, Spinner, StatusPill } from "@/components/kairos/ds";
import { cn } from "@/lib/utils";
import { CodeBlock, Empty, TrustBadge } from "./bits";

const EXAMPLES = [
  "ICS sales at invoice line level",
  "account level sales for BI",
  "where are pipeline load statuses logged",
  "healthcare organisation master data",
];

function FlowList({ title, items, onOpen }: { title: string; items?: FlowEntry[]; onOpen: (id: string) => void }) {
  if (!items || items.length === 0) return null;
  return (
    <div>
      <p className="k-label">{title}</p>
      <ul className="mt-1 space-y-1">
        {items.map((e) => (
          <li key={e.entity_id + title} className="flex items-baseline gap-2 text-k-caption">
            <button onClick={() => onOpen(e.entity_id)} className="truncate text-left text-ink hover:underline" title={e.entity_id}>
              {e.name}
            </button>
            <span className="shrink-0 truncate text-k-caption text-ink-subtle" title={e.evidence}>
              {e.evidence.startsWith("/") ? "pipeline code" : e.evidence}
              {e.status && e.status !== "verified" ? ` · ${e.status}` : ""}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ReportIssue({ entityId }: { entityId: string }) {
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState("incorrect");
  const [message, setMessage] = useState("");
  const [sent, setSent] = useState(false);
  if (sent) return <p className="text-k-caption font-medium text-ok">Reported — every agent sees it now, and the next enrichment pass will check it.</p>;
  if (!open)
    return (
      <button onClick={() => setOpen(true)} className="inline-flex items-center gap-1 text-k-caption text-ink-muted hover:text-ink">
        <Flag className="h-3.5 w-3.5" /> Report something wrong or missing
      </button>
    );
  return (
    <div className="flex flex-wrap items-center gap-2">
      <select value={kind} onChange={(e) => setKind(e.target.value)} className="k-input !h-8 !w-auto !px-2 !text-k-caption">
        {["incorrect", "missing", "stale", "confusing"].map((k) => (
          <option key={k}>{k}</option>
        ))}
      </select>
      <input
        value={message}
        onChange={(e) => setMessage(e.target.value)}
        placeholder="What is wrong, specifically?"
        className="k-input !h-8 min-w-[240px] flex-1 !text-k-caption"
      />
      <button
        disabled={!message.trim()}
        onClick={async () => {
          await postFeedback({ entity_id: entityId, kind, message: message.trim() });
          setSent(true);
        }}
        className="k-btn k-btn-primary k-btn-sm"
      >
        Send
      </button>
    </div>
  );
}

function Card({ card, onOpen }: { card: ContextCard; onOpen: (id: string) => void }) {
  const passing = (r: string) => ["ok", "holds", "corrected", "repaired", "skipped"].includes(r);
  return (
    <div className="space-y-4">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <StatusPill tone="neutral" size="sm" dot={false}>{card.kind}</StatusPill>
          <h3 className="font-mono text-[17px] font-semibold text-ink">{card.full_name || card.name}</h3>
          <TrustBadge level={card.trust.level} />
          {card.trust.stale && <StatusPill tone="warn" size="sm">re-profile due</StatusPill>}
        </div>
        {card.data_product && <p className="mt-0.5 text-k-caption text-ink-subtle">{card.data_product}</p>}
        {card.summary && <p className="mt-2 text-k-body leading-relaxed text-ink">{card.summary}</p>}
        {card.purpose && <p className="mt-1 text-k-caption leading-relaxed text-ink-muted">{card.purpose}</p>}
      </div>

      <div className="flex flex-wrap gap-1.5">
        {card.trust.checks.map((c) => (
          <StatusPill key={c.check} title={c.detail ?? ""} size="sm" tone={passing(c.result) ? "ok" : "danger"}>
            {c.check.replace("_", " ")}: {c.result}
          </StatusPill>
        ))}
        {card.trust.classification && (
          <StatusPill tone="brand" size="sm" dot={false}>
            {card.trust.classification.role.toLowerCase()} · {card.trust.classification.layer.toLowerCase()}
          </StatusPill>
        )}
      </div>

      {card.caveats.length > 0 && (
        <Callout tone="warn" icon={AlertTriangle}>
          <p className="font-semibold">Before relying on this</p>
          <ul className="mt-1 space-y-0.5 text-k-caption text-ink-2">
            {card.caveats.map((c) => (
              <li key={c}>· {c}</li>
            ))}
          </ul>
        </Callout>
      )}

      {card.shape && (
        <div>
          <p className="k-label">Grain</p>
          <p className="text-k-body text-ink">{card.shape.grain || "Not stated"}</p>
          {card.shape.grain_key.length > 0 && (
            <p className="mt-0.5 text-k-caption text-ink-muted">
              Key: <code className="font-mono">{card.shape.grain_key.join(" + ")}</code>{" "}
              {card.shape.grain_key_unique === true && <span className="text-ok">· verified unique</span>}
              {card.shape.grain_key_unique === false && <span className="text-danger">· not unique</span>}
            </p>
          )}
        </div>
      )}

      {card.flow && (
        <div className="grid gap-3 md:grid-cols-2">
          <FlowList title="Produced by" items={card.flow.produced_by} onOpen={onOpen} />
          <FlowList title="Read by" items={card.flow.read_by} onOpen={onOpen} />
          <FlowList title="Upstream tables" items={card.flow.upstream_tables} onOpen={onOpen} />
          <FlowList title="Downstream tables" items={card.flow.downstream_tables} onOpen={onOpen} />
          <FlowList title="Reads" items={card.flow.reads} onOpen={onOpen} />
          <FlowList title="Writes" items={card.flow.writes} onOpen={onOpen} />
        </div>
      )}

      {card.tasks && card.tasks.length > 0 && (
        <div>
          <p className="k-label">Tasks</p>
          <ul className="mt-1 space-y-1">
            {card.tasks.map((t) => (
              <li key={t.entity_id} className="text-k-caption">
                <button onClick={() => onOpen(t.entity_id)} className="font-medium text-ink hover:underline">{t.task_key}</button>
                {t.summary && <span className="text-ink-muted"> — {t.summary.slice(0, 160)}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {card.usage?.example_sql && (
        <div>
          <p className="k-label mb-1">Example query</p>
          <CodeBlock code={card.usage.example_sql} />
        </div>
      )}

      {card.usage && card.usage.join_candidates.length > 0 && (
        <div>
          <p className="k-label">Joins to</p>
          <ul className="mt-1 space-y-1">
            {card.usage.join_candidates.map((j) => (
              <li key={j.entity_id} className="flex items-baseline gap-2 text-k-caption">
                <button onClick={() => onOpen(j.entity_id)} className="truncate text-ink hover:underline">{j.name}</button>
                <span className="shrink-0 text-k-caption text-ink-subtle">on {j.on.join(", ")} · {j.evidence}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {card.shape && card.shape.columns.length > 0 && (
        <div>
          <p className="k-label">
            Columns ({card.shape.column_count}){card.shape.columns_truncated ? ` · first ${card.shape.columns.length} shown` : ""}
          </p>
          <div className="mt-1.5 max-h-72 overflow-y-auto rounded-lg border border-hairline">
            <table className="w-full text-k-caption">
              <tbody>
                {card.shape.columns.map((c) => (
                  <tr key={c.name} className="border-b border-hairline last:border-b-0">
                    <td className="whitespace-nowrap px-2.5 py-1.5 font-mono text-k-caption text-ink">{c.name}</td>
                    <td className="whitespace-nowrap px-2 py-1.5 text-k-caption text-ink-subtle">{c.type}</td>
                    <td className="px-2 py-1.5 text-ink-muted">
                      {c.meaning || <span className="text-ink-subtle">—</span>}
                      {String(c.tags || "").includes("pii") && (
                        <StatusPill tone="danger" size="sm" className="ml-1.5">PII</StatusPill>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <ReportIssue entityId={card.entity_id} />
    </div>
  );
}

export function ExplorerPanel({ initialQuery = "" }: { initialQuery?: string }) {
  const [q, setQ] = useState(initialQuery);
  const [result, setResult] = useState<SearchResult | null>(null);
  const [card, setCard] = useState<ContextCard | null>(null);
  const [loading, setLoading] = useState<"search" | "card" | null>(null);

  async function run(question: string) {
    if (!question.trim()) return;
    setQ(question);
    setLoading("search");
    setCard(null);
    try {
      const r = await searchContext(question, 10);
      setResult(r);
      if (r.results[0]) await open(r.results[0].entity_id);
    } finally {
      setLoading(null);
    }
  }

  // Run a search handed in by a link, once.
  const ran = useRef(false);
  useEffect(() => {
    if (initialQuery && !ran.current) {
      ran.current = true;
      void run(initialQuery);
    }
  });

  async function open(entityId: string) {
    setLoading("card");
    try {
      setCard(await getContextCard(entityId));
    } finally {
      setLoading(null);
    }
  }

  return (
    <div className="space-y-4">
      <section className="kairos-panel p-5">
        <p className="text-k-body text-ink-muted">
          Ask the way an agent would. This is exactly what <code className="font-mono">find_data</code> and{" "}
          <code className="font-mono">get_context</code> return to any connected agent.
        </p>
        <form
          className="mt-3 flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            run(q);
          }}
        >
          <div className="relative flex-1">
            <Search className="absolute left-3 top-[9px] h-4 w-4 text-ink-subtle" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="e.g. monthly sales by account, or a table name"
              className="k-input !pl-9"
            />
          </div>
          <button type="submit" className="k-btn k-btn-primary min-w-[84px]">
            {loading === "search" ? <Loader2 className="h-4 w-4 animate-spin" /> : "Search"}
          </button>
        </form>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {EXAMPLES.map((ex) => (
            <Chip key={ex} onClick={() => run(ex)}>
              {ex}
            </Chip>
          ))}
        </div>
      </section>

      {result && (
        <div className="grid gap-4 lg:grid-cols-[340px_minmax(0,1fr)]">
          <section className="kairos-panel overflow-hidden">
            <p className="border-b border-hairline px-4 py-2.5 text-k-caption text-ink-muted">
              {result.results.length} result(s) · retrievers:{" "}
              {Object.entries(result.retrievers).map(([k, v]) => `${k} ${v}`).join(" · ")}
            </p>
            {result.note && <p className="px-4 py-2 text-k-caption text-warn">{result.note}</p>}
            {result.results.length === 0 && <Empty>Nothing matched.</Empty>}
            {result.results.map((h) => (
              <button
                key={h.entity_id}
                onClick={() => open(h.entity_id)}
                className={cn(
                  "relative block w-full border-b border-hairline px-4 py-3 text-left transition-colors duration-200 last:border-b-0 hover:bg-sunken",
                  card?.entity_id === h.entity_id && "bg-brand-soft/60 shadow-[inset_3px_0_0_var(--brand)] hover:bg-brand-soft/60"
                )}
              >
                <div className="flex items-center gap-2">
                  <StatusPill tone="neutral" size="sm" dot={false}>{h.kind}</StatusPill>
                  <span className="min-w-0 flex-1 truncate text-k-body font-medium text-ink">{h.name.split(".").pop()}</span>
                  <TrustBadge level={h.trust_level} />
                </div>
                <p className="mt-0.5 line-clamp-2 text-k-caption text-ink-muted">{h.what_it_is}</p>
                <p className="mt-0.5 text-[11px] text-ink-subtle">matched by {h.matched_by.join(" + ")}</p>
              </button>
            ))}
          </section>
          <section className="kairos-panel min-w-0 p-5">
            {loading === "card" && <Spinner />}
            {!card && loading !== "card" && (
              <p className="flex items-center gap-1 text-k-body text-ink-subtle">
                <ArrowRight className="h-3.5 w-3.5" /> Pick a result to see its full context.
              </p>
            )}
            {card && loading !== "card" && (
              <div key={card.entity_id} className="k-rise">
                <Card card={card} onOpen={open} />
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
