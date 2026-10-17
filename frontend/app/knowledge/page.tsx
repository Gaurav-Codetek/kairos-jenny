"use client";

import { useCallback, useEffect, useState } from "react";
import { BookOpen, Check, RefreshCw, Search, Sparkles, Undo2, X } from "lucide-react";

import { Callout, EmptyState, Segmented, Spinner, StatusPill, Tabs } from "@/components/kairos/ds";
import { PageHeader } from "@/components/shell/app-shell";
import { Empty, timeAgo } from "@/components/agents/bits";
import { listWorkspaces } from "@/lib/connections";
import {
  classifyWorkspace,
  entityLabel,
  getConcept,
  getPacks,
  listBindings,
  reloadPack,
  reviewBinding,
  searchKnowledge,
  why,
  type Binding,
  type BindingPredicate,
  type BindingStatus,
  type Concept,
  type ConceptHit,
  type PacksResponse,
} from "@/lib/knowledge";
import { cn } from "@/lib/utils";

const TABS = [
  { id: "tables", label: "Tables → dataset types" },
  { id: "columns", label: "Columns → identifiers" },
  { id: "browse", label: "Browse knowledge" },
] as const;
type Tab = (typeof TABS)[number]["id"];

const STATUSES: BindingStatus[] = ["proposed", "confirmed", "rejected"];

