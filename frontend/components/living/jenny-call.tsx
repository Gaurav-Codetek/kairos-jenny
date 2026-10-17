"use client";

/**
 * A voice call with Jenny, shown as a pill at the top of the chat — nothing else on the screen is
 * covered. The call is the same conversation as the chat below it, and is kept.
 *
 * How it feels like talking to a composed assistant rather than a reader:
 *   - No stock fillers ("One moment.", "Still checking."): while she works, what's heard is her own account of
 *     what she's doing, and otherwise a soft thinking tone. A thank-you or a reaction gets just her reply.
 *   - She thinks out loud: each line she says before a look at the data ("Let me pull today's numbers by
 *     city…") and each reaction to what came back ("Okay — Lucknow's the one slipping…") is spoken as it
 *     arrives. They come from her real steps, never invented.
 *   - Her answer is spoken sentence by sentence while it is still being written, not after.
 *   - Tone follows the facts: the model marks a sentence [upbeat], [concerned], [thoughtful]… and the voice
 *     shifts pace and pitch to match (an HD voice can later take the same cues directly).
 *   - A soft thinking tone fills a longer wait instead of dead air.
 *   - Talk over her the way ElevenLabs Agents handle it: she stops only on a confirmed cut-in — your first words
 *     that aren't her own echo (judged by whether they follow her sentence in order) or an "mm-hm". A voice alone
 *     changes nothing on speakers; on headphones her voice dips a little meanwhile. What you'd heard is kept.
 *   - Her own turn-taking (lib/turn-taking.ts): the microphone itself tells her within a tenth of a second when
 *     you start or stop talking; when you pause she judges whether you've finished (how your words end, then a
 *     quick model read), waits through a mid-thought pause, and learns how long you tend to pause.
 *   - Speculative turns: once you pause and have likely finished, she starts on the answer (hidden); if you do
 *     carry on, it's dropped — so when you really have finished, part of the answer is already written.
 *
 * Her voice is her own: open-source text to speech (Kokoro, voice af_heart) running beside Kairos. Each
 * phrase is made while the one before it plays, so she never waits on a whole answer; long sentences are
 * split at their natural pauses, and everyday phrases are made ahead of time. When that voice service is
 * down she uses the browser's voice instead. Each phrase has a safety timer either way: a phrase that never
 * reports "done" must not stall a call.
 * Open the browser console and filter on [jenny] to follow a call step by step.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { stage } from "@/lib/stage";
import { Mic, MicOff, PhoneOff } from "lucide-react";

import {
  dropSpeculation,
  getRaises,
  logCall,
  markSeen,
  raiseMoment,
  takeWelcome,
  newChat,
  say,
  speculate,
  turnAudio,
  turnFinished,
  voiceAudio,
  voiceInfo,
  voiceStreamUrl,
  type ChatSession,
} from "@/lib/companion";
import {
  BACKCHANNEL,
  COMMON,
  completeness,
  CUE,
  fuse,
  isOwnerSpeaking,
  MicVad,
  PauseLearner,
  shouldEnd,
  withoutBackchannel,
} from "@/lib/turn-taking";
import { cn } from "@/lib/utils";

const RECOGNITION_LANG = "en-IN"; // Indian English understands Indian accents and standard English alike

export type CallPhase = "connecting" | "listening" | "thinking" | "speaking" | "paused" | "unsupported" | "blocked";

// The Web Speech API is not in TypeScript's DOM types everywhere: the little we use, typed here.
interface Recognition {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  maxAlternatives: number;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null;
  onend: (() => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  start: (track?: MediaStreamTrack) => void;
  stop: () => void;
  abort: () => void;
}
type RecognitionCtor = new () => Recognition;

/** Start recognition on the echo-cancelled microphone track (so her voice from the speakers is taken out before
 *  any words are recognised). Browsers that can't take a track ignore it and use their own microphone. */
function startOn(r: Recognition, track: MediaStreamTrack | null | undefined) {
  if (!track || track.readyState !== "live") return r.start();
  const own = track.clone();
  const end = r.onend;
  r.onend = () => {
    own.stop();
    end?.();
  };
  try {
    r.start(own);
  } catch (e) {
    own.stop();
    r.onend = end;
    if (e instanceof TypeError) r.start();
    else throw e;
  }
}

function recognitionCtor(): RecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

function pickVoice(): SpeechSynthesisVoice | null {
  const voices = window.speechSynthesis.getVoices();
  return (
    voices.find((v) => /jenny/i.test(v.name)) ??
    voices.find((v) => /aria|emma|ava|neerja|samantha|zira/i.test(v.name) && /^en/i.test(v.lang)) ??
    voices.find((v) => /^en/i.test(v.lang)) ??
    null
  );
}

const log = (...a: unknown[]) => console.info("[jenny]", ...a);

// ── words to say ─────────────────────────────────────────────────────

/** How a tone cue shifts the browser voice (an HD voice takes the cue itself). */
const PROSODY: Record<string, { rate: number; pitch: number }> = {
  upbeat: { rate: 1.07, pitch: 1.08 },
  excited: { rate: 1.09, pitch: 1.1 },
  happy: { rate: 1.05, pitch: 1.06 },
  warm: { rate: 1.0, pitch: 1.04 },
  curious: { rate: 1.04, pitch: 1.06 },
  thoughtful: { rate: 0.96, pitch: 0.98 },
  reassuring: { rate: 0.97, pitch: 1.0 },
  calm: { rate: 0.97, pitch: 0.99 },
  serious: { rate: 0.96, pitch: 0.96 },
  concerned: { rate: 0.94, pitch: 0.93 },
  sad: { rate: 0.93, pitch: 0.92 },
};
const BASE = { rate: 1.02, pitch: 1.0 };

