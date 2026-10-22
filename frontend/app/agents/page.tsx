"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";

import { Tabs } from "@/components/kairos/ds";
import { PageHeader } from "@/components/shell/app-shell";
import { ActivityPanel } from "@/components/agents/activity-panel";
import { ConnectPanel } from "@/components/agents/connect-panel";
import { ExplorerPanel } from "@/components/agents/explorer-panel";
import { FeedbackPanel } from "@/components/agents/feedback-panel";
import { KeysPanel } from "@/components/agents/keys-panel";
import { ReadinessPanel } from "@/components/agents/readiness-panel";

const TABS = [
  { id: "connect", label: "Connect" },
  { id: "explore", label: "What agents see" },
  { id: "readiness", label: "Readiness" },
  { id: "keys", label: "Agents & keys" },
  { id: "activity", label: "Activity" },
  { id: "feedback", label: "Reports" },
] as const;

type Tab = (typeof TABS)[number]["id"];

export default function AgentsPage() {
  return (
    <Suspense>
      <AgentsScreen />
    </Suspense>
  );
}

/** Deep links: /agents?tab=explore&q=account%20sales opens the explorer with that search. */
function AgentsScreen() {
  const params = useSearchParams();
  const requested = params.get("tab");
  const [tab, setTab] = useState<Tab>(TABS.some((t) => t.id === requested) ? (requested as Tab) : "connect");
  const [creatingKey, setCreatingKey] = useState(false);

  return (
    <>
      <PageHeader
        title="Agents"
        description="Any agent connects once and understands this data platform — no per-agent setup"
      />
      <div data-guide="agents:tabs">
        <Tabs items={TABS} value={tab} onChange={setTab} />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div key={tab} data-guide="agents:body" className="k-rise mx-auto max-w-6xl px-7 py-6">
          {tab === "connect" && (
            <ConnectPanel
              onCreateKey={() => {
                setCreatingKey(true);
                setTab("keys");
              }}
            />
          )}
          {tab === "explore" && <ExplorerPanel initialQuery={params.get("q") ?? ""} />}
          {tab === "readiness" && <ReadinessPanel />}
          {tab === "keys" && <KeysPanel startCreating={creatingKey} />}
          {tab === "activity" && <ActivityPanel />}
          {tab === "feedback" && <FeedbackPanel />}
        </div>
      </div>
    </>
  );
}
