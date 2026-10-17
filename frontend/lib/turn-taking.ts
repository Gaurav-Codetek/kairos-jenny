/**
 * Jenny's turn-taking: when you've started talking, when you've finished, and how long you tend to pause.
 *
 *   MicVad          listens to the microphone itself (with the browser's echo cancellation and noise
 *                   suppression) and knows within a tenth of a second when someone starts or stops speaking —
 *                   long before words come back from speech recognition. Its threshold follows the room: the
 *                   background noise while you're quiet, and how much of her own voice leaks into the
 *                   microphone while she speaks, so her echo doesn't count as you.
 *   completeness    a first, local read of whether your words so far sound finished ("…and", "what about…"
 *                   don't); a quick model judgment refines it during a pause.
 *   PauseLearner    how long you pause mid-thought, learned as you talk, so she waits long enough for you —
 *                   and no longer.
 *   shouldEnd       the decision: finished-sounding words after your usual pause, or a long silence.
 */

export type VadMode = "listening" | "jenny";

const BLUETOOTH = /bluetooth|hands-?free|headset|airpods|buds|\bbt\b/i;

/** The microphone just opened is a Bluetooth headset's and there's another one: that other one (labels are only
 *  readable once a microphone is open). */
async function otherThanBluetooth(open: MediaStream): Promise<MediaDeviceInfo | null> {
  const label = open.getAudioTracks()[0]?.label ?? "";
  if (!BLUETOOTH.test(label) || !navigator.mediaDevices.enumerateDevices) return null;
  try {
    const inputs = (await navigator.mediaDevices.enumerateDevices()).filter(
      (d) => d.kind === "audioinput" && d.deviceId && !["default", "communications"].includes(d.deviceId)
    );
    return inputs.find((d) => d.label && !BLUETOOTH.test(d.label)) ?? null;
  } catch {
    return null;
  }
}

export class MicVad {
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private analyser: AnalyserNode | null = null;
  private buf: Float32Array<ArrayBuffer> | null = null;
  private timer: number | null = null;
  private stopped = false;
  private ring: Float32Array | null = null; // the last few seconds of the microphone, at the device's rate
  private ringAt = 0;
  private ringFull = false;
  private voicedSince = 0;
  noise = 0.008; // the room's background level
  echo = 0; // her own voice leaking into the microphone while she speaks
  private echoKept = 0; // what her echo was last time she spoke (the room and speakers don't change mid-call)
  private echoKnown = false; // heard her at least once this call
  private jennySince = 0;
  voiced = false;
  lastVoiceAt = 0;
  speechStartedAt = 0;
  phraseStartedAt = 0; // where the current phrase began: the first speech after a real pause (0.7 s or more)
  private gapBefore = 0;
  mode: VadMode = "listening";
  micLabel = ""; // which microphone it's listening on

  constructor(private on: { start?: () => void; end?: () => void } = {}) {}

