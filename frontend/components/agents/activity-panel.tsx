"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, XCircle } from "lucide-react";

import { CHANNELS, getActivity, getAgentStats, type ActivityRow, type AgentStats } from "@/lib/agents";
import { Segmented, stagger } from "@/components/kairos/ds";
import { Empty, timeAgo } from "./bits";

const CHANNEL_LABEL: Record<string, string> = Object.fromEntries(CHANNELS.filter((c) => c.id).map((c) => [c.id, c.label]));

function usd(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (value === 0) return "$0";
  return value < 0.01 ? `$${value.toFixed(5)}` : `$${value.toFixed(4)}`;
}

function tokens(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value >= 10000 ? `${(value / 1000).toFixed(1)}K` : value.toLocaleString();
}

function argSummary(row: ActivityRow): string {
  const a = row.arguments || {};
  if (typeof a.sql === "string") return a.sql.replace(/\s+/g, " ").trim();
  if (row.tool === "list_incidents") return a.pipeline ? `pipeline: ${a.pipeline}` : "all pipelines";
  const v = (a.question ?? a.entity_id ?? a.from_entity ?? a.query ?? "") as string;
  const extra = a.to_entity ? ` → ${String(a.to_entity).split(":").pop()}` : "";
  const text = typeof v === "string" && v.includes(":") && !a.question ? v.split(":").pop() : v;
  return `${text ?? ""}${extra}`;
}