export default function KnowledgePage() {
  const [tab, setTab] = useState<Tab>("tables");
  const [packs, setPacks] = useState<PacksResponse | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [concept, setConcept] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    getPacks().then(setPacks).catch(() => undefined);
  }, [version]);

  const pack = packs?.packs[0];

  async function reclassify() {
    setBusy("classify");
    setMessage(null);
    try {
      const workspaces = await listWorkspaces();
      let types = 0, ids = 0, withdrawn = 0;
      for (const w of workspaces) {
        const r = await classifyWorkspace(w.id);
        types += r.dataset_types_proposed ?? 0;
        ids += r.identifier_columns_proposed ?? 0;
        withdrawn += r.withdrawn ?? 0;
      }
      setMessage(`Re-read the warehouse: ${types} table and ${ids} column proposals up to date, ${withdrawn} withdrawn. Reviewed bindings were kept.`);
      setVersion((v) => v + 1);
    } catch {
      setMessage("Classification failed — is the API running?");
    } finally {
      setBusy(null);
    }
  }

  async function reload() {
    setBusy("reload");
    setMessage(null);
    try {
      const r = await reloadPack();
      setMessage(r.unchanged ? "The pack is unchanged." : `Pack reloaded: ${r.updated} concepts updated, ${r.removed} removed.`);
      setVersion((v) => v + 1);
    } catch {
      setMessage("Could not load the pack.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <PageHeader
        title="Knowledge"
        description="Industry knowledge, bound to this warehouse — Kairos proposes, a person confirms"
        actions={
          <div className="flex gap-2">
            <button onClick={reload} disabled={!!busy} className="k-btn">
              {busy === "reload" ? <Spinner /> : <RefreshCw className="h-4 w-4" />}
              Reload pack
            </button>
            <button onClick={reclassify} disabled={!!busy} className="k-btn k-btn-primary">
              {busy === "classify" ? <Spinner className="border-white/30" /> : <Sparkles className="h-4 w-4" />}
              Re-classify warehouse
            </button>
          </div>
        }
      />

      <div className="border-b border-hairline bg-surface px-7 py-3.5">
        {pack ? (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-soft text-brand">
              <BookOpen className="h-4 w-4" />
            </span>
            <div className="min-w-0">
              <p className="text-k-title font-semibold text-ink">{pack.title ?? pack.name}</p>
              <p className="text-k-caption text-ink-muted">
                {pack.concepts} concepts · version <span className="font-mono">{pack.version.slice(0, 8)}</span> · loaded{" "}
                {timeAgo(pack.loaded_at)}
              </p>
            </div>
            <div className="ml-auto flex flex-wrap gap-1.5">
              {Object.entries(packs?.concept_types ?? {})
                .slice(0, 6)
                .map(([t, n]) => (
                  <StatusPill key={t} tone="neutral" size="sm" dot={false}>
                    {t} <span className="tabular-nums opacity-70">{n}</span>
                  </StatusPill>
                ))}
            </div>
          </div>
        ) : (
          <p className="text-k-body text-ink-muted">No knowledge pack loaded. Use “Reload pack” to load it.</p>
        )}
        {message && (
          <Callout tone="brand" icon={Check} className="k-pop mt-3">
            {message}
          </Callout>
        )}
      </div>

      <Tabs items={TABS} value={tab} onChange={setTab} />

      <div className="grid min-h-0 flex-1 content-start items-start gap-5 overflow-y-auto px-7 py-6 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div key={tab} className="k-rise min-w-0">
          {tab === "tables" && <BindingsPanel key={`t${version}`} predicate="instance_of" onConcept={setConcept} />}
          {tab === "columns" && <BindingsPanel key={`c${version}`} predicate="identified_by" onConcept={setConcept} />}
          {tab === "browse" && <BrowsePanel onConcept={setConcept} />}
        </div>
        <ConceptPanel id={concept} onConcept={setConcept} />
      </div>
    </>
  );
}

function BindingsPanel({ predicate, onConcept }: { predicate: BindingPredicate; onConcept: (id: string) => void }) {
  const [status, setStatus] = useState<BindingStatus>("proposed");
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<Binding[]>([]);
  const [counts, setCounts] = useState<Partial<Record<BindingStatus, number>>>({});
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    listBindings({ predicate, status, q: q || undefined })
      .then((r) => {
        setRows(r.bindings);
        setCounts(r.counts);
      })
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  }, [predicate, status, q]);

  useEffect(() => {
    const t = window.setTimeout(load, 200);
    return () => window.clearTimeout(t);
  }, [load]);

  async function decide(b: Binding, next: BindingStatus) {
    await reviewBinding(b.id, next);
    setRows((rs) => rs.filter((r) => r.id !== b.id));
    setCounts((c) => ({ ...c, [b.status]: Math.max(0, (c[b.status] ?? 1) - 1), [next]: (c[next] ?? 0) + 1 }));
  }

  return (
    <section className="kairos-panel overflow-hidden">
      <div className="flex flex-wrap items-center gap-3 border-b border-hairline px-5 py-3.5">
        <div className="min-w-0 flex-1">
          <h3 className="text-k-title font-semibold text-ink">
            {predicate === "instance_of" ? "Which kind of industry data each table is" : "Which columns hold industry identifiers"}
          </h3>
          <p className="text-k-caption text-ink-muted">
            Agents see proposals marked as proposed, confirmations as settled, and never see rejections. Kairos never
            re-proposes what a person rejected.
          </p>
        </div>
        <Segmented
          items={STATUSES.map((s) => ({ id: s, label: s[0].toUpperCase() + s.slice(1), count: counts[s] ?? 0 }))}
          value={status}
          onChange={setStatus}
        />
      </div>
      <div className="border-b border-hairline px-5 py-3">
        <label className="relative block">
          <Search className="absolute left-3 top-[9px] h-4 w-4 text-ink-subtle" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Filter by table, column or concept"
            className="k-input !pl-9"
          />
        </label>
      </div>
      {loading && rows.length === 0 && <Empty>Loading…</Empty>}
      {!loading && rows.length === 0 && <Empty>No {status} bindings{q ? " match" : ""}.</Empty>}
      {rows.map((b) => (
        <div key={b.id} className="k-row flex items-start gap-4 border-b border-hairline px-5 py-3.5 last:border-b-0">
          <Confidence value={b.confidence} />
          <div className="min-w-0 flex-1">
            <p className="truncate font-mono text-k-caption font-semibold text-ink" title={b.entity_id}>
              {entityLabel(b.entity_id)}
            </p>
            <p className="mt-1 flex flex-wrap items-center gap-1.5 text-k-caption text-ink-muted">
              {predicate === "instance_of" ? "is a" : "holds"}
              <button
                onClick={() => onConcept(b.concept_id)}
                className="inline-flex h-6 items-center rounded-full bg-brand-soft px-2.5 font-semibold text-brand-strong transition-colors hover:bg-brand-border/60"
              >
                {b.concept_title ?? b.concept_id}
              </button>
            </p>
            <p className="mt-1 truncate text-k-caption text-ink-subtle" title={why(b.evidence)}>
              {why(b.evidence)}
              {b.reviewed_by ? ` · ${b.status} by ${b.reviewed_by} ${timeAgo(b.reviewed_at)}` : ""}
            </p>
          </div>
          <div className="flex shrink-0 gap-1">
            {b.status === "proposed" ? (
              <>
                <IconButton label="Confirm" onClick={() => decide(b, "confirmed")} tone="ok">
                  <Check className="h-3.5 w-3.5" />
                </IconButton>
                <IconButton label="Reject" onClick={() => decide(b, "rejected")} tone="danger">
                  <X className="h-3.5 w-3.5" />
                </IconButton>
              </>
            ) : (
              <IconButton label="Back to proposed" onClick={() => decide(b, "proposed")}>
                <Undo2 className="h-3.5 w-3.5" />
              </IconButton>
            )}
          </div>
        </div>
      ))}
    </section>
  );
}