  /** Ask for the microphone and start listening. False when it isn't available (the call still works without). */
  async start(): Promise<boolean> {
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) return false;
    const constraints = (deviceId?: string): MediaStreamConstraints => ({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        channelCount: { ideal: 1 },
        ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
      },
    });
    try {
      this.stream = await navigator.mediaDevices.getUserMedia(constraints());
    } catch {
      return false;
    }
    // Opening a Bluetooth headset's own microphone switches it into hands-free mode, which plays everything in
    // phone-call quality. If another microphone is there (the laptop's own), listen on that instead, so the
    // earphones keep playing her voice in full quality.
    const other = await otherThanBluetooth(this.stream);
    if (other) {
      try {
        const better = await navigator.mediaDevices.getUserMedia(constraints(other.deviceId));
        this.stream.getTracks().forEach((t) => t.stop());
        this.stream = better;
      } catch {
        /* keep the headset's microphone */
      }
    }
    this.micLabel = this.stream.getAudioTracks()[0]?.label ?? "";
    if (this.stopped) {
      // Hung up while the browser was still asking for the microphone.
      this.stream.getTracks().forEach((t) => t.stop());
      this.stream = null;
      return false;
    }
    this.ctx = new AudioContext();
    const source = this.ctx.createMediaStreamSource(this.stream);
    this.analyser = this.ctx.createAnalyser();
    this.analyser.fftSize = 1024;
    source.connect(this.analyser);
    this.buf = new Float32Array(new ArrayBuffer(this.analyser.fftSize * 4));
    // The last eight and a half seconds of the voice itself: how they said it, for the Smart Turn model.
    this.ring = new Float32Array(Math.ceil(this.ctx.sampleRate * 8.5));
    const tap = this.ctx.createScriptProcessor(4096, 1, 1);
    tap.onaudioprocess = (e) => this.keep(e.inputBuffer.getChannelData(0));
    const mute = this.ctx.createGain();
    mute.gain.value = 0;
    source.connect(tap);
    tap.connect(mute);
    mute.connect(this.ctx.destination); // a processor only runs when it leads somewhere
    this.timer = window.setInterval(() => this.tick(), 30);
    return true;
  }

  stop() {
    this.stopped = true;
    if (this.timer) window.clearInterval(this.timer);
    this.timer = null;
    this.stream?.getTracks().forEach((t) => t.stop());
    this.ctx?.close().catch(() => undefined);
    this.stream = null;
    this.ctx = null;
  }

  /** How loud the microphone is right now (RMS, 0–1). */
  level(): number {
    if (!this.analyser || !this.buf) return 0;
    this.analyser.getFloatTimeDomainData(this.buf);
    let sum = 0;
    for (let i = 0; i < this.buf.length; i++) sum += this.buf[i] * this.buf[i];
    return Math.sqrt(sum / this.buf.length);
  }

  private tick() {
    const rms = this.level();
    const now = performance.now();
    const jenny = this.mode === "jenny";
    // The first half second she ever speaks is for hearing how loud she comes back through the speakers (if at all),
    // not for hearing the owner: follow her peaks up quickly.
    if (jenny && !this.echoKnown) {
      this.echo = rms > this.echo ? this.echo * 0.7 + rms * 0.3 : this.echo * 0.98 + rms * 0.02;
      if (now - this.jennySince < 500) return;
      this.echoKnown = true;
    }
    const threshold = Math.max(this.noise * 3, 0.012, jenny ? this.echo * 2.2 : 0);
    // Only quiet moments teach the background and her echo (a voice must never become "background").
    if (rms <= threshold && !this.voiced) {
      if (!jenny) this.noise = rms < this.noise ? this.noise * 0.85 + rms * 0.15 : this.noise * 0.997 + rms * 0.003;
      else this.echo = rms > this.echo ? this.echo * 0.97 + rms * 0.03 : this.echo * 0.995 + rms * 0.005;
    }
    if (rms > threshold) {
      if (!this.voiced && !this.voicedSince) this.gapBefore = now - this.lastVoiceAt;
      this.lastVoiceAt = now;
      if (!this.voiced) {
        this.voicedSince = this.voicedSince || now;
        // Over her voice it takes a little longer to be sure it's you.
        if (now - this.voicedSince >= (this.mode === "jenny" ? 200 : 110)) {
          this.voiced = true;
          this.speechStartedAt = this.voicedSince;
          if (this.gapBefore >= 700) this.phraseStartedAt = this.voicedSince;
          this.on.start?.();
        }
      }
    } else {
      this.voicedSince = 0;
      if (this.voiced && now - this.lastVoiceAt > 220) {
        this.voiced = false;
        this.on.end?.();
      }
    }
  }

  private keep(chunk: Float32Array) {
    const ring = this.ring;
    if (!ring) return;
    for (let i = 0; i < chunk.length; i++) {
      ring[this.ringAt] = chunk[i];
      this.ringAt = (this.ringAt + 1) % ring.length;
      if (this.ringAt === 0) this.ringFull = true;
    }
  }

  /** The last `seconds` of the microphone as 16 kHz mono 16-bit PCM (what Smart Turn takes), or null. */
  recent(seconds = 8): Int16Array<ArrayBuffer> | null {
    const ring = this.ring;
    if (!ring || !this.ctx) return null;
    const have = this.ringFull ? ring.length : this.ringAt;
    const rate = this.ctx.sampleRate;
    const take = Math.min(have, Math.floor(rate * seconds));
    if (take < rate * 0.2) return null;
    const start = (this.ringAt - take + ring.length) % ring.length;
    const n = Math.floor((take * 16000) / rate);
    const out = new Int16Array(new ArrayBuffer(n * 2));
    for (let i = 0; i < n; i++) {
      const pos = (i * rate) / 16000; // linear interpolation down to 16 kHz
      const j = Math.floor(pos);
      const a = ring[(start + j) % ring.length];
      const b = ring[(start + Math.min(j + 1, take - 1)) % ring.length];
      const v = a + (b - a) * (pos - j);
      out[i] = Math.max(-32768, Math.min(32767, Math.round(v * 32767)));
    }
    return out;
  }

  /** The current phrase (since the last real pause, at most 8 s) as 16 kHz PCM: what Smart Turn should judge. A phrase
   *  before a long pause sounds like a separate one and muddles its read of how this one ends. */
  phrase(): Int16Array<ArrayBuffer> | null {
    if (!this.phraseStartedAt) return this.recent(8);
    return this.recent(Math.max(0.5, Math.min(8, (performance.now() - this.phraseStartedAt) / 1000 + 0.2)));
  }

  /** How long it has been quiet (0 while someone is speaking). */
  silenceMs(): number {
    if (this.voiced) return 0;
    return this.lastVoiceAt ? performance.now() - this.lastVoiceAt : Number.POSITIVE_INFINITY;
  }

  setMode(mode: VadMode) {
    if (mode === this.mode) return;
    this.mode = mode;
    if (mode === "jenny") {
      this.echo = Math.max(this.echoKept, this.noise);
      this.jennySince = performance.now();
      this.voiced = false;
      this.voicedSince = 0;
    } else {
      this.echoKept = this.echo;
    }
  }

  /** A new answer is starting: hear afresh how loud she comes back (headphones may have come off, or gone on). */
  relearn() {
    this.echoKnown = false;
    this.echo = this.noise;
    this.echoKept = 0;
    this.jennySince = performance.now();
  }

  /** Her voice comes back into the microphone: on speakers rather than headphones, so cut-ins need more proof. */
  leaky(): boolean {
    return Math.max(this.echo, this.echoKept) > Math.max(0.015, this.noise * 3);
  }

  /** The microphone with the browser's echo cancellation, for speech recognition to listen on too. */
  track(): MediaStreamTrack | null {
    return this.stream?.getAudioTracks()[0] ?? null;
  }
}

