"""Has the owner finished their turn — judged from *how* they said it (Smart Turn v3.2).

Jev reads the words; this reads the voice: falling intonation, a slowing pace, the way a finished sentence
sounds against a trailing "and…". The two together are how ElevenLabs' turn-taking works (prosody and meaning).

Smart Turn v3.2 (pipecat-ai, BSD-2-Clause): Whisper Tiny's encoder with a classifier, about 8 MB quantised, a
few tens of milliseconds on a CPU. It takes the last 8 seconds of 16 kHz speech as Whisper log-mel features and
returns the probability that the turn is complete. The features are computed here with numpy, exactly as
Whisper's feature extractor does (validated against it), so nothing heavier than onnxruntime is needed.

Settings: SMART_TURN_MODEL (default data/models/smart-turn-v3.2-cpu.onnx; downloaded on first use).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

MODEL_PATH = Path(os.getenv("SMART_TURN_MODEL", "data/models/smart-turn-v3.2-cpu.onnx"))
MODEL_URL = "https://huggingface.co/pipecat-ai/smart-turn-v3/resolve/main/smart-turn-v3.2-cpu.onnx"
SR, SECONDS, N_FFT, HOP, N_MELS = 16000, 8, 400, 160, 80

_session = None
_filters = None
_window = None
_failed_at = 0.0
_load_lock = asyncio.Lock()


def _hz_to_mel(f):
    import numpy as np

    f = np.asarray(f, dtype=np.float64)
    mel = f / (200.0 / 3)
    log_region = f >= 1000.0
    return np.where(log_region, 15.0 + np.log(np.maximum(f, 1e-10) / 1000.0) / (np.log(6.4) / 27.0), mel)


def _mel_to_hz(m):
    import numpy as np

    m = np.asarray(m, dtype=np.float64)
    hz = m * (200.0 / 3)
    return np.where(m >= 15.0, 1000.0 * np.exp((np.log(6.4) / 27.0) * (m - 15.0)), hz)


def _mel_filters():
    """Whisper's mel filter bank (Slaney scale and normalisation), shape (201, 80)."""
    import numpy as np

    fft_freqs = np.linspace(0, SR // 2, N_FFT // 2 + 1)
    filter_freqs = _mel_to_hz(np.linspace(_hz_to_mel(0.0), _hz_to_mel(SR / 2), N_MELS + 2))
    diff = np.diff(filter_freqs)
    slopes = filter_freqs[None, :] - fft_freqs[:, None]
    down = -slopes[:, :-2] / diff[:-1]
    up = slopes[:, 2:] / diff[1:]
    bank = np.maximum(0.0, np.minimum(down, up))
    bank *= (2.0 / (filter_freqs[2:N_MELS + 2] - filter_freqs[:N_MELS]))[None, :]
    return bank


def features(audio):
    """Whisper log-mel features for the last 8 s of 16 kHz audio (zero-padded at the start), shape (1, 80, 800)."""
    import numpy as np

    global _filters, _window
    if _filters is None:
        _filters = _mel_filters()
        _window = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(N_FFT) / N_FFT)  # periodic Hann
    x = np.asarray(audio, dtype=np.float32)[-SR * SECONDS:]
    x = np.pad(x, (SR * SECONDS - len(x), 0))
    x = (x - x.mean()) / np.sqrt(x.var() + 1e-7)  # do_normalize
    padded = np.pad(x.astype(np.float64), (N_FFT // 2, N_FFT // 2), mode="reflect")  # center=True
    n_frames = 1 + (len(padded) - N_FFT) // HOP
    idx = np.arange(N_FFT)[None, :] + HOP * np.arange(n_frames)[:, None]
    spec = np.abs(np.fft.rfft(padded[idx] * _window, n=N_FFT)) ** 2  # (frames, 201)
    mel = spec @ _filters  # (frames, 80)
    log_spec = np.log10(np.maximum(mel, 1e-10)).T[:, :-1]  # (80, 800), the last frame dropped
    log_spec = np.maximum(log_spec, log_spec.max() - 8.0)
    return ((log_spec + 4.0) / 4.0).astype(np.float32)[None, :, :]


async def _load():
    global _session, _failed_at
    if _session is not None or time.monotonic() - _failed_at < 300:
        return _session
    async with _load_lock:
        if _session is not None:
            return _session
        try:
            import onnxruntime as ort

            if not MODEL_PATH.exists():
                MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
                async with httpx.AsyncClient(timeout=120, follow_redirects=True) as c:
                    r = await c.get(MODEL_URL)
                    r.raise_for_status()
                    MODEL_PATH.write_bytes(r.content)
                logger.info("Downloaded Smart Turn (%d bytes) to %s", len(r.content), MODEL_PATH)
            so = ort.SessionOptions()
            so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            so.inter_op_num_threads = 1
            so.intra_op_num_threads = 2
            so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            _session = ort.InferenceSession(str(MODEL_PATH), sess_options=so)
        except Exception as exc:  # noqa: BLE001 — turn-taking falls back to the words alone
            _failed_at = time.monotonic()
            logger.warning("Smart Turn unavailable: %s", exc)
            return None
    return _session


def _run(session, pcm16: bytes) -> float:
    import numpy as np

    audio = np.frombuffer(pcm16, dtype="<i2").astype(np.float32) / 32768.0
    out = session.run(None, {"input_features": features(audio)})
    return float(np.asarray(out[0]).reshape(-1)[0])


async def probability(pcm16: bytes) -> Optional[float]:
    """How likely the speech in this clip (16 kHz mono 16-bit PCM, its end being now) is a finished turn."""
    if len(pcm16) < SR // 5 * 2:  # under 0.2 s: nothing to judge
        return None
    session = await _load()
    if session is None:
        return None
    try:
        return round(await asyncio.to_thread(_run, session, pcm16), 3)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Smart Turn failed: %s", exc)
        return None


async def warm() -> None:
    """Load (and if needed download) the model at startup, so the first pause of the first call isn't slow."""
    await _load()
