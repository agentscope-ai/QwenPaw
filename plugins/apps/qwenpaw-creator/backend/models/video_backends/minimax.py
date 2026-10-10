# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""MiniMax (Hailuo) video generation protocol.

This module speaks both official protocol generations, selected by the
configured model name:

v1 (Hailuo 2.x / 01-generation models; official API reference,
https://platform.minimax.io/docs/api-reference/video-generation-t2v):

    POST {base}/v1/video_generation
    GET  {base}/v1/query/video_generation?task_id={id}
    GET  {base}/v1/files/retrieve?file_id={id}

v2 (MiniMax-H3 / MiniMax-H3-Max; official API reference,
https://platform.minimax.io/docs/api-reference/video-generation-v2-create):

    POST {base}/v2/video_generation
    GET  {base}/v2/query/video_generation/{task_id}

Authentication is ``Authorization: Bearer <API key>`` for both.

v1: the create call returns a ``task_id``; polling reports ``Preparing/
Queueing/Processing/Success/Fail``; on success the ``file_id`` is
exchanged for a ``download_url`` (valid for 1 hour, downloaded promptly
by the shared materializer). Documented request fields used here:
``model``, ``prompt`` (<=2000 characters), ``duration``, ``resolution``,
``first_frame_image`` (image-to-video; URL or ``data:image/...;base64,``
data URL) and ``subject_reference`` (S2V-01 only: one character subject
carrying exactly one image; its request omits duration/resolution).
Duration/resolution combinations follow the official matrix: Hailuo
models render 768P at 6 or 10 seconds and 1080P at 6 seconds only; the
01-generation models render 720P at 6 seconds.

v2: the request carries a multimodal ``content`` array (``text`` plus
``image_url``/``video_url``/``audio_url`` parts tagged with ``role``:
``first_frame``, ``reference_image`` <=9, ``reference_video`` <=3,
``reference_audio`` <=3, 12 files total; frame roles and reference roles
are mutually exclusive) alongside ``resolution`` (480P/768P/2K),
``duration`` (H3 4-15s, H3-Max 5-15s) and ``ratio``. Polling reports
``queued/running/succeeded/failed/cancelled`` and delivers the video URL
directly at ``task.content.url`` — there is no file-retrieve step.
"""

from __future__ import annotations

from urllib.parse import quote

import httpx

from models.video_capabilities import (
    MINIMAX_H3_MAX_MODEL_RESOLUTIONS,
    MINIMAX_H3_MAX_PROMPT_CHARS,
    MINIMAX_H3_MAX_REFERENCE_AUDIO,
    MINIMAX_H3_MAX_TOTAL_MEDIA,
    MINIMAX_H3_RATIOS,
    MINIMAX_H3_RESOLUTIONS,
    MINIMAX_HAILUO_RESOLUTIONS,
    MINIMAX_HAILUO_02_RESOLUTIONS,
    MINIMAX_LEGACY_RESOLUTIONS,
    MINIMAX_MAX_PROMPT_CHARS,
    MINIMAX_SUBJECT_REFERENCE_MODEL,
    validate_video_mode,
    video_reference_capability,
    video_reference_violation,
)
from utils.exceptions import ModelError
from utils.logger import setup_logger

logger = setup_logger("model.video.minimax")

DEFAULT_BASE_URL = "https://api.minimax.io"


def _api_base(base_url: str) -> str:
    return base_url.rstrip("/")


def _is_hailuo(model_name: str) -> bool:
    lowered = model_name.casefold()
    return "hailuo" in lowered or lowered.startswith("minimax")


def is_h3_model(model_name: str) -> bool:
    """True for the v2-protocol H3 models (MiniMax-H3 / MiniMax-H3-Max)."""

    return model_name.strip().casefold() in {"minimax-h3", "minimax-h3-max"}


def _resolution_matrix(model_name: str) -> dict[str, tuple[int, ...]]:
    lowered = model_name.strip().casefold()
    if lowered == "minimax-h3":
        return MINIMAX_H3_RESOLUTIONS
    if lowered == "minimax-h3-max":
        return MINIMAX_H3_MAX_MODEL_RESOLUTIONS
    if lowered == "minimax-hailuo-02":
        return MINIMAX_HAILUO_02_RESOLUTIONS
    if _is_hailuo(model_name):
        return MINIMAX_HAILUO_RESOLUTIONS
    return MINIMAX_LEGACY_RESOLUTIONS


def _validated_resolution_duration(
    resolution: str,
    duration: int,
    model_name: str,
) -> str:
    matrix = _resolution_matrix(model_name)
    normalized = (resolution or "").strip().upper()
    if not normalized:
        normalized = next(iter(matrix))
    if normalized not in matrix:
        raise ModelError(
            f"MiniMax model `{model_name}` supports resolutions "
            f"{sorted(matrix)}, got {resolution!r}",
            model_name=model_name,
        )
    if duration not in matrix[normalized]:
        raise ModelError(
            f"MiniMax model `{model_name}` supports "
            f"{'/'.join(str(v) for v in matrix[normalized])}s at "
            f"{normalized}, got {duration}s",
            model_name=model_name,
        )
    return normalized


# v2 media part rendering: media-item type -> (content part type, role).
_H3_URL_PART_BY_TYPE = {
    "reference_image": ("image_url", "reference_image"),
    "reference_video": ("video_url", "reference_video"),
    "reference_audio": ("audio_url", "reference_audio"),
}


def _h3_media_part(part_type: str, url: str, role: str) -> dict:
    return {"type": part_type, part_type: {"url": url}, "role": role}


def _validated_h3_ratio(ratio: str, mode: str, model_name: str) -> str:
    normalized = (ratio or "").strip().casefold()
    if normalized == "auto":
        # Legacy alias of the documented "adaptive" value, kept consistent
        # across providers (the Seedance branch documents the same alias).
        normalized = "adaptive"
    if not normalized:
        normalized = "16:9" if mode == "t2v" else "adaptive"
    if normalized not in MINIMAX_H3_RATIOS:
        raise ModelError(
            f"MiniMax H3 supports ratios {sorted(MINIMAX_H3_RATIOS)}, "
            f"got {ratio!r}",
            model_name=model_name,
        )
    if mode == "t2v" and normalized == "adaptive":
        raise ModelError(
            "MiniMax H3 t2v does not accept ratio=adaptive; "
            "pick an explicit aspect ratio",
            model_name=model_name,
        )
    return normalized


def _h3_reference_content(
    media: list[dict],
    model_name: str,
) -> list[dict]:
    """Render r2v reference media as v2 content parts, enforcing budgets."""

    references = [
        item for item in media if item.get("type") in _H3_URL_PART_BY_TYPE
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
    parts: list[dict] = []
    for item in references:
        part_type, role = _H3_URL_PART_BY_TYPE[item["type"]]
        parts.append(_h3_media_part(part_type, item["url"], role))
    return parts


def _build_h3_submit_request(
    *,
    prompt: str,
    mode: str,
    media: list[dict],
    duration: int,
    resolution: str,
    ratio: str,
    model_name: str,
    api_key: str,
    base_url: str,
) -> tuple[str, dict, dict]:
    """Render the v2 video_generation submit request for one H3 task."""

    if len(prompt) > MINIMAX_H3_MAX_PROMPT_CHARS:
        raise ModelError(
            f"MiniMax H3 prompts must stay within "
            f"{MINIMAX_H3_MAX_PROMPT_CHARS} characters, got {len(prompt)}",
            model_name=model_name,
        )
    content: list[dict] = [{"type": "text", "text": prompt}]
    if mode == "i2v":
        first_frame = next(
            (item for item in media if item.get("type") == "first_frame"),
            None,
        )
        if first_frame is None:
            raise ModelError(
                "MiniMax i2v requires exactly one first-frame image",
                model_name=model_name,
            )
        content.append(
            _h3_media_part("image_url", first_frame["url"], "first_frame"),
        )
    if mode == "r2v":
        content.extend(_h3_reference_content(media, model_name))
    body = {
        "model": model_name,
        "content": content,
        "resolution": _validated_resolution_duration(
            resolution,
            duration,
            model_name,
        ),
        "duration": duration,
        "ratio": _validated_h3_ratio(ratio, mode, model_name),
    }
    url = f"{_api_base(base_url)}/v2/video_generation"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    return url, headers, body


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
    """Render the video_generation submit request for one MiniMax task."""

    try:
        normalized_mode = validate_video_mode("minimax", model_name, mode)
    except ValueError as exc:
        raise ModelError(str(exc), model_name=model_name) from exc

    if is_h3_model(model_name):
        return _build_h3_submit_request(
            prompt=prompt,
            mode=normalized_mode,
            media=media,
            duration=duration,
            resolution=resolution,
            ratio=ratio,
            model_name=model_name,
            api_key=api_key,
            base_url=base_url,
        )

    if len(prompt) > MINIMAX_MAX_PROMPT_CHARS:
        raise ModelError(
            f"MiniMax prompts must stay within {MINIMAX_MAX_PROMPT_CHARS} "
            f"characters, got {len(prompt)}",
            model_name=model_name,
        )
    reference_items = [
        item for item in media if item.get("type") == "reference_image"
    ]
    first_frame = next(
        (item for item in media if item.get("type") == "first_frame"),
        None,
    )
    body: dict = {
        "model": model_name,
        "prompt": prompt,
    }
    if normalized_mode != "r2v":
        body.update(
            {
                "duration": duration,
                "resolution": _validated_resolution_duration(
                    resolution,
                    duration,
                    model_name,
                ),
            },
        )
    if normalized_mode == "i2v":
        if first_frame is None:
            raise ModelError(
                "MiniMax i2v requires exactly one first-frame image",
                model_name=model_name,
            )
        body["first_frame_image"] = first_frame["url"]
    if normalized_mode == "r2v":
        if len(reference_items) != 1:
            raise ModelError(
                f"{MINIMAX_SUBJECT_REFERENCE_MODEL} requires exactly one "
                "character reference image",
                model_name=model_name,
            )
        # S2V-01: a single "character" subject with exactly one image.
        body["subject_reference"] = [
            {"type": "character", "image": [reference_items[0]["url"]]},
        ]
    url = f"{_api_base(base_url)}/v1/video_generation"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    return url, headers, body


def raise_on_base_resp(payload: dict, model_name: str) -> None:
    """Surface a MiniMax base_resp rejection wrapped in an HTTP 200."""
    base_resp = (
        payload.get("base_resp")
        if isinstance(payload.get("base_resp"), dict)
        else {}
    )
    status_code = base_resp.get("status_code")
    if status_code not in (None, 0):
        raise ModelError(
            f"MiniMax request rejected: {status_code}: "
            f"{base_resp.get('status_msg')}",
            model_name=model_name,
        )


def extract_task_id(payload: dict) -> str:
    if isinstance(payload, dict):
        return str(payload.get("task_id") or "").strip()
    return ""


async def _check_h3_status(
    task_id: str,
    *,
    api_key: str,
    base_url: str,
    timeout: int,
    model_name: str,
) -> dict:
    """One poll of an H3 (v2) task; the video URL is delivered inline."""

    headers = {"Authorization": f"Bearer {api_key}"}
    base = _api_base(base_url)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(
            f"{base}/v2/query/video_generation/{quote(task_id, safe='')}",
            headers=headers,
        )
        if resp.status_code >= 400:
            raise ModelError(
                f"MiniMax task poll failed with status {resp.status_code}: "
                f"{resp.text[:400]}",
                model_name=model_name,
                retryable=resp.status_code >= 500 or resp.status_code == 429,
            )
        payload = resp.json()
        raise_on_base_resp(payload, model_name)
    task = payload.get("task") if isinstance(payload.get("task"), dict) else {}
    status = str(task.get("status") or "").strip().casefold()
    if status in {"queued", "running", "preparing", "processing", ""}:
        return {"task_id": task_id, "status": "RUNNING"}
    if status != "succeeded":
        error = (
            task.get("error") if isinstance(task.get("error"), dict) else {}
        )
        detail = " ".join(
            str(error.get(key) or "").strip()
            for key in ("code", "message")
            if str(error.get(key) or "").strip()
        )
        suffix = f": {detail}" if detail else ""
        return {
            "task_id": task_id,
            "status": "FAILED",
            "error": f"MiniMax task ended {status or 'unknown'}{suffix}",
        }
    content = (
        task.get("content") if isinstance(task.get("content"), dict) else {}
    )
    result_url = str(content.get("url") or "").strip()
    if not result_url:
        return {
            "task_id": task_id,
            "status": "FAILED",
            "error": (
                "MiniMax H3 task succeeded without a video URL: "
                f"{str(task)[:300]}"
            ),
        }
    return {
        "task_id": task_id,
        "status": "SUCCEEDED",
        "result_url": result_url,
    }


async def check_status(
    task_id: str,
    *,
    api_key: str,
    base_url: str,
    timeout: int,
    model_name: str,
) -> dict:
    """One poll of a MiniMax task; resolves the file URL on success."""

    if is_h3_model(model_name):
        return await _check_h3_status(
            task_id,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            model_name=model_name,
        )

    headers = {"Authorization": f"Bearer {api_key}"}
    base = _api_base(base_url)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(
            f"{base}/v1/query/video_generation",
            params={"task_id": task_id},
            headers=headers,
        )
        if resp.status_code >= 400:
            raise ModelError(
                f"MiniMax task poll failed with status {resp.status_code}: "
                f"{resp.text[:400]}",
                model_name=model_name,
                retryable=resp.status_code >= 500 or resp.status_code == 429,
            )
        payload = resp.json()
        raise_on_base_resp(payload, model_name)
        status = str(payload.get("status") or "").strip()
        if status in {"Preparing", "Queueing", "Processing", ""}:
            return {"task_id": task_id, "status": "RUNNING"}
        if status != "Success":
            return {
                "task_id": task_id,
                "status": "FAILED",
                "error": f"MiniMax task ended {status or 'unknown'}",
            }
        file_id = str(payload.get("file_id") or "").strip()
        if not file_id:
            return {
                "task_id": task_id,
                "status": "FAILED",
                "error": "MiniMax task succeeded without a file_id",
            }
        retrieve = await client.get(
            f"{base}/v1/files/retrieve",
            params={"file_id": file_id},
            headers=headers,
        )
        if retrieve.status_code >= 400:
            raise ModelError(
                "MiniMax file retrieve failed with status "
                f"{retrieve.status_code}: {retrieve.text[:400]}",
                model_name=model_name,
                retryable=retrieve.status_code >= 500
                or retrieve.status_code == 429,
            )
        retrieved = retrieve.json()
        raise_on_base_resp(retrieved, model_name)
    file_info = (
        retrieved.get("file")
        if isinstance(retrieved.get("file"), dict)
        else {}
    )
    download_url = str(file_info.get("download_url") or "").strip()
    if not download_url:
        return {
            "task_id": task_id,
            "status": "FAILED",
            "error": (
                "MiniMax file retrieve returned no download_url: "
                f"{str(retrieved)[:300]}"
            ),
        }
    # download_url stays valid for 1 hour; the caller downloads promptly.
    return {
        "task_id": task_id,
        "status": "SUCCEEDED",
        "result_url": download_url,
    }
