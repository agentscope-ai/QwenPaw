# -*- coding: utf-8 -*-
"""Audio content facts: speech / music presence and audio-visual sync.

Ported from APE-benchmark ``grader/objective/program.py``
(``speech_detectability`` / ``music_presence`` / ``av_sync``) with the
librosa feature extraction re-implemented on plain numpy FFTs so the
operators stay dependency-free (numpy ships with the plugin).

These are facts, not verdicts: a video without speech or music is
entirely legitimate — the numbers only become an advisory finding when
the plan explicitly declared an expectation that plainly contradicts
them, and that judgement happens on the reviewer side, not here. The
av_sync offsets likewise stay raw: J-cut/L-cut editing legitimately
shifts speech across cuts.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

import numpy as np

# APE speech_detectability: voice fundamental band energy ratio.
_SPEECH_BAND_HZ = (85.0, 340.0)
_SPEECH_ENERGY_RATIO = 0.15
# APE music_presence: three-feature vote.
_MUSIC_TEMPO_BPM = 80.0
_MUSIC_HIGH_FREQ_RATIO = 0.10
_MUSIC_FLATNESS_MAX = 0.3
_HIGH_FREQ_SPLIT_HZ = 2000.0
# APE av_sync offset tiers (seconds -> score).
_AV_SYNC_TIERS = ((0.5, 1.0), (1.0, 0.7), (2.0, 0.4))
_FFT_WINDOW = 2048
_FFT_HOP = 1024


def _power_spectrum(
    pcm: np.ndarray,
    sample_rate: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Mean power spectrum over hann-windowed frames: (freqs, power)."""
    if pcm.size < _FFT_WINDOW:
        pcm = np.pad(pcm, (0, _FFT_WINDOW - pcm.size))
    frame_count = 1 + (pcm.size - _FFT_WINDOW) // _FFT_HOP
    frame_count = min(frame_count, 4000)
    window = np.hanning(_FFT_WINDOW).astype(np.float32)
    spectra = np.empty(
        (frame_count, _FFT_WINDOW // 2 + 1),
        dtype=np.float32,
    )
    for index in range(frame_count):
        start = index * _FFT_HOP
        chunk = pcm[start : start + _FFT_WINDOW] * window
        spectra[index] = np.abs(np.fft.rfft(chunk)) ** 2
    freqs = np.fft.rfftfreq(_FFT_WINDOW, d=1.0 / sample_rate)
    return freqs, spectra


def _spectral_flatness(spectra: np.ndarray) -> float:
    power = spectra + 1e-10
    log_mean = np.exp(np.log(power).mean(axis=1))
    arith_mean = power.mean(axis=1)
    return float(np.median(log_mean / arith_mean))


def _estimate_tempo_bpm(
    spectra: np.ndarray,
    sample_rate: int,
) -> float:
    """Coarse tempo from the onset-envelope autocorrelation.

    Takes the already-computed frame spectra: recomputing the STFT here
    would FFT the same audio twice per artifact.
    """
    hop_seconds = _FFT_HOP / sample_rate
    envelope = np.sqrt(spectra.sum(axis=1))
    onset = np.diff(envelope)
    onset[onset < 0] = 0.0
    if onset.size < 8 or float(onset.max()) <= 0:
        return 0.0
    onset = onset - onset.mean()
    corr = np.correlate(onset, onset, mode="full")[onset.size - 1 :]
    # Search lags for 40-240 BPM.
    min_lag = max(1, int(round(60.0 / 240.0 / hop_seconds)))
    max_lag = min(corr.size - 1, int(round(60.0 / 40.0 / hop_seconds)))
    if max_lag <= min_lag:
        return 0.0
    lag = int(np.argmax(corr[min_lag : max_lag + 1])) + min_lag
    peak = float(corr[lag])
    if peak <= 0 or peak < 0.1 * float(corr[0]):
        return 0.0
    return 60.0 / (lag * hop_seconds)


def audio_content_facts(
    pcm: np.ndarray | None,
    sample_rate: int,
    *,
    transcript_text: str = "",
) -> dict[str, Any]:
    """Speech/music presence facts for one decoded audio track."""
    if pcm is None or pcm.size == 0:
        return {
            "has_audio_track": False,
            "speech_detected": False,
            "music_detected": False,
            "note": "无音轨——是否构成问题取决于计划是否要求配音/BGM",
        }
    freqs, spectra = _power_spectrum(pcm, sample_rate)
    power = spectra.mean(axis=0)
    total = float(power.sum()) + 1e-10
    speech_band = (freqs >= _SPEECH_BAND_HZ[0]) & (freqs <= _SPEECH_BAND_HZ[1])
    speech_ratio = float(power[speech_band].sum()) / total
    high_band = freqs >= _HIGH_FREQ_SPLIT_HZ
    high_ratio = float(power[high_band].sum()) / total
    flatness = _spectral_flatness(spectra)
    tempo = _estimate_tempo_bpm(spectra, sample_rate)
    music_votes = {
        "tempo": tempo > _MUSIC_TEMPO_BPM,
        "high_freq": high_ratio > _MUSIC_HIGH_FREQ_RATIO,
        "harmonic": flatness < _MUSIC_FLATNESS_MAX,
    }
    speech_by_asr = bool(transcript_text.strip())
    facts: dict[str, Any] = {
        "has_audio_track": True,
        "speech_detected": speech_by_asr
        or speech_ratio > _SPEECH_ENERGY_RATIO,
        "speech_source": "asr" if speech_by_asr else "band_energy",
        "speech_band_energy_ratio": round(speech_ratio, 3),
        "music_detected": sum(music_votes.values()) >= 2,
        "music_votes": music_votes,
        "spectral_flatness": round(flatness, 3),
        "tempo_bpm": round(tempo, 1),
    }
    if speech_by_asr:
        facts["transcript_excerpt"] = transcript_text.strip()[:300]
    return facts


def av_sync_facts(
    sentences: Iterable[Mapping[str, Any]],
    cut_points_ms: Iterable[int],
) -> dict[str, Any]:
    """Offset of each speech-sentence start to its nearest cut point.

    ``sentences`` carry ``start_ms``/``end_ms``/``text`` (ASR sentence
    segments). Raw per-sentence offsets are reported alongside the APE
    tier score so the reviewer can spot a systematic shift versus one
    deliberate J-cut.
    """
    cuts = sorted(int(item) for item in cut_points_ms)
    rows: list[dict[str, Any]] = []
    scores: list[float] = []
    if not cuts:
        return {
            "measured": False,
            "note": "未检出切镜点，无参照物可测量音画同步",
        }
    for sentence in sentences:
        start_ms = int(sentence.get("start_ms") or 0)
        nearest = min(
            cuts,
            key=lambda cut, start=start_ms: abs(cut - start),
        )
        offset_seconds = abs(nearest - start_ms) / 1000.0
        score = 0.0
        for threshold, tier_score in _AV_SYNC_TIERS:
            if offset_seconds < threshold:
                score = tier_score
                break
        scores.append(score)
        rows.append(
            {
                "sentence_start_ms": start_ms,
                "nearest_cut_ms": nearest,
                "offset_seconds": round(offset_seconds, 2),
                "text": str(sentence.get("text") or "")[:60],
            },
        )
    if not rows:
        return {
            "measured": False,
            "note": "无语音句或无切镜点，音画同步无从测量",
        }
    return {
        "measured": True,
        "sentence_count": len(rows),
        "mean_tier_score": round(sum(scores) / len(scores), 2),
        "max_offset_seconds": max(row["offset_seconds"] for row in rows),
        "worst_sentences": sorted(
            rows,
            key=lambda row: -row["offset_seconds"],
        )[:3],
    }


__all__ = ["audio_content_facts", "av_sync_facts"]
