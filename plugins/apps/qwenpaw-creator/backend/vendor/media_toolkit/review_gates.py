# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
# Vendored from Qwen-MM-Plugins (Apache-2.0), release commit 077aea6.
# Upstream path: src/capabilities/video-edit/skill/scripts/black_check.sh,
#   src/capabilities/video-edit/skill/scripts/loudness_check.sh,
#   src/capabilities/video-edit/skill/scripts/review_gate.sh (gate order and
#   the REVIEW GATE evidence-block discipline).
# Modified for QwenPaw Creator. See backend/vendor/NOTICE.md.
"""Objective review gates ported from the upstream shell scripts.

Ports, thresholds preserved verbatim:

- ``black_gate`` — ffmpeg ``blackdetect`` (d=0.1, pix_th=0.10); black inside
  the first/last GRACE=0.5s is ADVISORY (a declared fade is legitimate),
  interior black is a hard finding.
- ``loudness_gate`` — audio stream presence, EBU R128 measurement via
  ``loudnorm print_format=json``; ``-inf`` integrated = digital silence,
  integrated < -50 LUFS = effectively silent, plus the hot(-10)/quiet(-24)
  /true-peak(-1.0) advisories.
- ``run_review_gates`` — the review_gate.sh sequence (ffprobe summary →
  loudness → black) emitting one structured evidence block with a
  byte-identity hash, mirroring the upstream rule that a verdict must carry
  the verbatim gate output.

Creator modification: the upstream ``exit 2`` DELIVERY-BLOCKING semantics is
not ported — gate failures become structured findings for the advisory run
review; nothing here ever blocks publishing. The plan gate (gate 4 upstream)
is not ported either: Creator plan context is supplied by the runtime.
ffmpeg/ffprobe run with stdin detached — inside a background service process
an ffmpeg reading the tty is suspended by SIGTTIN together with its whole
process group (the upstream scripts only ever ran in a foreground shell).
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_FFMPEG_TIMEOUT_SECONDS = 120.0

# black_check.sh defaults.
BLACK_MIN_DURATION_SECONDS = 0.1
BLACK_PIX_THRESHOLD = 0.10
BLACK_GRACE_SECONDS = 0.5

# loudness_check.sh thresholds.
SILENT_INTEGRATED_LUFS = -50.0
HOT_MIX_LUFS = -10.0
QUIET_MIX_LUFS = -24.0
TRUE_PEAK_CEILING_DBTP = -1.0

_BLACK_SEGMENT = re.compile(
    r"black_start:(?P<start>[0-9.]+) black_end:(?P<end>[0-9.]+) "
    r"black_duration:(?P<duration>[0-9.]+)",
)


class ReviewGateError(RuntimeError):
    """Raised when a gate cannot produce evidence (missing file/tooling)."""


@dataclass(slots=True)
class GateResult:
    """One gate's structured outcome (upstream printed the same fields)."""

    name: str
    passed: bool
    lines: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GateBlock:
    """The REVIEW GATE evidence block for one exact file.

    Upstream discipline: a review verdict without this block is void; the
    hash binds the evidence to the reviewed bytes.
    """

    file: str
    sha1_head12: str
    ran_at: str
    gates: list[GateResult] = field(default_factory=list)
    passed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise ReviewGateError(f"{name} is required for review gates")
    return path


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        # Detach stdin so ffmpeg is not suspended by SIGTTIN when it reads
        # the tty from a background process group.
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=_FFMPEG_TIMEOUT_SECONDS,
        check=False,
    )


def _sha1_head12(path: Path) -> str:
    # review_gate.sh: shasum of the first 1 MiB — identity of the reviewed
    # bytes without hashing multi-GB renders.
    digest = hashlib.sha1()
    with path.open("rb") as stream:
        digest.update(stream.read(1024 * 1024))
    return digest.hexdigest()[:12]


