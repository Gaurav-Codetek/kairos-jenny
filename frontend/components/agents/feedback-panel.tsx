"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";

import {
  approveReport,
  buildFromReport,
  listFeedback,
  rejectReport,
  rollBackReport,
  updateFeedback,
  workOnReport,
  type FeedbackItem,
  type LoopStage,
} from "@/lib/agents";
import { Segmented, Spinner, StatusPill, type Tone } from "@/components/kairos/ds";
import { Empty, timeAgo } from "./bits";

// Where a report stands. Reports about a data product move through the report loop (triage → proposal → checks →
// proof); reports about a table or column are folded into its next enrichment pass.
const FILTERS = [
  { id: "you", label: "Needs you" },
  { id: "working", label: "In progress" },
  { id: "done", label: "Done" },
  { id: "dismissed", label: "Dismissed" },
] as const;
type Filter = (typeof FILTERS)[number]["id"];

const STAGE: Record<LoopStage, { label: string; tone: Tone }> = {
  new: { label: "New", tone: "neutral" },
  triaged: { label: "Working on it", tone: "brand" },
  proposed: { label: "Needs approval", tone: "warn" },
  verified: { label: "Live and checked", tone: "ok" },
  needs_person: { label: "Needs a person", tone: "warn" },
  building: { label: "Building", tone: "brand" },
  merged: { label: "Merged", tone: "neutral" },
  dismissed: { label: "Dismissed", tone: "neutral" },
  rolled_back: { label: "Rolled back", tone: "neutral" },
};

const CATEGORY: Record<string, string> = {
  product_change: "product change",
  data_issue: "data problem",
  description: "description",
  new_product: "new product",
  not_actionable: "not actionable",
};

function filterOf(f: FeedbackItem): Filter {
  const stage = f.loop?.stage;
  if (f.status === "dismissed") return "dismissed";
  if (f.status === "applied") return "done";
  if (stage === "proposed" || stage === "needs_person") return "you";
  if (stage === "building") return "working";
  return f.loop ? "working" : "you"; // a table or column report waits for its next enrichment pass, shown with yours
}

export function FeedbackPanel() {
  const [filter, setFilter] = useState<Filter>("you");
  const [items, setItems] = useState<FeedbackItem[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    listFeedback()
      .then((r) => setItems(r.feedback))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    reload();
    const t = window.setInterval(reload, 15000); // the loop works in the background
    return () => window.clearInterval(t);
  }, [reload]);

  const counts = useMemo(() => {
    const c: Record<Filter, number> = { you: 0, working: 0, done: 0, dismissed: 0 };
    items.forEach((f) => (c[filterOf(f)] += 1));
    return c;
  }, [items]);
  const shown = items.filter((f) => filterOf(f) === filter);

  const act = async (id: string, fn: (id: string) => Promise<unknown>) => {
    setBusy(id);
    setError(null);
    try {
      await fn(id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "That didn't work. Try again.");
    } finally {
      setBusy(null);
      reload();
    }
  };

  return (
    <section className="kairos-panel overflow-hidden">
      <div className="flex flex-wrap items-center gap-3 border-b border-hairline px-5 py-3.5">
        <div className="min-w-0 flex-1">
          <h3 className="text-k-title font-semibold text-ink">What agents report</h3>
          <p className="text-k-caption text-ink-muted">
            When an agent can&apos;t get something from a data product, Kairos works out what would fix it. Additions that
            answer the report and hold up against the warehouse go live by themselves and are checked against live data;
            anything else waits here for you.
          </p>
        </div>
        <Segmented
          items={FILTERS.map((f) => ({ id: f.id, label: counts[f.id] ? `${f.label} · ${counts[f.id]}` : f.label }))}
          value={filter}
          onChange={setFilter}
        />
      </div>
      {error && <p className="border-b border-hairline px-5 py-2 text-k-caption text-danger">{error}</p>}
      {shown.length === 0 && <Empty>Nothing here.</Empty>}
      {shown.map((f) => (
        <Report key={f.id} f={f} busy={busy === f.id} act={act} />
      ))}
    </section>
  );
}