export interface Line {
  text: string;
  tone?: string;
  /** Her own voice for this line: an object URL once made, null if it couldn't be. */
  audio?: Promise<string | null>;
  /** Fine to skip if her voice is late (a thinking-out-loud line): better silence than another voice. */
  optional?: boolean;
}

/** Long sentences split at their natural pauses: shorter phrases are made faster, so she starts sooner. */
export function phrases(lines: Line[], maxWords = 14): Line[] {
  const out: Line[] = [];
  for (const l of lines) {
    const words = l.text.split(/\s+/);
    if (words.length <= maxWords) {
      out.push(l);
      continue;
    }
    let cur: string[] = [];
    const pieces = l.text.split(/(?<=[,;:—–])\s+/).flatMap((piece) =>
      piece.split(/\s+/).length <= maxWords ? [piece] : piece.split(/\s+(?=(?:to|and|but|because|so|which|while|than|versus|with)\s)/i)
    );
    for (const piece of pieces) {
      const n = piece.split(/\s+/).length;
      if (cur.length && (cur.join(" ").split(/\s+/).length + n > maxWords)) {
        out.push({ ...l, text: cur.join(" ") });
        cur = [];
      }
      cur.push(piece);
    }
    if (cur.length) out.push({ ...l, text: cur.join(" ") });
  }
  return out;
}