// Words a finished thought rarely ends on.
const TRAILING =
  /\b(and|but|or|so|because|cause|the|a|an|of|to|with|about|for|in|on|at|from|is|are|was|were|um+|uh+|er+|like|what|which|who|when|where|how|if|maybe|then|than|versus|my|our|your|their)\s*[,]?$/i;
const QUESTION_START = /^(how|what|which|who|when|where|why|is|are|was|can|could|would|should|do|does|did|will|tell|show|give)\b/i;

/** A first, local read: does this sound like a finished thought? (0 = clearly mid-sentence, 1 = clearly done.) */
export function completeness(text: string): number {
  const t = text.trim();
  if (!t) return 0;
  if (TRAILING.test(t)) return 0.1;
  if (/[?.!]$/.test(t)) return 0.8;
  const words = t.split(/\s+/).length;
  if (QUESTION_START.test(t) && words >= 4) return 0.7;
  if (words <= 2) return 0.5; // "Pune?" can be a whole turn; "What about" (caught above) can't
  return 0.55;
}

/** How long this person pauses mid-thought, learned as they talk. */
export class PauseLearner {
  private pauses: number[] = [];

  /** A pause that was followed by more of the same turn. */
  record(ms: number) {
    if (ms < 150 || ms > 4000) return;
    this.pauses = [...this.pauses.slice(-29), ms];
  }

  /** How long to wait before treating silence as the end of a finished-sounding turn. */
  usualPause(): number {
    if (this.pauses.length < 3) return 550;
    const sorted = [...this.pauses].sort((a, b) => a - b);
    const p80 = sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.8))];
    return Math.max(450, Math.min(1400, p80 + 150));
  }
}

/** Has the owner finished? From how long it's been quiet, how finished the words sound, and their usual pause. */
export function shouldEnd(silenceMs: number, done: number, usualPause: number): boolean {
  // Words and voice both say it's finished: answer after 0.3 s, as ElevenLabs' agent did (0.2-0.3 s after silence).
  if (done >= 0.9) return silenceMs >= Math.min(usualPause, 300);
  if (silenceMs >= 2600 && done >= 0.15) return true; // a long silence ends almost any turn
  if (silenceMs >= 3400) return true; // …even an unfinished one
  if (done >= 0.7) return silenceMs >= usualPause;
  if (done >= 0.4) return silenceMs >= Math.max(1200, usualPause * 1.6);
  return false;
}

/** The words' verdict (Jev, or the local read) and the voice's (Smart Turn), together, the way ElevenLabs'
 *  turn-taking reads meaning and prosody. When both lean unfinished, the surer one wins; otherwise they're
 *  averaged, so a misfire of either can neither cut the owner off nor leave them waiting long. */
export function fuse(words: number, voice: number | null | undefined): number {
  if (voice == null) return words;
  if (voice < 0.15 && words < 0.5) return Math.min(words, voice);
  return (words + voice) / 2;
}

