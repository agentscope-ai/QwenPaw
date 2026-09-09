# -*- coding: utf-8 -*-
"""Self-hosted MiniMax H3 served by SGLang.

Contract sources: the reproducible request scripts in the official
MiniMax-H3 repository (github.com/MiniMax-AI/MiniMax-H3,
scripts/readme/reproducible-768p-*.sh) and the SGLang cookbook
(https://docs.sglang.io/cookbook/diffusion/MiniMax/MiniMax-H3).

    POST {base}/v1/videos
    GET  {base}/v1/videos/{id}
    GET  {base}/v1/videos/{id}/content

One SGLang instance loads exactly one checkpoint variant
(``sglang serve --model-variant fl2va|ref2va``; the official examples
serve them on ports 30010/30011), so the configured model name —
``MiniMax-H3-FL2VA`` or ``MiniMax-H3-Ref2VA`` — records which variant
the endpoint serves and the capability table fail-closes the other
modes. The wire request never carries a model name; the ``task`` field
(``t2va``/``fl2va``/``ref2va``) must match the loaded checkpoint.

Requests carry ``prompt``, ``conditions`` (first frame:
``{"type": "image", "uri": ..., "role": "keyframe", "frame_index": 0}``;
references: ``{"type": "image"|"video"|"audio", "uri": ...,
"role": "reference"}``; ``uri`` accepts http(s), ``file://`` and
``data:<mime>;base64`` — verified in sglang material_io) and ``target``
(``short_edge`` 768, ``aspect_ratio`` incl. ``auto``,
``duration_seconds``). H3-Base renders 768p only; 2K needs the hosted
Regenerate-2K API. SGLang serves without authentication unless started
with ``--api-key``, in which case requests and the ``/content`` download
carry ``Authorization: Bearer``.
"""

from __future__ import annotations

from urllib.parse import quote

import httpx

from models.video_capabilities import (
    MINIMAX_H3_MAX_REFERENCE_AUDIO,
    MINIMAX_H3_MAX_TOTAL_MEDIA,
    MINIMAX_H3_RATIOS,
    MINIMAX_H3_SGLANG_RESOLUTIONS,
    validate_video_mode,
    video_reference_capability,
    video_reference_violation,
)
from utils.exceptions import ModelError
from utils.logger import setup_logger

logger = setup_logger("model.video.minimax_sglang")

DEFAULT_BASE_URL = "http://localhost:30010"
H3_SHORT_EDGE = 768

# Provider-download auth marker consumed by the shared materializer.
BEARER_DOWNLOAD_AUTH = "authorization-bearer"

_TASK_BY_MODE = {"t2v": "t2va", "i2v": "fl2va", "r2v": "ref2va"}
_CONDITION_TYPE_BY_REFERENCE = {
    "reference_image": "image",
    "reference_video": "video",
    "reference_audio": "audio",
}


def _api_base(base_url: str) -> str:
    return base_url.rstrip("/")


def _auth_headers(api_key: str) -> dict:
    if api_key:
        return {"Authorization": f"Bearer {api_key}"}
    return {}


def _validated_duration(
    resolution: str,
    duration: int,
    model_name: str,
) -> None:
    normalized = (resolution or "").strip().upper()
    if normalized and normalized not in MINIMAX_H3_SGLANG_RESOLUTIONS:
        raise ModelError(
            "Self-hosted MiniMax H3 renders 768P only (2K needs the "
            f"hosted Regenerate-2K API), got resolution {resolution!r}",
            model_name=model_name,
        )
    durations = MINIMAX_H3_SGLANG_RESOLUTIONS["768P"]
    if duration not in durations:
        raise ModelError(
            f"MiniMax H3 renders {durations[0]}-{durations[-1]}s, "
            f"got {duration}s",
            model_name=model_name,
        )


def _validated_aspect_ratio(ratio: str, mode: str, model_name: str) -> str:
    normalized = (ratio or "").strip().casefold()
    if normalized in {"adaptive", "auto"}:
        # The documented contract (and the cloud v2 path) rejects
        # adaptive for text-only generation.
        if mode == "t2v":
            raise ModelError(
                "MiniMax H3 t2v does not accept ratio=adaptive; "
                "pick an explicit aspect ratio",
                model_name=model_name,
            )
        return "auto"
    if not normalized:
        # The official t2va reproduction script pins 16:9 explicitly.
        return "16:9" if mode == "t2v" else "auto"
    if normalized not in MINIMAX_H3_RATIOS:
        raise ModelError(
            f"MiniMax H3 supports ratios {sorted(MINIMAX_H3_RATIOS)}, "
            f"got {ratio!r}",
            model_name=model_name,
        )
    return normalized


