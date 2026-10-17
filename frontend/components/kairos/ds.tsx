"use client";

/**
 * Kairos design system: the handful of pieces every screen is built from.
 * The look follows the launch film. White panels on a grey canvas, one
 * indigo accent, soft-tinted status pills with a dot, and numbers that
 * count in rather than appear.
 */

import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import Link from "next/link";
import { ArrowRight, type LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

export type Tone = "ok" | "warn" | "danger" | "neutral" | "brand";

const TONE: Record<Tone, { bg: string; fg: string; dot: string }> = {
  ok: { bg: "var(--ok-soft)", fg: "var(--ok)", dot: "var(--ok-dot)" },
  warn: { bg: "var(--warn-soft)", fg: "var(--warn)", dot: "var(--warn-dot)" },
  danger: { bg: "var(--danger-soft)", fg: "var(--danger)", dot: "var(--danger-dot)" },
  neutral: { bg: "var(--neutral-soft)", fg: "var(--neutral)", dot: "var(--neutral-dot)" },
  brand: { bg: "var(--brand-soft)", fg: "var(--brand-strong)", dot: "var(--brand)" },
};

export const toneColors = (tone: Tone) => TONE[tone];

/** Stagger index for the rise / pop / draw animations. */
export const stagger = (i: number): CSSProperties => ({ ["--i" as string]: i });

/** The mark from the film: an indigo dot inside a faint ring. */
export function KairosMark({ size = 22 }: { size?: number }) {
  return (
    <span className="relative inline-flex shrink-0 items-center justify-center" style={{ width: size, height: size }}>
      <span className="absolute inset-0 rounded-full border-[1.5px]" style={{ borderColor: "rgb(81 72 224 / 0.35)" }} />
      <span className="rounded-full" style={{ width: size * 0.5, height: size * 0.5, background: "var(--brand)" }} />
    </span>
  );
}

/** A soft-tinted pill with a status dot, like the film's Verified / Profiled / Synced. */
export function StatusPill({
  tone,
  children,
  dot = true,
  size = "md",
  title,
  className,
  style,
}: {
  tone: Tone;
  children: ReactNode;
  dot?: boolean;
  size?: "sm" | "md";
  title?: string;
  className?: string;
  style?: CSSProperties;
}) {
  const t = TONE[tone];
  return (
    <span
      title={title}
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full font-semibold",
        size === "sm" ? "h-5 px-2 text-[11px]" : "h-6 px-2.5 text-k-caption",
        className
      )}
      style={{ background: t.bg, color: t.fg, ...style }}
    >
      {dot && <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: t.dot }} />}
      {children}
    </span>
  );
}

/** A selectable pill: hairline when off, indigo tint when on (the film's chapter buttons). */
export function Chip({
  on,
  onClick,
  children,
  count,
  className,
}: {
  on?: boolean;
  onClick?: () => void;
  children: ReactNode;
  count?: number;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={on}
      className={cn(
        "inline-flex h-7 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-3 text-k-caption transition-colors duration-200",
        on
          ? "border-transparent bg-brand-soft font-semibold text-brand-strong"
          : "border-hairline text-ink-muted hover:border-hairline-strong hover:text-ink",
        className
      )}
    >
      {children}
      {count !== undefined && <span className="tabular-nums opacity-70">{count.toLocaleString()}</span>}
    </button>
  );
}

/** A white panel with an optional header row. */
export function Panel({
  title,
  icon: Icon,
  meta,
  action,
  children,
  className,
  bodyClassName,
  style,
}: {
  title?: ReactNode;
  icon?: LucideIcon;
  meta?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  style?: CSSProperties;
}) {
  return (
    <section className={cn("kairos-panel", className)} style={style}>
      {(title || action) && (
        <header className="flex min-h-[48px] items-center gap-2.5 border-b border-hairline px-4 py-2.5">
          {Icon && <Icon className="h-4 w-4 shrink-0 text-ink-subtle" strokeWidth={2} />}
          {title && <h2 className="truncate text-k-title font-semibold text-ink">{title}</h2>}
          {meta && <span className="truncate text-k-caption text-ink-muted">{meta}</span>}
          {action && <div className="ml-auto flex shrink-0 items-center gap-2">{action}</div>}
        </header>
      )}
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}

/** "See all →" link used in panel headers. */
export function PanelLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link
      href={href}
      className="group inline-flex items-center gap-1 text-k-caption font-medium text-brand hover:text-brand-strong"
    >
      {children}
      <ArrowRight className="h-3.5 w-3.5 transition-transform duration-200 group-hover:translate-x-0.5" />
    </Link>
  );
}