/** Recognition sometimes picks up her own soft "mm-hm" in the owner's words: take it out. */
export function withoutBackchannel(text: string): string {
  return text.replace(/\b(m+-?h?m+|mhm|uh-huh)\b[.,]?\s*/gi, " ").replace(/\s+/g, " ").trim();
}

// ── Cut-ins: is that the owner talking over her, or her own voice coming back? ──────────────────────────────

// Words that say nothing about who is talking: filler, and numbers (said as words, maybe heard as digits).
export const COMMON = new Set(
  `a an the and or but so of on in at for to it its is are was were be been i you we he she they this that these those
  yes no ok okay um uh hmm ah oh well just like right now today so far about very really not with as by from than then
  one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen
  nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred thousand million billion point percent minus`.split(/\s+/)
);
export const CUE = /\b(stop|wait|hold on|jenny|sorry|excuse me|actually|hang on)\b/i;
// What a listener says while the other person talks ("yeah", "okay", "mm-hmm"): never a cut-in.
export const BACKCHANNEL =
  /^(?:\s*(?:yeah|yes|yep|yup|ok(?:ay)?|mm+-?h?m+|mhm|uh-huh|right|sure|got it|cool|alright|all right|i see|hmm+|ah|oh|nice|great|true|exactly|go on|makes sense)[\s.,!?]*)+$/i;

const wordsOf = (s: string) => (s.toLowerCase().match(/[a-z']+/g) ?? []).filter((w) => w.length > 1);
const skeleton = (w: string) => w.replace(/[aeiouy']/g, "").replace(/(.)\1+/g, "$1");

function editDistance(a: string, b: string): number {
  let prev = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    for (let j = 1; j <= b.length; j++) cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    prev = cur;
  }
  return prev[b.length];
}

/** Could recognition have heard her word `hers` as `heard`? ("track"/"trek", "hours"/"ours", "del" of "delivered") */
function soundsLike(heard: string, hers: string): boolean {
  if (heard === hers) return true;
  if (heard.length >= 4 && hers.length >= 4) {
    if (editDistance(heard, hers) <= 1) return true;
    const [a, b] = [skeleton(heard), skeleton(hers)]; // consonants alone, when there are enough to mean something
    if (a.length >= 3 && b.length >= 3 && editDistance(a, b) <= 1) return true;
  }
  return heard.length >= 4 && (hers.startsWith(heard) || hers.endsWith(heard));
}

/** "del" + "ivered" back into "delivered", when that's one of her words and neither piece is one alone. */
function rejoined(heard: string[], hers: string[]): string[] {
  const out: string[] = [];
  for (let i = 0; i < heard.length; i++) {
    const next = heard[i + 1];
    const two = heard[i] + (next ?? "");
    const pieceIsHers = hers.some((h) => (heard[i].length >= 4 && soundsLike(heard[i], h)) || (!!next && next.length >= 4 && h === next));
    if (next && !pieceIsHers && hers.some((h) => h.length >= 6 && editDistance(two, h) <= 1)) {
      out.push(two);
      i++;
    } else out.push(heard[i]);
  }
  return out;
}

/** How many of the heard words follow her sentence in order (allowing for mishearing): longest common subsequence. */
function inOrder(heard: string[], hers: string[]): number {
  let prev = new Array(hers.length + 1).fill(0);
  for (let i = 1; i <= heard.length; i++) {
    const cur = [0];
    for (let j = 1; j <= hers.length; j++)
      cur[j] = soundsLike(heard[i - 1], hers[j - 1]) ? prev[j - 1] + 1 : Math.max(prev[j], cur[j - 1]);
    prev = cur;
  }
  return prev[hers.length];
}

/** Did the microphone hear the owner, or Jenny's own voice coming back from the speakers?
 *
 *  Her echo repeats her sentence in order, even when misheard ("del ivered orders are on trek"); the owner may reuse
 *  her words but not in her order, and with new ones around them. So: it's her echo when most of what was heard lines
 *  up with what she's just said; otherwise it's the owner, after two words, or after one once the microphone has
 *  already heard a voice louder than her echo (`voiceHeard`). "Yeah", "mm-hm" never count. */
export function isOwnerSpeaking(heard: string, beingSaid: string, voiceHeard = false): boolean {
  if (BACKCHANNEL.test(heard.trim())) return false;
  const hers = wordsOf(beingSaid);
  const said = rejoined(wordsOf(heard), hers);
  if (!said.length) return false;
  const echo = inOrder(said, hers) / said.length;
  if (CUE.test(heard) && !CUE.test(beingSaid)) return echo < 0.8;
  return said.length >= (voiceHeard ? 1 : 2) && echo <= 0.5;
}
