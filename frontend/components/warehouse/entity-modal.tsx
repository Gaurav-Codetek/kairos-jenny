"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { ArrowLeft, Crosshair, FileCode2, FileSearch, Info, Network, Quote, X } from "lucide-react";

import { kindVisual } from "@/components/graph/lineage-card";
import { Callout, Spinner, StatusPill, Tabs } from "@/components/kairos/ds";

import {
  fetchEntityCard,
  formatValue,
  kindStyle,
  RELATION_GROUP_STYLE,
  type EntityCard,
  type LinkReason,
  type MapItem,
} from "@/lib/warehouse";
import { cn } from "@/lib/utils";

type ModalTab = "overview" | "relations" | "profile" | "evidence";

/** Kinds that exist only as records about something else: there is nothing to centre the map on. */
const NOT_ON_MAP = new Set(["evidence", "change", "syncstate"]);

/**
 * Everything Kairos knows about one entity, every id resolved into what it is. Related entities open in the same
 * modal (with Back), so a person can follow a table to its evidence to the job that wrote it without losing place.
 */
export function EntityModal({
  entityId,
  onClose,
  onShowOnMap,
}: {
  entityId: string;
  onClose: () => void;
  onShowOnMap?: (entityId: string) => void;
}) {
  const [trail, setTrail] = useState<string[]>([entityId]);
  const current = trail[trail.length - 1];
  const [card, setCard] = useState<EntityCard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<ModalTab>("overview");
  // Cards already fetched: Back, and revisiting an entity, are instant.
  const cache = useRef(new Map<string, EntityCard>());
  const scroller = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => setTrail([entityId]), [entityId]);

  useEffect(() => {
    let live = true;
    const show = (c: EntityCard) => {
      setCard(c);
      setTab(c.kind === "evidence" ? "evidence" : "overview");
      setLoading(false);
      scroller.current?.scrollTo({ top: 0 });
    };
    setError(null);
    const cached = cache.current.get(current);
    if (cached) {
      show(cached);
      return;
    }
    // The previous card stays on screen (dimmed) until the next one arrives, so the modal never collapses.
    setLoading(true);
    fetchEntityCard(current)
      .then((c) => {
        cache.current.set(current, c);
        if (live) show(c);
      })
      .catch((e) => {
        if (!live) return;
        setLoading(false);
        setError(e instanceof Error ? e.message : "Could not load this entity");
      });
    return () => {
      live = false;
    };
  }, [current]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && closeRef.current();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const open = (id: string) => setTrail((t) => (t[t.length - 1] === id ? t : [...t, id]));

  // On document.body: the panels that open it sit in animated (transformed) containers, which would trap a
  // fixed overlay inside them. No backdrop blur: over the map's hundreds of nodes it re-blurs every frame and
  // makes the opening animation stutter.
  return createPortal(
    <div
      className="k-page fixed inset-0 z-50 flex items-center justify-center bg-[rgb(26_29_36/0.42)] p-6"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="entity-modal-title"
        aria-busy={loading}
        className="kairos-panel k-modal-in flex h-[min(86vh,760px)] w-full max-w-3xl flex-col overflow-hidden shadow-[0_24px_60px_-20px_rgb(26_29_36/0.35)]"
        onClick={(e) => e.stopPropagation()}
      >
        {!card && !error && (
          <div className="flex flex-1 items-center justify-center">
            <Spinner />
          </div>
        )}
        {error && (
          <div className="flex items-start gap-3 p-5">
            <Callout tone="danger" className="flex-1">
              {error}
            </Callout>
            <button onClick={onClose} className="k-btn k-btn-ghost k-btn-sm !px-1.5" aria-label="Close">
              <X className="h-4 w-4" />
            </button>
          </div>
        )}
        {card && (
          <>
            <Header
              card={card}
              loading={loading}
              canGoBack={trail.length > 1}
              onBack={() => setTrail((t) => t.slice(0, -1))}
              onClose={onClose}
              onShowOnMap={onShowOnMap && !NOT_ON_MAP.has(card.kind) ? () => onShowOnMap(card.id) : undefined}
            />
            <Tabs
              size="panel"
              items={[
                ...(card.evidence ? [{ id: "evidence" as const, label: "Evidence", icon: Quote }] : []),
                { id: "overview" as const, label: "Overview", icon: Info },
                { id: "relations" as const, label: "Relations", icon: Network, count: card.relation_total },
                ...(card.profile ? [{ id: "profile" as const, label: "Profile", icon: FileCode2 }] : []),
              ]}
              value={tab}
              onChange={setTab}
            />
            <div
              ref={scroller}
              className={cn(
                "min-h-0 flex-1 overflow-y-auto overscroll-contain p-5 transition-opacity duration-150",
                loading && "pointer-events-none opacity-50"
              )}
            >
              {tab === "evidence" && card.evidence && <EvidenceBody card={card} onOpen={open} />}
              {tab === "overview" && <Overview card={card} />}
              {tab === "relations" && <Relations card={card} onOpen={open} />}
              {tab === "profile" && card.profile && <ProfileBody profile={card.profile} />}
            </div>
          </>
        )}
      </div>
    </div>,
    document.body
  );
}

