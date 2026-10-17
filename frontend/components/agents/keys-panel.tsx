"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Bot, KeyRound, RotateCw, Ban } from "lucide-react";

import {
  createAgent,
  listAgents,
  revokeAgent,
  rotateAgentKey,
  type AgentClient,
  type AgentWithKey,
} from "@/lib/agents";
import { listWorkspaces, type Workspace } from "@/lib/connections";
import { Chip, Field, Spinner, StatusPill } from "@/components/kairos/ds";
import { CodeBlock, Empty, timeAgo } from "./bits";

export function KeysPanel({ startCreating = false }: { startCreating?: boolean }) {
  const [agents, setAgents] = useState<AgentClient[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [creating, setCreating] = useState(startCreating);
  const [fresh, setFresh] = useState<AgentWithKey | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [scope, setScope] = useState<string[]>([]);
  const [canQuery, setCanQuery] = useState(false);
  const [canFiles, setCanFiles] = useState(false);

  const reload = useCallback(() => {
    listAgents().then((r) => setAgents(r.agents)).catch(() => undefined);
  }, []);

  useEffect(() => {
    reload();
    listWorkspaces().then(setWorkspaces).catch(() => undefined);
  }, [reload]);

  async function submit() {
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const made = await createAgent({
        name: name.trim(),
        description: description.trim() || undefined,
        workspace_ids: scope.length ? scope : null,
        scopes: ["read", ...(canQuery ? ["query"] : []), ...(canFiles ? ["files"] : [])],
      });
      setFresh(made);
      setCreating(false);
      setName("");
      setDescription("");
      setScope([]);
      setCanQuery(false);
      setCanFiles(false);
      reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create the agent");
    } finally {
      setBusy(false);
    }
  }

  const wsName = (id: string) => workspaces.find((w) => w.id === id)?.name ?? id.slice(0, 8);

  return (
    <div className="space-y-4">
      {fresh && (
        <section className="kairos-panel k-pop p-5" style={{ borderColor: "var(--ok-dot)" }}>
          <div className="flex items-start gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-ok-soft text-ok">
              <KeyRound className="h-4 w-4" />
            </span>
            <div className="min-w-0 flex-1">
              <h3 className="text-k-title font-semibold text-ink">Key for {fresh.name}</h3>
              <p className="flex items-center gap-1 text-k-caption font-medium text-warn">
                <AlertTriangle className="h-3.5 w-3.5" /> Shown only once. Kairos stores only a hash of it.
              </p>
              <CodeBlock className="mt-2" code={fresh.key} />
            </div>
            <button onClick={() => setFresh(null)} className="k-btn k-btn-sm">
              Done
            </button>
          </div>
        </section>
      )}

      <section className="kairos-panel overflow-hidden">
        <div className="flex items-center gap-4 border-b border-hairline px-5 py-3.5">
          <div>
            <h3 className="text-k-title font-semibold text-ink">Agents</h3>
            <p className="text-k-caption text-ink-muted">
              One key per agent: its calls are attributed, its workspaces limited, and it can be revoked on its own.
            </p>
          </div>
          {!creating && (
            <button
              onClick={() => setCreating(true)}
              className="k-btn k-btn-primary ml-auto"
            >
              <KeyRound className="h-3.5 w-3.5" /> New agent
            </button>
          )}
        </div>

        {creating && (
          <div className="k-rise space-y-4 border-b border-hairline bg-sunken px-5 py-5">
            <div className="grid gap-3 md:grid-cols-2">
              <Field label="Name">
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Sales analytics copilot"
                  className="k-input"
                />
              </Field>
              <Field label="What it does (optional)">
                <input
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Answers revenue questions for the BI team"
                  className="k-input"
                />
              </Field>
            </div>
            <div>
              <span className="mb-1.5 block text-k-caption font-semibold text-ink-2">Workspaces it may see</span>
              <div className="flex flex-wrap gap-2">
                {workspaces.map((w) => {
                  const on = scope.includes(w.id);
                  return (
                    <Chip key={w.id} on={on} onClick={() => setScope((s) => (on ? s.filter((x) => x !== w.id) : [...s, w.id]))} className={on ? "" : "bg-surface"}>
                      {w.name}
                    </Chip>
                  );
                })}
                <span className="self-center text-k-caption text-ink-subtle">
                  {scope.length ? `${scope.length} selected` : "None selected: every workspace"}
                </span>
              </div>
            </div>
            <label className="flex cursor-pointer items-center gap-2 text-k-caption text-ink-muted">
              <input type="checkbox" checked={canQuery} onChange={(e) => setCanQuery(e.target.checked)} className="accent-[var(--brand)]" />
              Can run read-only SQL on the platform
              <span className="text-k-caption text-ink-subtle">(run_sql — SELECT only, row-capped, personal-data columns masked)</span>
            </label>
            <label className="flex cursor-pointer items-center gap-2 text-k-caption text-ink-muted">
              <input type="checkbox" checked={canFiles} onChange={(e) => setCanFiles(e.target.checked)} className="accent-[var(--brand)]" />
              Can read Volume files
              <span className="text-k-caption text-ink-subtle">(list_volume_files, read_volume_file — start of file only, personal data masked)</span>
            </label>
            {error && <p className="text-k-caption text-danger">{error}</p>}
            <div className="flex gap-2">
              <button
                onClick={submit}
                disabled={busy || !name.trim()}
                className="k-btn k-btn-primary"
              >
                {busy && <Spinner className="border-white/30" />} Create and show key
              </button>
              <button onClick={() => setCreating(false)} className="k-btn">
                Cancel
              </button>
            </div>
          </div>
        )}

        {agents.length === 0 && !creating && (
          <Empty>No agents registered yet. Agents can still connect anonymously while keys are optional.</Empty>
        )}
        {agents.map((a) => (
          <div key={a.id} className="k-row flex items-center gap-3 border-b border-hairline px-5 py-3.5 last:border-b-0">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-soft">
              <Bot className="h-4 w-4 text-brand" />
            </span>
            <div className="min-w-0 flex-1">
              <p className="flex items-center gap-2 text-k-body font-semibold text-ink">
                {a.name}
                {a.revoked && <StatusPill tone="danger" size="sm">revoked</StatusPill>}
                {a.scopes.includes("query") && <StatusPill tone="brand" size="sm" dot={false}>can run SQL</StatusPill>}
                {a.scopes.includes("files") && <StatusPill tone="brand" size="sm" dot={false}>can read files</StatusPill>}
              </p>
              <p className="truncate text-k-caption text-ink-subtle">
                <code className="font-mono">{a.key_prefix}…</code> ·{" "}
                {a.workspace_ids.length ? a.workspace_ids.map(wsName).join(", ") : "all workspaces"}
                {a.description ? ` · ${a.description}` : ""}
              </p>
            </div>
            <div className="shrink-0 text-right">
              <p className="text-k-body font-semibold tabular-nums text-ink">{a.call_count.toLocaleString()} calls</p>
              <p className="text-k-caption text-ink-subtle">last seen {timeAgo(a.last_seen_at)}</p>
            </div>
            <div className="flex shrink-0 gap-1">
              <button
                title="Issue a new key; the old one stops working"
                onClick={async () => setFresh(await rotateAgentKey(a.id))}
                className="k-btn k-btn-sm !px-2"
              >
                <RotateCw className="h-3.5 w-3.5" />
              </button>
              {!a.revoked && (
                <button
                  title="Revoke"
                  onClick={async () => {
                    await revokeAgent(a.id);
                    reload();
                  }}
                  className="k-btn k-btn-sm !px-2 !text-danger"
                >
                  <Ban className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          </div>
        ))}
      </section>
    </div>
  );
}
