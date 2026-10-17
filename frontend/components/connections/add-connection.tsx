"use client";

import { useState } from "react";
import { ArrowRight, Check, X } from "lucide-react";

import { Callout, Spinner } from "@/components/kairos/ds";

import { PLATFORM_META, createWorkspace, type Platform } from "@/lib/connections";
import { cn } from "@/lib/utils";

interface Props {
  onClose: () => void;
  onCreated: (id: string) => void;
}

/**
 * Onboarding a platform is the first thing a new tenant does, so it is a
 * guided flow rather than a bare form: pick a platform, describe the
 * connection, then land on the sync step with the result explained.
 */
export function AddConnectionDialog({ onClose, onCreated }: Props) {
  const [platform, setPlatform] = useState<Platform | null>(null);
  const [name, setName] = useState("");
  const [host, setHost] = useState("");
  const [description, setDescription] = useState("");
  // Snowflake: non-secret settings. Each falls back to the server's SNOWFLAKE_* configuration.
  const [account, setAccount] = useState("");
  const [warehouse, setWarehouse] = useState("");
  const [role, setRole] = useState("");
  const [databases, setDatabases] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const available = platform !== null;
  const snowflake = platform === "snowflake";
  const canSubmit = available && name.trim() && (snowflake || host.trim()) && !saving;

  async function handleCreate() {
    if (!canSubmit) return;
    setSaving(true);
    setError(null);
    try {
      const dbs = databases.split(",").map((d) => d.trim()).filter(Boolean);
      const created = await createWorkspace({
        name: name.trim(),
        platform: platform ?? "databricks",
        host: snowflake ? "" : host.trim(),
        description: description.trim() || undefined,
        connection_config: snowflake
          ? Object.fromEntries(
              Object.entries({
                account: account.trim(),
                warehouse: warehouse.trim(),
                role: role.trim(),
                databases: dbs.length ? dbs : undefined,
              }).filter(([, v]) => v)
            )
          : undefined,
      });
      onCreated(created.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create the connection");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="k-page fixed inset-0 z-50 flex items-center justify-center bg-[rgb(26_29_36/0.28)] p-8 backdrop-blur-[3px]"
      onClick={onClose}
    >
      <div
        className="kairos-panel k-pop w-full max-w-lg shadow-[0_24px_60px_-20px_rgb(26_29_36/0.35)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 border-b border-hairline px-5 py-4">
          <span aria-hidden className="h-6 w-1 rounded-full bg-brand" />
          <h2 className="text-[17px] font-bold text-ink">Connect a platform</h2>
          <button
            onClick={onClose}
            className="k-btn k-btn-ghost k-btn-sm ml-auto !px-1.5"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="p-5">
          <p className="k-label mb-2">
            Platform
          </p>
          <div className="grid grid-cols-2 gap-2.5">
            {(Object.keys(PLATFORM_META) as Platform[]).map((p) => {
              const meta = PLATFORM_META[p];
              const live = true;
              const active = platform === p;
              return (
                <button
                  key={p}
                  onClick={() => setPlatform(p)}
                  className={cn(
                    "rounded-lg border p-3.5 text-left transition-all duration-200",
                    active ? "border-brand bg-brand-soft/60 shadow-[0_0_0_3px_var(--brand-soft)]" : "border-hairline hover:border-brand-border hover:bg-sunken",
                    !live && "opacity-70"
                  )}
                >
                  <span className="flex items-center gap-2">
                    <span
                      className="flex h-8 w-8 items-center justify-center rounded-full text-[12px] font-bold"
                      style={{ background: meta.tint, color: meta.accent }}
                    >
                      {meta.label[0]}
                    </span>
                    <span className="text-k-title font-semibold text-ink">{meta.label}</span>
                    {active && (
                      <span className="k-pop ml-auto flex h-5 w-5 items-center justify-center rounded-full bg-brand text-white">
                        <Check className="h-3 w-3" strokeWidth={3} />
                      </span>
                    )}
                  </span>
                  <span className="mt-2 block text-k-caption leading-snug text-ink-muted">
                    {meta.blurb}
                  </span>
                  {!live && (
                    <span className="mt-1.5 inline-block rounded bg-sunken px-1 py-px text-[10.5px] font-medium text-ink-subtle ring-1 ring-hairline">
                      Not available yet
                    </span>
                  )}
                </button>
              );
            })}
          </div>


          {available && (
            <div className="k-rise mt-5 space-y-4 border-t border-hairline pt-5">
              <label className="block">
                <span className="mb-1.5 block text-k-caption font-semibold text-ink-2">Connection name</span>
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Production warehouse"
                  className="k-input"
                />
              </label>

              {snowflake ? (
                <>
                  <div className="grid grid-cols-2 gap-3">
                    {(
                      [
                        ["sf-account", "Account identifier", account, setAccount, "orgname-accountname"],
                        ["sf-warehouse", "Warehouse", warehouse, setWarehouse, "COMPUTE_WH"],
                        ["sf-role", "Role", role, setRole, "KAIROS_READER"],
                        ["sf-databases", "Databases (optional)", databases, setDatabases, "all, or SALES, CRM"],
                      ] as const
                    ).map(([id, label, value, set, ph]) => (
                      <label key={id} className="block" htmlFor={id}>
                        <span className="mb-1.5 block text-k-caption font-semibold text-ink-2">{label}</span>
                        <input
                          id={id}
                          value={value}
                          onChange={(e) => set(e.target.value)}
                          placeholder={ph}
                          className="k-input font-mono !text-k-caption"
                        />
                      </label>
                    ))}
                  </div>
                  <p className="text-k-caption leading-snug text-ink-subtle">
                    Leave a field empty to use the server&apos;s SNOWFLAKE_* setting. Lineage, task history and
                    tags need a role that can read SNOWFLAKE.ACCOUNT_USAGE.
                  </p>
                </>
              ) : (
                <label className="block">
                  <span className="mb-1.5 block text-k-caption font-semibold text-ink-2">Workspace URL</span>
                  <input
                    value={host}
                    onChange={(e) => setHost(e.target.value)}
                    placeholder="https://adb-000000000000.0.azuredatabricks.net"
                    className="k-input font-mono !text-k-caption"
                  />
                </label>
              )}

              <label className="block">
                <span className="mb-1.5 block text-k-caption font-semibold text-ink-2">
                  Description <span className="font-normal text-ink-subtle">(optional)</span>
                </span>
                <input
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="What this platform holds"
                  className="k-input"
                />
              </label>

              {/* Credentials are deliberately not collected here — being
                  explicit about that is better than a field that silently
                  does nothing. */}
              <p className="rounded-lg border border-hairline bg-sunken px-3.5 py-2.5 text-k-caption leading-snug text-ink-muted">
                Credentials are read from server configuration, not stored per
                connection. Per-workspace encrypted credentials are required before
                this is safe for more than one tenant.
              </p>
            </div>
          )}

          {error && (
            <Callout tone="danger" className="mt-4">
              {error}
            </Callout>
          )}
        </div>

        <div className="flex items-center gap-2 border-t border-hairline bg-sunken px-5 py-3.5">
          <button onClick={onClose} className="k-btn">
            Cancel
          </button>
          <button
            onClick={handleCreate}
            disabled={!canSubmit}
            className="k-btn k-btn-primary ml-auto"
          >
            {saving ? <Spinner className="border-white/30" /> : null}
            Create connection
            {!saving && <ArrowRight className="h-3.5 w-3.5" />}
          </button>
        </div>
      </div>
    </div>
  );
}
