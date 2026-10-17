"use client";

/**
 * One data product, opened from the graph: what it is, its semantic model, its
 * input and output ports, its contracts, its supply chain, an Ask console on its
 * query port, and exactly what an agent receives.
 */

import { useEffect, useState } from "react";
import {
  AlertTriangle,
  Bot,
  Braces,
  Check,
  Copy,
  Layers,
  Pencil,
  Play,
  Plug,
  RefreshCw,
  ShieldCheck,
  Trash2,
  Wrench,
  X,
} from "lucide-react";

import { Callout, Spinner, StatusPill, Tabs } from "@/components/kairos/ds";
import { AskPanel } from "@/components/products/ask-panel";
import { ProductFlow } from "@/components/products/product-flow";
import { timeAgo } from "@/components/agents/bits";
import { cn } from "@/lib/utils";
import {
  checkProduct,
  deleteProduct,
  getProductForAgent,
  HEALTH_TONE,
  pretty,
  ROLE_TONE,
  tail,
  trustTone,
  updateProduct,
  type Contract,
  type Product,
} from "@/lib/products";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "model", label: "Semantic model" },
  { id: "ports", label: "Ports" },
  { id: "contracts", label: "Contracts" },
  { id: "supply", label: "Supply chain" },
  { id: "ask", label: "Ask" },
  { id: "agent", label: "Agent view" },
] as const;
type Tab = (typeof TABS)[number]["id"];

const CONTRACT_TONE: Record<string, "ok" | "warn" | "danger" | "neutral"> = {
  ok: "ok",
  info: "neutral",
  breached: "warn",
  broken: "danger",
  error: "danger",
};

export function ProductDrawer({
  product,
  onClose,
  onChanged,
  onDeleted,
  onRebuild,
}: {
  product: Product;
  onClose: () => void;
  onChanged: (p: Product) => void;
  onDeleted: () => void;
  onRebuild: () => void;
}) {
  const [tab, setTab] = useState<Tab>("overview");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState(product.name);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const health = product.contracts.health;

  async function act(kind: string, fn: () => Promise<void>) {
    setBusy(kind);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : "That did not work.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <aside className="k-rise absolute inset-y-0 right-0 z-20 flex w-[min(620px,100%)] flex-col border-l border-hairline bg-surface shadow-[-20px_0_40px_-28px_rgb(26_29_36/0.35)]">
      {/* ── header ── */}
      <div className="border-b border-hairline px-5 pb-3 pt-4">
        <div className="flex items-start gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand text-white">
            <Layers className="h-[18px] w-[18px]" />
          </span>
          <div className="min-w-0 flex-1">
            {renaming ? (
              <form
                className="flex items-center gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  act("rename", async () => {
                    onChanged(await updateProduct(product.id, { name }));
                    setRenaming(false);
                  });
                }}
              >
                <input autoFocus value={name} onChange={(e) => setName(e.target.value)} className="k-input h-8 w-52" />
                <button className="k-btn k-btn-sm k-btn-primary">Save</button>
              </form>
            ) : (
              <div className="flex items-center gap-1.5">
                <h2 className="truncate text-k-title font-bold text-ink">{product.name}</h2>
                <button
                  className="k-btn k-btn-ghost k-btn-sm"
                  aria-label="Rename"
                  onClick={() => {
                    setName(product.name);
                    setRenaming(true);
                  }}
                >
                  <Pencil className="h-3.5 w-3.5" />
                </button>
              </div>
            )}
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              <StatusPill tone={product.status === "confirmed" ? "ok" : "warn"} size="sm">
                {product.status}
              </StatusPill>
              <StatusPill tone={HEALTH_TONE[health.status]} size="sm">
                {health.status} · {health.ok}/{health.total} contracts
              </StatusPill>
              {product.domain && (
                <StatusPill tone="brand" size="sm" dot={false}>
                  {product.domain}
                </StatusPill>
              )}
            </div>
          </div>
          <button onClick={onClose} className="k-btn k-btn-ghost k-btn-sm" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {product.status === "draft" ? (
            <button
              className="k-btn k-btn-sm k-btn-primary"
              disabled={!!busy}
              onClick={() => act("confirm", async () => onChanged(await updateProduct(product.id, { status: "confirmed" })))}
            >
              <Check className="h-3.5 w-3.5" /> Confirm product
            </button>
          ) : (
            <button
              className="k-btn k-btn-sm"
              disabled={!!busy}
              onClick={() => act("confirm", async () => onChanged(await updateProduct(product.id, { status: "draft" })))}
            >
              Back to draft
            </button>
          )}
          <button className="k-btn k-btn-sm" disabled={!!busy} onClick={onRebuild}>
            <RefreshCw className="h-3.5 w-3.5" /> Rebuild
          </button>
          {confirmDelete ? (
            <>
              <button
                className="k-btn k-btn-sm k-btn-danger"
                onClick={() =>
                  act("delete", async () => {
                    await deleteProduct(product.id);
                    onDeleted();
                  })
                }
              >
                Delete {product.name}
              </button>
              <button className="k-btn k-btn-sm k-btn-ghost" onClick={() => setConfirmDelete(false)}>
                Keep
              </button>
            </>
          ) : (
            <button className="k-btn k-btn-sm k-btn-ghost ml-auto" onClick={() => setConfirmDelete(true)} aria-label="Delete">
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
        {error && (
          <Callout tone="danger" className="mt-2">
            {error}
          </Callout>
        )}
      </div>

      <Tabs size="panel" items={TABS} value={tab} onChange={setTab} />
      <div key={tab} className="k-rise min-h-0 flex-1 overflow-y-auto px-5 py-4">
        {tab === "overview" && <Overview product={product} />}
        {tab === "model" && <Model product={product} />}
        {tab === "ports" && <Ports product={product} onAsk={() => setTab("ask")} />}
        {tab === "contracts" && <Contracts product={product} onChanged={onChanged} />}
        {tab === "supply" && (
          <div className="-mx-5">
            <ProductFlow bundle={product.bundle} />
          </div>
        )}
        {tab === "ask" && <AskPanel product={product} />}
        {tab === "agent" && <AgentView id={product.id} slug={product.slug} />}
      </div>
    </aside>
  );
}