/** Written words → words to say: no markdown, and numbers as a person reads them. */
export function spoken(text: string): string[] {
  const clean = text
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/[*_`#>]+/g, "")
    .replace(/^\s*[-•]\s+/gm, "")
    .replace(/\|/g, ", ")
    .replace(/−/g, "minus ")
    .replace(/\bvs\.?\b/gi, "versus")
    .replace(/(\d+(?:\.\d+)?)k\b/g, "$1 thousand")
    .replace(/(\d+(?:\.\d+)?)M\b/g, "$1 million")
    .replace(/(\d+(?:\.\d+)?)B\b/g, "$1 billion")
    .replace(/\s+/g, " ")
    .trim();
  const out: string[] = [];
  for (const s of clean.split(/(?<=[.!?])\s+/)) {
    if (!s) continue;
    if (s.length <= 200) out.push(s);
    else out.push(...(s.match(/[^,;]+[,;]?/g) ?? [s]).map((x) => x.trim()).filter(Boolean));
  }
  return out;
}

/** Text with tone cues → lines to speak, each carrying the tone of the cue before it. */
export function toLines(text: string): Line[] {
  const out: Line[] = [];
  let tone: string | undefined;
  for (const part of text.split(/(\[[a-z]+\])/i)) {
    const cue = part.match(/^\[([a-z]+)\]$/i);
    if (cue) {
      tone = cue[1].toLowerCase();
      continue;
    }
    for (const sentence of spoken(part)) out.push({ text: sentence, tone });
  }
  return out;
}

/** How much of a still-growing text can be said now: up to the end of the last finished sentence. */
export function sayableUpTo(text: string, from: number): number {
  const re = /[.!?…](?=\s|$)/g;
  re.lastIndex = from;
  let end = from;
  for (let m = re.exec(text); m; m = re.exec(text)) end = m.index + 1;
  return end;
}

// Start on the answer during a pause once the turn is this likely finished (ElevenLabs starts at about 60%).
const SPECULATE_AT = 0.6;
const SPECULATE_AFTER_MS = 200;
// Speaking first on a call: look for something worth raising every 15 s; raise it only into a real lull (she isn't
// talking or working, they haven't spoken for a few seconds), and at most once every 10 minutes.
const RAISE_CHECK_MS = 15_000;
const RAISE_LULL_MS = 3_000;
const RAISE_COOLDOWN_MS = 10 * 60_000;
const sameWords = (a: string, b: string) => {
  const norm = (t: string) => t.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  return norm(a) === norm(b);
};

/** The fallback when her own welcome isn't ready. The status line is her notes, never read out, so it's left out. */
function greeting(): string {
  const h = new Date().getHours();
  const hello = h < 5 ? "Hey, burning the midnight oil?" : h < 12 ? "Good morning." : h < 17 ? "Good afternoon." : "Good evening.";
  const ask = ["What would you like to know?", "What's on your mind?", "Where do you want to start?"][Math.floor(Math.random() * 3)];
  return `${hello} It's Jenny. ${ask}`;
}

// ── a soft thinking tone: a breath of sound instead of dead air ─────────

function useThinkingTone() {
  const ctx = useRef<AudioContext | null>(null);
  const timer = useRef<number | null>(null);
  const stop = useCallback(() => {
    if (timer.current) window.clearInterval(timer.current);
    timer.current = null;
  }, []);
  const start = useCallback(() => {
    if (timer.current) return;
    try {
      ctx.current = ctx.current ?? new AudioContext();
    } catch {
      return;
    }
    const pulse = () => {
      const c = ctx.current;
      if (!c) return;
      const t = c.currentTime;
      const g = c.createGain();
      g.gain.setValueAtTime(0, t);
      g.gain.linearRampToValueAtTime(0.022, t + 0.35);
      g.gain.linearRampToValueAtTime(0, t + 1.1);
      g.connect(c.destination);
      for (const f of [196, 293.7]) {
        const o = c.createOscillator();
        o.type = "sine";
        o.frequency.value = f;
        o.connect(g);
        o.start(t);
        o.stop(t + 1.15);
      }
    };
    pulse();
    timer.current = window.setInterval(pulse, 1900);
  }, []);
  useEffect(() => () => {
    stop();
    ctx.current?.close().catch(() => undefined);
  }, [stop]);
  return { start, stop };
}

// ── the call ─────────────────────────────────────────────────────────

/** The call itself, driven by the chat session the panel keeps current. */
export function useJennyCall({
  workspaceId,
  session,
  onSession,
}: {
  workspaceId: string;
  session: ChatSession | null;
  onSession: (s: ChatSession) => void;
}) {
  const [supported] = useState(() => typeof window !== "undefined" && !!recognitionCtor() && "speechSynthesis" in window);
  const [phase, setPhase] = useState<CallPhase>(supported ? "connecting" : "unsupported");
  const [heard, setHeard] = useState("");
  const [said, setSaid] = useState("");
  const [muted, setMuted] = useState(false);
  const thinking = useThinkingTone();

  const active = useRef(true);
  const mutedRef = useRef(false);
  const rec = useRef<Recognition | null>(null);
  const ear = useRef<Recognition | null>(null); // the second ear, open while she speaks
  const voice = useRef<SpeechSynthesisVoice | null>(null);
  const utterance = useRef<SpeechSynthesisUtterance | null>(null); // held so the browser never drops it
  const ownVoice = useRef(false); // Kokoro is up: speak with it rather than the browser's voice
  const wholeSentences = useRef(false); // her voice is ElevenLabs: say each sentence in one piece
  const player = useRef<HTMLAudioElement | null>(null);
  const making = useRef<Promise<unknown>>(Promise.resolve()); // phrases are made one after another
  const makingCtl = useRef<AbortController | null>(null);
  const run = useRef(0); // bumped to drop everything queued
  const queue = useRef<Line[]>([]);
  const busy = useRef(false);
  const starting = useRef(false);
  const spokenNow = useRef<string[]>([]); // what she has said of the current answer, for a cut-in
  const nowSaying = useRef<string[]>([]); // the phrase she's saying and the two before: all that can echo back
  // The answer in flight: which message, how much of each part has been queued, and whether it's finished.
  const turn = useRef<{ id: string | null; queued: number[]; done: boolean } | null>(null);
  const cut = useRef<string | null>(null); // set when the owner talked over her: what they had heard
  const callStarted = useRef<number | null>(null);
  const vad = useRef<MicVad | null>(null);
  const pauses = useRef(new PauseLearner());
  const ducked = useRef(0); // when she lowered her voice because someone started talking over her
  const voiceEndedAt = useRef(0);
  const listening = useRef<{ hasText: boolean; firstVoiceAt: number } | null>(null);
  const lastSpoke = useRef(0); // when she last started saying something
  const lastLine = useRef(""); // the last line of this answer queued in her voice: the next one flows on from it
  const spec = useRef<{ text: string; id: Promise<string | null> } | null>(null); // the turn started during a pause
  const sessionRef = useRef(session);
  const listenRef = useRef<(carry?: string) => void>(() => {});
  const askRef = useRef<(t: string) => void>(() => {});
  const earRef = useRef<() => void>(() => {});
  const pumpRef = useRef<() => void>(() => {});
  useEffect(() => {
    sessionRef.current = session;
  }, [session]);

  /** Stop her voice and drop what was queued — the ear stays open. */
  const silence = useCallback(() => {
    run.current += 1;
    queue.current = [];
    busy.current = false;
    starting.current = false;
    nowSaying.current = [];
    window.speechSynthesis.cancel();
    if (player.current) {
      player.current.pause();
      player.current = null;
    }
    makingCtl.current?.abort(); // phrases still being made for what was cut off
    makingCtl.current = null;
    making.current = Promise.resolve();
  }, []);

  /** Silence everything: the queue, the voice, and the ear. */
  const hush = useCallback(() => {
    silence();
    ear.current?.abort();
  }, [silence]);

  /** Nothing left to say right now: listen if the answer is finished, otherwise wait with the thinking tone. */
  const idle = useCallback(() => {
    if (!active.current) return;
    const t = turn.current;
    if (t && !t.done) {
      vad.current?.setMode("listening");
      setPhase("thinking");
      thinking.start();
      if (!ear.current) earRef.current();
      return;
    }
    turn.current = null;
    listenRef.current();
  }, [thinking]);

  const pump = useCallback(() => {
    if (!active.current) return;
    const line = queue.current.shift();
    if (!line) {
      busy.current = false;
      idle();
      return;
    }
    busy.current = true;
    const mine = run.current;
    rec.current?.abort();
    if (!ear.current) earRef.current();
    let finished = false;
    let guard = 0;
    const finish = () => {
      if (finished) return;
      finished = true;
      window.clearTimeout(guard);
      if (mine === run.current) pumpRef.current();
    };
    const begin = () => {
      lastSpoke.current = performance.now();
      thinking.stop();
      vad.current?.setMode("jenny");
      setPhase("speaking");
      setSaid(line.text);
      stage.speech(line.text, 0);
      spokenNow.current.push(line.text);
      nowSaying.current = [...nowSaying.current.slice(-2), line.text];
    };
    const browserVoice = () => {
      begin();
      const u = new SpeechSynthesisUtterance(line.text);
      const p = (line.tone && PROSODY[line.tone]) || BASE;
      if (voice.current) u.voice = voice.current;
      u.lang = voice.current?.lang ?? "en-US";
      u.rate = p.rate;
      u.pitch = p.pitch;
      guard = window.setTimeout(() => {
        log("a phrase never finished; moving on", line.text.slice(0, 40));
        finish();
      }, 4000 + line.text.length * 110);
      u.onboundary = (e) => stage.speech(line.text, e.charIndex / Math.max(1, line.text.length)); // word by word
      u.onend = finish;
      u.onerror = (e) => {
        if (e.error !== "interrupted" && e.error !== "canceled") log("speech error", e.error);
        finish();
      };
      utterance.current = u;
      window.speechSynthesis.resume(); // a paused engine stays silent otherwise
      window.speechSynthesis.speak(u);
    };
    if (!line.audio) {
      browserVoice();
      return;
    }
    // Her own voice: wait for the phrase to be made (it usually already is), then play it. Switching voices
    // mid-call is worse than a short wait: a late thinking-out-loud line is skipped, an answer line waits, and
    // the browser's voice is only for a phrase her voice failed to make.
    const LATE = "late";
    const late = new Promise<typeof LATE>((r) => window.setTimeout(() => r(LATE), line.optional ? 8000 : 30000));
    Promise.race([line.audio, late]).then((url) => {
      if (mine !== run.current || !active.current) return;
      if (url === LATE) {
        log(line.optional ? "skipped a late thinking-out-loud line" : "a phrase was very late; skipping it", line.text.slice(0, 40));
        finish();
        return;
      }
      if (!url) {
        log("her voice couldn't make a phrase; using the browser's for it");
        browserVoice();
        return;
      }
      begin();
      const a = new Audio(url);
      player.current = a;
      // How far into the line she is: what she has named so far lights up.
      a.ontimeupdate = () => a.duration && isFinite(a.duration) && stage.speech(line.text, a.currentTime / a.duration);
      guard = window.setTimeout(() => {
        log("a phrase never finished; moving on", line.text.slice(0, 40));
        finish();
      }, 30000);
      a.onended = () => {
        URL.revokeObjectURL(url);
        finish();
      };
      a.onerror = () => {
        URL.revokeObjectURL(url);
        if (mine !== run.current) return;
        if (url.startsWith("http")) browserVoice(); // the stream failed outright: say it anyway
        else finish();
      };
      a.play().catch(() => {
        URL.revokeObjectURL(url);
        if (mine === run.current) browserVoice();
      });
    });
  }, [idle, thinking]);
  useEffect(() => {
    pumpRef.current = pump;
  }, [pump]);

  /** Add lines to what she's about to say. */
  const enqueue = useCallback((given: Line[]) => {
    // A line that's only a tone tag or punctuation has nothing to say: never sent to a voice (ElevenLabs refuses it,
    // and the fallback would say it in another voice).
    const raw = given.filter((l) => /[A-Za-z0-9]/.test(l.text.replace(/\[[^\]]*\]/g, "")));
    if (!raw.length || !active.current) return;
    // Kokoro on a CPU is slow on long lines, so they go in pieces; ElevenLabs is fast and streams, and a sentence
    // said in pieces breaks up (a gap and a fresh intonation at every piece), so it gets whole sentences.
    const lines = ownVoice.current ? phrases(raw, wholeSentences.current ? 80 : 14) : raw;
    if (ownVoice.current) {
      makingCtl.current = makingCtl.current ?? new AbortController();
      const ctl = makingCtl.current;
      lines.forEach((line, i) => {
        // Fillers and "still on it" lines stand alone (and stay cached); answer lines flow on from the one before.
        const previous = line.optional ? undefined : lastLine.current || undefined;
        if (!line.optional) lastLine.current = line.text;
        // Nothing playing or waiting: the first phrase streams, so it starts as soon as the first audio arrives.
        if (i === 0 && !busy.current && !queue.current.length) {
          line.audio = Promise.resolve(voiceStreamUrl(line.text, line.tone, previous));
          return;
        }
        const made = making.current.then(async () => {
          if (ctl.signal.aborted) return null;
          try {
            return URL.createObjectURL(await voiceAudio(line.text, line.tone, ctl.signal, previous));
          } catch {
            return null;
          }
        });
        line.audio = made;
        making.current = made.catch(() => null);
      });
    }
    queue.current.push(...lines);
    if (busy.current || starting.current) return;
    starting.current = true;
    window.setTimeout(() => {
      // A beat before speaking: speech queued straight after a cancel can be dropped.
      starting.current = false;
      if (!busy.current) pumpRef.current();
    }, 120);
  }, []);

  /** While she speaks or thinks: listen for the owner talking over her. One listener for the whole answer —
   *  restarting it between sentences loses what the owner says in the gaps. */
  // Has the owner finished? Checked every tenth of a second while they hold the turn; `finish` once they have.
  // Used while listening and after they cut in over her, so a mid-thought pause is safe in both.
  const watchTurn = useCallback(
    (
      words: () => string,
      lastWordsAt: () => number,
      finish: () => void,
      hold: () => boolean = () => false,
      onJudged?: (text: string, done: number, silent: number) => void
    ) => {
      const startedAt = performance.now();
      const judged = new Map<string, number | null>();
      const heardAs = new Map<number, number | null>(); // each pause (by when the voice stopped) -> Smart Turn's verdict
      const lastJenny = () =>
        [...(sessionRef.current?.messages ?? [])].reverse().find((m) => m.role === "assistant" && !m.pending)?.text ?? "";
      const timer = window.setInterval(() => {
        if (!active.current || hold()) return;
        const t = words();
        if (!t) return;
        const now = performance.now();
        if (now - lastWordsAt() < 250) return; // words are still arriving
        // The microphone knows the moment they stopped; if it never heard them this turn (a quiet voice), the words do.
        const v = vad.current;
        const silent = v && v.lastVoiceAt >= startedAt ? v.silenceMs() : now - lastWordsAt();
        const usual = pauses.current.usualPause();
        // At their usual pause, ask once how finished these words sound; until it answers, judge locally.
        if (silent >= Math.min(usual, 500) && !judged.has(t)) {
          judged.set(t, null);
          turnFinished(t, lastJenny())
            .then((res) => judged.set(t, res.done))
            .catch(() => undefined);
        }
        // How they said it: a fifth of a second into each pause, Smart Turn hears the phrase they've just said.
        const pause = v && v.lastVoiceAt >= startedAt ? v.lastVoiceAt : 0;
        if (pause && silent >= 200 && !heardAs.has(pause)) {
          heardAs.set(pause, null);
          const pcm = v?.phrase();
          if (pcm)
            turnAudio(pcm)
              .then((res) => heardAs.set(pause, res.done))
              .catch(() => undefined);
        }
        const voiceSays = pause ? heardAs.get(pause) : null;
        const wordsSay = judged.get(t) ?? completeness(t);
        const done = fuse(wordsSay, voiceSays);
        onJudged?.(t, done, silent);
        if (shouldEnd(silent, done, usual)) {
          window.clearInterval(timer);
          log(
            `turn over after ${Math.round(silent)} ms quiet (finished ${done.toFixed(2)}: words ${wordsSay.toFixed(2)}, ` +
              `voice ${voiceSays == null ? "-" : voiceSays.toFixed(2)}; usual pause ${usual} ms)`
          );
          finish();
          return;
        }
      }, 100);
      return () => window.clearInterval(timer);
    },
    []
  );

  const openEar = useCallback(() => {
    const Ctor = recognitionCtor();
    if (!Ctor || mutedRef.current) return;
    ear.current?.abort();
    const r = new Ctor();
    r.lang = RECOGNITION_LANG;
    r.interimResults = true;
    r.continuous = true;
    r.maxAlternatives = 1;
    let interrupted = false;
    let ended = false;
    let latest = "";
    let lastWordsAt = 0;
    let unwatch: (() => void) | null = null;
    let base = 0; // where the owner's words start, once they cut in
    r.onresult = (e) => {
      const parts: string[] = [];
      for (let i = interrupted ? base : 0; i < e.results.length; i++) parts.push(e.results[i][0].transcript);
      const text = parts.join(" ").replace(/\s+/g, " ").trim();
      latest = text;
      lastWordsAt = performance.now();
      if (!interrupted) {
        if (!busy.current && !turn.current) return;
        // Only the newest thing heard, against only what she is saying now: older results hold echoes of her
        // earlier sentences, and her whole answer shares too many words with any question about it.
        const newest = e.results[e.results.length - 1][0].transcript;
        const voiceHeard = !!ducked.current && performance.now() - ducked.current < 1500; // headphones only
        const owner = busy.current
          ? isOwnerSpeaking(newest, nowSaying.current.join(" "), voiceHeard)
          : newest.trim().split(/\s+/).filter((w) => !COMMON.has(w.toLowerCase())).length >= 2 || CUE.test(newest);
        if (!owner && ducked.current && BACKCHANNEL.test(newest.trim())) ducked.current = 0; // just "mm-hm" from them
        if (!owner && busy.current && newest.trim().split(/\s+/).length >= 2) log("heard over her, taken as her echo:", newest.trim());
        if (owner) {
          interrupted = true;
          ducked.current = 0;
          cut.current = spokenNow.current.join(" ");
          log("cut in after:", cut.current.slice(0, 60) || "(nothing yet)");
          silence(); // her voice stops; the ear keeps listening to the rest of the owner's words
          thinking.stop();
          turn.current = null;
          setHeard(newest);
          setPhase("listening");
          base = e.results.length - 1;
          listening.current = { hasText: true, firstVoiceAt: performance.now() };
          unwatch = watchTurn(
            () => withoutBackchannel(latest).trim(),
            () => lastWordsAt,
            () => {
              ended = true;
              r.stop();
            }
          );
        }
      } else {
        setHeard(text);
      }
    };
    r.onerror = () => undefined;
    r.onend = () => {
      unwatch?.();
      if (ear.current === r) ear.current = null;
      if (!active.current) return;
      if (interrupted) {
        const q = withoutBackchannel(latest).trim();
        listening.current = null;
        if (ended && q) askRef.current(q);
        else listenRef.current(q); // the recogniser stopped before they finished: keep listening, keeping their words
        return;
      }
      // Not cut in: recognisers stop after a pause; keep the ear open while she is talking or thinking.
      window.setTimeout(() => active.current && (busy.current || turn.current) && !ear.current && earRef.current(), 150);
    };
    ear.current = r;
    try {
      startOn(r, vad.current?.track());
    } catch {
      /* already listening */
    }
  }, [silence, thinking, watchTurn]);
  useEffect(() => {
    earRef.current = openEar;
  }, [openEar]);

  // A turn that has likely ended: start on it now, hidden; dropped if they carry on.
  const startSpeculation = useCallback((text: string) => {
    const conv = sessionRef.current?.id;
    if (!conv || spec.current) return;
    log("you've likely finished: starting on it while you pause");
    spec.current = { text, id: speculate(conv, text).then((r) => r.id).catch(() => null) };
  }, []);
  const dropSpec = useCallback(() => {
    const sp = spec.current;
    const conv = sessionRef.current?.id;
    if (!sp) return;
    spec.current = null;
    // Only if nothing newer has started: a new speculation replaces the old one on the server anyway.
    sp.id.then((id) => id && conv && !spec.current && dropSpeculation(conv)).catch(() => undefined);
  }, []);

  const ask = useCallback(
    async (text: string) => {
      log("heard:", text);
      vad.current?.relearn(); // her answer starts: hear afresh how much of her comes back
      lastLine.current = "";
      setHeard(text);
      const heardBefore = cut.current;
      cut.current = null;
      // Started on during the pause? With the same words it's confirmed (already part-written); otherwise the
      // server drops it when the real turn arrives.
      const sp = spec.current;
      spec.current = null;
      const specId = sp && heardBefore === null && sameWords(sp.text, text) ? await sp.id : null;
      if (specId) log("confirmed the answer started during your pause");
      spokenNow.current = [];
      turn.current = { id: null, queued: [], done: false };
      rec.current?.abort();
      setPhase("thinking");
      try {
        let s: ChatSession;
        const cutInfo = heardBefore !== null ? { heard: heardBefore } : undefined;
        try {
          if (!sessionRef.current) throw new Error("no conversation yet");
          s = await say(sessionRef.current.id, text, true, cutInfo, specId, stage.takePointing());
        } catch (err) {
          if (/still answering/i.test(String(err))) {
            enqueue([{ text: "I'm still working on your last question — one moment." }]);
            return;
          }
          s = await say((await newChat(workspaceId)).id, text, true); // the conversation is gone: start one
        }
        if (turn.current)
          turn.current.id =
            (specId && s.messages.some((m) => m.id === specId) ? specId : null) ??
            [...s.messages].reverse().find((m) => m.role === "assistant" && m.pending)?.id ??
            null;
        onSession(s);
      } catch {
        turn.current = null;
        enqueue([{ text: "Sorry — I couldn't reach the data just now. Try me again in a moment.", tone: "concerned" }]);
      }
    },
    [enqueue, onSession, workspaceId]
  );
  useEffect(() => {
    askRef.current = ask;
  }, [ask]);

  const listen = useCallback(
    (carry = "") => {
      if (!active.current) return;
      thinking.stop();
      vad.current?.setMode("listening");
      if (mutedRef.current) {
        setPhase("paused");
        return;
      }
      const Ctor = recognitionCtor();
      if (!Ctor) return;
      rec.current?.abort();
      ear.current?.abort();
      const r = new Ctor();
      r.lang = RECOGNITION_LANG;
      r.interimResults = true;
      r.continuous = true; // the recogniser listens; she decides when the turn is over
      r.maxAlternatives = 1;
      let finals = carry ? `${carry} ` : "";
      let interim = "";
      let lastWordsAt = performance.now();
      let ended = false;
      let stop = false;
      const words = () => withoutBackchannel(`${finals} ${interim}`).trim();
      listening.current = { hasText: !!carry, firstVoiceAt: 0 };

      r.onresult = (e) => {
        let f = carry ? `${carry} ` : "";
        let i2 = "";
        for (let i = 0; i < e.results.length; i++) {
          const t = e.results[i][0].transcript;
          if (e.results[i].isFinal) f += `${t} `;
          else i2 += t;
        }
        finals = f;
        interim = i2;
        lastWordsAt = performance.now();
        const t = words();
        if (spec.current && !sameWords(spec.current.text, t)) dropSpec(); // they carried on
        if (t && listening.current) {
          listening.current.hasText = true;
          listening.current.firstVoiceAt ||= performance.now();
        }
        setHeard(t);
      };
      r.onerror = (e) => {
        if (e.error === "not-allowed" || e.error === "service-not-allowed") {
          stop = true;
          setPhase("blocked");
        } else if (e.error !== "no-speech" && e.error !== "aborted") {
          log("listening error", e.error);
        }
      };

      const unwatch = watchTurn(
        words,
        () => lastWordsAt,
        () => {
          ended = true;
          r.stop();
        },
        () => ended || busy.current || !!turn.current,
        (t, done, silent) => {
          if (spec.current && !sameWords(spec.current.text, t)) dropSpec();
          if (!spec.current && silent >= SPECULATE_AFTER_MS && done >= SPECULATE_AT) startSpeculation(t);
        }
      );

      r.onend = () => {
        unwatch();
        if (rec.current === r) rec.current = null;
        if (!active.current || stop || busy.current || turn.current) return;
        const t = words();
        if (ended && t) {
          listening.current = null;
          ask(t);
          return;
        }
        // The recogniser stopped on its own (they do, after a while): carry on, keeping what was said.
        window.setTimeout(() => !busy.current && !turn.current && listenRef.current(t), 150);
      };
      rec.current = r;
      try {
        startOn(r, vad.current?.track());
        setPhase("listening");
      } catch {
        window.setTimeout(() => listenRef.current(carry), 500);
      }
    },
    [ask, thinking, watchTurn, dropSpec, startSpeculation]
  );
  useEffect(() => {
    listenRef.current = listen;
  }, [listen]);

  // Start: pick the voice, greet, then listen. Hang up on unmount. The call is logged when the greeting
  // starts (not on mount, which development mode does twice).
  useEffect(() => {
    if (!supported) return;
    active.current = true;
    const choose = () => {
      voice.current = pickVoice();
    };
    choose();
    window.speechSynthesis.onvoiceschanged = choose;
    let cancelled = false;
    // "Welcome back": what changed since you were last here, worded by her (the template if it's slow).
    const welcome = Promise.race([takeWelcome(workspaceId), new Promise<null>((r) => window.setTimeout(() => r(null), 5500))]);
    const greet = window.setTimeout(async () => {
      choose();
      const info = await Promise.race([voiceInfo().catch(() => null), new Promise<null>((r) => window.setTimeout(() => r(null), 5000))]);
      if (cancelled) return;
      ownVoice.current = !!info?.available;
      wholeSentences.current = /elevenlabs/i.test(info?.engine ?? "");
      if (!ownVoice.current) {
        // A slow first check shouldn't leave the whole call on the browser's voice: look again shortly.
        window.setTimeout(() => {
          voiceInfo()
            .then((v) => {
              if (!cancelled && v.available && !ownVoice.current) {
                ownVoice.current = true;
                log("her own voice is up now:", v.voice);
              }
            })
            .catch(() => undefined);
        }, 3000);
      }
      // (The everyday phrases are already made when Kairos starts.)
      log("call started, voice:", ownVoice.current ? `${info?.voice} (${info?.engine})` : voice.current?.name ?? "browser default");
      callStarted.current = Date.now();
      const v = new MicVad({
        start: () => {
          // Someone started talking over her. Nothing audible changes on a voice alone, as with ElevenLabs Agents:
          // only a confirmed cut-in (their words) stops her — a headset hears breathing and the room, speakers her
          // own voice. On headphones the voice still counts as evidence, so one word of theirs is enough.
          if (busy.current && player.current) {
            const speakers = v.leaky();
            log(`voice over hers (${speakers ? "speakers" : "headphones"}): waiting for words`);
            if (!speakers) ducked.current = performance.now();
          }
          // Mid-turn, after a pause: the length of that pause teaches her how long this person pauses.
          if (!busy.current && listening.current?.hasText && voiceEndedAt.current)
            pauses.current.record(performance.now() - voiceEndedAt.current);
        },
        end: () => {
          voiceEndedAt.current = performance.now();
        },
      });
      vad.current = v;
      v.start().then((ok) =>
        log(ok ? `voice detection on: ${v.micLabel || "default microphone"} (echo cancellation, mono)` : "voice detection unavailable; using words alone")
      );
      const s = sessionRef.current;
      if (s) logCall(s.id, "start").then(onSession).catch(() => undefined);
      const w = await welcome;
      if (cancelled) return;
      const hello = w?.text;
      log(hello ? `welcome back, with what changed (${w.notes.length} moment(s))` : "greeting (no welcome ready)");
      if (hello) markSeen(w.notes).catch(() => undefined);
      enqueue(toLines(hello ? (/^\s*\[/.test(hello) ? hello : `[warm] ${hello}`) : `[warm] ${greeting()}`));
    }, 300);
    return () => {
      cancelled = true;
      active.current = false;
      window.clearTimeout(greet);
      rec.current?.abort();
      hush();
      thinking.stop();
      vad.current?.stop();
      vad.current = null;
      dropSpec();
      window.speechSynthesis.onvoiceschanged = null;
      const s = sessionRef.current;
      if (callStarted.current && s) {
        logCall(s.id, "end", Math.round((Date.now() - callStarted.current) / 1000)).then(onSession).catch(() => undefined);
        callStarted.current = null;
      }
      log("call ended");
    };
    // The greeting is said once, when the call starts.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // As the answer streams in (the panel keeps the session current): say each part as soon as a sentence of
  // it is finished — the thinking-out-loud lines first, then the answer — and listen again when it's all said.
  useEffect(() => {
    const t = turn.current;
    if (!t?.id || !session) return;
    const m = session.messages.find((x) => x.id === t.id);
    if (!m) return;
    const narration = m.narration ?? [];
    const parts = [...narration, m.pending ? m.live ?? "" : m.text];
    const lines: Line[] = [];
    // "Fair enough —" said in her first line isn't said again at the start of a later one.
    const opener = (parts[0] ?? "").match(/^\s*(?:\[[a-z]+\]\s*)?([A-Za-z' ]{2,30}?)\s*[—–-]\s+/)?.[1];
    parts.forEach((part, i) => {
      if (i > 0 && opener && t.queued[i] === undefined) {
        const body = part.replace(/^\s*(?:\[[a-z]+\]\s*)?/i, "");
        const again = body.match(/^([A-Za-z' ]{2,30}?)\s*[—–-]\s+/);
        if (again && again[1].trim().toLowerCase() === opener.trim().toLowerCase()) t.queued[i] = part.length - body.length + again[0].length;
      }
      const from = t.queued[i] ?? 0;
      const finished = i < narration.length || !m.pending;
      const upTo = finished ? part.length : sayableUpTo(part, from);
      if (upTo > from) {
        const optional = i < narration.length; // a thinking-out-loud line
        lines.push(...toLines(part.slice(from, upTo)).map((l) => ({ ...l, optional })));
        t.queued[i] = upTo;
      }
    });
    if (!m.pending && !t.done) {
      t.done = true;
      log(m.from_memory ? "answer from memory" : "answer complete");
    }
    if (lines.length) enqueue(lines);
    else if (t.done && !busy.current && !starting.current) idle();
  }, [session, enqueue, idle]);

  const toggleMute = useCallback(() => {
    const next = !mutedRef.current;
    mutedRef.current = next;
    setMuted(next);
    if (next) {
      rec.current?.abort();
      ear.current?.abort();
      setPhase((p) => (p === "listening" ? "paused" : p));
    } else if (!turn.current && !busy.current) {
      listenRef.current();
    }
  }, []);

  // Speak first: something material found during the call is raised at the next lull ("Sorry to interrupt…"),
  // never over the owner and never while she's answering. Asking with on_call also tells the server a call is
  // open, so it says these live instead of leaving a voice note.
  const lastRaise = useRef(0);
  useEffect(() => {
    if (!supported) return;
    const t = window.setInterval(async () => {
      const r = await getRaises(workspaceId, true).catch(() => null);
      const next = r?.raises[0];
      const s = sessionRef.current;
      const now = performance.now();
      if (!next || !s || !active.current || mutedRef.current) return;
      if (busy.current || turn.current || queue.current.length || spec.current) return;
      if (!listening.current || listening.current.hasText) return; // they've started saying something
      if (now - Math.max(voiceEndedAt.current, lastSpoke.current) < RAISE_LULL_MS) return;
      if (lastRaise.current && now - lastRaise.current < RAISE_COOLDOWN_MS) return;
      lastRaise.current = now;
      log("raising something myself:", next.title);
      spokenNow.current = [];
      lastLine.current = "";
      turn.current = { id: null, queued: [], done: false };
      rec.current?.abort();
      setPhase("thinking");
      try {
        const v = await raiseMoment(s.id, next.id, true);
        if (turn.current)
          turn.current.id = [...v.messages].reverse().find((m) => m.role === "assistant" && m.proactive)?.id ?? null;
        onSession(v);
      } catch {
        turn.current = null;
        listenRef.current();
      }
    }, RAISE_CHECK_MS);
    return () => window.clearInterval(t);
  }, [supported, workspaceId, onSession]);

  /** Tap Jenny: cut in while she speaks, or start listening when paused. */
  const tap = useCallback(() => {
    if (phase === "speaking" || phase === "thinking") {
      cut.current = spokenNow.current.join(" ");
      hush();
      thinking.stop();
      turn.current = null;
      listenRef.current();
    } else if (phase === "paused" && !mutedRef.current) {
      listenRef.current();
    }
  }, [phase, hush, thinking]);

  return { phase, heard, said, muted, toggleMute, tap };
}

const CAPTION: Record<CallPhase, string> = {
  connecting: "Connecting…",
  listening: "Listening…",
  thinking: "Thinking…",
  speaking: "Speaking · talk or tap to cut in",
  paused: "Tap to talk",
  unsupported: "Voice calls need Edge or Chrome",
  blocked: "Microphone blocked — allow it in the address bar",
};

/** The call, as a large pill: Jenny, what she's doing, the words in flight, mute and hang up. */
export function CallPill({
  workspaceId,
  session,
  onSession,
  onEnd,
}: {
  workspaceId: string;
  session: ChatSession | null;
  onSession: (s: ChatSession) => void;
  onEnd: () => void;
}) {
  const { phase, heard, said, muted, toggleMute, tap } = useJennyCall({ workspaceId, session, onSession });
  const live = phase === "listening" ? heard : phase === "speaking" ? said : phase === "thinking" ? heard : "";
  return (
    <div className="k-pop border-b border-hairline px-3 py-3">
      <div className="flex items-center gap-3 rounded-full border border-brand-border bg-brand-soft/60 py-2 pl-2 pr-2.5 shadow-[0_6px_20px_rgb(81_72_224/0.12)]">
        <button onClick={tap} className="relative flex h-14 w-14 shrink-0 items-center justify-center" aria-label="Jenny — tap to cut in or talk">
          {(phase === "speaking" || phase === "listening") &&
            [0, 1].map((i) => (
              <span
                key={i}
                className="k-pulse absolute inset-0 rounded-full"
                style={{
                  background: phase === "speaking" ? "var(--brand-soft)" : "transparent",
                  border: phase === "listening" ? "2px solid var(--brand-border)" : "none",
                  animationDelay: `${i * 0.6}s`,
                }}
              />
            ))}
          {phase === "thinking" && <span className="k-spin absolute inset-0 rounded-full border-2 border-brand-soft border-t-brand" />}
          <span
            className={cn("relative flex h-11 w-11 items-center justify-center rounded-full text-[18px] font-semibold text-white transition-transform duration-300", phase === "speaking" && "scale-110")}
            style={{ background: "var(--brand)" }}
          >
            J
          </span>
        </button>
        <div className="min-w-0 flex-1">
          <p className="flex items-center gap-1.5 text-k-body font-semibold text-ink">
            Jenny
            <span className={cn("text-k-caption font-normal", phase === "blocked" || phase === "unsupported" ? "text-danger" : "text-ink-muted")}>· {muted && phase === "paused" ? "Microphone off" : CAPTION[phase]}</span>
          </p>
          <p className="truncate text-[12px] text-ink-2" title={live}>
            {live ? (phase === "speaking" ? live : `“${live}”`) : <span className="text-ink-subtle">Ask how today is going…</span>}
          </p>
        </div>
        <button
          onClick={toggleMute}
          disabled={phase === "unsupported"}
          className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-full border transition-colors", muted ? "border-transparent bg-ink text-white" : "border-hairline bg-surface text-ink-2 hover:bg-sunken")}
          aria-label={muted ? "Turn microphone on" : "Turn microphone off"}
        >
          {muted ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
        </button>
        <button onClick={onEnd} className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-white" style={{ background: "var(--danger-dot)" }} aria-label="End call">
          <PhoneOff className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
