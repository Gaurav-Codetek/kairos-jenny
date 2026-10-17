"use client";

import { useEffect, useState } from "react";
import { ExternalLink, FileCode2, Info, Network, Sparkles, X } from "lucide-react";

import { kindVisual } from "@/components/graph/lineage-card";
import { Callout, EmptyState, Spinner, StatusPill, Tabs } from "@/components/kairos/ds";

import { getProfileYaml } from "@/lib/enrichment";
import {
  fetchEntityDetail,
  formatValue,
  kindStyle,
  RELATION_GROUP_STYLE,
  type EntityDetail,
} from "@/lib/warehouse";

interface EntityDetailPanelProps {
  entityId: string | null;
  onClose: () => void;
  onFocus: (entityId: string) => void;
}

type DetailTab = "overview" | "relations" | "profile";

/** Attributes that add noise rather than meaning in the overview. */
const HIDDEN_ATTRS = new Set(["id", "workspace_id", "created_at", "updated_at"]);

export function EntityDetailPanel({ entityId, onClose, onFocus }: EntityDetailPanelProps) {
  const [detail, setDetail] = useState<EntityDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState<DetailTab>("overview");

  const [yaml, setYaml] = useState<string | null>(null);
  const [yamlLoading, setYamlLoading] = useState(false);
  const [hasProfile, setHasProfile] = useState(false);

  useEffect(() => {
    if (!entityId) {
      setDetail(null);
      return;
    }
    setLoading(true);
    setTab("overview");
    fetchEntityDetail(entityId)
      .then(setDetail)
      .catch(() => setDetail(null))
      .finally(() => setLoading(false));

    // A profile only exists once the enrichment agent has reached this entity.
    setYaml(null);
    setYamlLoading(true);
    getProfileYaml(entityId)
      .then((response) => {
        setYaml(response.yaml);
        setHasProfile(true);
      })
      .catch(() => {
        setYaml(null);
        setHasProfile(false);
      })
      .finally(() => setYamlLoading(false));
  }, [entityId]);

  if (!entityId) return null;

  if (loading || !detail) {
    return (
      <aside className="flex h-full w-[400px] shrink-0 items-center justify-center border-l border-hairline bg-surface">
        <Spinner />
      </aside>
    );
  }

  const style = kindStyle(detail.kind);
  const visual = kindVisual(detail.kind);
  const attributes = Object.entries(detail.attributes).filter(
    ([key, value]) => !HIDDEN_ATTRS.has(key) && value !== null && value !== ""
  );

  return (
    <aside className="flex h-full w-[400px] shrink-0 flex-col border-l border-hairline bg-surface">
      <div key={detail.id} className="k-rise flex items-start gap-3 border-b border-hairline px-5 py-4">
        <span
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full"
          style={{ background: visual.bg, color: visual.fg }}
        >
          <visual.icon className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <StatusPill tone="neutral" size="sm" dot={false}>
              {style.label}
            </StatusPill>
            {!detail.known && (
              <StatusPill tone="warn" size="sm">
                unsynced
              </StatusPill>
            )}
            {hasProfile && (
              <StatusPill tone="brand" size="sm">
                profiled
              </StatusPill>
            )}
          </div>
          <p className="mt-1.5 break-all font-mono text-k-caption font-semibold text-ink">{detail.id.split(":").slice(-1)[0]}</p>
          <p className="break-all font-mono text-[11px] text-ink-subtle">{detail.id}</p>
        </div>
        <button type="button" onClick={onClose} className="k-btn k-btn-ghost k-btn-sm !px-1.5" aria-label="Close">
          <X className="h-4 w-4" />
        </button>
      </div>

      {detail.note && (
        <div className="border-b border-hairline px-5 py-3">
          <Callout tone="warn">{detail.note}</Callout>
        </div>
      )}

      <Tabs
        size="panel"
        items={[
          { id: "overview" as const, label: "Attributes", icon: Info, count: attributes.length },
          { id: "relations" as const, label: "Relations", icon: Network, count: detail.relation_total },
          { id: "profile" as const, label: "Profile", icon: FileCode2 },
        ]}
        value={tab}
        onChange={setTab}
      />

      <div key={tab} className="k-rise flex-1 overflow-y-auto p-4">
        {tab === "overview" && (
          <dl className="divide-y divide-hairline rounded-lg border border-hairline">
            {attributes.length === 0 && <p className="py-6 text-center text-k-body text-ink-muted">No stored attributes.</p>}
            {attributes.map(([key, value]) => (
              <div key={key} className="flex items-baseline gap-3 px-3 py-2">
                <dt className="w-32 shrink-0 font-mono text-[11.5px] text-ink-muted">{key}</dt>
                <dd className="min-w-0 flex-1 break-words text-k-caption text-ink">{formatValue(value)}</dd>
              </div>
            ))}
          </dl>
        )}

        {tab === "relations" && (
          <div className="space-y-2.5">
            {detail.relations.length === 0 && (
              <p className="py-6 text-center text-k-body text-ink-muted">No relationships recorded.</p>
            )}
            {detail.relations.map((relation) => {
              const groupStyle = RELATION_GROUP_STYLE[relation.group];
              return (
                <div key={relation.relation} className="kairos-panel p-3">
                  <div className="flex items-center gap-2">
                    <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: groupStyle?.stroke ?? "var(--neutral-dot)" }} />
                    <span className="font-mono text-k-caption font-semibold text-brand-strong">{relation.relation}</span>
                    <span className="ml-auto rounded-full bg-neutral-soft px-1.5 text-[11px] font-semibold tabular-nums text-ink-muted">
                      {relation.count}
                    </span>
                  </div>
                  <div className="mt-2 space-y-0.5">
                    {relation.sample.slice(0, 6).map((target) => (
                      <button
                        key={target}
                        type="button"
                        onClick={() => onFocus(target)}
                        title={target}
                        className="group flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-left transition-colors hover:bg-brand-soft"
                      >
                        <ExternalLink className="h-3 w-3 shrink-0 text-ink-subtle group-hover:text-brand" />
                        <span className="truncate font-mono text-k-caption text-ink-2 group-hover:text-brand-strong">
                          {target.split(":").slice(-1)[0]}
                        </span>
                      </button>
                    ))}
                    {relation.count > 6 && <p className="px-1.5 text-k-caption text-ink-subtle">+{relation.count - 6} more</p>}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {tab === "profile" && (
          <>
            {yamlLoading && (
              <div className="flex justify-center py-6">
                <Spinner />
              </div>
            )}
            {!yamlLoading && !yaml && (
              <EmptyState
                icon={Sparkles}
                title="No profile yet"
                action={
                  <a href="/enrichment" className="k-btn k-btn-primary k-btn-sm">
                    Open Enrichment
                  </a>
                }
              >
                Run the enrichment agent on this entity to generate its semantic profile and discover what it connects
                to.
              </EmptyState>
            )}
            {!yamlLoading && yaml && (
              <pre className="whitespace-pre-wrap break-words rounded-lg border border-hairline bg-sunken p-3 font-mono text-[11.5px] leading-relaxed text-ink-2">
                {yaml}
              </pre>
            )}
          </>
        )}
      </div>
    </aside>
  );
}