// ── tabs ──────────────────────────────────────────────────────────────

function Section({ title, children, className }: { title: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={cn("mb-5", className)}>
      <p className="k-label mb-2">{title}</p>
      {children}
    </section>
  );
}

function Overview({ product }: { product: Product }) {
  const m = product.spec.model;
  return (
    <>
      <p className="text-k-body text-ink-2">{product.description}</p>
      {m.purpose && <p className="mt-2 text-k-body text-ink-muted">{m.purpose}</p>}
      <div className="my-4 grid grid-cols-4 gap-2">
        {[
          [m.metrics.length, "metrics"],
          [m.dimensions.length, "dimensions"],
          [product.spec.inputs.length, "input ports"],
          [m.tools.length, "tools"],
        ].map(([n, l]) => (
          <div key={l as string} className="rounded-lg bg-sunken px-3 py-2">
            <p className="text-[20px] font-bold tabular-nums text-ink">{n}</p>
            <p className="text-k-caption text-ink-muted">{l}</p>
          </div>
        ))}
      </div>
      {m.agent_guidance.length > 0 && (
        <Section title="Rules for agents answering from it">
          <ol className="space-y-1.5">
            {m.agent_guidance.map((g, i) => (
              <li key={g} className="flex gap-2 text-k-body text-ink-2">
                <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-brand-soft text-[11px] font-semibold text-brand">
                  {i + 1}
                </span>
                {g}
              </li>
            ))}
          </ol>
        </Section>
      )}
      {m.caveats.length > 0 && (
        <Section title="Caveats">
          <div className="space-y-1.5">
            {m.caveats.map((c) => (
              <Callout key={c} tone="warn" icon={AlertTriangle}>
                {c}
              </Callout>
            ))}
          </div>
        </Section>
      )}
      {product.consumers.length > 0 && (
        <Section title="Used by">
          {product.consumers.map((c) => (
            <p key={c.agent + c.channel} className="text-k-body text-ink-2">
              <Bot className="mr-1.5 inline h-3.5 w-3.5 text-brand" />
              {c.agent} <span className="text-ink-muted">· {c.channel} · {c.calls} calls{c.last ? ` · ${timeAgo(c.last)}` : ""}</span>
            </p>
          ))}
        </Section>
      )}
      <p className="text-k-caption text-ink-subtle">
        Concept “{product.spec.concept}”
        {product.intent && <> · intent: {product.intent}</>}
        {product.built_at && <> · built {timeAgo(product.built_at)}</>}
        {product.model && <> · {product.model}</>}
      </p>
    </>
  );
}

