"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";

import { StatusPill, type Tone } from "@/components/kairos/ds";
import { TRUST_META, type TrustLevel } from "@/lib/agents";
import { cn } from "@/lib/utils";

const TRUST_TONE: Record<TrustLevel, Tone> = { verified: "ok", profiled: "warn", synced: "neutral" };

export function TrustBadge({ level, className }: { level: TrustLevel; className?: string }) {
  const meta = TRUST_META[level] ?? TRUST_META.synced;
  return (
    <StatusPill tone={TRUST_TONE[level] ?? "neutral"} size="sm" title={meta.hint} className={className}>
      {meta.label}
    </StatusPill>
  );
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      onClick={() => {
        navigator.clipboard?.writeText(text).then(() => {
          setDone(true);
          window.setTimeout(() => setDone(false), 1500);
        });
      }}
      className="inline-flex h-7 items-center gap-1.5 rounded-md border border-hairline bg-surface px-2.5 text-k-caption font-medium text-ink-muted transition-colors hover:border-hairline-strong hover:text-ink"
    >
      {done ? <Check className="h-3.5 w-3.5" style={{ color: "var(--ok-dot)" }} /> : <Copy className="h-3.5 w-3.5" />}
      {done ? "Copied" : label}
    </button>
  );
}

export function CodeBlock({ code, className }: { code: string; className?: string }) {
  return (
    <div className={cn("relative", className)}>
      <pre className="overflow-x-auto rounded-lg border border-hairline bg-sunken px-3.5 py-3 pr-24 font-mono text-k-caption leading-relaxed text-ink-2">
        {code}
      </pre>
      <div className="absolute right-2 top-2">
        <CopyButton text={code} />
      </div>
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <p className="px-4 py-10 text-center text-k-body text-ink-muted">{children}</p>;
}

export function timeAgo(iso: string | null): string {
  if (!iso) return "never";
  const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000);
  if (s < 60) return `${Math.floor(s)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}
