"use client";

import { useState } from "react";
import { AlertTriangle, Check, Trash2, X } from "lucide-react";

import { Callout, Field, Spinner } from "@/components/kairos/ds";
import { PLATFORM_META, deleteWorkspace, type WorkspaceStatus } from "@/lib/connections";

interface Props {
  id: string;
  status: WorkspaceStatus;
  onClose: () => void;
  onDeleted: () => void;
}

/**
 * Deleting a connection cannot be undone, so the dialog says exactly what goes
 * and what stays, and asks for the connection's name before it will act.
 */
export function DeleteConnectionDialog({ id, status, onClose, onDeleted }: Props) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const platform = (PLATFORM_META[status.platform] ?? PLATFORM_META.databricks).label;
  const confirmed = typed.trim() === status.name.trim();

  const c = status.counts;
  const mirrored = [
    [c.tables, "tables"],
    [c.columns, "columns"],
    [c.jobs, "pipelines"],
    [c.runs, "runs"],
  ]
    .filter(([n]) => Number(n) > 0)
    .map(([n, label]) => `${Number(n).toLocaleString()} ${label}`);

  async function handleDelete() {
    if (!confirmed || busy) return;
    setBusy(true);
    setError(null);
    try {
      await deleteWorkspace(id);
      onDeleted();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not delete the connection.");
      setBusy(false);
    }
  }

  return (
    <div
      className="k-page fixed inset-0 z-50 flex items-center justify-center bg-[rgb(26_29_36/0.28)] p-8 backdrop-blur-[3px]"
      onClick={busy ? undefined : onClose}
    >
      <div
        role="alertdialog"
        aria-labelledby="delete-connection-title"
        className="kairos-panel k-pop w-full max-w-md shadow-[0_24px_60px_-20px_rgb(26_29_36/0.35)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-3 border-b border-hairline px-5 py-4">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-danger-soft text-danger">
            <Trash2 className="h-4 w-4" />
          </span>
          <div className="min-w-0 flex-1">
            <h2 id="delete-connection-title" className="text-[17px] font-bold text-ink">
              Delete {status.name}?
            </h2>
            <p className="text-k-caption text-ink-muted">This cannot be undone.</p>
          </div>
          <button onClick={onClose} disabled={busy} className="k-btn k-btn-ghost k-btn-sm !px-1.5" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-4 px-5 py-5">
          <div>
            <p className="mb-2 text-k-caption font-semibold text-ink-2">Removed from Kairos</p>
            <ul className="space-y-1.5 text-k-body text-ink">
              <li className="flex gap-2">
                <X className="mt-[3px] h-3.5 w-3.5 shrink-0 text-danger" strokeWidth={2.6} />
                Everything mirrored from it{mirrored.length ? `: ${mirrored.join(", ")}` : ""}, with its lineage and objects
              </li>
              <li className="flex gap-2">
                <X className="mt-[3px] h-3.5 w-3.5 shrink-0 text-danger" strokeWidth={2.6} />
                Its semantic profiles, discovered links, knowledge bindings and agent reports
              </li>
              {status.mcp_url && (
                <li className="flex gap-2">
                  <X className="mt-[3px] h-3.5 w-3.5 shrink-0 text-danger" strokeWidth={2.6} />
                  <span>
                    Its agent endpoint <code className="font-mono text-k-caption text-ink-2">{status.mcp_url}</code>{" "}
                    stops answering
                  </span>
                </li>
              )}
            </ul>
          </div>
          <div>
            <p className="mb-2 text-k-caption font-semibold text-ink-2">Kept</p>
            <ul className="space-y-1.5 text-k-body text-ink-muted">
              <li className="flex gap-2">
                <Check className="mt-[3px] h-3.5 w-3.5 shrink-0 text-ok" strokeWidth={2.6} />
                {platform} itself: nothing is changed or deleted on the platform
              </li>
              <li className="flex gap-2">
                <Check className="mt-[3px] h-3.5 w-3.5 shrink-0 text-ok" strokeWidth={2.6} />
                The audit trail of agent calls, and your other connections
              </li>
            </ul>
          </div>

          <Field label={<>Type <span className="font-mono text-ink">{status.name}</span> to confirm</>}>
            <input
              autoFocus
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleDelete()}
              className="k-input"
              aria-label="Connection name"
            />
          </Field>

          {error && (
            <Callout tone="danger" icon={AlertTriangle}>
              {error}
            </Callout>
          )}
        </div>

        <div className="flex items-center gap-2 border-t border-hairline bg-sunken px-5 py-3.5">
          <button onClick={onClose} disabled={busy} className="k-btn ml-auto">
            Cancel
          </button>
          <button onClick={handleDelete} disabled={!confirmed || busy} className="k-btn k-btn-danger">
            {busy ? <Spinner className="border-white/30" /> : <Trash2 className="h-4 w-4" />}
            Delete connection
          </button>
        </div>
      </div>
    </div>
  );
}
