// Jenny's microphone and camera in the Meet tab. Meet asks the browser for a microphone and a camera; it gets her
// voice (MP3 sentences from Kairos, decoded and played into a WebAudio stream) and her tile (a canvas drawn by
// camera.js). Sentences play one after another; each start and end is reported (Kairos knows when she's speaking,
// the camera lights up what she names), and "stop" silences her at once when someone talks over her.
(() => {
  if (window.__jenny) return;
  const emit = (e) => {
    try {
      window.__jennyEmit && window.__jennyEmit(e);
    } catch (_) {}
  };

  const canvas = document.createElement("canvas");
  canvas.width = 1280;
  canvas.height = 720;
  let ctx = null;
  let dest = null;
  let analyser = null;
  let vstream = null;

  function audio() {
    if (!ctx) {
      ctx = new AudioContext({ sampleRate: 48000 });
      dest = ctx.createMediaStreamDestination();
      analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      analyser.connect(dest);
    }
    if (ctx.state === "suspended") ctx.resume().catch(() => {});
    return ctx;
  }
  const video = () => (vstream = vstream || canvas.captureStream(24));

  const md = navigator.mediaDevices;
  if (md && md.getUserMedia) {
    const original = md.getUserMedia.bind(md);
    md.getUserMedia = async (c) => {
      const tracks = [];
      if (c && c.audio) {
        audio();
        tracks.push(dest.stream.getAudioTracks()[0].clone());
      }
      if (c && c.video) tracks.push(video().getVideoTracks()[0].clone());
      return tracks.length ? new MediaStream(tracks) : original(c);
    };
  }

  // ── her voice: a queue of sentences ──
  const queue = [];
  let playing = null;
  let current = null;

  function say(id, b64, text) {
    audio();
    const bytes = Uint8Array.from(atob(b64), (ch) => ch.charCodeAt(0));
    queue.push({ id, text, buf: ctx.decodeAudioData(bytes.buffer) });
    if (!playing) next();
  }

  async function next() {
    const item = queue.shift();
    if (!item) {
      playing = null;
      current = null;
      return;
    }
    playing = item;
    let buf;
    try {
      buf = await item.buf;
    } catch (_) {
      emit({ type: "spoken", id: item.id, event: "error", last: queue.length === 0 });
      return next();
    }
    if (playing !== item) return; // stopped while it was being decoded
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.connect(analyser);
    current = { src, start: ctx.currentTime, dur: buf.duration, text: item.text };
    emit({ type: "spoken", id: item.id, event: "start" });
    src.onended = () => {
      if (playing !== item) return;
      emit({ type: "spoken", id: item.id, event: "end", last: queue.length === 0 });
      next();
    };
    src.start();
  }

  function stop() {
    const was = playing;
    queue.length = 0;
    playing = null;
    try {
      current && current.src.stop();
    } catch (_) {}
    current = null;
    emit({ type: "spoken", id: was && was.id, event: "stopped", last: true });
  }

  function level() {
    if (!analyser || !current) return 0;
    const d = new Uint8Array(analyser.fftSize);
    analyser.getByteTimeDomainData(d);
    let s = 0;
    for (const v of d) s += ((v - 128) / 128) ** 2;
    return Math.min(1, Math.sqrt(s / d.length) * 4);
  }
  const progress = () =>
    current ? { text: current.text, p: Math.min(1, Math.max(0, (ctx.currentTime - current.start) / current.dur)) } : null;

  window.__jenny = {
    say,
    stop,
    scene: (s) => window.__jennyCamera && window.__jennyCamera.scene(s),
    status: (s) => window.__jennyCamera && window.__jennyCamera.status(s),
    level,
    progress,
    canvas,
  };
  window.__jennyCamera && window.__jennyCamera.attach(canvas, { level, progress });
})();