function Header({
  card,
  loading,
  canGoBack,
  onBack,
  onClose,
  onShowOnMap,
}: {
  card: EntityCard;
  loading: boolean;
  canGoBack: boolean;
  onBack: () => void;
  onClose: () => void;
  onShowOnMap?: () => void;
}) {
  const visual = kindVisual(card.kind);
  return (
    <div className="flex items-start gap-3 border-b border-hairline px-5 py-4">
      {canGoBack && (
        <button onClick={onBack} className="k-btn k-btn-ghost k-btn-sm !px-1.5" aria-label="Back" title="Back">
          <ArrowLeft className="h-4 w-4" />
        </button>
      )}
      <span
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full"
        style={{ background: visual.bg, color: visual.fg }}
      >
        <visual.icon className="h-[18px] w-[18px]" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <StatusPill tone="neutral" size="sm" dot={false}>
            {kindStyle(card.kind).label}
          </StatusPill>
          {card.connection && (
            <StatusPill tone="neutral" size="sm" dot={false}>
              {card.connection}
            </StatusPill>
          )}
          {card.profiled && (
            <StatusPill tone="brand" size="sm">
              profiled
            </StatusPill>
          )}
          {card.discovered && (
            <StatusPill tone="brand" size="sm" dot={false}>
              found by the agent
            </StatusPill>
          )}
          {!card.known && (
            <StatusPill tone="warn" size="sm">
              unsynced
            </StatusPill>
          )}
        </div>
        <h2 id="entity-modal-title" className="mt-1.5 break-words text-[17px] font-bold text-ink">
          {card.label}
        </h2>
        {card.sublabel && card.sublabel !== card.label && (
          <p className="break-all font-mono text-[11.5px] text-ink-subtle">{card.sublabel}</p>
        )}
        {card.summary && <p className="mt-2 text-k-body leading-relaxed text-ink-2">{card.summary}</p>}
      </div>
      <div className="flex shrink-0 items-center gap-1">
        {loading && <Spinner />}
        {onShowOnMap && (
          <button onClick={onShowOnMap} className="k-btn k-btn-sm" title="Centre the map on this entity">
            <Crosshair className="h-3.5 w-3.5" />
            Show on map
          </button>
        )}
        <button onClick={onClose} className="k-btn k-btn-ghost k-btn-sm !px-1.5" aria-label="Close">
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

function Overview({ card }: { card: EntityCard }) {
  const attributes = Object.entries(card.attributes);
  const p = card.profile;
  return (
    <div className="space-y-4">
      {card.note && <Callout tone="warn">{card.note}</Callout>}
      {p && (p.purpose || p.data_product || p.tags.length > 0) && (
        <section className="space-y-2">
          {p.purpose && (
            <Labelled label="Purpose">
              <p className="text-k-body leading-relaxed text-ink">{p.purpose}</p>
            </Labelled>
          )}
          {p.data_product && (
            <Labelled label="Data product">
              <p className="text-k-body text-ink">{p.data_product}</p>
            </Labelled>
          )}
          {p.tags.length > 0 && (
            <Labelled label="Tags">
              <div className="flex flex-wrap gap-1">
                {p.tags.map((t) => (
                  <span key={t} className="rounded-full bg-neutral-soft px-2 py-0.5 text-[11px] text-ink-muted">
                    {t}
                  </span>
                ))}
              </div>
            </Labelled>
          )}
        </section>
      )}
      <Labelled label="Stored attributes">
        {attributes.length === 0 ? (
          <p className="text-k-caption text-ink-muted">None stored.</p>
        ) : (
          <dl className="divide-y divide-hairline rounded-lg border border-hairline">
            {attributes.map(([key, value]) => (
              <div key={key} className="flex items-baseline gap-3 px-3 py-2">
                <dt className="w-40 shrink-0 font-mono text-[11.5px] text-ink-muted">{key}</dt>
                <dd className="min-w-0 flex-1 break-words text-k-caption text-ink">{formatValue(value)}</dd>
              </div>
            ))}
          </dl>
        )}
      </Labelled>
    </div>
  );
}

function Relations({ card, onOpen }: { card: EntityCard; onOpen: (id: string) => void }) {
  if (card.relations.length === 0) {
    return <p className="py-6 text-center text-k-body text-ink-muted">No relationships recorded.</p>;
  }
  return (
    <div className="space-y-4">
      {card.relations.map((r) => (
        <section key={r.relation}>
          <div className="mb-1.5 flex items-center gap-2">
            <span
              className="h-2 w-2 shrink-0 rounded-full"
              style={{ backgroundColor: RELATION_GROUP_STYLE[r.group]?.stroke ?? "var(--neutral-dot)" }}
            />
            <span className="font-mono text-k-caption font-semibold text-brand-strong">{r.relation}</span>
            <span className="text-[11px] text-ink-subtle">{RELATION_GROUP_STYLE[r.group]?.label}</span>
            <span className="ml-auto rounded-full bg-neutral-soft px-1.5 text-[11px] font-semibold tabular-nums text-ink-muted">
              {r.count}
            </span>
          </div>
          <div className="space-y-1">
            {r.items.map((item) => (
              <RelatedRow key={item.id} item={item} reason={item.reason} onOpen={onOpen} />
            ))}
            {r.count > r.items.length && (
              <p className="px-2 text-k-caption text-ink-subtle">+{r.count - r.items.length} more</p>
            )}
          </div>
        </section>
      ))}
    </div>
  );
}

/** One related entity, as what it is. Clicking opens it in this modal. */
export function RelatedRow({
  item,
  reason,
  onOpen,
  compact = false,
}: {
  item: MapItem;
  reason?: LinkReason;
  onOpen: (id: string) => void;
  compact?: boolean;
}) {
  const visual = kindVisual(item.kind);
  return (
    <button
      type="button"
      onClick={() => onOpen(item.id)}
      title={item.id}
      className="group flex w-full items-start gap-2.5 rounded-lg border border-transparent px-2 py-1.5 text-left transition-colors hover:border-brand-border hover:bg-brand-soft"
    >
      <span
        className="mt-0.5 flex h-5 w-8 shrink-0 items-center justify-center rounded text-[8px] font-bold"
        style={{ background: visual.bg, color: visual.fg }}
      >
        {visual.code}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-k-caption font-medium text-ink group-hover:text-brand-strong">
          {item.label}
        </span>
        {item.sublabel && item.sublabel !== item.label && (
          <span className="block truncate font-mono text-[10.5px] text-ink-subtle">{item.sublabel}</span>
        )}
        {item.summary && (
          <span className={cn("mt-0.5 block text-[11.5px] leading-snug text-ink-muted", compact ? "line-clamp-1" : "line-clamp-2")}>
            {item.summary}
          </span>
        )}
        {reason && (
          <span className="mt-1 block rounded-md border border-hairline bg-sunken px-2 py-1 text-[11px] leading-snug text-ink-2">
            <span className="font-semibold">Why: </span>
            {reason.rationale}
            <span className="text-ink-subtle">
              {" "}
              · {Math.round(reason.confidence * 100)}% · {reason.status}
              {reason.evidence ? ` · ${reason.evidence.title}` : ""}
            </span>
          </span>
        )}
      </span>
    </button>
  );
}

function EvidenceBody({ card, onOpen }: { card: EntityCard; onOpen: (id: string) => void }) {
  const e = card.evidence!;
  const about = card.relations.flatMap((r) => r.items).find((i) => i.id === e.about);
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <Labelled label="Kind of evidence">
          <p className="text-k-body text-ink">{e.source_label}</p>
        </Labelled>
        <Labelled label="Observed">
          <p className="text-k-body text-ink">{e.observed_at ? new Date(e.observed_at).toLocaleString() : "—"}</p>
        </Labelled>
        {e.source && (
          <Labelled label="Source">
            <p className="break-all font-mono text-k-caption text-ink">{e.source}</p>
          </Labelled>
        )}
      </div>
      {about && (
        <Labelled label="About">
          <RelatedRow item={about} onOpen={onOpen} />
        </Labelled>
      )}
      {e.excerpt && (
        <Labelled label={e.truncated ? `What was seen (first ${e.excerpt.length.toLocaleString()} of ${e.size_chars.toLocaleString()} characters)` : "What was seen"}>
          <pre className="max-h-[42vh] overflow-auto whitespace-pre-wrap break-words rounded-lg border border-hairline bg-sunken p-3 font-mono text-[11.5px] leading-relaxed text-ink-2">
            {e.excerpt}
          </pre>
        </Labelled>
      )}
      <p className="flex items-center gap-1.5 text-[11px] text-ink-subtle">
        <FileSearch className="h-3.5 w-3.5" />
        E-mail addresses are masked.
      </p>
    </div>
  );
}

function ProfileBody({ profile }: { profile: NonNullable<EntityCard["profile"]> }) {
  const doc = profile.document ?? {};
  const shape = (doc.shape ?? {}) as { columns?: Array<{ name: string; type?: string; meaning?: string | null }> };
  const columns = Array.isArray(shape.columns) ? shape.columns : [];
  const grain = typeof doc.grain === "string" ? doc.grain : typeof doc.grain_key === "string" ? doc.grain_key : null;
  return (
    <div className="space-y-4">
      {grain && (
        <Labelled label="Grain">
          <p className="text-k-body text-ink">{grain}</p>
        </Labelled>
      )}
      {columns.length > 0 && (
        <Labelled label={`Columns (${columns.length})`}>
          <div className="overflow-hidden rounded-lg border border-hairline">
            {columns.map((c) => (
              <div key={c.name} className="flex items-baseline gap-3 border-b border-hairline px-3 py-1.5 last:border-b-0">
                <span className="w-48 shrink-0 truncate font-mono text-[11.5px] text-ink">{c.name}</span>
                <span className="w-24 shrink-0 truncate font-mono text-[11px] text-ink-subtle">{c.type}</span>
                <span className="min-w-0 flex-1 text-[11.5px] text-ink-muted">{c.meaning || "—"}</span>
              </div>
            ))}
          </div>
        </Labelled>
      )}
      {profile.yaml && (
        <Labelled label={`Full profile${profile.generated_at ? ` · ${new Date(profile.generated_at).toLocaleDateString()}` : ""}`}>
          <pre className="max-h-[40vh] overflow-auto whitespace-pre-wrap break-words rounded-lg border border-hairline bg-sunken p-3 font-mono text-[11.5px] leading-relaxed text-ink-2">
            {profile.yaml}
          </pre>
        </Labelled>
      )}
    </div>
  );
}

function Labelled({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-ink-subtle">{label}</p>
      {children}
    </div>
  );
}
