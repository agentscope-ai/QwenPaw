# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
# Vendored from Qwen-MM-Plugins (Apache-2.0), release commit 077aea6.
# Upstream path: src/capabilities/video-edit/skill/scripts/auto_grade.py
#   (probe_duration, sample_stats and the analyze-mode judgment thresholds).
# Modified for QwenPaw Creator. See backend/vendor/NOTICE.md.
"""Frame statistics ported from the upstream auto_grade analyzer.

Upstream mental model: "correction, not creative grading" — sample frames
via ffmpeg signalstats, normalize luma mean / luma range / saturation, and
judge exposure/contrast/saturation against fixed thresholds. Creator ports
only the ANALYZE side (numeric evidence for the run review); the eq-filter
derivation and apply mode are intentionally not vendored — grading stays an
opt-in art-direction decision, never an automatic mutation.

Creator modifications: ``sys.exit`` becomes ``FrameStatsError``; a
single-image helper reuses the same signalstats parse for still artifacts;
the reported YBITDEPTH is clamped to >=8 — ffmpeg's signalstats emits the
EFFECTIVE bit depth of the frame content (flat synthetic frames read as
low as 3), which would inflate the normalization on real >=8-bit sources;
ffmpeg runs with stdin detached — inside a background service process an
ffmpeg reading the tty is suspended by SIGTTIN together with its whole
process group (the upstream script only ever ran in a foreground shell).
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

_FFMPEG_TIMEOUT_SECONDS = 120.0

# auto_grade.py analyze-mode judgment thresholds (kept verbatim).
DARK_Y_MEAN = 0.42
HOT_Y_MEAN = 0.60
FLAT_Y_RANGE = 0.65
DESATURATED_SAT = 0.18
PUNCHY_SAT = 0.38


class FrameStatsError(RuntimeError):
    """Raised when signalstats sampling cannot produce evidence."""


def probe_duration(path: Path) -> float:
    try:
        out = (
            subprocess.check_output(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=nw=1:nk=1",
                    str(path),
                ],
                stdin=subprocess.DEVNULL,
                timeout=_FFMPEG_TIMEOUT_SECONDS,
            )
            .decode()
            .strip()
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise FrameStatsError(f"ffprobe failed for {path}") from exc
    try:
        return float(out)
    except ValueError:
        return 10.0


def _parse_signalstats(meta_text: str) -> dict[str, float]:
    vals: dict[str, list[float]] = {
        "YAVG": [],
        "YMIN": [],
        "YMAX": [],
        "SATAVG": [],
    }
    depth = 8
    for line in meta_text.splitlines():
        line = line.strip()
        for key in ("YBITDEPTH", *vals.keys()):
            tag = f"lavfi.signalstats.{key}="
            if tag in line:
                try:
                    value = float(line.rsplit("=", 1)[1])
                except ValueError:
                    continue
                if key == "YBITDEPTH":
                    # Effective content bit depth; never below the 8-bit
                    # storage floor (see module docstring).
                    depth = max(8, int(value))
                else:
                    vals[key].append(value)
    if not vals["YAVG"]:
        raise FrameStatsError(
            "signalstats produced no samples (decode failed?)",
        )
    mx = (2**depth) - 1
    y_mean = sum(vals["YAVG"]) / len(vals["YAVG"]) / mx
    y_range = (
        (
            (sum(vals["YMAX"]) / len(vals["YMAX"]))
            - (sum(vals["YMIN"]) / len(vals["YMIN"]))
        )
        / mx
        if vals["YMAX"]
        else 0.7
    )
    sat = (
        (sum(vals["SATAVG"]) / len(vals["SATAVG"]) / mx)
        if vals["SATAVG"]
        else 0.25
    )
    return {"y_mean": y_mean, "y_range": y_range, "sat_mean": sat}


def _run_signalstats(
    input_args: list[str],
    video_filter: str,
) -> dict[str, float]:
    meta = Path(tempfile.mkstemp(suffix=".txt")[1])
    try:
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-nostats",
                    *input_args,
                    "-vf",
                    f"{video_filter},signalstats,metadata=print:file={meta}",
                    "-f",
                    "null",
                    "-",
                ],
                check=True,
                # Detach stdin so ffmpeg is not suspended by SIGTTIN when it
                # reads the tty from a background process group.
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=_FFMPEG_TIMEOUT_SECONDS,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            raise FrameStatsError("signalstats sampling failed") from exc
        # signalstats lines are pure ASCII; source metadata echoed into the
        # print file may carry arbitrary bytes, so decode permissively.
        return _parse_signalstats(
            meta.read_text(encoding="utf-8", errors="replace"),
        )
    finally:
        meta.unlink(missing_ok=True)


def sample_stats(
    video: Path,
    start: float = 0.0,
    duration: float | None = None,
    n: int = 12,
) -> dict[str, float]:
    """Sample n frames via signalstats; return normalized y_mean/y_range/sat_mean."""
    span = duration if duration is not None else probe_duration(video)
    fps = max(0.5, min(n / max(span, 0.1), 10.0))
    return _run_signalstats(
        [
            "-ss",
            f"{start:.3f}",
            "-i",
            str(video),
            "-t",
            f"{span:.3f}",
        ],
        f"fps={fps:.2f}",
    )


def image_stats(image: Path) -> dict[str, float]:
    """Signalstats for one still image (Creator addition, same parse)."""
    return _run_signalstats(
        ["-i", str(image), "-frames:v", "1"],
        "scale=iw:ih",
    )


def judge_stats(stats: dict[str, float]) -> dict[str, str]:
    """The analyze-mode judgment printout as structured labels."""
    y_mean = stats["y_mean"]
    y_range = stats["y_range"]
    sat = stats["sat_mean"]
    return {
        "exposure": (
            "dark"
            if y_mean < DARK_Y_MEAN
            else "hot"
            if y_mean > HOT_Y_MEAN
            else "exposure ok"
        ),
        "contrast": "flat" if y_range < FLAT_Y_RANGE else "contrast ok",
        "saturation": (
            "desaturated"
            if sat < DESATURATED_SAT
            else "punchy"
            if sat > PUNCHY_SAT
            else "saturation ok"
        ),
    }


__all__ = [
    "DARK_Y_MEAN",
    "DESATURATED_SAT",
    "FLAT_Y_RANGE",
    "FrameStatsError",
    "HOT_Y_MEAN",
    "PUNCHY_SAT",
    "image_stats",
    "judge_stats",
    "probe_duration",
    "sample_stats",
]
