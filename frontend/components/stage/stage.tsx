"use client";

// Jenny's stage: the scene she's talking about, large, with the conversation's earlier scenes in a filmstrip.
// New scenes slide in as she puts them up; what she names lights up as she says it; clicking a mark points at it,
// so "why this one?" in your next words means that one.

import { AnimatePresence, MotionConfig, motion } from "motion/react";
import { ArrowLeftRight, BarChart3, Clock3, Grid3x3, Hash, LineChart, MousePointerClick, PieChart, Presentation, Rows3, ScatterChart, TrendingUp, X } from "lucide-react";

import { EmptyState } from "@/components/kairos/ds";
import { BreakdownScene, CompareScene, HoursScene, NumberScene, TrendScene } from "@/components/stage/scenes";
import { DeviationScene, HeatmapScene, ScatterScene, SeriesScene, ShareScene } from "@/components/stage/forms";
import { stage, useStage, type BarRow, type Scene, type SceneKind } from "@/lib/stage";
import { cn } from "@/lib/utils";

const ICON: Record<SceneKind, typeof BarChart3> = {
  breakdown: Rows3,
  deviation: ArrowLeftRight,
  share: PieChart,
  series: TrendingUp,
  heatmap: Grid3x3,
  scatter: ScatterChart,
  trend: LineChart,
  hours: Clock3,
  number: Hash,
  compare: BarChart3,
};

function SceneView({ scene, focus }: { scene: Scene; focus: string[] | null }) {
  const point = (r: BarRow) => stage.point({ scene_id: scene.id, key: r.key, label: r.label, title: scene.title });
  switch (scene.kind) {
    case "breakdown":
      return <BreakdownScene scene={scene} focus={focus} onPoint={point} />;
    case "hours":
      return <HoursScene scene={scene} focus={focus} onPoint={point} />;
    case "trend":
      return <TrendScene scene={scene} focus={focus} />;
    case "number":
      return <NumberScene scene={scene} />;
    case "compare":
      return <CompareScene scene={scene} focus={focus} />;
    case "series":
      return <SeriesScene scene={scene} focus={focus} />;
    case "heatmap":
      return <HeatmapScene scene={scene} focus={focus} />;
    case "scatter":
      return <ScatterScene scene={scene} focus={focus} />;
    case "deviation":
      return <DeviationScene scene={scene} focus={focus} />;
    case "share":
      return <ShareScene scene={scene} focus={focus} />;
  }
}

export function Stage() {
  const st = useStage();
  const scene = st.scenes.find((s) => s.id === st.currentId) ?? null;
  if (!scene) {
    return (
      <section className="kairos-panel">
        <EmptyState icon={Presentation} title="Jenny's stage">
          When a picture makes her answer clearer — which cities, which hours, today against normal — Jenny puts it up
          here as she talks, and lights up what she&apos;s naming. Ask her something like “which cities are driving
          cancellations?”
        </EmptyState>
      </section>
    );
  }
  const Icon = ICON[scene.kind];
  return (
    <MotionConfig reducedMotion="user">
      <section className="kairos-panel overflow-hidden">
        <header className="flex flex-wrap items-start gap-3 border-b border-hairline px-5 py-4">
          <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-soft text-brand">
            <Icon className="h-4 w-4" strokeWidth={2} />
          </span>
          <AnimatePresence mode="wait">
            <motion.div
              key={scene.id}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{ duration: 0.25 }}
              className="min-w-0 flex-1"
            >
              <h2 className="text-k-title font-semibold text-ink">{scene.title}</h2>
              <p className="text-k-caption text-ink-muted">
                {scene.subtitle}
                {scene.source?.lookup_id && <> · from Jenny&apos;s lookup {scene.source.lookup_id}</>}
              </p>
            </motion.div>
          </AnimatePresence>
          {st.pointing && st.pointing.scene_id === scene.id && (
            <motion.span
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              className="inline-flex items-center gap-1.5 rounded-full border border-brand-border bg-brand-soft py-1 pl-2.5 pr-1 text-[12px] text-brand-strong"
            >
              <MousePointerClick className="h-3.5 w-3.5" />
              Pointing at <b>{st.pointing.label}</b> — ask Jenny about it
              <button onClick={() => stage.point(null)} className="ml-1 rounded-full p-0.5 hover:bg-white/60" aria-label="Stop pointing">
                <X className="h-3 w-3" />
              </button>
            </motion.span>
          )}
        </header>
        <div className="px-5 py-5">
          <AnimatePresence mode="wait">
            <motion.div
              key={scene.id}
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10, scale: 0.985 }}
              transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
            >
              <SceneView scene={scene} focus={st.focus} />
            </motion.div>
          </AnimatePresence>
        </div>
        {st.scenes.length > 1 && (
          <footer className="flex gap-2 overflow-x-auto border-t border-hairline bg-sunken px-5 py-3">
            {st.scenes.map((s) => {
              const I = ICON[s.kind];
              const on = s.id === scene.id;
              return (
                <button
                  key={s.id}
                  onClick={() => stage.show(s.id)}
                  className={cn(
                    "inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full border px-3 text-k-caption transition-colors",
                    on ? "border-transparent bg-brand-soft font-semibold text-brand-strong" : "border-hairline bg-surface text-ink-muted hover:text-ink"
                  )}
                >
                  <I className="h-3.5 w-3.5" /> {s.title}
                </button>
              );
            })}
          </footer>
        )}
      </section>
    </MotionConfig>
  );
}
