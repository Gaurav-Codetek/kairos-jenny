// Jenny's ears, the fast way: the meeting's own audio. Every voice Meet plays to her (its incoming WebRTC audio
// tracks) is mixed, brought down to 16 kHz 16-bit mono, and sent to Kairos in 100 ms pieces, where ElevenLabs'
// realtime speech to text turns it into words as they're said. Her own voice is sent, never received, so she can't
// hear herself. Off until Kairos turns it on ({type: "hearing", on: true}); captions still name who's speaking.
(() => {
  if (window.__jennyHearing) return;
  const emit = (e) => {
    try {
      window.__jennyEmit && window.__jennyEmit(e);
    } catch (_) {}
  };

  const RATE = 16000;
  const CHUNK = 1600; // 100 ms at 16 kHz
  const QUIET = 0.002; // RMS below this is silence (Meet's comfort noise sits under it)
  const HANGOVER = 15; // pieces (1.5 s) still sent after the last sound, so the end of a phrase is heard
  let on = false;
  let ctx = null;
  let mix = null;
  const tracks = new Map(); // track id -> its source node

  let buf = new Int16Array(CHUNK);
  let n = 0;
  let quietFor = HANGOVER;
  let before = null; // the piece before a sound starts, so its first syllable isn't clipped

  const b64 = (i16) => {
    const bytes = new Uint8Array(i16.buffer);
    let s = "";
    for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    return btoa(s);
  };

  function piece(chunk) {
    let sq = 0;
    for (let i = 0; i < chunk.length; i++) sq += (chunk[i] / 32768) ** 2;
    const loud = Math.sqrt(sq / chunk.length) >= QUIET;
    quietFor = loud ? 0 : quietFor + 1;
    if (quietFor > HANGOVER) {
      before = chunk; // long silence: nothing sent, but kept in case speech starts in the next piece
      return;
    }
    if (before) {
      emit({ type: "audio", pcm: b64(before) });
      before = null;
    }
    emit({ type: "audio", pcm: b64(chunk) });
  }

  function start() {
    if (ctx) return;
    ctx = new AudioContext({ sampleRate: 48000 });
    mix = ctx.createGain();
    const node = ctx.createScriptProcessor(4096, 1, 1);
    const ratio = RATE / ctx.sampleRate;
    let acc = 0;
    let cnt = 0;
    let phase = 0;
    node.onaudioprocess = (e) => {
      if (!on) return;
      const x = e.inputBuffer.getChannelData(0);
      for (let i = 0; i < x.length; i++) {
        // average down to 16 kHz (a crude low-pass, plenty for speech)
        acc += x[i];
        cnt++;
        phase += ratio;
        if (phase >= 1) {
          phase -= 1;
          const v = Math.max(-1, Math.min(1, acc / cnt));
          acc = 0;
          cnt = 0;
          buf[n++] = v < 0 ? v * 32768 : v * 32767;
          if (n === CHUNK) {
            piece(buf);
            buf = new Int16Array(CHUNK);
            n = 0;
          }
        }
      }
    };
    mix.connect(node);
    node.connect(ctx.destination); // a script node only runs when connected; it writes nothing, so it's silent
    if (ctx.state === "suspended") ctx.resume().catch(() => {});
  }

  function listen(track) {
    if (track.kind !== "audio" || tracks.has(track.id)) return;
    start();
    const src = ctx.createMediaStreamSource(new MediaStream([track]));
    src.connect(mix);
    tracks.set(track.id, src);
    track.addEventListener("ended", () => {
      try {
        src.disconnect();
      } catch (_) {}
      tracks.delete(track.id);
    });
  }

  // Every audio track Meet receives passes through here (patched before Meet's own scripts run).
  const Original = window.RTCPeerConnection;
  if (Original) {
    function Patched(...args) {
      const pc = new Original(...args);
      pc.addEventListener("track", (e) => listen(e.track));
      return pc;
    }
    Patched.prototype = Original.prototype;
    Object.setPrototypeOf(Patched, Original); // static methods (generateCertificate)
    window.RTCPeerConnection = Patched;
  }

  window.__jennyHearing = {
    set(v) {
      on = !!v;
      if (on && ctx && ctx.state === "suspended") ctx.resume().catch(() => {});
    },
    tracks: () => tracks.size,
  };
  if (window.__jenny) window.__jenny.hearing = (v) => window.__jennyHearing.set(v);
})();