function Confidence({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  return (
    <div className="mt-1 w-11 shrink-0" title={`Confidence ${pct}%`}>
      <div className="h-1.5 overflow-hidden rounded-full bg-neutral-soft">
        <div className="k-grow h-full rounded-full bg-brand" style={{ width: `${pct}%` }} />
      </div>
      <p className="mt-1 text-[11px] font-semibold tabular-nums text-ink-muted">{pct}%</p>
    </div>
  );
}

function IconButton({
  label,
  onClick,
  tone,
  children,
}: {
  label: string;
  onClick: () => void;
  tone?: "ok" | "danger";
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      title={label}
      aria-label={label}
      className={cn(
        "k-btn k-btn-sm",
        tone === "ok" && "!text-ok hover:!border-ok-dot hover:!bg-ok-soft",
        tone === "danger" && "!text-danger hover:!border-danger-dot hover:!bg-danger-soft"
      )}
    >
      {children}
      <span className="hidden sm:inline">{label}</span>
    </button>
  );
}

function BrowsePanel({ onConcept }: { onConcept: (id: string) => void }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<ConceptHit[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!q.trim()) {
      setHits([]);
      return;
    }
    const t = window.setTimeout(() => {
      setLoading(true);
      searchKnowledge(q)
        .then((r) => setHits(r.results))
        .catch(() => setHits([]))
        .finally(() => setLoading(false));
    }, 300);
    return () => window.clearTimeout(t);
  }, [q]);

  return (
    <section className="kairos-panel overflow-hidden">
      <div className="border-b border-hairline px-5 py-4">
        <h3 className="text-k-title font-semibold text-ink">Search the knowledge an agent can read</h3>
        <p className="text-k-caption text-ink-muted">
          The same search agents get through <code className="font-mono text-ink-2">find_knowledge</code>.
        </p>
        <label className="relative mt-3 block">
          <Search className="absolute left-3 top-[9px] h-4 w-4 text-ink-subtle" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="e.g. net sales from distributor data, NPI, NBRx, PDRP"
            className="k-input !pl-9"
          />
          {loading && <Spinner className="absolute right-3 top-[10px]" />}
        </label>
      </div>
      {!q && <Empty>Ask the way an agent would.</Empty>}
      {q && !loading && hits.length === 0 && <Empty>Nothing found.</Empty>}
      {hits.map((h) => (
        <button
          key={h.concept_id}
          onClick={() => onConcept(h.concept_id)}
          className="k-row k-rise block w-full border-b border-hairline px-5 py-3 text-left last:border-b-0"
        >
          <p className="flex items-center gap-2 text-k-body font-semibold text-ink">
            {h.title}
            <StatusPill tone="neutral" size="sm" dot={false}>
              {h.type}
            </StatusPill>
          </p>
          {h.description && <p className="line-clamp-2 text-k-caption text-ink-muted">{h.description}</p>}
          <p className="mt-0.5 text-k-caption text-ink-subtle">
            <span className="font-mono">{h.concept_id}</span> · {h.warehouse_entities_bound} bound here
          </p>
        </button>
      ))}
    </section>
  );
}

