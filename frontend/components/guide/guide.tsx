"use client";

// The guides (lib/guides.ts) on screen: a spotlight on the element each step is about, and a card beside it that
// explains it. On a first visit the starter guide opens by itself; after it, each screen's own guide opens the first
// time that screen does. The "?" in a screen's header and "Starter guide" in the sidebar replay them.

import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { ArrowLeft, ArrowRight, CircleHelp, Compass, X } from "lucide-react";

import { WELCOME, screenGuide, seenKey, type Guide } from "@/lib/guides";
import { cn } from "@/lib/utils";

type Ctx = { startWelcome: () => void; startScreen: () => void; screen: Guide | null };
const GuideCtx = createContext<Ctx>({ startWelcome: () => {}, startScreen: () => {}, screen: null });
export const useGuide = () => useContext(GuideCtx);

const seen = (id: string) => {
  try {
    return window.localStorage.getItem(seenKey(id)) === "1";
  } catch {
    return true; // no storage (a private window, say): never pop up on its own
  }
};
const markSeen = (id: string) => {
  try {
    window.localStorage.setItem(seenKey(id), "1");
  } catch {
    /* nothing to remember it in */
  }
};

/** How long a screen gets to load its data before its guide points at it. */
const SETTLE_MS = 1200;

export function GuideProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const screen = screenGuide(pathname);
  const [active, setActive] = useState<Guide | null>(null);
  const [step, setStep] = useState(0);

  const open = useCallback((g: Guide) => {
    setStep(0);
    setActive(g);
  }, []);
  const close = useCallback(() => {
    if (active) markSeen(active.id);
    setActive(null);
  }, [active]);

  // First visit: the starter guide; after it, this screen's guide the first time the screen opens. Never on its own
  // in an automated browser (screenshots, tests).
  useEffect(() => {
    if (active || navigator.webdriver) return;
    const t = window.setTimeout(() => {
      if (!seen(WELCOME.id)) open(WELCOME);
      else if (screen && !seen(screen.id)) open(screen);
    }, SETTLE_MS);
    return () => window.clearTimeout(t);
  }, [pathname, active, screen, open]);

  const ctx: Ctx = {
    startWelcome: () => open(WELCOME),
    startScreen: () => screen && open(screen),
    screen,
  };
  const welcomeEnd = active?.id === WELCOME.id && step === active.steps.length - 1;
  return (
    <GuideCtx.Provider value={ctx}>
      {children}
      {active && (
        <Coachmarks
          guide={active}
          step={step}
          onStep={setStep}
          onClose={close}
          extra={
            welcomeEnd && pathname !== "/living"
              ? {
                  label: "Meet Jenny",
                  onClick: () => {
                    close();
                    router.push("/living");
                  },
                }
              : undefined
          }
        />
      )}
    </GuideCtx.Provider>
  );
}

/** The "?" in a screen's header: replays that screen's guide. */
export function ScreenGuideButton() {
  const { screen, startScreen } = useGuide();
  if (!screen) return null;
  return (
    <button onClick={startScreen} className="k-btn k-btn-ghost !px-2" title={`How to use ${screen.title}`} aria-label={`How to use ${screen.title}`}>
      <CircleHelp className="h-[18px] w-[18px]" />
    </button>
  );
}

/** "Starter guide" at the bottom of the sidebar: replays the tour. */
export function StarterGuideButton() {
  const { startWelcome } = useGuide();
  return (
    <button onClick={startWelcome} data-guide="guide:help" className="k-btn k-btn-sm w-full justify-center">
      <Compass className="h-3.5 w-3.5" /> Starter guide
    </button>
  );
}

// ── the spotlight and its card ──

type Box = { x: number; y: number; w: number; h: number };
const PAD = 6;
const CARD_W = 372;
const GAP = 14;

/** Where an element is on screen; a display:contents wrapper has no box of its own, so it's its children's. */
function boxOf(el: Element): Box | null {
  const r = el.getBoundingClientRect();
  if (r.width > 0 && r.height > 0) return { x: r.left, y: r.top, w: r.width, h: r.height };
  const kids = [...el.children].map((c) => c.getBoundingClientRect()).filter((k) => k.width > 0 && k.height > 0);
  if (!kids.length) return null;
  const x = Math.min(...kids.map((k) => k.left));
  const y = Math.min(...kids.map((k) => k.top));
  return { x, y, w: Math.max(...kids.map((k) => k.right)) - x, h: Math.max(...kids.map((k) => k.bottom)) - y };
}

/** The element's box, kept up to date as the screen loads and moves; null when it isn't on the screen. */
function useTargetBox(target: string | undefined): Box | null {
  const [box, setBox] = useState<Box | null>(null);
  useLayoutEffect(() => {
    if (!target) return;
    let scrolled = false;
    const read = () => {
      const el = document.querySelector(`[data-guide="${target}"]`);
      if (el && !scrolled) {
        el.scrollIntoView({ block: "nearest", inline: "nearest" });
        scrolled = true;
      }
      const b = el ? boxOf(el) : null;
      setBox((prev) =>
        prev && b && Math.abs(prev.x - b.x) < 1 && Math.abs(prev.y - b.y) < 1 && Math.abs(prev.w - b.w) < 1 && Math.abs(prev.h - b.h) < 1
          ? prev
          : b
      );
    };
    read();
    const t = window.setInterval(read, 250);
    window.addEventListener("resize", read);
    return () => {
      window.clearInterval(t);
      window.removeEventListener("resize", read);
    };
  }, [target]);
  return target ? box : null;
}

