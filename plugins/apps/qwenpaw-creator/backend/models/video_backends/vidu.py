# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Vidu video generation protocol (official channel, reference-to-video).

Endpoints (official .md references under https://platform.vidu.com/docs):

    POST {base}/ent/v2/reference2video
    GET  {base}/ent/v2/tasks/{id}/creations

Authentication is ``Authorization: Token <API key>``. The flat
"Reference to Video" contract is used: ``images`` carries 1-7 reference
image URLs or data URLs (base64 payload <=10MB after decoding, request
body <=20MB); ``videos`` is viduq2-pro only (at most 1 video of 8s or 2
of 5s, images then limited to 1-4); ``prompt`` is at most 5000
characters. Duration/resolution windows are model-specific (documented
per model in the request-body table). Polling reads ``state``
(created/queueing/processing/success/failed) and ``creations[].url``
(valid for 24 hours, downloaded promptly).
"""

from __future__ import annotations

import httpx

from models.video_capabilities import (
    VIDU_DIRECT_SPECS,
    VIDU_MAX_PROMPT_CHARS,
)
from utils.exceptions import ModelError
from utils.logger import setup_logger

logger = setup_logger("model.video.vidu")

DEFAULT_BASE_URL = "https://api.vidu.com"

# Official image constraint: base64 payloads must decode to <=10MB.
_IMAGE_BASE64_MAX_CHARS = 10 * 1024 * 1024 * 4 // 3


def _api_base(base_url: str) -> str:
    return base_url.rstrip("/")


def build_submit_request(
    *,
    prompt: str,
    media: list[dict],
    ratio: str,
    duration: int,
    resolution: str,
    generate_audio: bool,
    model_name: str,
    api_key: str,
    base_url: str,
) -> tuple[str, dict, dict]:
    """Render the official-channel Vidu reference2video request."""
    # pylint: disable=too-many-branches
    spec = VIDU_DIRECT_SPECS.get(model_name.strip())
    if spec is None:
        raise ModelError(
            f"Vidu model `{model_name}` is not one of the official "
            "reference2video models "
            f"({', '.join(sorted(VIDU_DIRECT_SPECS))})",
            model_name=model_name,
        )
    if len(prompt) > VIDU_MAX_PROMPT_CHARS:
        raise ModelError(
            f"Vidu prompts must stay within {VIDU_MAX_PROMPT_CHARS} "
            f"characters, got {len(prompt)}",
            model_name=model_name,
        )
    low, high = spec["durations"]
    if duration < low or duration > high:
        raise ModelError(
            f"Vidu model `{model_name}` duration must be an integer "
            f"between {low} and {high} seconds, got {duration}",
            model_name=model_name,
        )
    normalized_resolution = (
        (resolution or spec["default_resolution"]).strip().lower()
    )
    if normalized_resolution not in spec["resolutions"]:
        raise ModelError(
            f"Vidu model `{model_name}` supports resolutions "
            f"{list(spec['resolutions'])}, got {resolution!r}",
            model_name=model_name,
        )
    ratio_value = ratio or "16:9"
    if ratio_value not in spec["ratios"]:
        raise ModelError(
            f"Vidu model `{model_name}` supports aspect ratios "
            f"{list(spec['ratios'])}, got {ratio!r}",
            model_name=model_name,
        )
    images: list[str] = []
    videos: list[str] = []
    for item in media:
        url = item.get("url") or ""
        if not url:
            continue
        if item["type"] == "reference_video":
            videos.append(url)
            continue
        if (
            url.startswith("data:")
            and len(url.partition(",")[2]) > _IMAGE_BASE64_MAX_CHARS
        ):
            raise ModelError(
                "Vidu base64 reference images must decode to at most "
                "10MB; downscale the media or provide a public HTTPS URL",
                model_name=model_name,
            )
        images.append(url)
    if videos and not images:
        raise ModelError(
            "Vidu reference generation requires at least 1 reference "
            "image even when reference videos are supplied",
            model_name=model_name,
        )
    if videos and len(images) > 4:
        raise ModelError(
            "viduq2-pro accepts at most 4 reference images together with "
            f"reference videos, got {len(images)}",
            model_name=model_name,
        )
    body: dict = {
        "model": model_name.strip(),
        "images": images,
        "prompt": prompt,
        "duration": duration,
        "resolution": normalized_resolution,
        "aspect_ratio": ratio_value,
    }
    if videos:
        body["videos"] = videos
    if spec["audio"]:
        body["audio"] = bool(generate_audio)
    url = f"{_api_base(base_url)}/ent/v2/reference2video"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Token {api_key}",
    }
    return url, headers, body


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
    """One poll of an official-channel Vidu task."""

    url = f"{_api_base(base_url)}/ent/v2/tasks/{task_id}/creations"
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(
            url,
            headers={"Authorization": f"Token {api_key}"},
        )
        if resp.status_code >= 400:
            raise ModelError(
                f"Vidu task poll failed with status {resp.status_code}: "
                f"{resp.text[:400]}",
                model_name=model_name,
                retryable=resp.status_code >= 500 or resp.status_code == 429,
            )
        payload = resp.json()
    state = (
        str(payload.get("state") or "").strip()
        if isinstance(payload, dict)
        else ""
    )
    if state in {"created", "queueing", "processing", ""}:
        return {"task_id": task_id, "status": "RUNNING"}
    if state != "success":
        return {
            "task_id": task_id,
            "status": "FAILED",
            "error": (
                f"Vidu task ended {state or 'unknown'}: "
                f"{payload.get('err_code') or ''}"
            ).strip(),
        }
    creations = payload.get("creations")
    if isinstance(creations, list):
        for creation in creations:
            if isinstance(creation, dict) and creation.get("url"):
                # URLs stay valid for 24 hours; downloaded promptly.
                return {
                    "task_id": task_id,
                    "status": "SUCCEEDED",
                    "result_url": str(creation["url"]),
                }
    return {
        "task_id": task_id,
        "status": "FAILED",
        "error": "Vidu task succeeded without a creation URL",
    }