def _reference_conditions(media: list[dict], model_name: str) -> list[dict]:
    references = [
        item
        for item in media
        if item.get("type") in _CONDITION_TYPE_BY_REFERENCE
    ]
    image_count = sum(
        1 for item in references if item["type"] == "reference_image"
    )
    video_count = sum(
        1 for item in references if item["type"] == "reference_video"
    )
    audio_count = sum(
        1 for item in references if item["type"] == "reference_audio"
    )
    capability = video_reference_capability(model_name)
    if capability is None:
        raise ModelError(
            f"MiniMax H3 reference contract unknown for `{model_name}`",
            model_name=model_name,
        )
    violation = video_reference_violation(
        capability,
        image_count=image_count,
        video_count=video_count,
    )
    if violation:
        raise ModelError(violation, model_name=model_name)
    if audio_count > MINIMAX_H3_MAX_REFERENCE_AUDIO:
        raise ModelError(
            f"MiniMax H3 accepts at most {MINIMAX_H3_MAX_REFERENCE_AUDIO} "
            f"reference audio clips, got {audio_count}",
            model_name=model_name,
        )
    total = image_count + video_count + audio_count
    if total > MINIMAX_H3_MAX_TOTAL_MEDIA:
        raise ModelError(
            f"MiniMax H3 accepts at most {MINIMAX_H3_MAX_TOTAL_MEDIA} "
            f"reference files in total, got {total}",
            model_name=model_name,
        )
    return [
        {
            "type": _CONDITION_TYPE_BY_REFERENCE[item["type"]],
            "uri": item["url"],
            "role": "reference",
        }
        for item in references
    ]


def build_submit_request(
    *,
    prompt: str,
    mode: str,
    media: list[dict],
    duration: int,
    resolution: str,
    model_name: str,
    api_key: str,
    base_url: str,
    ratio: str = "",
) -> tuple[str, dict, dict]:
    """Render the /v1/videos submit request for one self-hosted H3 task."""

    try:
        normalized_mode = validate_video_mode(
            "minimax_sglang",
            model_name,
            mode,
        )
    except ValueError as exc:
        raise ModelError(str(exc), model_name=model_name) from exc

    _validated_duration(resolution, duration, model_name)
    conditions: list[dict] = []
    if normalized_mode == "i2v":
        first_frame = next(
            (item for item in media if item.get("type") == "first_frame"),
            None,
        )
        if first_frame is None:
            raise ModelError(
                "MiniMax H3 i2v requires exactly one first-frame image",
                model_name=model_name,
            )
        conditions.append(
            {
                "type": "image",
                "uri": first_frame["url"],
                "role": "keyframe",
                "frame_index": 0,
            },
        )
    if normalized_mode == "r2v":
        conditions = _reference_conditions(media, model_name)
    body = {
        "task": _TASK_BY_MODE[normalized_mode],
        "prompt": prompt,
        "conditions": conditions,
        "target": {
            "short_edge": H3_SHORT_EDGE,
            "aspect_ratio": _validated_aspect_ratio(
                ratio,
                normalized_mode,
                model_name,
            ),
            "duration_seconds": duration,
        },
    }
    url = f"{_api_base(base_url)}/v1/videos"
    headers = {"Content-Type": "application/json", **_auth_headers(api_key)}
    return url, headers, body


def extract_task_id(payload: dict) -> str:
    if isinstance(payload, dict):
        return str(payload.get("id") or "").strip()
    return ""


async def check_status(
    task_id: str,
    *,
    api_key: str,
    base_url: str,
    timeout: int,
    model_name: str,
) -> dict:
    """One poll of a self-hosted H3 task."""

    base = _api_base(base_url)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(
            f"{base}/v1/videos/{quote(task_id, safe='')}",
            headers=_auth_headers(api_key),
        )
        if resp.status_code >= 400:
            raise ModelError(
                "MiniMax H3 (SGLang) task poll failed with status "
                f"{resp.status_code}: {resp.text[:400]}",
                model_name=model_name,
                retryable=resp.status_code >= 500 or resp.status_code == 429,
            )
        payload = resp.json()
    status = str(payload.get("status") or "").strip().casefold()
    if status in {"completed", "succeeded"}:
        result: dict = {
            "task_id": task_id,
            "status": "SUCCEEDED",
            "result_url": (
                f"{base}/v1/videos/{quote(task_id, safe='')}/content"
            ),
        }
        if api_key:
            result["download_auth"] = BEARER_DOWNLOAD_AUTH
        return result
    if status in {"failed", "cancelled", "error"}:
        detail = str(payload.get("error") or "").strip()
        suffix = f": {detail}" if detail else ""
        return {
            "task_id": task_id,
            "status": "FAILED",
            "error": f"MiniMax H3 (SGLang) task ended {status}{suffix}",
        }
    return {"task_id": task_id, "status": "RUNNING"}