def probe_summary_gate(video_path: Path) -> GateResult:
    """Gate 1 upstream: the ffprobe stream/format summary."""
    ffprobe = _require_tool("ffprobe")
    result = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate",
            "-of",
            "default=nw=1",
            str(video_path),
        ],
    )
    lines = [
        line.strip()
        for line in (result.stdout or "").splitlines()
        if line.strip()
    ]
    passed = result.returncode == 0 and bool(lines)
    if not passed:
        lines.append((result.stderr or "ffprobe failed").strip()[:300])
    duration = None
    for line in lines:
        if line.startswith("duration="):
            try:
                duration = float(line.split("=", 1)[1])
            except ValueError:
                duration = None
    return GateResult(
        name="ffprobe",
        passed=passed,
        lines=lines,
        metrics={"duration_seconds": duration},
    )


def loudness_gate(video_path: Path) -> GateResult:
    """Port of loudness_check.sh (thresholds preserved)."""
    ffprobe = _require_tool("ffprobe")
    ffmpeg = _require_tool("ffmpeg")
    streams = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index,codec_name,channels,sample_rate",
            "-of",
            "csv=p=0",
            str(video_path),
        ],
    )
    stream_desc = (streams.stdout or "").strip()
    if not stream_desc:
        return GateResult(
            name="loudness",
            passed=False,
            lines=[
                "AUDIO STREAM : ABSENT",
                "VERDICT      : FAIL — no audio stream ([audio-preserved]:"
                " needs explicit approval)",
            ],
            metrics={"has_audio": False},
        )
    lines = [f"AUDIO STREAM : present ({stream_desc.splitlines()[0]})"]
    measured = _run(
        [
            ffmpeg,
            "-hide_banner",
            "-nostats",
            "-i",
            str(video_path),
            "-map",
            "a:0",
            "-af",
            "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
            "-f",
            "null",
            "-",
        ],
    )
    stats = measured.stderr or ""
    metrics: dict[str, Any] = {"has_audio": True}
    if re.search(r'"input_i"[^0-9-]*-inf', stats):
        lines.append("INTEGRATED   : -inf LUFS  (digital silence)")
        lines.append("VERDICT      : FAIL — track is digitally silent")
        metrics["integrated_lufs"] = None
        metrics["digital_silence"] = True
        return GateResult(
            name="loudness",
            passed=False,
            lines=lines,
            metrics=metrics,
        )

    def _measure(key: str) -> float | None:
        match = re.search(
            rf'"{key}"[^-0-9]*(-?[0-9][0-9.]*)',
            stats,
        )
        try:
            return float(match.group(1)) if match else None
        except ValueError:
            return None

    integrated = _measure("input_i")
    true_peak = _measure("input_tp")
    lra = _measure("input_lra")
    metrics.update(
        {
            "integrated_lufs": integrated,
            "true_peak_dbtp": true_peak,
            "lra_lu": lra,
        },
    )
    lines.append(
        f"INTEGRATED   : {integrated if integrated is not None else '?'} "
        "LUFS   (platform target -14, podcasts -16)",
    )
    lines.append(
        f"TRUE PEAK    : {true_peak if true_peak is not None else '?'} "
        "dBTP   (keep <= -1.0 ~ -1.5)",
    )
    lines.append(
        f"LRA          : {lra if lra is not None else '?'} LU     "
        "(dialogue-led 6-12 typical)",
    )
    if integrated is not None and integrated < SILENT_INTEGRATED_LUFS:
        lines.append(
            "VERDICT      : FAIL — track is effectively silent "
            f"(I={integrated} LUFS)",
        )
        metrics["effectively_silent"] = True
        return GateResult(
            name="loudness",
            passed=False,
            lines=lines,
            metrics=metrics,
        )
    notes: list[str] = []
    if integrated is not None and integrated > HOT_MIX_LUFS:
        notes.append(
            f"hot mix ({integrated} LUFS > {HOT_MIX_LUFS}): platforms will "
            "turn it down",
        )
    if integrated is not None and integrated < QUIET_MIX_LUFS:
        notes.append(
            f"quiet mix ({integrated} LUFS < {QUIET_MIX_LUFS}): viewers "
            "will crank volume",
        )
    if true_peak is not None and true_peak > TRUE_PEAK_CEILING_DBTP:
        notes.append(
            f"true peak {true_peak} dBTP > {TRUE_PEAK_CEILING_DBTP}: "
            "clipping risk after lossy encode",
        )
    lines.append(
        "ADVISORY     : "
        + ("; ".join(notes) if notes else "levels look reasonable"),
    )
    lines.append("VERDICT      : PASS — audio present and measured")
    metrics["advisories"] = notes
    return GateResult(
        name="loudness",
        passed=True,
        lines=lines,
        metrics=metrics,
    )