function Model({ product }: { product: Product }) {
  const m = product.spec.model;
  return (
    <>
      <Section title={`Metrics · defined once`}>
        <div className="space-y-2">
          {m.metrics.map((x) => (
            <div key={x.name} className="rounded-lg border border-hairline px-3 py-2.5">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-k-body font-semibold text-ink">{x.label || x.name}</span>
                <span className="font-mono text-[11px] text-ink-subtle">{x.name}</span>
                {x.unit && <span className="text-[11px] text-ink-muted">· {x.unit}</span>}
                <StatusPill tone={x.additive ? "neutral" : "warn"} size="sm" dot={false} className="ml-auto">
                  {x.additive ? "additive" : "not additive"}
                </StatusPill>
              </div>
              <p className="mt-0.5 text-k-caption text-ink-muted">{x.description}</p>
              <code className="mt-1.5 block break-words rounded-md bg-sunken px-2 py-1 font-mono text-[11px] text-ink-2">
                {x.expression} <span className="text-ink-subtle">· on {tail(x.base_table)}</span>
              </code>
              {x.shortcuts.length > 0 && (
                <p className="mt-1.5 text-[11px] text-ink-muted">
                  fast path:{" "}
                  {x.shortcuts.map((s) => (
                    <span key={s.table + s.column} className="mr-1.5 font-mono text-ok">
                      {tail(s.table)}.{s.column}
                      {s.rollup === "none" ? " (own grain)" : ""}
                    </span>
                  ))}
                </p>
              )}
              {x.caveat && <p className="mt-1 text-[11px] text-warn">{x.caveat}</p>}
            </div>
          ))}
        </div>
      </Section>
      <Section title="Dimensions">
        <div className="grid grid-cols-2 gap-2">
          {m.dimensions.map((d) => (
            <div key={d.name} className="rounded-lg border border-hairline px-3 py-2">
              <p className="text-k-body font-semibold text-ink">
                {d.label || d.name} <span className="text-[11px] font-normal text-ink-subtle">{d.type}</span>
              </p>
              <p className="font-mono text-[11px] text-ink-muted">
                {tail(d.table)}.{d.column}
              </p>
              {d.joins.length > 0 && (
                <p className="mt-0.5 text-[11px] text-ink-subtle">
                  joins {d.joins.map((j) => `${tail(j.from_table)}.${j.from_column}`).join(", ")}
                </p>
              )}
            </div>
          ))}
        </div>
      </Section>
      {m.entities.length > 0 && (
        <Section title="Entities">
          <div className="flex flex-wrap gap-1.5">
            {m.entities.map((e) => (
              <StatusPill key={e.name} tone="brand" dot={false} title={`${e.description} · key ${tail(e.table)}.${e.key}`}>
                {e.name}
              </StatusPill>
            ))}
          </div>
        </Section>
      )}
      {m.glossary.length > 0 && (
        <Section title="Glossary">
          <dl className="space-y-1">
            {m.glossary.map((g) => (
              <div key={g.term} className="text-k-body">
                <dt className="inline font-semibold text-ink">{g.term}</dt>
                <dd className="inline text-ink-muted"> — {g.meaning}</dd>
              </div>
            ))}
          </dl>
        </Section>
      )}
    </>
  );
}

