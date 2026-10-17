"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  BookOpen,
  Bot,
  Database,
  FlaskConical,
  GitBranch,
  Layers,
  Radar,
  MessagesSquare,
  Plug,
  Sparkles,
  type LucideIcon,
} from "lucide-react";

import { KairosMark } from "@/components/kairos/ds";
import { VoiceNotesPill } from "@/components/living/voice-notes";
import { cn } from "@/lib/utils";

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Grouping header this item sits under. */
  section: string;
}

// Ordered by how the platform is actually used: connect a source, sync it,
// understand it, then act on what breaks.
const NAV: NavItem[] = [
  { href: "/", label: "Overview", icon: Activity, section: "Platform" },
  { href: "/connections", label: "Connections", icon: Plug, section: "Platform" },
  { href: "/agents", label: "Agents", icon: Bot, section: "Platform" },
  { href: "/evals", label: "Evaluations", icon: FlaskConical, section: "Platform" },
  { href: "/test", label: "Test", icon: MessagesSquare, section: "Platform" },
  { href: "/graph", label: "Lineage", icon: GitBranch, section: "Explore" },
  { href: "/catalog", label: "Catalog", icon: Database, section: "Explore" },
  { href: "/enrichment", label: "Enrichment", icon: Sparkles, section: "Intelligence" },
  { href: "/knowledge", label: "Knowledge", icon: BookOpen, section: "Intelligence" },
  { href: "/products", label: "Data Products", icon: Layers, section: "Intelligence" },
  { href: "/living", label: "Living Agent", icon: Radar, section: "Intelligence" },
  // Incidents is hidden from the sidebar for now; /incidents still works.
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  const sections = NAV.reduce<Record<string, NavItem[]>>((acc, item) => {
    (acc[item.section] ||= []).push(item);
    return acc;
  }, {});

  return (
    <div className="flex h-screen overflow-hidden bg-canvas">
      <aside className="flex w-[232px] shrink-0 flex-col border-r border-hairline bg-surface">
        <Link href="/" className="flex h-16 shrink-0 items-center gap-2.5 px-5">
          <KairosMark size={24} />
          <span className="text-[17px] font-bold tracking-tight text-ink">Kairos</span>
        </Link>

        <nav className="flex-1 overflow-y-auto px-3 pb-3 pt-1">
          {Object.entries(sections).map(([section, items]) => (
            <div key={section} className="mb-5">
              <p className="k-label px-2.5 pb-1.5">{section}</p>
              <div className="space-y-0.5">
                {items.map(({ href, label, icon: Icon }) => {
                  // Exact match for root; prefix match elsewhere so detail
                  // routes keep their parent highlighted.
                  const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
                  return (
                    <Link
                      key={href}
                      href={href}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "group flex h-9 items-center gap-2.5 rounded-lg px-2.5 text-k-body transition-colors duration-200",
                        active
                          ? "bg-brand-soft font-semibold text-brand-strong"
                          : "text-ink-muted hover:bg-sunken hover:text-ink"
                      )}
                    >
                      <Icon
                        className={cn(
                          "h-4 w-4 transition-colors duration-200",
                          active ? "text-brand" : "text-ink-subtle group-hover:text-ink-muted"
                        )}
                        strokeWidth={2}
                      />
                      {label}
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        <div className="border-t border-hairline px-5 py-4">
          <p className="k-label">Platforms</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {["Databricks", "Snowflake"].map((p) => (
              <span
                key={p}
                className="inline-flex h-6 items-center rounded-full border border-hairline px-2.5 text-k-caption text-ink-muted"
              >
                {p}
              </span>
            ))}
          </div>
        </div>
      </aside>

      <main key={pathname} className="k-page flex min-w-0 flex-1 flex-col overflow-hidden">
        {children}
      </main>
      <VoiceNotesPill />
    </div>
  );
}

/** Consistent page header across platform screens. */
export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  return (
    <header className="flex min-h-16 shrink-0 items-center gap-3.5 border-b border-hairline bg-surface px-7 py-3">
      <span aria-hidden className="h-7 w-1 shrink-0 rounded-full bg-brand" />
      <div className="min-w-0">
        <h1 className="truncate text-k-h1 font-bold text-ink">{title}</h1>
        {description && <p className="truncate text-k-body text-ink-muted">{description}</p>}
      </div>
      {actions && <div className="ml-auto flex items-center gap-2">{actions}</div>}
    </header>
  );
}
