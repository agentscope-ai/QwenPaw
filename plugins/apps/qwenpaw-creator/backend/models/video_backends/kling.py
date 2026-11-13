# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Kling AI Open Platform video generation protocol (official channel).

Endpoints (official .md references under https://kling.ai/document-api):

    POST {base}/text-to-video/{model}     e.g. kling-2.6   (t2v)
    POST {base}/image-to-video/{model}    e.g. kling-2.6   (i2v)
    POST {base}/omni-video/{model}        e.g. kling-3.0-omni (r2v)
    GET  {base}/tasks?task_ids={id}       (poll)

The new-generation API authenticates with ``Authorization: Bearer
<API Key>`` (the JWT AK/SK flow only applies to legacy model_name-style
endpoints, which this module does not use). The official domain is
https://api-singapore.klingai.com.

Documented contracts used here:

- t2v/i2v (kling-2.6): prompt <= 2500 chars; settings.resolution
  720p/1080p; settings.duration 5 or 10; t2v settings.aspect_ratio
  16:9/9:16/1:1; i2v sends ``contents`` entries (prompt text +
  first_frame url, URL or Base64; .jpg/.jpeg/.png, <=50MB, >=300px,
  aspect within 1:2.5-2.5:1).
- omni (kling-3.0-omni): ``contents`` with refer_image / feature_video
  entries referenced from the prompt as @id; without a reference video
  up to 7 refer images, with one (max 1) up to 4 and audio must be off;
  settings.duration integer 3-15; settings.resolution 720p/1080p/4k;
  settings.aspect_ratio required when no first frame / reference video.
- Poll: GET /tasks?task_ids={id} -> data[0].status
  (submitted/processing/succeeded/failed) and outputs[type=video].url
  (results are cleared after 30 days).
"""

from __future__ import annotations

import httpx

from models.video_capabilities import (
    KLING_MAX_PROMPT_CHARS,
    KLING_OMNI_DURATIONS,
    KLING_OMNI_RESOLUTIONS,
    KLING_RATIOS,
    KLING_REFER_MAX_IMAGES_WITH_VIDEO,
    KLING_V26_DURATIONS,
    KLING_V26_RESOLUTIONS,
    is_kling_omni_model,
    validate_video_mode,
)
from utils.exceptions import ModelError
from utils.logger import setup_logger

logger = setup_logger("model.video.kling")

DEFAULT_BASE_URL = "https://api-singapore.klingai.com"


def _api_base(base_url: str) -> str:
    return base_url.rstrip("/")


def _media_url(url: str) -> str:
    """Kling accepts public URLs or Base64; strip the data-URL header.

    The legacy Kling contract documents Base64 image payloads without a
    ``data:`` prefix and the new reference pages say "URL or Base64", so
    inlined local media is sent as the bare Base64 payload.
    """

    if url.startswith("data:"):
        return url.partition(",")[2]
    return url


def _validated_settings(
    *,
    mode: str,
    ratio: str,
    duration: int,
    resolution: str,
    generate_audio: bool,
    has_feature_video: bool,
    needs_aspect_ratio: bool,
    model_name: str,
) -> dict:
    is_omni = is_kling_omni_model(model_name)
    durations = KLING_OMNI_DURATIONS if is_omni else KLING_V26_DURATIONS
    resolutions = KLING_OMNI_RESOLUTIONS if is_omni else KLING_V26_RESOLUTIONS
    if duration not in durations:
        raise ModelError(
            f"Kling model `{model_name}` duration must be one of "
            f"{sorted(durations)} seconds, got {duration}",
            model_name=model_name,
        )
    normalized_resolution = (resolution or "720p").lower()
    if normalized_resolution not in resolutions:
        raise ModelError(
            f"Kling model `{model_name}` supports resolutions "
            f"{sorted(resolutions)}, got {resolution!r}",
            model_name=model_name,
        )
    settings: dict = {
        "resolution": normalized_resolution,
        "duration": duration,
        # Native audio is not supported with a feature reference video.
        "audio": (
            "native" if generate_audio and not has_feature_video else "off"
        ),
    }
    if is_omni and mode == "r2v":
        # Creator renders one shot per task; disable intelligent
        # multi-shot planning (documented default is true).
        settings["multi_shot"] = False
    if needs_aspect_ratio:
        if ratio not in KLING_RATIOS:
            raise ModelError(
                f"Kling aspect_ratio must be one of {sorted(KLING_RATIOS)}, "
                f"got {ratio!r}",
                model_name=model_name,
            )
        settings["aspect_ratio"] = ratio
    return settings


def build_submit_request(
    *,
    prompt: str,
    mode: str,
    media: list[dict],
    ratio: str,
    duration: int,
    resolution: str,
    watermark: bool,
    generate_audio: bool,
    model_name: str,
    api_key: str,
    base_url: str,
) -> tuple[str, dict, dict]:
    """Render the official-channel Kling create-task request."""

    try:
        mode = validate_video_mode("kling", model_name, mode)
    except ValueError as exc:
        raise ModelError(str(exc), model_name=model_name) from exc

    if len(prompt) > KLING_MAX_PROMPT_CHARS:
        raise ModelError(
            f"Kling prompts must stay within {KLING_MAX_PROMPT_CHARS} "
            f"characters, got {len(prompt)}",
            model_name=model_name,
        )
    if mode == "r2v" and not is_kling_omni_model(model_name):
        raise ModelError(
            "Kling reference generation on the official channel is served "
            "by the omni endpoint (e.g. kling-3.0-omni); the configured "
            f"model `{model_name}` supports t2v/i2v only",
            model_name=model_name,
        )
    contents: list[dict] = []
    image_count = 0
    video_count = 0
    for item in media:
        if item["type"] == "first_frame":
            contents.append(
                {"type": "first_frame", "url": _media_url(item["url"])},
            )
        elif item["type"] == "reference_video":
            video_count += 1
            contents.append(
                {
                    "type": "feature_video",
                    "url": item["url"],
                    "id": f"video_{video_count}",
                },
            )
        else:
            image_count += 1
            contents.append(
                {
                    "type": "refer_image",
                    "url": _media_url(item["url"]),
                    "id": f"image_{image_count}",
                },
            )
    if video_count and image_count > KLING_REFER_MAX_IMAGES_WITH_VIDEO:
        raise ModelError(
            "Kling omni generation accepts at most "
            f"{KLING_REFER_MAX_IMAGES_WITH_VIDEO} reference images together "
            f"with a feature reference video, got {image_count}",
            model_name=model_name,
        )
    has_first_frame = any(item["type"] == "first_frame" for item in media)
    settings = _validated_settings(
        mode=mode,
        ratio=ratio,
        duration=duration,
        resolution=resolution,
        generate_audio=generate_audio,
        has_feature_video=bool(video_count),
        # aspect_ratio is required when no first frame / reference video
        # anchors the frame (t2v and image-only omni reference).
        needs_aspect_ratio=not has_first_frame and not video_count,
        model_name=model_name,
    )
    base = _api_base(base_url)
    if mode == "t2v":
        url = f"{base}/text-to-video/{model_name}"
        body: dict = {"prompt": prompt}
    else:
        endpoint = "omni-video" if mode == "r2v" else "image-to-video"
        url = f"{base}/{endpoint}/{model_name}"
        body = {
            "contents": [{"type": "prompt", "text": prompt}, *contents],
        }
    body["settings"] = settings
    body["options"] = {"watermark_info": {"enabled": watermark}}
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    return url, headers, body


def raise_on_error_code(payload: dict, model_name: str) -> None:
    """Surface a Kling ``code != 0`` rejection wrapped in an HTTP 200."""

    if isinstance(payload, dict) and payload.get("code") not in (None, 0):
        raise ModelError(
            f"Kling request rejected: {payload.get('code')}: "
            f"{payload.get('message')}",
            model_name=model_name,
        )


def extract_task_id(payload: dict) -> str:
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return str(payload["data"].get("id") or "").strip()
    return ""


async def check_status(
    task_id: str,
    *,
    api_key: str,
    base_url: str,
    timeout: int,
    model_name: str,
) -> dict:
    """One poll of an official-channel Kling task."""

    url = f"{_api_base(base_url)}/tasks"
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(
            url,
            params={"task_ids": task_id},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        if resp.status_code >= 400:
            raise ModelError(
                f"Kling task poll failed with status {resp.status_code}: "
                f"{resp.text[:400]}",
                model_name=model_name,
                retryable=resp.status_code >= 500 or resp.status_code == 429,
            )
        payload = resp.json()
    raise_on_error_code(payload, model_name)
    tasks = payload.get("data") if isinstance(payload, dict) else None
    task = tasks[0] if isinstance(tasks, list) and tasks else None
    if not isinstance(task, dict):
        return {
            "task_id": task_id,
            "status": "FAILED",
            "error": f"Kling task {task_id} not found in poll response",
        }
    status = str(task.get("status") or "").strip()
    if status in {"submitted", "processing", ""}:
        return {"task_id": task_id, "status": "RUNNING"}
    if status != "succeeded":
        return {
            "task_id": task_id,
            "status": "FAILED",
            "error": (
                f"Kling task ended {status or 'unknown'}: "
                f"{task.get('message') or ''}"
            ).strip(),
        }
    for output in task.get("outputs") or []:
        if isinstance(output, dict) and output.get("type") == "video":
            video_url = str(output.get("url") or "").strip()
            if video_url:
                # Results are cleared after 30 days; downloaded promptly.
                return {
                    "task_id": task_id,
                    "status": "SUCCEEDED",
                    "result_url": video_url,
                }
    return {
        "task_id": task_id,
        "status": "FAILED",
        "error": "Kling task succeeded without a video output",
    }