def black_gate(
    video_path: Path,
    *,
    min_duration: float = BLACK_MIN_DURATION_SECONDS,
    pix_threshold: float = BLACK_PIX_THRESHOLD,
    grace: float = BLACK_GRACE_SECONDS,
) -> GateResult:
    """Port of black_check.sh (thresholds and head/tail grace preserved)."""
    ffprobe = _require_tool("ffprobe")
    ffmpeg = _require_tool("ffmpeg")
    probed = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(video_path),
        ],
    )
    try:
        duration = float((probed.stdout or "").strip())
    except ValueError as exc:
        raise ReviewGateError("black gate could not probe duration") from exc
    lines = [
        f"DURATION     : {duration}s   (min flagged black: {min_duration}s,"
        f" luma th: {pix_threshold})",
    ]
    detect = _run(
        [
            ffmpeg,
            "-hide_banner",
            "-nostats",
            "-i",
            str(video_path),
            "-vf",
            f"blackdetect=d={min_duration}:pix_th={pix_threshold}",
            "-an",
            "-f",
            "null",
            "-",
        ],
    )
    segments = list(_BLACK_SEGMENT.finditer(detect.stderr or ""))
    interior: list[dict[str, float]] = []
    head_tail: list[dict[str, Any]] = []
    if not segments:
        lines.append("BLACK GAPS   : none")
        lines.append(
            f"VERDICT      : PASS — no black segments >= {min_duration}s",
        )
    for match in segments:
        start = float(match.group("start"))
        end = float(match.group("end"))
        span = float(match.group("duration"))
        kind = (
            "head"
            if start < grace
            else "tail"
            if end > duration - grace
            else "interior"
        )
        if kind == "interior":
            interior.append({"start": start, "end": end, "duration": span})
            lines.append(
                f"BLACK GAP    : {start}s -> {end}s  ({span}s)  INTERIOR — "
                "broken transition / timeline gap",
            )
        else:
            head_tail.append(
                {"start": start, "end": end, "duration": span, "kind": kind},
            )
            lines.append(
                f"BLACK GAP    : {start}s -> {end}s  ({span}s)  {kind} — "
                "advisory (fade-in/out is legitimate if declared)",
            )
    if interior:
        lines.append(
            f"VERDICT      : FAIL — {len(interior)} interior black gap(s); "
            "inspect the timeline at those timestamps",
        )
    elif segments:
        lines.append(
            "VERDICT      : PASS — only head/tail black (verify it is a "
            "declared fade)",
        )
    return GateResult(
        name="black",
        passed=not interior,
        lines=lines,
        metrics={
            "duration_seconds": duration,
            "interior_gaps": interior,
            "head_tail_gaps": head_tail,
        },
    )


def run_review_gates(video_path: Path) -> GateBlock:
    """Run the review_gate.sh sequence and return the evidence block."""
    path = Path(video_path)
    if not path.is_file():
        raise ReviewGateError(f"file not found: {path}")
    block = GateBlock(
        file=str(path),
        sha1_head12=_sha1_head12(path),
        ran_at=datetime.now(UTC).isoformat(),
    )
    for gate in (
        probe_summary_gate(path),
        loudness_gate(path),
        black_gate(path),
    ):
        block.gates.append(gate)
        block.passed = block.passed and gate.passed
    return block


__all__ = [
    "BLACK_GRACE_SECONDS",
    "BLACK_MIN_DURATION_SECONDS",
    "BLACK_PIX_THRESHOLD",
    "GateBlock",
    "GateResult",
    "HOT_MIX_LUFS",
    "QUIET_MIX_LUFS",
    "ReviewGateError",
    "SILENT_INTEGRATED_LUFS",
    "TRUE_PEAK_CEILING_DBTP",
    "black_gate",
    "loudness_gate",
    "probe_summary_gate",
    "run_review_gates",
]
