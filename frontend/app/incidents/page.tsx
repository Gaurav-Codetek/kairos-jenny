"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, ArrowRight, Check, Clock, Database, ExternalLink } from "lucide-react";

import { EmptyState, Panel, StatusPill, stagger } from "@/components/kairos/ds";
import { PageHeader } from "@/components/shell/app-shell";
import { fetchApi } from "@/lib/api";
import { describeIncident, type Incident } from "@/lib/incidents";
import { relativeTime } from "@/lib/connections";

// Problems with the data itself, not a pipeline run: what agents reported (triaged by the report loop, with their
// evidence) and streams Jenny's pulse saw stop.
interface DataProblem {
  id: string;
  source: "report" | "pulse";
  product: string | null;
  title: string;
  reporter: string;
  status: "open" | "resolved" | "dismissed";
  note: string | null;
  resolution: string | null;
  question: string | null;
  at: string;
}

export default function IncidentsPage() {
  const [incidents, setIncidents] = useState<Incident[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [problems, setProblems] = useState<DataProblem[] | null>(null);

  useEffect(() => {
    fetchApi("/incidents/data-problems")
      .then((r: { problems: DataProblem[] }) => setProblems(r.problems))
      .catch(() => setProblems([]));
  }, []);

  useEffect(() => {
    fetchApi("/incidents")
      .then(setIncidents)
      .catch((e) => {
        setError(String(e?.message ?? e));
        setIncidents([]);
      });
  }, []);

  return (
    <>
      <PageHeader title="Incidents" description="Failed pipeline runs, and problems with the data itself" />

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-5xl px-7 py-6">
          <Panel
            title="Failed runs"
            icon={AlertTriangle}
            meta={incidents ? `${incidents.length} recorded` : undefined}
            className="k-rise"
          >
            {incidents === null ? (
              <p className="px-4 py-6 text-k-body text-ink-muted">Loading…</p>
            ) : error ? (
              <p className="px-4 py-6 text-k-body text-danger">Could not load incidents: {error}</p>
            ) : incidents.length === 0 ? (
              <EmptyState icon={Check} title="No failed runs">
                Every pipeline Kairos watches finished cleanly.
              </EmptyState>
            ) : (
              <ul className="divide-y divide-hairline">
                {incidents.map((incident, i) => {
                  const d = describeIncident(incident);
                  return (
                    <li key={incident.run_id} className="k-rise k-row group relative flex items-start gap-4 px-4 py-4" style={stagger(Math.min(i, 8))}>
                      {/* The whole row opens the run; the platform link sits above it. */}
                      <Link href={`/incidents/${incident.run_id}`} aria-label={d.title} className="absolute inset-0" />
                        <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-danger-soft text-danger">
                          <AlertTriangle className="h-4 w-4" />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="flex items-center gap-2">
                            <span className="truncate text-k-title font-semibold text-ink">{d.title}</span>
                            <StatusPill tone="danger" size="sm">
                              Failed
                            </StatusPill>
                          </span>
                          <span className="mt-1 line-clamp-2 block text-k-body text-ink-muted">{d.message}</span>
                          <span className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-k-caption text-ink-subtle">
                            {d.workspace && <span>{d.workspace}</span>}
                            <span className="font-mono">run {incident.source_native_id}</span>
                            <span className="inline-flex items-center gap-1">
                              <Clock className="h-3.5 w-3.5" />
                              {relativeTime(incident.start_time)}
                              {d.duration && ` · ran ${d.duration}`}
                            </span>
                            {incident.run_page_url && (
                              <a
                                href={incident.run_page_url}
                                target="_blank"
                                rel="noreferrer"
                                className="relative z-10 inline-flex items-center gap-1 text-brand hover:text-brand-strong"
                              >
                                Open in platform <ExternalLink className="h-3 w-3" />
                              </a>
                            )}
                          </span>
                        </span>
                        <ArrowRight className="mt-2 h-4 w-4 shrink-0 text-ink-subtle transition-transform duration-200 group-hover:translate-x-0.5 group-hover:text-brand" />
                    </li>
                  );
                })}
              </ul>
            )}
          </Panel>

          <Panel
            title="Data problems"
            icon={Database}
            meta={problems ? `${problems.filter((p) => p.status === "open").length} open` : undefined}
            className="k-rise mt-6"
          >
            {problems === null ? (
              <p className="px-4 py-6 text-k-body text-ink-muted">Loading…</p>
            ) : problems.length === 0 ? (
              <EmptyState icon={Check} title="No data problems">
                Nothing missing or wrong in the data has been reported or seen in the last two weeks.
              </EmptyState>
            ) : (
              <ul className="divide-y divide-hairline">
                {problems.map((p, i) => (
                  <li key={p.id} className="k-rise flex items-start gap-4 px-4 py-4" style={stagger(Math.min(i, 8))}>
                    <span
                      className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${
                        p.status === "open" ? "bg-warn-soft text-warn" : "bg-ok-soft text-ok"
                      }`}
                    >
                      <Database className="h-4 w-4" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="text-k-title font-semibold text-ink">{p.title}</span>
                        <StatusPill tone={p.status === "open" ? "warn" : p.status === "resolved" ? "ok" : "neutral"} size="sm">
                          {p.status === "open" ? "Open" : p.status === "resolved" ? "Resolved" : "Dismissed"}
                        </StatusPill>
                      </span>
                      {p.question && <span className="mt-1 block text-k-caption text-ink-muted">Asked: “{p.question}”</span>}
                      {(p.resolution || p.note) && (
                        <span className={`mt-1 block text-k-body ${p.resolution ? "text-ok" : "text-ink-muted"}`}>
                          {p.resolution || p.note}
                        </span>
                      )}
                      <span className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-k-caption text-ink-subtle">
                        <span>{p.source === "report" ? `Reported by ${p.reporter}` : "Seen by Jenny's pulse"}</span>
                        {p.product && <span>{p.product}</span>}
                        <span className="inline-flex items-center gap-1">
                          <Clock className="h-3.5 w-3.5" />
                          {relativeTime(p.at)}
                        </span>
                        {p.source === "report" && (
                          <Link href="/agents?tab=feedback" className="text-brand hover:text-brand-strong">
                            In Reports →
                          </Link>
                        )}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
      </div>
    </>
  );
}
