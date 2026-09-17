# -*- coding: utf-8 -*-
"""BGM beat grid for cut-point / transition snapping (WT-B5).

Ports the upstream video-edit beat-sync methodology's measurement side:
a beat grid extracted once per music track, which cut points and
transition insertions can snap to. ``librosa`` is an optional dependency
— when it is missing the caller receives an explicit
``BeatGridUnavailable`` instead of a silent no-op, so degradation is
always declared (upstream [no-silent-downgrade]).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from domain.errors import ValidationError
from utils.logger import setup_logger

logger = setup_logger("creator.media_files.beat_grid")

# Snapping tolerance: a cut point further than this from every beat is
# left untouched (snapping across larger gaps would visibly retime cuts).
DEFAULT_SNAP_TOLERANCE_MS = 220


class BeatGridUnavailable(RuntimeError):
    """librosa is not installed; beat analysis cannot run."""


@dataclass(frozen=True, slots=True)
class BeatGrid:
    """Beat timestamps (ms) plus the estimated tempo of one audio file."""

    beats_ms: tuple[int, ...]
    tempo_bpm: float

    def snap_ms(
        self,
        value_ms: int,
        tolerance_ms: int = DEFAULT_SNAP_TOLERANCE_MS,
    ) -> int:
        """Return the nearest beat within tolerance, else the input."""
        if not self.beats_ms:
            return value_ms
        nearest = min(self.beats_ms, key=lambda beat: abs(beat - value_ms))
        if abs(nearest - value_ms) <= tolerance_ms:
            return nearest
        return value_ms


def extract_beat_grid(audio_path: str | Path) -> BeatGrid:
    """Analyze one audio file into a beat grid.

    Raises ``BeatGridUnavailable`` when librosa is missing and
    ``ValidationError`` when the file is absent — never a silent empty
    grid, so callers must acknowledge the degradation.
    """
    path = Path(audio_path)
    if not path.is_file():
        raise ValidationError(f"beat grid source does not exist: {path}")
    try:
        import librosa
    except ImportError as error:
        raise BeatGridUnavailable(
            "librosa is not installed; beat-sync snapping is unavailable "
            "(install with: pip install librosa) — proceed without beat "
            "snapping and say so, do not pretend",
        ) from error
    waveform, sample_rate = librosa.load(str(path), mono=True)
    tempo, beat_frames = librosa.beat.beat_track(
        y=waveform,
        sr=sample_rate,
    )
    beat_times = librosa.frames_to_time(beat_frames, sr=sample_rate)
    beats_ms = tuple(round(float(t) * 1000) for t in beat_times)
    tempo_value = float(tempo if not hasattr(tempo, "item") else tempo.item())
    logger.info(
        "beat grid extracted: %s beats=%d tempo=%.1f",
        path.name,
        len(beats_ms),
        tempo_value,
    )
    return BeatGrid(beats_ms=beats_ms, tempo_bpm=tempo_value)


__all__ = [
    "BeatGrid",
    "BeatGridUnavailable",
    "DEFAULT_SNAP_TOLERANCE_MS",
    "extract_beat_grid",
]
