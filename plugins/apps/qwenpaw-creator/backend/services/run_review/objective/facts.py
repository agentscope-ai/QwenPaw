# -*- coding: utf-8 -*-
"""Objective-fact orchestrator: run every operator fail-open, render hints.

One synchronous entry point per artifact kind assembles the per-operator
facts. Every operator is wrapped individually: a crash records
``status="error"`` for that operator only, a missing dependency records
``status="skipped"`` with the reason — collecting facts must never sink
a review round.

The rendered block frames everything as HINTS: detections are factual
inputs for the reviewer's reasoning, not pass/fail judgements. "No
speech detected" on a plan that never asked for a voiceover is simply
context.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext

import numpy as np

from services.run_review.objective import (
    audio_facts as audio_ops,
)
from services.run_review.objective import (
    camera_motion as camera_ops,
)
from services.run_review.objective import (
    consistency as consistency_ops,
)
from services.run_review.objective import (
    light_metrics as light_ops,
)
from services.run_review.objective import (
    machine_params as machine_ops,
)
from services.run_review.objective import (
    ocr_check as ocr_ops,
)
from services.run_review.objective import video_index as index_ops
from services.run_review.objective.media_io import (
    PCM_SAMPLE_RATE,
    GraySamples,
    decode_pcm_mono,
    probe_info,
    sample_gray_frames,
    sample_rgb_frame,
)
from services.run_review.operator_registry import is_operator_enabled
from utils.logger import setup_logger

logger = setup_logger("creator.run_review.objective.facts")

_FACTS_PREAMBLE = (
    "以下为程序化客观检测结果，仅是事实提示、不是对错结论：检测到/未检测到"
    "某要素本身不构成缺陷（如无人声对纯环境音剪辑完全合法、静止镜头可能是"
    "刻意定机位、程序刀数与计划的差异可能来自叠化转场）。仅当计划明确声明了"
    "对应期望且与事实明显矛盾时才可作为发现，且必须结合画面证据确认。"
)


_DISABLED_BLOCK = {
    "status": "disabled",
    "reason": "已在自我审阅高级配置中关闭",
}

# Operators that read the shared gray frame ladder. The decode runs when
# any of them is enabled, so switching off one never starves the others.
_GRAY_CONSUMERS = (
    "video_index",
    "light_metrics",
    "av_sync",
    "cross_shot_consistency",
    "camera_motion",
    "ocr_text",
)

# One shared pool for the three independent decodes. ``collect_*_facts``
# already runs inside a ``to_thread`` worker, so spawning a fresh pool
# per artifact would stack new threads on top of every review in flight.
_DECODE_POOL = ThreadPoolExecutor(
    max_workers=3,
    thread_name_prefix="creator-objective-decode",
)


def _safe(
    facts: dict[str, Any],
    key: str,
    operator: Callable[[], Any],
    *,
    switch: str | None = None,
) -> None:
    """Run one operator fail-open; honour its advanced-config switch.

    ``switch`` names the registry key (defaults to ``key``): a disabled
    operator records a visible ``disabled`` block instead of silently
    vanishing from the facts, so review reports stay self-explaining.
    """
    if not is_operator_enabled(switch or key):
        facts[key] = dict(_DISABLED_BLOCK)
        return
    try:
        facts[key] = operator()
    except Exception as exc:  # noqa: BLE001 - fail-open per operator
        logger.warning("objective operator %s failed: %s", key, exc)
        facts[key] = {"status": "error", "error": str(exc)[:200]}


def _rgb_probe_frames(
    media_path: Path,
    timestamps_ms: Sequence[int],
    *,
    count: int = 3,
) -> list[tuple[int, np.ndarray]]:
    if not timestamps_ms:
        return []
    picks = np.linspace(0, len(timestamps_ms) - 1, num=count, dtype=int)
    frames: list[tuple[int, np.ndarray]] = []
    for index in dict.fromkeys(picks):
        timestamp = int(timestamps_ms[int(index)])
        try:
            frames.append(
                (
                    timestamp,
                    sample_rgb_frame(media_path, timestamp_ms=timestamp),
                ),
            )
        except Exception:  # noqa: BLE001 - single-frame failure tolerated
            continue
    return frames


def collect_video_facts(
    media_path: Path,
    *,
    expected_duration_seconds: float | None = None,
    expected_aspect: Any = None,
    expected_texts: Sequence[str] | None = None,
    planned_shot_count: int | None = None,
    transcript_sentences: Sequence[Mapping[str, Any]] | None = None,
    predecoded_gray_samples: GraySamples | None = None,
) -> dict[str, Any]:
    """All CPU objective facts for one video artifact (thread-safe).

    The three decodes this needs (container probe, gray frame ladder,
    mono PCM) are independent ffmpeg passes, so they are started
    together in a small thread pool; every operator then runs on the
    already-decoded buffers. Each operator stays individually fail-open.

    The gray ladder is shared by several operators, so it is decoded
    whenever *any* of them is on — switching off the cut/freeze facts
    never silently disables sharpness, consistency, motion or OCR.
    """
    # pylint: disable=too-many-statements
    facts: dict[str, Any] = {}
    decode_gray = any(is_operator_enabled(key) for key in _GRAY_CONSUMERS)
    decode_pcm = is_operator_enabled("audio_content")
    # nullcontext: the pool is process-wide, so it must not be shut down
    # when one artifact finishes.
    with nullcontext(_DECODE_POOL) as pool:
        probe_future = (
            pool.submit(probe_info, media_path)
            if is_operator_enabled("machine_params")
            else None
        )
        gray_future = (
            pool.submit(sample_gray_frames, media_path)
            if decode_gray and predecoded_gray_samples is None
            else None
        )
        pcm_future = (
            pool.submit(decode_pcm_mono, media_path) if decode_pcm else None
        )

        def machine_param_block() -> dict[str, Any]:
            if probe_future is None:  # pragma: no cover - gate guards it
                return {"status": "skipped", "skip_reason": "未探测容器信息"}
            return machine_ops.machine_param_facts(
                probe_future.result(),
                expected_duration_seconds=expected_duration_seconds,
                expected_aspect=expected_aspect,
            )

        _safe(facts, "machine_params", machine_param_block)

        # Lazily shared decode results: computed once, reported honestly.
        # A real decode failure carries its own message so the skip
        # reason never claims something that did not happen.
        shared: dict[str, Any] = {}

        def gray_samples() -> GraySamples | None:
            if "samples" not in shared:
                try:
                    shared["samples"] = (
                        predecoded_gray_samples
                        if predecoded_gray_samples is not None
                        else (
                            gray_future.result()
                            if gray_future is not None
                            else None
                        )
                    )
                except Exception as exc:  # noqa: BLE001 - fail-open
                    logger.warning("gray frame decode failed: %s", exc)
                    shared["samples"] = None
                    shared["decode_error"] = str(exc)[:120]
            return shared["samples"]

        def gray_skip_reason() -> str:
            error = shared.get("decode_error")
            return f"灰度帧解码失败：{error}" if error else "灰度帧不可用"

        def frame_diffs() -> np.ndarray | None:
            if "diffs" not in shared:
                samples = gray_samples()
                shared["diffs"] = (
                    index_ops.frame_diffs(samples)
                    if samples is not None
                    else None
                )
            return shared["diffs"]

        def video_index() -> dict[str, Any] | None:
            """Shot index for downstream operators.

            Computed even when the cut/freeze facts themselves are
            switched off, because consistency and camera motion need the
            scene boundaries and the derivation is pure arithmetic on
            frames that are already decoded.
            """
            if "index" not in shared:
                samples = gray_samples()
                diffs = frame_diffs()
                shared["index"] = (
                    index_ops.build_video_index(samples, diffs=diffs)
                    if samples is not None and diffs is not None
                    else None
                )
            return shared["index"]

        def index_block() -> dict[str, Any]:
            index = video_index()
            if index is None:
                return {"status": "skipped", "skip_reason": gray_skip_reason()}
            payload = dict(index)
            if planned_shot_count is not None:
                payload["planned_shot_count"] = planned_shot_count
            # Keep the prompt block bounded: scenes stay, raw curve does
            # not.
            return payload

        _safe(facts, "video_index", index_block)

        def light_block() -> dict[str, Any]:
            samples = gray_samples()
            diffs = frame_diffs()
            if samples is None or diffs is None:
                return {"status": "skipped", "skip_reason": gray_skip_reason()}
            rgb_frames = _rgb_probe_frames(media_path, samples.timestamps_ms)
            return {
                "sharpness": light_ops.sharpness_facts(
                    light_ops.representative_gray_frames(samples),
                ),
                "stability": light_ops.stability_facts(diffs),
                "color": light_ops.color_facts(
                    [frame for _, frame in rgb_frames],
                ),
            }

        _safe(facts, "light_metrics", light_block)

        transcript_rows = [dict(row) for row in (transcript_sentences or [])]
        transcript_text = " ".join(
            str(row.get("text") or "") for row in transcript_rows
        ).strip()

        def audio_block() -> dict[str, Any]:
            if pcm_future is None:  # pragma: no cover - gate guards it
                return {"status": "skipped", "skip_reason": "未解码音频"}
            return audio_ops.audio_content_facts(
                pcm_future.result(),
                PCM_SAMPLE_RATE,
                transcript_text=transcript_text,
            )

        _safe(facts, "audio_content", audio_block)

        def av_sync_block() -> dict[str, Any]:
            if not transcript_rows:
                return {
                    "measured": False,
                    "note": "无 ASR 转写（未配置、无人声或单镜头），音画同步跳过",
                }
            index = video_index()
            if index is None:
                return {
                    "status": "skipped",
                    "skip_reason": gray_skip_reason(),
                }
            return audio_ops.av_sync_facts(
                transcript_rows,
                index.get("cut_points_ms") or [],
            )

        _safe(facts, "av_sync", av_sync_block)

        def consistency_block() -> dict[str, Any]:
            samples = gray_samples()
            index = video_index()
            if samples is None or index is None:
                return {
                    "status": "skipped",
                    "skip_reason": gray_skip_reason(),
                }
            return consistency_ops.cross_shot_consistency_facts(
                samples,
                list(index.get("scenes") or []),
            )

        _safe(facts, "cross_shot_consistency", consistency_block)

        def camera_block() -> dict[str, Any]:
            samples = gray_samples()
            index = video_index()
            if samples is None or index is None:
                return {
                    "status": "skipped",
                    "skip_reason": gray_skip_reason(),
                }
            return camera_ops.camera_motion_facts(
                samples,
                dynamic_frame_ratio=float(
                    index.get("dynamic_frame_ratio") or 0.0,
                ),
            )

        _safe(facts, "camera_motion", camera_block)

        def ocr_block() -> dict[str, Any]:
            expected = [
                text for text in (expected_texts or []) if text.strip()
            ]
            if not expected:
                return {"measured": False, "note": "计划未声明需渲染的文字"}
            if not ocr_ops.ocr_available():
                return {
                    "measured": False,
                    "status": "skipped",
                    "skip_reason": "easyocr 未安装：文字核验回退纯 VLM 路径",
                }
            samples = gray_samples()
            if samples is None:
                return {
                    "status": "skipped",
                    "skip_reason": gray_skip_reason(),
                }
            stamped = _rgb_probe_frames(
                media_path,
                samples.timestamps_ms,
                count=6,
            )
            return ocr_ops.text_render_facts(stamped, expected)

        _safe(facts, "text_render", ocr_block, switch="ocr_text")
    return facts


def collect_image_facts(image_path: Path) -> dict[str, Any]:
    """Light objective facts for one still image (sharpness/color)."""
    facts: dict[str, Any] = {}

    def load() -> np.ndarray:
        from PIL import Image  # local import: PIL arrives via matplotlib

        with Image.open(image_path) as handle:
            return np.asarray(handle.convert("RGB"))

    def image_block() -> dict[str, Any]:
        rgb = load()
        gray = rgb.astype(np.float32).mean(axis=2).astype(np.uint8)
        return {
            "sharpness": light_ops.sharpness_facts([gray]),
            "color": light_ops.color_facts([rgb]),
        }

    _safe(facts, "light_metrics", image_block, switch="light_metrics")
    return facts


def render_facts_block(facts: Mapping[str, Any]) -> str:
    """Prompt-ready facts block with the hint framing attached."""
    return (
        "【客观事实提示（objective facts）】\n"
        + _FACTS_PREAMBLE
        + "\n"
        + json.dumps(dict(facts), ensure_ascii=False, default=str)
    )


__all__ = [
    "collect_image_facts",
    "collect_video_facts",
    "render_facts_block",
]