function Report({
  f,
  busy,
  act,
}: {
  f: FeedbackItem;
  busy: boolean;
  act: (id: string, fn: (id: string) => Promise<unknown>) => void;
}) {
  const loop = f.loop;
  const stage = loop?.stage ? STAGE[loop.stage] : null;
  const last = loop?.history?.[loop.history.length - 1];
  const adds = loop?.proposal?.adds ?? [];
  const checks = (loop?.checks ?? []).filter((c) => !c.replay);
  const replays = (loop?.checks ?? []).filter((c) => c.replay);
  return (
    <div className="k-row flex items-start gap-3 border-b border-hairline px-5 py-4 last:border-b-0">
      <div className="flex w-32 shrink-0 flex-col gap-1.5">
        {stage ? (
          <StatusPill tone={stage.tone} size="sm">
            {stage.label}
          </StatusPill>
        ) : (
          <StatusPill tone={f.kind === "incorrect" ? "danger" : f.kind === "stale" ? "warn" : "neutral"} size="sm">
            {f.kind}
          </StatusPill>
        )}
        {loop?.category && <span className="text-k-caption text-ink-subtle">{CATEGORY[loop.category]}</span>}
      </div>
      <div className="min-w-0 flex-1 space-y-1.5">
        <p className="text-k-body text-ink">{f.message}</p>
        <p className="truncate text-k-caption text-ink-subtle" title={f.entity_id}>
          {f.name}
          {f.field ? ` · ${f.field}` : ""} · {f.reporter} · {timeAgo(f.created_at)}
          {loop?.also_reported ? ` · reported ${loop.also_reported + 1} times` : ""}
        </p>
        {loop?.question && <p className="text-k-caption text-ink-muted">Asked: “{loop.question}”</p>}
        {!loop && f.suggestion && <p className="text-k-caption text-ink-muted">Suggested: {f.suggestion}</p>}

        {adds.length > 0 && (
          <div className="rounded-lg border border-hairline bg-muted px-3 py-2">
            <p className="text-k-caption font-medium text-ink">
              {loop?.stage === "verified" ? "Added to the product" : "Proposed addition"}
              {loop?.proposal?.answers != null && loop.proposal.answers < 0.6 ? " · only partly what was asked" : ""}
            </p>
            {adds.map((a) => (
              <p key={a.name} className="mt-1 break-words font-mono text-k-caption text-ink-muted">
                <span className="text-ink">
                  + {a.kind} {a.name}
                </span>{" "}
                = {a.definition}
              </p>
            ))}
            {loop?.proposal?.reason && <p className="mt-1.5 text-k-caption text-ink-muted">{loop.proposal.reason}</p>}
            {(loop?.proposal?.dropped ?? []).length > 0 && (
              <p className="mt-1 text-k-caption text-ink-subtle">
                Left out: {(loop?.proposal?.dropped ?? []).map((d) => `${d.item} (${d.reason.split(":")[0]})`).join("; ")}
              </p>
            )}
          </div>
        )}

        {checks.length > 0 && (
          <div className="space-y-0.5">
            {checks.map((c) => (
              <p key={c.what} className={`text-k-caption ${c.ok ? "text-ok" : "text-danger"}`}>
                {c.ok ? "✓" : "✗"} {c.what}
                {c.ok && c.sample?.length ? (
                  <span className="text-ink-subtle"> · e.g. {c.sample.map((r) => r.join(" ")).join(", ")}</span>
                ) : null}
                {!c.ok && c.error ? <span className="text-ink-subtle"> · {c.error}</span> : null}
              </p>
            ))}
            {replays.map((c) => (
              <p key={c.what} className="text-k-caption text-ink-subtle">
                {c.ok ? "✓" : "·"} {c.what}
                {c.ok ? " now works" : " still fails as it was asked (the new name may differ)"}
              </p>
            ))}
          </div>
        )}

        {loop?.new_product && loop.stage !== "verified" && (
          <div className="rounded-lg border border-hairline bg-muted px-3 py-2">
            <p className="text-k-caption font-medium text-ink">New data product: {loop.new_product.concept}</p>
            <p className="mt-0.5 text-k-caption text-ink-muted">{loop.new_product.intent}</p>
          </div>
        )}
        {loop?.built_product && (
          <p className="text-k-caption">
            <Link href="/products" className="text-brand hover:text-brand-strong">
              Open {loop.built_product.name} under Data products →
            </Link>
          </p>
        )}
        {last && loop?.stage !== "verified" && (
          <p className="text-k-caption text-ink-muted">{last.note}</p>
        )}
        {f.resolution && <p className="text-k-caption text-ok">{f.resolution}</p>}
      </div>
      <div className="flex shrink-0 flex-col items-end gap-1.5">
        {busy && <Spinner />}
        {!busy && loop?.stage === "proposed" && (
          <>
            <button onClick={() => act(f.id, approveReport)} className="k-btn k-btn-sm k-btn-primary">
              Approve
            </button>
            <button onClick={() => act(f.id, rejectReport)} className="k-btn k-btn-sm">
              Reject
            </button>
          </>
        )}
        {!busy && (loop?.stage === "needs_person" || loop?.stage === "proposed") && loop.new_product && (
          <button onClick={() => act(f.id, buildFromReport)} className="k-btn k-btn-sm k-btn-primary">
            Build {loop.new_product.concept}
          </button>
        )}
        {loop?.stage === "building" && <Spinner />}
        {!busy && loop?.stage === "verified" && !loop.built_product && (
          <button onClick={() => act(f.id, rollBackReport)} className="k-btn k-btn-sm">
            Roll back
          </button>
        )}
        {!busy && (loop?.stage === "new" || loop?.stage === "triaged") && (
          <button onClick={() => act(f.id, workOnReport)} className="k-btn k-btn-sm">
            Work on it now
          </button>
        )}
        {!busy && f.status === "open" && loop?.stage !== "proposed" && (
          <button onClick={() => act(f.id, (id) => updateFeedback(id, "dismissed"))} className="k-btn k-btn-sm">
            Dismiss
          </button>
        )}
        {!busy && f.status === "dismissed" && !loop && (
          <button onClick={() => act(f.id, (id) => updateFeedback(id, "open"))} className="k-btn k-btn-sm">
            Reopen
          </button>
        )}
      </div>
    </div>
  );
}