function Ports({ product, onAsk }: { product: Product; onAsk: () => void }) {
  const schema = new Map(
    product.contracts.contracts.filter((c) => c.contract === "schema").map((c) => [c.port.toUpperCase(), c])
  );
  return (
    <>
      <Section title={`Input ports · ${product.spec.inputs.length}`}>
        <div className="space-y-1.5">
          {product.spec.inputs.map((i) => {
            const s = schema.get(i.table.toUpperCase());
            return (
              <div key={i.entity_id} className="rounded-lg border border-hairline px-3 py-2">
                <div className="flex items-center gap-2">
                  <span className="truncate font-mono text-[12px] font-semibold text-ink">{i.table}</span>
                  <StatusPill tone={ROLE_TONE[i.role] ?? "neutral"} size="sm" dot={false} className="ml-auto">
                    {i.role}
                  </StatusPill>
                  <StatusPill tone={trustTone(i.trust)} size="sm">
                    {i.trust}
                  </StatusPill>
                </div>
                <p className="mt-0.5 text-k-caption text-ink-muted">{i.why}</p>
                {s?.columns && (
                  <p className="mt-1 text-[11px] text-ink-subtle">
                    expects <span className="font-mono">{s.columns.join(", ")}</span>
                  </p>
                )}
              </div>
            );
          })}
        </div>
        {product.spec.left_out.length > 0 && (
          <details className="mt-2">
            <summary className="cursor-pointer text-k-caption text-ink-muted">
              {product.spec.left_out.length} related tables left out, and why
            </summary>
            <ul className="mt-1.5 space-y-1">
              {product.spec.left_out.map((l) => (
                <li key={l.table} className="text-k-caption text-ink-muted">
                  <span className="font-mono text-ink-2">{tail(l.table)}</span> — {l.why}
                </li>
              ))}
            </ul>
          </details>
        )}
      </Section>
      <Section title="Output ports">
        <div className="space-y-2">
          <div className="rounded-lg border border-brand-border bg-brand-soft/40 px-3 py-2.5">
            <p className="flex items-center gap-1.5 text-k-body font-semibold text-ink">
              <Braces className="h-4 w-4 text-brand" /> Query port
              <button onClick={onAsk} className="k-btn k-btn-sm ml-auto">
                <Play className="h-3.5 w-3.5" /> Try it
              </button>
            </p>
            <p className="mt-1 text-k-caption text-ink-muted">
              Metrics by dimensions, never tables. Kairos picks a pre-aggregated table when it answers, the base table
              otherwise, and runs read-only SQL with personal data masked.
            </p>
          </div>
          <div className="rounded-lg border border-hairline px-3 py-2.5">
            <p className="flex items-center gap-1.5 text-k-body font-semibold text-ink">
              <Wrench className="h-4 w-4 text-brand" /> Domain tools · {product.spec.model.tools.length}
            </p>
            <div className="mt-1.5 space-y-1">
              {product.spec.model.tools.map((t) => (
                <p key={t.name} className="text-k-caption text-ink-muted">
                  <span className="font-mono text-ink-2">{t.name}</span> — {t.description}
                </p>
              ))}
            </div>
          </div>
          <div className="rounded-lg border border-hairline px-3 py-2.5">
            <p className="flex items-center gap-1.5 text-k-body font-semibold text-ink">
              <Plug className="h-4 w-4 text-brand" /> MCP
            </p>
            <code className="mt-1.5 block rounded-md bg-sunken px-2 py-1.5 font-mono text-[11px] leading-relaxed text-ink-2">
              get_data_product(&quot;{product.slug}&quot;)
              <br />
              query_data_product(&quot;{product.slug}&quot;, metrics=[&quot;{product.spec.model.metrics[0]?.name}&quot;], by=[&quot;
              {product.spec.model.dimensions[0]?.name}&quot;])
            </code>
          </div>
        </div>
      </Section>
    </>
  );
}

