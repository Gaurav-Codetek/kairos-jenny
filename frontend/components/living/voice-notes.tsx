"use client";

// Voice notes: what Jenny raised herself while you were away. She keeps watching on the server; when the pulse finds
// something material and no call is open, she records a short note in her own voice. It waits here, unplayed, for
// the next time you open Kairos.

import { useCallback, useEffect, useRef, useState } from "react";
import { Pause, Play, X } from "lucide-react";

import { getVoiceNotes, voiceNoteHeard, voiceNoteUrl, withoutTones, type VoiceNote } from "@/lib/companion";
import { cn } from "@/lib/utils";

const CHECK_EVERY_MS = 60_000;

const clock = (at: string) => {
  const d = new Date(at);
  const today = new Date().toDateString() === d.toDateString();
  const time = d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  return today ? time : `${d.toLocaleDateString(undefined, { weekday: "short" })} ${time}`;
};

/** Plays one recording; `onDone` when it has been played through. */
function usePlayer(onDone: (id: string) => void) {
  const audio = useRef<HTMLAudioElement | null>(null);
  const [playing, setPlaying] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);

  const stop = useCallback(() => {
    audio.current?.pause();
    audio.current = null;
    setPlaying(null);
    setProgress(0);
  }, []);

  const toggle = useCallback(
    (id: string) => {
      if (playing === id) return stop();
      stop();
      const a = new Audio(voiceNoteUrl(id));
      audio.current = a;
      a.ontimeupdate = () => a.duration && setProgress(a.currentTime / a.duration);
      a.onended = () => {
        stop();
        onDone(id);
      };
      a.onerror = () => stop();
      setPlaying(id);
      a.play().catch(stop);
    },
    [playing, stop, onDone]
  );

  useEffect(() => () => audio.current?.pause(), []);
  return { playing, progress, toggle };
}

/** The pill: shown across Kairos while Jenny has a note you haven't heard. */
export function VoiceNotesPill() {
  const [notes, setNotes] = useState<VoiceNote[]>([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    const check = () =>
      getVoiceNotes()
        .then((r) => alive && setNotes(r.notes))
        .catch(() => undefined);
    check();
    const t = window.setInterval(check, CHECK_EVERY_MS);
    window.addEventListener("focus", check);
    return () => {
      alive = false;
      window.clearInterval(t);
      window.removeEventListener("focus", check);
    };
  }, []);

  const done = useCallback((id: string) => {
    voiceNoteHeard(id).catch(() => undefined);
    setNotes((n) => n.filter((x) => x.id !== id));
  }, []);
  const { playing, progress, toggle } = usePlayer(done);

  if (!notes.length) return null;
  const first = notes[0];
  const play = (n: VoiceNote) => (n.audio ? toggle(n.id) : setOpen(true));

  return (
    <div className="k-pop fixed bottom-5 right-5 z-50 w-[340px] max-w-[calc(100vw-32px)]">
      {open && (
        <div className="mb-2 max-h-[50vh] space-y-1.5 overflow-y-auto rounded-2xl border border-hairline bg-surface p-2 shadow-[0_12px_32px_rgb(15_23_42/0.14)]">
          {notes.map((n) => (
            <div key={n.id} className="rounded-xl px-2.5 py-2 hover:bg-sunken">
              <div className="flex items-center gap-2">
                {n.audio && (
                  <button onClick={() => toggle(n.id)} className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand text-white" aria-label={playing === n.id ? "Pause" : "Play"}>
                    {playing === n.id ? <Pause className="h-3 w-3" /> : <Play className="ml-0.5 h-3 w-3" />}
                  </button>
                )}
                <p className="min-w-0 flex-1 truncate text-[12px] font-semibold text-ink">{n.title ?? "A note from Jenny"}</p>
                <span className="text-[11px] text-ink-subtle">{clock(n.at)}</span>
                <button onClick={() => done(n.id)} className="text-ink-subtle hover:text-ink" aria-label="Mark as heard">
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
              <p className="mt-1 text-[12px] leading-snug text-ink-2">{withoutTones(n.text)}</p>
            </div>
          ))}
        </div>
      )}
      <div className="flex items-center gap-3 rounded-full border border-brand-border bg-surface py-2 pl-2 pr-3 shadow-[0_8px_24px_rgb(81_72_224/0.18)]">
        <button onClick={() => play(first)} className="relative flex h-11 w-11 shrink-0 items-center justify-center" aria-label={playing ? "Pause Jenny's note" : "Play Jenny's note"}>
          {!playing && <span className="k-pulse absolute inset-0 rounded-full" style={{ background: "var(--brand-soft)" }} />}
          <span className="relative flex h-9 w-9 items-center justify-center rounded-full text-white" style={{ background: "var(--brand)" }}>
            {playing === first.id ? <Pause className="h-4 w-4" /> : <Play className="ml-0.5 h-4 w-4" />}
          </span>
        </button>
        <button onClick={() => setOpen((o) => !o)} className="min-w-0 flex-1 text-left">
          <p className="flex items-center gap-1.5 text-k-body font-semibold text-ink">
            Jenny
            <span className="text-k-caption font-normal text-ink-muted">
              · {notes.length > 1 ? `${notes.length} voice notes` : "left you a voice note"} · {clock(first.at)}
            </span>
          </p>
          {playing === first.id ? (
            <span className="mt-1.5 block h-1 overflow-hidden rounded-full bg-brand-soft">
              <span className="block h-full rounded-full bg-brand transition-[width] duration-200" style={{ width: `${Math.round(progress * 100)}%` }} />
            </span>
          ) : (
            <p className={cn("truncate text-[12px] text-ink-2")} title={first.text}>
              {first.title ?? withoutTones(first.text)}
            </p>
          )}
        </button>
      </div>
    </div>
  );
}

/** A recorded note in the conversation: play it where it was left. */
export function NotePlay({ id, heard }: { id: string; heard?: boolean }) {
  const [wasHeard, setHeard] = useState(!!heard);
  const done = useCallback((nid: string) => {
    setHeard(true);
    voiceNoteHeard(nid).catch(() => undefined);
  }, []);
  const { playing, progress, toggle } = usePlayer(done);
  return (
    <button onClick={() => toggle(id)} className="inline-flex items-center gap-2 rounded-full border border-brand-border bg-brand-soft/60 py-1 pl-1 pr-3 text-[11px] font-medium text-brand-strong">
      <span className="flex h-5 w-5 items-center justify-center rounded-full bg-brand text-white">
        {playing ? <Pause className="h-2.5 w-2.5" /> : <Play className="ml-px h-2.5 w-2.5" />}
      </span>
      {playing ? (
        <span className="block h-1 w-16 overflow-hidden rounded-full bg-surface">
          <span className="block h-full bg-brand" style={{ width: `${Math.round(progress * 100)}%` }} />
        </span>
      ) : wasHeard ? (
        "Play again"
      ) : (
        "Voice note · not played"
      )}
    </button>
  );
}
