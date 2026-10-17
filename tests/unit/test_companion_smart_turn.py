"""Smart Turn's audio features (Whisper log-mel, computed with numpy) — no model, no network."""

import pytest

np = pytest.importorskip("numpy")

from kairos_kb.companion import smart_turn  # noqa: E402


def test_features_have_the_shape_the_model_takes():
    f = smart_turn.features(np.zeros(16000, dtype=np.float32))
    assert f.shape == (1, 80, 800) and f.dtype == np.float32


def test_short_audio_is_padded_at_the_start_so_the_speech_sits_at_the_end():
    tone = np.sin(2 * np.pi * 220 * np.arange(16000) / 16000).astype(np.float32)
    f = smart_turn.features(tone)[0]
    energy = f.mean(axis=0)
    assert energy[-50:].mean() > energy[:50].mean()  # the sound is in the last second, not the first


def test_the_mel_filters_cover_the_spectrum_like_whispers():
    bank = smart_turn._mel_filters()
    assert bank.shape == (201, 80)
    assert (bank >= 0).all() and (bank.sum(axis=0) > 0).all()  # every filter has a band


async def test_too_little_audio_is_not_judged():
    assert await smart_turn.probability(b"\x00\x00" * 1000) is None