function Contracts({ product, onChanged }: { product: Product; onChanged: (p: Product) => void }) {
  const [busy, setBusy] = useState(false);
  const [slo, setSlo] = useState(String(product.contracts.freshness_slo_hours ?? ""));
  const c = product.contracts;
  const groups = c.contracts.reduce<Record<string, Contract[]>>((acc, x) => {
    (acc[x.contract] ??= []).push(x);
    return acc;
  }, {});
  const ORDER = ["schema", "metric", "reconcile", "grain", "pipeline", "freshness"];
  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <StatusPill tone={HEALTH_TONE[c.health.status]}>{c.health.status}</StatusPill>
        <span className="text-k-caption text-ink-muted">
          {c.health.ok} of {c.health.total} ok
          {c.live_at ? ` · platform checked ${timeAgo(c.live_at)}` : " · platform not checked yet"}
        </span>
        <button
          disabled={busy}
          className="k-btn k-btn-sm k-btn-primary ml-auto"
          onClick={async () => {
            setBusy(true);
            try {
              const contracts = await checkProduct(product.id);
              onChanged({ ...product, contracts, health: contracts.health });
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? <Spinner className="border-white/30" /> : <ShieldCheck className="h-3.5 w-3.5" />}
          {busy ? "Checking on the platform…" : "Run live checks"}
        </button>
      </div>
      {ORDER.filter((k) => groups[k]).map((k) => (
        <Section key={k} title={`${k} · ${groups[k].filter((x) => x.status === "ok").length}/${groups[k].length} ok`}>
          <div className="divide-y divide-hairline rounded-lg border border-hairline">
            {groups[k].map((x, i) => (
              <div key={i} className="flex items-start gap-2 px-3 py-1.5">
                <StatusPill tone={CONTRACT_TONE[x.status] ?? "neutral"} size="sm" className="mt-px">
                  {x.status}
                </StatusPill>
                <div className="min-w-0">
                  <p className="truncate font-mono text-[11.5px] text-ink">{tail(x.port)}</p>
                  {x.detail && <p className="text-[11px] text-ink-muted">{x.detail}</p>}
                </div>
              </div>
            ))}
          </div>
        </Section>
      ))}
      <Section title="Freshness SLO">
        <form
          className="flex items-center gap-2"
          onSubmit={async (e) => {
            e.preventDefault();
            onChanged(await updateProduct(product.id, { freshness_slo_hours: Number(slo) || 0 }));
          }}
        >
          <input value={slo} onChange={(e) => setSlo(e.target.value)} placeholder="hours" className="k-input h-8 w-24" />
          <span className="text-k-caption text-ink-muted">hours since an input last changed; empty for no promise</span>
          <button className="k-btn k-btn-sm ml-auto">Save</button>
        </form>
      </Section>
      {product.validation.dropped.length > 0 && (
        <Section title="Dropped while building">
          {product.validation.dropped.map((d) => (
            <p key={d.kind + d.item} className="text-k-caption text-ink-muted">
              <span className="font-semibold text-ink-2">{pretty(d.kind)} {d.item}</span>: {d.reason}
            </p>
          ))}
        </Section>
      )}
    </>
  );
}

function AgentView({ id, slug }: { id: string; slug: string }) {
  const [doc, setDoc] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    getProductForAgent(id)
      .then((d) => setDoc(JSON.stringify(d, null, 2)))
      .catch(() => setDoc("Could not load the agent view."));
  }, [id]);
  return (
    <>
      <div className="mb-2 flex items-center gap-2">
        <p className="min-w-0 flex-1 text-k-caption text-ink-muted">
          What a chatbot receives from <span className="font-mono text-ink">get_data_product(&quot;{slug}&quot;)</span>.
        </p>
        <button
          className="k-btn k-btn-sm"
          disabled={!doc}
          onClick={() => {
            if (doc) navigator.clipboard?.writeText(doc).then(() => setCopied(true));
            window.setTimeout(() => setCopied(false), 1500);
          }}
        >
          {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      {doc === null ? (
        <p className="flex items-center gap-2 text-k-body text-ink-muted">
          <Spinner /> Loading…
        </p>
      ) : (
        <pre className="overflow-auto rounded-lg bg-[#0F172A] p-3 font-mono text-[11px] leading-relaxed text-[#E2E8F0]">{doc}</pre>
      )}
    </>
  );
}
