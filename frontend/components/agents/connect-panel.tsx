"use client";

import { useEffect, useState } from "react";
import { Globe, KeyRound, Plug, Radio, ShieldAlert, ShieldCheck, type LucideIcon } from "lucide-react";

import { Callout, Panel, SectionIntro, StatusPill, Tabs, stagger } from "@/components/kairos/ds";
import { getConnectInfo, type ConnectInfo } from "@/lib/agents";
import { CodeBlock, CopyButton } from "./bits";

const TABS = [
  { id: "claude_code", label: "Claude Code" },
  { id: "mcp_json", label: "MCP config (Claude Desktop, Cursor, …)" },
  { id: "python_mcp", label: "Python (MCP SDK)" },
  { id: "rest_curl", label: "REST (any HTTP client)" },
] as const;

function Endpoint({
  icon: Icon,
  title,
  meta,
  url,
  copy,
  copyLabel,
  index,
}: {
  icon: LucideIcon;
  title: string;
  meta: string;
  url: string;
  copy: string;
  copyLabel?: string;
  index: number;
}) {
  return (
    <div className="kairos-panel k-hover k-rise flex items-center gap-3 px-3.5 py-3" style={stagger(index)}>
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand">
        <Icon className="h-4 w-4" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-k-body font-semibold text-ink">{title}</span>
          <span className="truncate text-k-caption text-ink-subtle">{meta}</span>
        </div>
        <code className="mt-0.5 block truncate font-mono text-k-caption text-ink-2">{url}</code>
      </div>
      <CopyButton text={copy} label={copyLabel} />
    </div>
  );
}

export function ConnectPanel({ onCreateKey }: { onCreateKey: () => void }) {
  const [info, setInfo] = useState<ConnectInfo | null>(null);
  const [tab, setTab] = useState<(typeof TABS)[number]["id"]>("claude_code");

  useEffect(() => {
    getConnectInfo().then(setInfo).catch(() => setInfo(null));
  }, []);

  if (!info) return <p className="text-k-body text-ink-muted">Loading…</p>;
  const snippet = tab === "mcp_json" ? JSON.stringify(info.snippets.mcp_json, null, 2) : String(info.snippets[tab]);
  const secure = info.auth_mode === "required";
  let i = 0;

  return (
    <div className="space-y-5">
      <Panel bodyClassName="p-5">
        <SectionIntro title="One endpoint for every agent">
          Point any agent at Kairos once. It gets the whole map of this platform (what each table means, how far to
          trust it, how to join and query it) with no per-agent setup, prompts or semantic modelling.
        </SectionIntro>

        <p className="k-label mb-2 mt-5">All connections</p>
        <div className="grid gap-2.5 md:grid-cols-2">
          <Endpoint icon={Radio} title="MCP server" meta="v1 · 20 tools" url={info.mcp_url} copy={info.mcp_url} index={i++} />
          {info.mcp_v2_url && (
            <Endpoint
              icon={Radio}
              title="MCP server v2"
              meta="11 consolidated tools"
              url={info.mcp_v2_url}
              copy={info.mcp_v2_url}
              index={i++}
            />
          )}
          <Endpoint
            icon={Globe}
            title="REST context API"
            meta="OpenAPI"
            url={info.rest_base}
            copy={info.openapi_url}
            copyLabel="Spec"
            index={i++}
          />
        </div>

        {(info.connections ?? []).length > 0 && (
          <>
            <p className="k-label mb-2 mt-5">One connection only</p>
            <div className="grid gap-2.5 md:grid-cols-2">
              {(info.connections ?? []).map((c) => (
                <Endpoint
                  key={c.slug}
                  icon={Plug}
                  title={c.name}
                  meta={`${c.platform} · ${c.tools.length} tools`}
                  url={c.mcp_url}
                  copy={c.mcp_url}
                  index={i++}
                />
              ))}
            </div>
          </>
        )}

        <Callout tone={secure ? "ok" : "warn"} icon={secure ? ShieldCheck : ShieldAlert} className="mt-5">
          Agent keys are <b>{info.auth_mode}</b>.{" "}
          {secure
            ? "Every call must carry a valid key; each agent sees only the workspaces its key grants."
            : "Calls without a key are allowed and audited as “anonymous”. Set AGENT_AUTH_MODE=required for production."}
        </Callout>
      </Panel>

      <Panel>
        <Tabs
          size="panel"
          items={TABS}
          value={tab}
          onChange={setTab}
          trailing={
            <button onClick={onCreateKey} className="k-btn k-btn-primary k-btn-sm">
              <KeyRound className="h-3.5 w-3.5" /> Create an agent key
            </button>
          }
        />
        <div className="p-4">
          <CodeBlock code={snippet} />
          <p className="mt-2.5 text-k-caption text-ink-muted">
            Replace <code className="font-mono text-ink-2">&lt;agent key&gt;</code> with a key from the Agents &amp; keys
            tab. On connect the agent receives Kairos&apos;s instructions and tools, the{" "}
            <code className="font-mono text-ink-2">kairos://overview</code> resource and a{" "}
            <code className="font-mono text-ink-2">start_here</code> prompt.
          </p>
        </div>
      </Panel>

      <Panel bodyClassName="p-5">
        <SectionIntro title="What a newly connected agent does" />
        <ol className="relative mt-5 grid gap-3 md:grid-cols-5">
          <span aria-hidden className="absolute left-[10%] right-[10%] top-[15px] hidden h-px bg-brand-border md:block" />
          {[
            ["get_overview()", "learns what the platform covers"],
            ["find_data(question)", "finds data by meaning"],
            ["get_context(id)", "meaning, trust, grain, columns, SQL, caveats"],
            ["find_join_path(a, b)", "joins on evidence, not guesses"],
            ["report_context_issue()", "fixes the map for every agent"],
          ].map(([tool, what], n) => (
            <li key={tool} className="k-rise relative flex flex-col items-center text-center" style={stagger(n)}>
              <span className="relative z-10 flex h-8 w-8 items-center justify-center rounded-full border-2 border-surface bg-brand text-k-caption font-bold text-white">
                {n + 1}
              </span>
              <code className="mt-2.5 font-mono text-k-caption font-semibold text-ink">{tool}</code>
              <span className="mt-0.5 text-k-caption text-ink-muted">{what}</span>
            </li>
          ))}
        </ol>
        <div className="mt-5 flex justify-center">
          <StatusPill tone="brand" dot={false}>
            Five calls from zero to a trusted answer
          </StatusPill>
        </div>
      </Panel>
    </div>
  );
}