export function ActivityPanel() {
  const [rows, setRows] = useState<ActivityRow[]>([]);
  const [stats, setStats] = useState<AgentStats | null>(null);
  const [channel, setChannel] = useState("");

  useEffect(() => {
    const load = () => {
      getActivity(80, channel).then((r) => setRows(r.activity)).catch(() => undefined);
      getAgentStats(7, channel).then(setStats).catch(() => undefined);
    };
    load();
    const h = window.setInterval(load, 5000);
    return () => window.clearInterval(h);
  }, [channel]);

  const compared = ["mcp", "mcp-v2"].filter((c) => stats?.by_channel?.[c]);

  const tools = stats ? Object.entries(stats.by_tool).sort((a, b) => b[1] - a[1]) : [];
  const maxTool = tools.length ? tools[0][1] : 1;

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
      <section className="kairos-panel overflow-hidden">
        <div className="flex flex-wrap items-center gap-3 border-b border-hairline px-5 py-3.5">
          <div>
            <h3 className="text-k-title font-semibold text-ink">Every call, by every agent</h3>
            <p className="flex items-center gap-1.5 text-k-caption text-ink-muted">
              <span className="relative flex h-2 w-2">
                <span className="k-pulse absolute inset-0 rounded-full bg-ok-dot" />
                <span className="relative h-2 w-2 rounded-full bg-ok-dot" />
              </span>
              Live · refreshes every 5 seconds
            </p>
          </div>
          <Segmented
            className="ml-auto"
            items={CHANNELS.map((c) => ({ id: c.id, label: c.label }))}
            value={channel}
            onChange={setChannel}
          />
        </div>
        {rows.length === 0 && <Empty>No agent has called Kairos yet.</Empty>}
        <div className="max-h-[560px] overflow-auto">
          <table className="w-full min-w-[680px] table-fixed text-k-caption">
            <colgroup>
              <col className="w-9" />
              <col className="w-[110px]" />
              <col className="w-[132px]" />
              <col />
              <col className="w-[68px]" />
              <col className="w-[64px]" />
              <col className="w-[76px]" />
              <col className="w-[72px]" />
            </colgroup>
            <thead className="sticky top-0 z-10 bg-surface">
              <tr className="k-label border-b border-hairline">
                <th className="py-2 pl-4" />
                <th className="py-2 pl-2 text-left font-medium">Agent</th>
                <th className="py-2 pl-2 text-left font-medium">Tool</th>
                <th className="py-2 pl-2 text-left font-medium">Asked</th>
                <th className="py-2 pl-2 text-right font-medium">Time</th>
                <th className="py-2 pl-2 text-right font-medium" title="Tokens the call added to the agent's context: arguments + response">Tokens</th>
                <th className="py-2 pl-2 text-right font-medium" title="Estimated cost to the agent at the configured model's rates">Cost</th>
                <th className="py-2 pl-2 pr-4 text-right font-medium">When</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="k-row border-b border-hairline last:border-b-0">
                  <td className="py-2.5 pl-4">
                    {r.ok ? (
                      <CheckCircle2 className="h-4 w-4" style={{ color: "var(--ok-dot)" }} />
                    ) : (
                      <XCircle className="h-4 w-4" style={{ color: "var(--danger-dot)" }} />
                    )}
                  </td>
                  <td className="truncate py-2 pl-2 text-ink" title={r.agent}>{r.agent}</td>
                  <td className="truncate py-2 pl-2 font-mono text-k-caption text-ink" title={`${r.tool} · ${CHANNEL_LABEL[r.channel] ?? r.channel}`}>
                    {r.channel === "mcp-v2" && (
                      <span className="mr-1.5 rounded-full bg-brand-soft px-1.5 py-px font-sans text-[10.5px] font-semibold text-brand-strong">v2</span>
                    )}
                    {r.tool}
                  </td>
                  <td className="truncate py-2 pl-2 text-ink-muted" title={r.error || argSummary(r)}>
                    {r.error ? <span className="text-danger">{r.error}</span> : argSummary(r)}
                  </td>
                  <td className="whitespace-nowrap py-2 pl-2 text-right tabular-nums text-ink-subtle">{r.duration_ms} ms</td>
                  <td
                    className="whitespace-nowrap py-2 pl-2 text-right tabular-nums text-ink"
                    title={r.tokens === null ? "Recorded before token tracking" : `${r.args_tokens} in arguments, ${r.result_tokens} in the response`}
                  >
                    {tokens(r.tokens)}
                  </td>
                  <td className="whitespace-nowrap py-2 pl-2 text-right tabular-nums text-ink-muted">{usd(r.est_cost_usd)}</td>
                  <td className="whitespace-nowrap py-2 pl-2 pr-4 text-right text-ink-subtle">{timeAgo(r.at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <div className="space-y-4">
        {compared.length === 2 && (
          <section className="kairos-panel k-rise p-4">
            <p className="text-k-caption font-medium text-ink-muted">MCP v1 vs v2 · last 7 days</p>
            <table className="mt-2 w-full text-k-caption tabular-nums">
              <thead>
                <tr className="text-[11px] text-ink-subtle">
                  <th className="text-left font-medium" />
                  <th className="text-right font-medium">Calls</th>
                  <th className="text-right font-medium">Tools</th>
                  <th className="text-right font-medium">Avg tok</th>
                  <th className="text-right font-medium">Errors</th>
                </tr>
              </thead>
              <tbody>
                {compared.map((c) => {
                  const s = stats!.by_channel[c];
                  return (
                    <tr key={c} className="border-t border-hairline">
                      <td className="py-1 text-ink">{CHANNEL_LABEL[c]}</td>
                      <td className="py-1 text-right text-ink">{s.calls}</td>
                      <td className="py-1 text-right text-ink-muted">{s.tools_used}</td>
                      <td className="py-1 text-right text-ink-muted">{tokens(s.avg_tokens)}</td>
                      <td className="py-1 text-right text-ink-muted">{s.errors}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>
        )}
        <section className="kairos-panel k-rise p-4" style={stagger(1)}>
          <p className="text-k-caption font-medium text-ink-muted">Last 7 days{channel ? ` · ${CHANNEL_LABEL[channel]}` : ""}</p>
          <p className="mt-1 text-k-stat font-bold tabular-nums text-ink">{(stats?.calls ?? 0).toLocaleString()} calls</p>
          <p className="text-k-caption tabular-nums text-ink-subtle">
            {Object.keys(stats?.by_agent ?? {}).length} agent(s) · {((stats?.error_rate ?? 0) * 100).toFixed(1)}% errors
          </p>
          <div className="mt-3 grid grid-cols-2 gap-2 border-t border-hairline pt-3">
            <div>
              <p className="text-k-caption text-ink-muted">Tokens to agents</p>
              <p className="text-[16px] font-semibold tabular-nums text-ink">
                {tokens((stats?.tokens.args ?? 0) + (stats?.tokens.results ?? 0))}
              </p>
            </div>
            <div>
              <p className="text-k-caption text-ink-muted">Est. cost</p>
              <p className="text-[16px] font-semibold tabular-nums text-ink">{usd(stats?.est_cost_usd ?? 0)}</p>
            </div>
          </div>
          {stats?.pricing && (
            <p className="mt-1 text-[11px] leading-snug text-ink-subtle" title={stats.pricing.basis}>
              At {stats.pricing.model} rates: ${stats.pricing.input_per_m}/M in · ${stats.pricing.output_per_m}/M out
            </p>
          )}
          <div className="mt-3 space-y-1.5">
            {tools.map(([tool, n]) => (
              <div key={tool}>
                <div className="flex justify-between gap-2 text-k-caption">
                  <span className="font-mono text-ink">{tool}</span>
                  <span className="tabular-nums text-ink-muted">
                    {n} call{n === 1 ? "" : "s"}
                    {stats?.tool_usage[tool]?.avg_tokens ? ` · ${tokens(stats.tool_usage[tool].avg_tokens)} tokens avg` : ""}
                  </span>
                </div>
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-neutral-soft">
                  <div className="k-grow h-full rounded-full bg-brand" style={{ width: `${(n / maxTool) * 100}%` }} />
                </div>
              </div>
            ))}
          </div>
        </section>
        <section className="kairos-panel k-rise p-4" style={stagger(2)}>
          <p className="text-k-caption font-medium text-ink-muted">Most requested context</p>
          {(stats?.most_requested ?? []).length === 0 && <p className="mt-1 text-k-caption text-ink-subtle">Nothing yet.</p>}
          <ol className="mt-2 space-y-1.5">
            {(stats?.most_requested ?? []).map((m) => (
              <li key={m.entity_id} className="flex justify-between gap-2 text-k-caption">
                <span className="truncate text-ink" title={m.entity_id}>{m.name}</span>
                <span className="tabular-nums text-ink-muted">{m.count}</span>
              </li>
            ))}
          </ol>
        </section>
      </div>
    </div>
  );
}