const FIELD_ORDER = ["grain", "primary_key", "join_keys", "measures", "phi_status", "projection", "refresh_cadence", "identifier_format", "issuer"];

function ConceptPanel({ id, onConcept }: { id: string | null; onConcept: (id: string) => void }) {
  const [concept, setConcept] = useState<Concept | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!id) return;
    setError(false);
    getConcept(id)
      .then(setConcept)
      .catch(() => setError(true));
  }, [id]);

  if (!id) {
    return (
      <aside className="kairos-panel h-fit lg:sticky lg:top-0">
        <EmptyState icon={BookOpen} title="Pick a concept">
          See what Kairos knows about it: the same answer an agent gets from <code className="font-mono">get_concept</code>.
        </EmptyState>
      </aside>
    );
  }
  if (error) return <aside className="kairos-panel h-fit p-5 text-k-body text-danger">Could not load {id}.</aside>;
  if (!concept || concept.concept_id !== id) {
    return (
      <aside className="kairos-panel flex h-fit justify-center p-6">
        <Spinner />
      </aside>
    );
  }

  const fields = concept.fields ?? {};
  const sections = Object.entries(concept.sections).filter(([k]) => !["Schema"].includes(k));
  return (
    <aside key={concept.concept_id} className="kairos-panel k-rise h-fit overflow-hidden lg:sticky lg:top-0">
      <div className="border-b border-hairline px-5 py-4">
        <StatusPill tone="brand" size="sm" dot={false}>
          {concept.type}
        </StatusPill>
        <h3 className="mt-2 text-[17px] font-bold text-ink">{concept.title}</h3>
        {concept.description && <p className="mt-1 text-k-caption text-ink-muted">{concept.description}</p>}
      </div>
      <dl className="grid grid-cols-[110px_1fr] gap-x-3 gap-y-2 border-b border-hairline bg-sunken px-5 py-3.5 text-k-caption">
        {FIELD_ORDER.filter((k) => fields[k] != null).map((k) => (
          <div key={k} className="contents">
            <dt className="font-medium text-ink-muted">{k.replace(/_/g, " ")}</dt>
            <dd className="break-words text-ink">{Array.isArray(fields[k]) ? (fields[k] as unknown[]).join(", ") : String(fields[k])}</dd>
          </div>
        ))}
      </dl>
      <div className="max-h-[520px] overflow-y-auto">
        {sections.map(([name, body]) => (
          <div key={name} className="border-b border-hairline px-5 py-3">
            <p className="k-label">{name}</p>
            <p className="mt-1 whitespace-pre-line text-k-caption leading-relaxed text-ink">{body}</p>
          </div>
        ))}
        {concept.relations.out.length + concept.relations.in.length > 0 && (
          <div className="border-b border-hairline px-5 py-3">
            <p className="k-label">Related</p>
            <ul className="mt-1 space-y-0.5 text-k-caption">
              {[...concept.relations.out, ...concept.relations.in].slice(0, 20).map((r, i) => (
                <li key={`${r.concept_id}${i}`}>
                  <span className="text-ink-subtle">{r.predicate.replace(/_/g, " ")} </span>
                  <button onClick={() => onConcept(r.concept_id)} className="font-medium text-brand hover:text-brand-strong">
                    {r.title ?? r.concept_id}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        <div className="px-5 py-3">
          <p className="k-label">
            In this warehouse ({concept.in_this_warehouse.length})
          </p>
          {concept.in_this_warehouse.length === 0 && <p className="mt-1 text-k-caption text-ink-muted">Nothing bound yet.</p>}
          <ul className="mt-1 space-y-0.5">
            {concept.in_this_warehouse.slice(0, 40).map((b) => (
              <li key={b.entity_id} className="flex items-center gap-2 text-k-caption">
                <span className="truncate font-mono text-ink" title={b.entity_id}>
                  {entityLabel(b.entity_id)}
                </span>
                <StatusPill tone={b.status === "confirmed" ? "ok" : b.status === "rejected" ? "danger" : "warn"} size="sm" className="ml-auto">
                  {b.status}
                </StatusPill>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </aside>
  );
}
