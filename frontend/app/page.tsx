"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  Bot,
  Check,
  Database,
  Layers,
  Plug,
  Radio,
  Sparkles,
} from "lucide-react";

import {
  EmptyState,
  KairosMark,
  Meter,
  Panel,
  PanelLink,
  Stat,
  StatusPill,
  stagger,
} from "@/components/kairos/ds";
import { PageHeader } from "@/components/shell/app-shell";
import { getAgentStats, getContextHealth, type AgentStats, type ContextHealth } from "@/lib/agents";
import { fetchApi } from "@/lib/api";
import type { Incident } from "@/lib/incidents";
import { listWorkspaces, PLATFORM_META, relativeTime, type Workspace } from "@/lib/connections";
import { cn } from "@/lib/utils";

interface EntityMap {
  kinds: Array<{ kind: string; label: string; count: number }>;
  totals: { entities: number; lineage_edges: number };
}

type Health = ContextHealth["workspaces"][number];

export default function OverviewPage() {
  const [map, setMap] = useState<EntityMap | null>(null);
  const [workspaces, setWorkspaces] = useState<Workspace[] | null>(null);
  const [health, setHealth] = useState<Health[]>([]);
  const [stats, setStats] = useState<AgentStats | null>(null);
  const [incidents, setIncidents] = useState<Incident[] | null>(null);
  const [links, setLinks] = useState<number | undefined>(undefined);
  const [profiles, setProfiles] = useState<number | undefined>(undefined);

  useEffect(() => {
    fetchApi("/warehouse/map").then(setMap).catch(() => undefined);
    listWorkspaces().then(setWorkspaces).catch(() => setWorkspaces([]));
    getContextHealth().then((h) => setHealth(h.workspaces)).catch(() => undefined);
    getAgentStats(7).then(setStats).catch(() => undefined);
    fetchApi("/incidents?limit=6").then(setIncidents).catch(() => setIncidents([]));
    fetchApi("/enrichment/discovered")
      .then((d) =>
        setLinks((d.relation_types ?? []).reduce((n: number, r: { count: number }) => n + r.count, 0))
      )
      .catch(() => undefined);
    fetchApi("/enrichment/profiles")
      .then((p) => setProfiles((p.profiles ?? []).length))
      .catch(() => undefined);
  }, []);

  // Profiles on the connections shown (the profile list is capped, so it can't be counted from there).
  const profileCount = health.length
    ? health.reduce((n, w) => n + Object.values(w.profiles_by_kind ?? {}).reduce((a, b) => a + b, 0), 0)
    : profiles;
  const tables = health.reduce((n, w) => n + w.tables, 0);
  const profiled = health.reduce((n, w) => n + w.tables_profiled, 0);
  const verified = health.reduce((n, w) => n + w.tables_verified, 0);

  const structural = map?.kinds.filter((k) => ["catalog", "schema", "table", "column"].includes(k.kind)) ?? [];
  const operational = map?.kinds.filter((k) => ["job", "task", "run", "taskrun"].includes(k.kind)) ?? [];

  return (
    <>
      <PageHeader title="Overview" description="What Kairos knows about your platforms, and which agents are using it" />

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-6xl space-y-5 px-7 py-6">
          <LayerScene
            workspaces={workspaces}
            health={health}
            stats={stats}
            tables={tables}
            profiled={profiled}
            verified={verified}
            links={links}
          />

          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Stat
              index={0}
              icon={Layers}
              label="Entities mapped"
              value={map?.totals.entities}
              hint={map ? `${map.totals.lineage_edges.toLocaleString()} lineage edges` : undefined}
              href="/graph"
            />
            <Stat
              index={1}
              icon={Sparkles}
              label="Semantic profiles"
              value={profileCount}
              hint={`${verified.toLocaleString()} tables verified`}
              href="/enrichment"
            />
            <Stat
              index={2}
              icon={Bot}
              label="Agent calls · 7 days"
              value={stats?.calls}
              hint={stats ? `${(stats.error_rate * 100).toFixed(1)}% returned an error` : undefined}
              href="/agents?tab=activity"
            />
            <Stat
              index={3}
              icon={AlertTriangle}
              label="Recent failed runs"
              value={incidents?.length}
              tone="danger"
              hint={incidents?.length ? "Pipelines that need a look" : "Nothing failing"}
              href="/incidents"
            />
          </div>

          <div className="grid items-start gap-4 lg:grid-cols-2">
              <TrustCoverage health={health} />

              <Panel title="Warehouse composition" icon={Database} className="k-rise" style={stagger(5)}>
                {!map ? (
                  <p className="px-4 py-6 text-k-body text-ink-muted">Loading…</p>
                ) : (
                  <div className="grid gap-6 p-4 sm:grid-cols-2">
                    {(
                      [
                        ["Structure", structural],
                        ["Operations", operational],
                      ] as const
                    ).map(([label, group]) => {
                      const max = Math.max(1, ...group.map((k) => k.count));
                      return (
                        <div key={label}>
                          <p className="k-label mb-2.5">{label}</p>
                          <div className="space-y-2.5">
                            {group.map((k, i) => (
                              <div key={k.kind} className="grid grid-cols-[84px_1fr_64px] items-center gap-3">
                                <span className="truncate text-k-body text-ink-muted">{k.label}</span>
                                <Meter value={k.count} max={max} index={i} />
                                <span className="text-right text-k-body font-semibold tabular-nums text-ink">
                                  {k.count.toLocaleString()}
                                </span>
                              </div>
                            ))}
                            {group.length === 0 && <p className="text-k-body text-ink-subtle">Nothing synced yet.</p>}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </Panel>
          </div>
        </div>
      </div>
    </>
  );
}

/* ── The context layer, as the film draws it ────────────────────────
   Platforms on the left feed Kairos in the middle, which serves the
   agents on the right. Live connections are drawn in indigo with data
   travelling along them; idle ones are dashed. */

function channelLabel(id: string): { name: string; sub: string } {
  if (id === "mcp") return { name: "MCP server", sub: "v1 · all connections" };
  if (id === "mcp-v2") return { name: "MCP server v2", sub: "Consolidated tools" };
  if (id === "rest") return { name: "REST API", sub: "Direct calls" };
  if (id === "eval") return { name: "Evaluations", sub: "Test harness" };
  if (id.startsWith("mcp:")) return { name: id.slice(4), sub: "Connection endpoint" };
  return { name: id, sub: "Channel" };
}

const hCurve = (a: [number, number], b: [number, number]) => {
  const dx = (b[0] - a[0]) / 2;
  return `M ${a[0]} ${a[1]} C ${a[0] + dx} ${a[1]}, ${b[0] - dx} ${b[1]}, ${b[0]} ${b[1]}`;
};

function LayerScene({
  workspaces,
  health,
  stats,
  tables,
  profiled,
  verified,
  links,
}: {
  workspaces: Workspace[] | null;
  health: Health[];
  stats: AgentStats | null;
  tables: number;
  profiled: number;
  verified: number;
  links: number | undefined;
}) {
  const healthById = new Map(health.map((h) => [h.workspace_id, h]));
  const sources = (workspaces ?? [])
    .map((w) => ({ w, h: healthById.get(w.id) }))
    .sort((a, b) => (b.h?.tables ?? 0) - (a.h?.tables ?? 0));
  const shownSources = sources.slice(0, 4);
  const moreSources = sources.length - shownSources.length;

  const channels = Object.entries(stats?.by_channel ?? {})
    .filter(([, c]) => c.calls > 0)
    .sort((a, b) => b[1].calls - a[1].calls)
    .slice(0, 4);

  const box = useRef<HTMLDivElement>(null);
  const hub = useRef<HTMLDivElement>(null);
  const left = useRef<(HTMLElement | null)[]>([]);
  const right = useRef<(HTMLElement | null)[]>([]);
  const [edges, setEdges] = useState<{ key: string; d: string; live: boolean }[]>([]);

  const liveLeft = shownSources.map(({ w, h }) => Boolean(w.last_synced_at && (h?.tables ?? 0) > 0));
  const liveKey = `${liveLeft.join(",")}|${channels.length}|${workspaces?.length ?? -1}|${stats ? 1 : 0}`;

  const measure = useCallback(() => {
    const root = box.current?.getBoundingClientRect();
    const h = hub.current?.getBoundingClientRect();
    if (!root || !h) return;
    const out: { key: string; d: string; live: boolean }[] = [];
    const fan = (i: number, n: number) => (i - (n - 1) / 2) * 16;
    const hubY = h.top + h.height / 2 - root.top;
    const L = left.current.slice(0, Math.max(1, shownSources.length));
    L.forEach((el, i) => {
      if (!el) return;
      const r = el.getBoundingClientRect();
      out.push({
        key: `l${i}`,
        d: hCurve([r.right - root.left, r.top + r.height / 2 - root.top], [h.left - root.left, hubY + fan(i, L.length)]),
        live: liveLeft[i] ?? false,
      });
    });
    const R = right.current.slice(0, Math.max(1, channels.length));
    R.forEach((el, i) => {
      if (!el) return;
      const r = el.getBoundingClientRect();
      out.push({
        key: `r${i}`,
        d: hCurve([h.right - root.left, hubY + fan(i, R.length)], [r.left - root.left, r.top + r.height / 2 - root.top]),
        live: channels.length > 0,
      });
    });
    setEdges(out);
    // liveKey captures everything measure reads besides the DOM.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveKey, shownSources.length]);

  useLayoutEffect(() => {
    measure();
    // The cards rise into place; measure again once they have landed.
    const settle = window.setTimeout(measure, 1100);
    const ro = new ResizeObserver(measure);
    if (box.current) ro.observe(box.current);
    return () => {
      window.clearTimeout(settle);
      ro.disconnect();
    };
  }, [measure]);

  return (
    <section className="kairos-panel k-rise relative overflow-hidden" style={stagger(0)}>
      <div className="flex items-center gap-2.5 border-b border-hairline px-5 py-3">
        <Radio className="h-4 w-4 text-ink-subtle" />
        <h2 className="text-k-title font-semibold text-ink">The context layer</h2>
        <span className="text-k-caption text-ink-muted">Platforms in, agents out</span>
      </div>

      <div ref={box} className="kairos-canvas relative px-6 py-7">
        <svg className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden>
          {edges.map((e, i) =>
            e.live ? (
              <path
                key={e.key}
                d={e.d}
                pathLength={1}
                className="k-draw"
                style={stagger(i)}
                fill="none"
                stroke="var(--brand)"
                strokeOpacity={0.85}
                strokeWidth={2}
              />
            ) : (
              <path key={e.key} d={e.d} fill="none" stroke="var(--edge)" strokeWidth={1.5} strokeDasharray="5 6" />
            )
          )}
        </svg>
        {edges
          .filter((e) => e.live)
          .flatMap((e, i) =>
            [0, 1].map((k) => (
              <span
                key={`${e.key}-${k}`}
                aria-hidden
                className="k-travel pointer-events-none absolute left-0 top-0 h-2 w-2 rounded-full bg-brand opacity-0"
                style={{ offsetPath: `path('${e.d}')`, offsetRotate: "0deg", ...stagger(i + k * 1.5) }}
              />
            ))
          )}

        <div className="relative grid grid-cols-[minmax(0,1fr)_260px_minmax(0,1fr)] items-center gap-16">
          {/* Platforms */}
          <div className="space-y-2.5">
            <p className="k-label">Platforms</p>
            {workspaces === null && <SkeletonCard />}
            {workspaces?.length === 0 && (
              <Link
                ref={(el) => {
                  left.current[0] = el;
                }}
                href="/connections"
                className="kairos-panel k-hover flex items-center gap-3 border-dashed px-3.5 py-3"
              >
                <span className="flex h-9 w-9 items-center justify-center rounded-full bg-brand-soft text-brand">
                  <Plug className="h-4 w-4" />
                </span>
                <span>
                  <span className="block text-k-title font-semibold text-ink">Connect a platform</span>
                  <span className="block text-k-caption text-ink-muted">Databricks or Snowflake</span>
                </span>
              </Link>
            )}
            {shownSources.map(({ w, h }, i) => (
              <Link
                key={w.id}
                ref={(el) => {
                  left.current[i] = el;
                }}
                href="/connections"
                className="kairos-panel k-hover k-rise flex items-center gap-3 px-3.5 py-3"
                style={stagger(i + 1)}
              >
                <PlatformGlyph platform={w.platform} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-k-title font-semibold text-ink">{w.name}</span>
                  <span className="block truncate text-k-caption text-ink-muted">
                    {PLATFORM_META[w.platform]?.label ?? w.platform}
                    {h && h.tables > 0 ? ` · ${h.tables.toLocaleString()} tables` : ""}
                  </span>
                </span>
                {w.last_synced_at ? (
                  <StatusPill tone="neutral" size="sm">
                    {relativeTime(w.last_synced_at)}
                  </StatusPill>
                ) : (
                  <StatusPill tone="neutral" size="sm" dot={false}>
                    Not synced
                  </StatusPill>
                )}
              </Link>
            ))}
            {moreSources > 0 && (
              <Link href="/connections" className="block pl-1 text-k-caption font-medium text-brand">
                +{moreSources} more
              </Link>
            )}
          </div>

          {/* Kairos */}
          <div
            ref={hub}
            className="kairos-panel k-pop relative px-5 py-5"
            style={{ ...stagger(2), borderColor: "var(--brand-border)" }}
          >
            <div className="flex flex-col items-center text-center">
              <span className="relative flex h-10 w-10 items-center justify-center">
                <span className="k-pulse absolute inset-1 rounded-full bg-brand/30" />
                <KairosMark size={34} />
              </span>
              <p className="mt-2 text-[17px] font-bold text-ink">Kairos</p>
              <p className="text-k-caption text-ink-muted">Context layer</p>
            </div>
            <div className="my-4 h-px bg-hairline" />
            <ul className="space-y-2">
              {[
                `${tables.toLocaleString()} tables mapped`,
                `${profiled.toLocaleString()} profiled, ${verified.toLocaleString()} verified`,
                `${(links ?? 0).toLocaleString()} links discovered`,
              ].map((t, i) => (
                <li
                  key={i}
                  className="k-rise flex items-center gap-2 text-k-body font-medium text-ink"
                  style={stagger(i + 4)}
                >
                  <Check className="h-4 w-4 shrink-0" style={{ color: "var(--ok-dot)" }} strokeWidth={2.6} />
                  {t}
                </li>
              ))}
            </ul>
            <div className="mt-4 flex flex-wrap justify-center gap-1.5">
              {["Read-only", "Every call audited"].map((t, i) => (
                <span
                  key={t}
                  className="k-pop inline-flex h-6 items-center gap-1 rounded-full bg-brand-soft px-2.5 text-[11.5px] font-semibold text-brand-strong"
                  style={stagger(i + 7)}
                >
                  <Check className="h-3 w-3" strokeWidth={3} />
                  {t}
                </span>
              ))}
            </div>
          </div>

          {/* Agents */}
          <div className="space-y-2.5">
            <p className="k-label">Agents · last 7 days</p>
            {stats === null && <SkeletonCard />}
            {stats && channels.length === 0 && (
              <Link
                ref={(el) => {
                  right.current[0] = el;
                }}
                href="/agents"
                className="kairos-panel k-hover flex items-center gap-3 border-dashed px-3.5 py-3"
              >
                <span className="flex h-9 w-9 items-center justify-center rounded-full bg-brand-soft text-brand">
                  <Bot className="h-4 w-4" />
                </span>
                <span>
                  <span className="block text-k-title font-semibold text-ink">Connect an agent</span>
                  <span className="block text-k-caption text-ink-muted">Copy the MCP address</span>
                </span>
              </Link>
            )}
            {channels.map(([id, c], i) => {
              const { name, sub } = channelLabel(id);
              return (
                <Link
                  key={id}
                  ref={(el) => {
                    right.current[i] = el;
                  }}
                  href="/agents?tab=activity"
                  className="kairos-panel k-hover k-rise flex items-center gap-3 px-3.5 py-3"
                  style={stagger(i + 3)}
                >
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand">
                    <Bot className="h-4 w-4" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-k-title font-semibold text-ink">{name}</span>
                    <span className="block truncate text-k-caption text-ink-muted">{sub}</span>
                  </span>
                  <span className="text-right">
                    <span className="block text-k-title font-bold tabular-nums text-ink">{c.calls.toLocaleString()}</span>
                    <span className={cn("block text-[11px]", c.errors ? "text-warn" : "text-ink-subtle")}>
                      {c.errors ? `${c.errors} ${c.errors === 1 ? "error" : "errors"}` : "calls"}
                    </span>
                  </span>
                </Link>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}

function PlatformGlyph({ platform }: { platform: string }) {
  return (
    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-soft text-[13px] font-bold text-brand">
      {platform === "snowflake" ? "S" : platform === "databricks" ? "D" : <Database className="h-4 w-4" />}
    </span>
  );
}

function SkeletonCard() {
  return <div className="kairos-panel h-[62px] animate-pulse bg-sunken" />;
}

/* ── Trust coverage: how much of each connection Kairos can vouch for ── */

function TrustCoverage({ health }: { health: Health[] }) {
  const rows = health.filter((h) => h.tables > 0);
  return (
    <Panel
      title="Trust coverage"
      icon={Sparkles}
      meta="Verified, profiled or only synced"
      action={<PanelLink href="/enrichment">Enrich</PanelLink>}
      className="k-rise"
      style={stagger(4)}
    >
      {rows.length === 0 ? (
        <EmptyState icon={Plug} title="Nothing synced yet">
          Sync a connection and its tables appear here as Synced, then Profiled and Verified as enrichment runs.
        </EmptyState>
      ) : (
        <div className="divide-y divide-hairline">
          {rows.map((h, i) => {
            const v = h.tables_verified;
            const p = Math.max(0, h.tables_profiled - v);
            const s = Math.max(0, h.tables - h.tables_profiled);
            const parts: [number, string][] = [
              [v, "var(--ok-dot)"],
              [p, "var(--warn-dot)"],
              [s, "var(--hairline-strong)"],
            ];
            return (
              <div key={h.workspace_id} className="px-4 py-3.5">
                <div className="mb-2.5 flex items-center gap-3">
                  <span className="min-w-0 flex-1 truncate text-k-title font-semibold text-ink">{h.name}</span>
                  <span className="text-k-caption tabular-nums text-ink-muted">{h.tables.toLocaleString()} tables</span>
                </div>
                <div className="flex h-2 gap-0.5 overflow-hidden rounded-full">
                  {parts
                    .filter(([n]) => n > 0)
                    .map(([n, c], k) => (
                      <span
                        key={k}
                        className="k-grow h-full"
                        style={{ width: `${(n / h.tables) * 100}%`, background: c, ...stagger(i + k) }}
                      />
                    ))}
                </div>
                <div className="mt-2.5 flex flex-wrap gap-1.5">
                  <StatusPill tone="ok" size="sm">
                    Verified {v.toLocaleString()}
                  </StatusPill>
                  <StatusPill tone="warn" size="sm">
                    Profiled {p.toLocaleString()}
                  </StatusPill>
                  <StatusPill tone="neutral" size="sm">
                    Synced {s.toLocaleString()}
                  </StatusPill>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Panel>
  );
}