/** Counts from 0 to `value` with the film's ease-out; instant under reduced motion. */
export function useCountUp(value: number | undefined, duration = 900): number | undefined {
  const [shown, setShown] = useState<number | undefined>(value === undefined ? undefined : 0);
  const from = useRef(0);
  useEffect(() => {
    if (value === undefined) return;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const start = from.current;
    if (reduce || start === value) {
      from.current = value;
      setShown(value);
      return;
    }
    let raf = 0;
    const t0 = performance.now();
    const tick = (now: number) => {
      const u = Math.min(1, (now - t0) / duration);
      const eased = 1 - Math.pow(1 - u, 3);
      setShown(Math.round(start + (value - start) * eased));
      if (u < 1) raf = requestAnimationFrame(tick);
      else from.current = value;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value, duration]);
  return shown;
}

/** A headline number that counts in, with its label underneath. */
export function Stat({
  value,
  label,
  hint,
  icon: Icon,
  tone,
  href,
  index = 0,
  format,
}: {
  value: number | undefined;
  label: string;
  hint?: ReactNode;
  icon?: LucideIcon;
  tone?: Tone;
  href?: string;
  index?: number;
  format?: (n: number) => string;
}) {
  const n = useCountUp(value);
  const color = tone && tone !== "neutral" && tone !== "brand" && value ? TONE[tone].fg : "var(--ink)";
  const body = (
    <>
      <div className="flex items-center justify-between gap-2">
        <span className="text-k-caption font-medium text-ink-muted">{label}</span>
        {Icon && (
          <span className="flex h-7 w-7 items-center justify-center rounded-full bg-brand-soft text-brand">
            <Icon className="h-3.5 w-3.5" strokeWidth={2.2} />
          </span>
        )}
      </div>
      <p className="mt-2 text-k-stat font-bold tabular-nums" style={{ color }}>
        {n === undefined ? "–" : format ? format(n) : n.toLocaleString()}
      </p>
      {hint && <div className="mt-1 truncate text-k-caption text-ink-muted">{hint}</div>}
    </>
  );
  const cls = "kairos-panel k-rise block p-4";
  return href ? (
    <Link href={href} className={cn(cls, "k-hover")} style={stagger(index)}>
      {body}
    </Link>
  ) : (
    <div className={cls} style={stagger(index)}>
      {body}
    </div>
  );
}

/** A thin indigo bar that grows to its share. */
export function Meter({ value, max, tone = "brand", index = 0 }: { value: number; max: number; tone?: Tone; index?: number }) {
  const pct = max > 0 ? Math.max(value > 0 ? 2 : 0, Math.min(100, (value / max) * 100)) : 0;
  return (
    <span className="block h-1.5 w-full overflow-hidden rounded-full bg-neutral-soft">
      <span
        className="k-grow block h-full rounded-full"
        style={{ width: `${pct}%`, background: TONE[tone].dot, ...stagger(index) }}
      />
    </span>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  children,
  action,
  className,
}: {
  icon?: LucideIcon;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center px-6 py-10 text-center", className)}>
      {Icon && (
        <span className="mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-brand-soft text-brand">
          <Icon className="h-[18px] w-[18px]" />
        </span>
      )}
      <p className="text-k-title font-semibold text-ink">{title}</p>
      {children && <p className="mt-1 max-w-sm text-k-body text-ink-muted">{children}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

/** Small spinner arc in the accent, like the film's "Searching…" loader. */
export function Spinner({ className }: { className?: string }) {
  return (
    <span
      className={cn("k-spin inline-block h-3.5 w-3.5 rounded-full border-2 border-brand-soft", className)}
      style={{ borderTopColor: "var(--brand)" }}
      aria-hidden
    />
  );
}

/** Underline tabs. "page" sits under the page header; "panel" sits inside a panel header. */
export function Tabs<T extends string>({
  items,
  value,
  onChange,
  size = "page",
  className,
  trailing,
}: {
  items: readonly { id: T; label: ReactNode; count?: number; icon?: LucideIcon }[];
  value: T;
  onChange: (id: T) => void;
  size?: "page" | "panel";
  className?: string;
  trailing?: ReactNode;
}) {
  return (
    <div
      role="tablist"
      className={cn(
        "flex items-center gap-1 overflow-x-auto border-b border-hairline",
        size === "page" ? "bg-surface px-6" : "px-3",
        className
      )}
    >
      {items.map(({ id, label, count, icon: Icon }) => {
        const on = id === value;
        return (
          <button
            key={id}
            role="tab"
            type="button"
            aria-selected={on}
            onClick={() => onChange(id)}
            className={cn(
              "relative -mb-px inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap border-b-2 transition-colors duration-200",
              size === "page" ? "h-11 px-3 text-k-body" : "h-10 px-2.5 text-k-caption",
              on
                ? "border-brand font-semibold text-ink"
                : "border-transparent text-ink-muted hover:border-hairline-strong hover:text-ink"
            )}
          >
            {Icon && <Icon className={cn("h-3.5 w-3.5", on ? "text-brand" : "text-ink-subtle")} />}
            {label}
            {count !== undefined && (
              <span
                className={cn(
                  "rounded-full px-1.5 text-[11px] font-semibold tabular-nums",
                  on ? "bg-brand-soft text-brand-strong" : "bg-neutral-soft text-ink-muted"
                )}
              >
                {count.toLocaleString()}
              </span>
            )}
          </button>
        );
      })}
      {trailing && <div className="ml-auto flex shrink-0 items-center gap-2 py-1.5">{trailing}</div>}
    </div>
  );
}

/** A pill-shaped switch between a few options (the film's chapter row, grouped). */
export function Segmented<T extends string>({
  items,
  value,
  onChange,
  className,
  size = "md",
}: {
  items: readonly { id: T; label: ReactNode; count?: number }[];
  value: T;
  onChange: (id: T) => void;
  className?: string;
  size?: "sm" | "md";
}) {
  return (
    <div role="radiogroup" className={cn("inline-flex shrink-0 items-center gap-0.5 rounded-full bg-neutral-soft p-0.5", className)}>
      {items.map(({ id, label, count }) => {
        const on = id === value;
        return (
          <button
            key={id}
            type="button"
            role="radio"
            aria-checked={on}
            onClick={() => onChange(id)}
            className={cn(
              "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full transition-all duration-200",
              size === "sm" ? "h-6 px-2.5 text-[12px]" : "h-7 px-3 text-k-caption",
              on
                ? "bg-surface font-semibold text-ink shadow-[0_1px_2px_rgb(26_29_36/0.08),0_0_0_1px_var(--hairline)]"
                : "text-ink-muted hover:text-ink"
            )}
          >
            {label}
            {count !== undefined && <span className={cn("tabular-nums", on ? "text-brand" : "opacity-70")}>{count.toLocaleString()}</span>}
          </button>
        );
      })}
    </div>
  );
}

/** A tinted note: the film's soft-fill boxes for warnings, success and hints. */
export function Callout({
  tone = "brand",
  icon: Icon,
  children,
  className,
}: {
  tone?: Tone;
  icon?: LucideIcon;
  children: ReactNode;
  className?: string;
}) {
  const t = TONE[tone];
  return (
    <div
      className={cn("flex items-start gap-2.5 rounded-lg px-3.5 py-2.5 text-k-body", className)}
      style={{ background: t.bg, color: t.fg }}
    >
      {Icon && <Icon className="mt-[3px] h-4 w-4 shrink-0" />}
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

/** A label above a form control, with an optional hint underneath. */
export function Field({ label, hint, children, className }: { label: ReactNode; hint?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <label className={cn("block", className)}>
      <span className="mb-1.5 block text-k-caption font-semibold text-ink-2">{label}</span>
      {children}
      {hint && <span className="mt-1.5 block text-k-caption text-ink-subtle">{hint}</span>}
    </label>
  );
}

/** Title + description at the top of a panel body. */
export function SectionIntro({ title, children, action }: { title: ReactNode; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex items-start gap-4">
      <div className="min-w-0 flex-1">
        <h3 className="text-k-title font-semibold text-ink">{title}</h3>
        {children && <p className="mt-1 max-w-3xl text-k-body text-ink-muted">{children}</p>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

/** An on/off switch: indigo track when on, the knob slides with the film's ease. */
export function Switch({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors duration-200 disabled:opacity-50",
        checked ? "bg-brand" : "bg-hairline-strong"
      )}
    >
      <span
        className={cn(
          "inline-block h-4 w-4 rounded-full bg-white shadow-[0_1px_2px_rgb(26_29_36/0.25)] transition-transform duration-200",
          checked ? "translate-x-[18px]" : "translate-x-0.5"
        )}
        style={{ transitionTimingFunction: "var(--ease-out)" }}
      />
    </button>
  );
}