/** Where the card goes: beside the spotlight where it fits (right, left, below, above), always inside the window. */
function place(box: Box | null, cardH: number): { left: number; top: number } {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  if (!box) return { left: (vw - CARD_W) / 2, top: Math.max(16, (vh - cardH) / 2) };
  const clampY = (y: number) => Math.min(Math.max(16, y), vh - cardH - 16);
  const clampX = (x: number) => Math.min(Math.max(16, x), vw - CARD_W - 16);
  if (box.x + box.w + PAD + GAP + CARD_W <= vw - 16) return { left: box.x + box.w + PAD + GAP, top: clampY(box.y) };
  if (box.x - PAD - GAP - CARD_W >= 16) return { left: box.x - PAD - GAP - CARD_W, top: clampY(box.y) };
  if (box.y + box.h + PAD + GAP + cardH <= vh - 16) return { left: clampX(box.x), top: box.y + box.h + PAD + GAP };
  if (box.y - PAD - GAP - cardH >= 16) return { left: clampX(box.x), top: box.y - PAD - GAP - cardH };
  return { left: vw - CARD_W - 24, top: vh - cardH - 24 }; // a spotlight bigger than the window: the card in a corner
}

function Coachmarks({
  guide,
  step,
  onStep,
  onClose,
  extra,
}: {
  guide: Guide;
  step: number;
  onStep: (n: number) => void;
  onClose: () => void;
  extra?: { label: string; onClick: () => void };
}) {
  const s = guide.steps[step];
  const last = step === guide.steps.length - 1;
  const box = useTargetBox(s.target);
  const card = useRef<HTMLDivElement>(null);
  const [cardH, setCardH] = useState(220);
  useLayoutEffect(() => {
    if (card.current) setCardH(card.current.offsetHeight);
  }, [step, box]);

  const next = useCallback(() => (last ? onClose() : onStep(step + 1)), [last, onClose, onStep, step]);
  const back = useCallback(() => step > 0 && onStep(step - 1), [onStep, step]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowRight" || e.key === "Enter") next();
      else if (e.key === "ArrowLeft") back();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [next, back, onClose]);

  const at = place(box, cardH);
  const welcome = guide.id === "welcome";
  return (
    <div className="fixed inset-0 z-[100]" role="dialog" aria-modal="true" aria-label={guide.title}>
      {/* the dimmed screen, with a window cut around the step's element */}
      {box ? (
        <div
          className="pointer-events-none absolute rounded-xl ring-2 ring-brand transition-all duration-300 ease-out"
          style={{
            left: box.x - PAD,
            top: box.y - PAD,
            width: box.w + PAD * 2,
            height: box.h + PAD * 2,
            boxShadow: "0 0 0 9999px rgb(26 29 36 / 0.55)",
          }}
        />
      ) : (
        <div className="absolute inset-0 bg-[rgb(26_29_36/0.55)]" />
      )}
      {/* clicks outside the card do nothing: the guide ends from its own buttons */}
      <div className="absolute inset-0" onClick={(e) => e.stopPropagation()} />

      <div
        ref={card}
        key={`${guide.id}-${step}`}
        className="kairos-panel k-pop absolute flex flex-col gap-3 p-5 shadow-[0_24px_60px_-20px_rgb(26_29_36/0.55)] transition-[left,top] duration-300 ease-out"
        style={{ left: at.left, top: at.top, width: CARD_W }}
      >
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-soft px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-brand-strong">
            {welcome ? <Compass className="h-3 w-3" /> : <CircleHelp className="h-3 w-3" />}
            {welcome ? "Starter guide" : `${guide.title} guide`}
          </span>
          <span className="text-k-caption tabular-nums text-ink-subtle">
            {step + 1} of {guide.steps.length}
          </span>
          <button onClick={onClose} className="k-btn k-btn-ghost k-btn-sm ml-auto !px-1.5" aria-label="Close the guide" title="Close (Esc)">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div>
          <h2 className="text-[17px] font-bold leading-snug text-ink">{s.title}</h2>
          <p className="mt-1.5 text-k-body leading-relaxed text-ink-2">{s.body}</p>
        </div>
        <div className="flex items-center gap-1.5 pt-1">
          {guide.steps.map((_, i) => (
            <button
              key={i}
              onClick={() => onStep(i)}
              aria-label={`Step ${i + 1}`}
              className={cn("h-1.5 rounded-full transition-all duration-200", i === step ? "w-5 bg-brand" : "w-1.5 bg-hairline hover:bg-ink-subtle")}
            />
          ))}
        </div>
        <div className="flex items-center gap-2 border-t border-hairline pt-3">
          {!last && (
            <button onClick={onClose} className="k-btn k-btn-ghost k-btn-sm">
              Skip
            </button>
          )}
          <div className="ml-auto flex items-center gap-2">
            {step > 0 && (
              <button onClick={back} className="k-btn k-btn-sm">
                <ArrowLeft className="h-3.5 w-3.5" /> Back
              </button>
            )}
            {last && extra && (
              <button onClick={extra.onClick} className="k-btn k-btn-sm">
                {extra.label}
              </button>
            )}
            <button onClick={next} className="k-btn k-btn-primary k-btn-sm">
              {last ? (welcome ? "Start exploring" : "Got it") : "Next"}
              {!last && <ArrowRight className="h-3.5 w-3.5" />}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
