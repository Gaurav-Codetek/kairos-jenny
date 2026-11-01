"use client";

import { useState } from "react";
import { KeyRound } from "lucide-react";

import { Callout, Spinner } from "@/components/kairos/ds";

import { setWorkspaceToken } from "@/lib/connections";

/**
 * A Databricks connection's credentials: whether it holds its own token or uses the server's DATABRICKS_TOKEN, and a
 * way to give it a new one (personal access tokens expire). The token itself is never shown.
 */
export function TokenRow({ id, config, onSaved }: { id: string; config: Record<string, unknown>; onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [token, setToken] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const own = config.has_token === true;
  const warehouse = typeof config.warehouse_id === "string" ? config.warehouse_id : null;

  async function save() {
    if (!token.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await setWorkspaceToken(id, token.trim());
      setToken("");
      setOpen(false);
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save the token");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mt-4 rounded-lg border border-hairline px-3.5 py-3">
      <div className="flex items-center gap-2.5 text-k-caption text-ink-muted">
        <KeyRound className="h-4 w-4 shrink-0 text-ink-subtle" />
        <p className="min-w-0 flex-1">
          {own ? "Uses its own access token" : "Uses the server's DATABRICKS_TOKEN"}
          {" · "}
          {warehouse ? (
            <>
              SQL warehouse <span className="font-mono text-ink">{warehouse}</span>
            </>
          ) : (
            "the server's SQL warehouse"
          )}
        </p>
        {!open && (
          <button onClick={() => setOpen(true)} className="k-btn k-btn-sm">
            {own ? "Replace token" : "Set token"}
          </button>
        )}
      </div>
      {open && (
        <div className="k-rise mt-3 flex items-center gap-2">
          <input
            type="password"
            autoComplete="off"
            autoFocus
            value={token}
            onChange={(e) => setToken(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && save()}
            placeholder="dapi…"
            aria-label="New personal access token"
            className="k-input flex-1 font-mono !text-k-caption"
          />
          <button onClick={save} disabled={!token.trim() || saving} className="k-btn k-btn-primary k-btn-sm">
            {saving ? <Spinner className="border-white/30" /> : null}
            Save
          </button>
          <button
            onClick={() => {
              setOpen(false);
              setToken("");
              setError(null);
            }}
            className="k-btn k-btn-sm"
          >
            Cancel
          </button>
        </div>
      )}
      {error && (
        <Callout tone="danger" className="mt-3">
          {error}
        </Callout>
      )}
    </div>
  );
}
