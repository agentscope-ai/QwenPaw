# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""MiniMax (Hailuo) video generation protocol.

Endpoints (official API reference,
https://platform.minimax.io/docs/api-reference/video-generation-t2v):

    POST {base}/v1/video_generation
    GET  {base}/v1/query/video_generation?task_id={id}
    GET  {base}/v1/files/retrieve?file_id={id}

Authentication is ``Authorization: Bearer <API key>``. The create call
returns a ``task_id``; polling reports ``Preparing/Queueing/Processing/
Success/Fail``; on success the ``file_id`` is exchanged for a
``download_url`` (valid for 1 hour, downloaded promptly by the shared
materializer).

Documented request fields used here: ``model``, ``prompt`` (<=2000
characters), ``duration``, ``resolution``, ``first_frame_image``
(image-to-video; URL or ``data:image/...;base64,`` data URL) and
``subject_reference`` (S2V-01 only: one character subject carrying
exactly one image; its request omits duration/resolution).
Duration/resolution combinations follow the official matrix: Hailuo
models render 768P at 6 or 10 seconds and 1080P at 6 seconds only; the
01-generation models render 720P at 6 seconds.
"""

from __future__ import annotations

import httpx

from models.video_capabilities import (
    MINIMAX_HAILUO_RESOLUTIONS,
    MINIMAX_HAILUO_02_RESOLUTIONS,
    MINIMAX_LEGACY_RESOLUTIONS,
    MINIMAX_MAX_PROMPT_CHARS,
    MINIMAX_SUBJECT_REFERENCE_MODEL,
    validate_video_mode,
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


def _resolution_matrix(model_name: str) -> dict[str, tuple[int, ...]]:
    if model_name.strip().casefold() == "minimax-hailuo-02":
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
) -> tuple[str, dict, dict]:
    """Render the video_generation submit request for one MiniMax task."""

    try:
        normalized_mode = validate_video_mode("minimax", model_name, mode)
    except ValueError as exc:
        raise ModelError(str(exc), model_name=model_name) from exc

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


async def check_status(
    task_id: str,
    *,
    api_key: str,
    base_url: str,
    timeout: int,
    model_name: str,
) -> dict:
    """One poll of a MiniMax task; resolves the file URL on success."""

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
