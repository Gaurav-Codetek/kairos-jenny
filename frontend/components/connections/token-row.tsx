"use client";

import { useState } from "react";
import { KeyRound } from "lucide-react";

import { Callout, Spinner } from "@/components/kairos/ds";

import { listWarehouses, setWorkspaceToken, setWorkspaceWarehouse, type SqlWarehouse } from "@/lib/connections";

/**
 * A Databricks connection's credentials: whether it holds its own token or uses the server's DATABRICKS_TOKEN, and
 * the SQL warehouse it queries. Either can be changed in place (tokens expire; a warehouse can be wrong or retired)
 * without losing what Kairos learned. The token itself is never shown.
 */
export function TokenRow({ id, config, onSaved }: { id: string; config: Record<string, unknown>; onSaved: () => void }) {
  const [open, setOpen] = useState<"token" | "warehouse" | null>(null);
  const [token, setToken] = useState("");
  const [warehouses, setWarehouses] = useState<SqlWarehouse[] | null>(null);
  const [choice, setChoice] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const own = config.has_token === true;
  const warehouse = typeof config.warehouse_id === "string" ? config.warehouse_id : null;

  function close() {
    setOpen(null);
    setToken("");
    setChoice("");
    setError(null);
  }

  async function openWarehouses() {
    setOpen("warehouse");
    setError(null);
    setWarehouses(null);
    try {
      const r = await listWarehouses(id);
      setWarehouses(r.warehouses);
      setChoice(r.warehouses.some((w) => w.id === r.current) ? (r.current ?? "") : (r.warehouses[0]?.id ?? ""));
    } catch (e) {
      setWarehouses([]);
      setError(e instanceof Error ? e.message : "Could not list the warehouses");
    }
  }

  async function save() {
    const value = open === "token" ? token.trim() : choice.trim();
    if (!value) return;
    setBusy(true);
    setError(null);
    try {
      if (open === "token") await setWorkspaceToken(id, value);
      else await setWorkspaceWarehouse(id, value);
      close();
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save");
    } finally {
      setBusy(false);
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
          <>
            <button onClick={() => setOpen("token")} className="k-btn k-btn-sm">
              {own ? "Replace token" : "Set token"}
            </button>
            <button onClick={openWarehouses} className="k-btn k-btn-sm">
              Change warehouse
            </button>
          </>
        )}
      </div>
      {open === "token" && (
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
          <button onClick={save} disabled={!token.trim() || busy} className="k-btn k-btn-primary k-btn-sm">
            {busy ? <Spinner className="border-white/30" /> : null}
            Save
          </button>
          <button onClick={close} className="k-btn k-btn-sm">
            Cancel
          </button>
        </div>
      )}
      {open === "warehouse" && (
        <div className="k-rise mt-3 flex items-center gap-2">
          {warehouses === null ? (
            <span className="flex flex-1 items-center gap-2 text-k-caption text-ink-muted">
              <Spinner /> Asking Databricks which warehouses this token can use…
            </span>
          ) : warehouses.length ? (
            <select
              value={choice}
              onChange={(e) => setChoice(e.target.value)}
              aria-label="SQL warehouse"
              className="k-input flex-1 !text-k-caption"
            >
              {warehouses.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name} · {w.id}
                  {w.state ? ` · ${w.state.toLowerCase()}` : ""}
                  {w.serverless ? " · serverless" : ""}
                </option>
              ))}
            </select>
          ) : (
            <input
              autoFocus
              value={choice}
              onChange={(e) => setChoice(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && save()}
              placeholder="SQL warehouse ID"
              aria-label="SQL warehouse ID"
              className="k-input flex-1 font-mono !text-k-caption"
            />
          )}
          <button onClick={save} disabled={!choice.trim() || busy} className="k-btn k-btn-primary k-btn-sm">
            {busy ? <Spinner className="border-white/30" /> : null}
            Save
          </button>
          <button onClick={close} className="k-btn k-btn-sm">
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
