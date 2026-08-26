# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Vidu video generation protocol (official channel).

Endpoints (official .md references under https://platform.vidu.com/docs):

    POST {base}/ent/v2/text2video
    POST {base}/ent/v2/img2video
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
    validate_video_mode,
)
from utils.exceptions import ModelError
from utils.logger import setup_logger

logger = setup_logger("model.video.vidu")

DEFAULT_BASE_URL = "https://api.vidu.com"

# Official image constraint: base64 payloads must decode to <=10MB.
_IMAGE_BASE64_MAX_CHARS = 10 * 1024 * 1024 * 4 // 3


def _with_duration(spec: dict, low: int, high: int) -> dict:
    return {**spec, "durations": (low, high)}


# Vidu publishes independent accepted-model tables for each endpoint. Mode
# membership below is explicit and never inferred from the r2v table; entries
# reuse an r2v constraint mapping only where the independently documented
# duration/resolution/ratio values are identical.
_VIDU_DIRECT_MODE_SPECS: dict[str, dict[str, dict]] = {
    "r2v": VIDU_DIRECT_SPECS,
    "t2v": {
        "viduq3-turbo": {
            **_with_duration(VIDU_DIRECT_SPECS["viduq3-turbo"], 1, 16),
            "ratios": ("16:9", "9:16", "3:4", "4:3", "1:1"),
        },
        "viduq2": VIDU_DIRECT_SPECS["viduq2"],
        "viduq1": VIDU_DIRECT_SPECS["viduq1"],
    },
    "i2v": {
        "viduq3-turbo": _with_duration(
            VIDU_DIRECT_SPECS["viduq3-turbo"],
            1,
            16,
        ),
        "viduq2-pro": _with_duration(VIDU_DIRECT_SPECS["viduq2-pro"], 1, 10),
        "viduq1": VIDU_DIRECT_SPECS["viduq1"],
        "vidu2.0": {
            **VIDU_DIRECT_SPECS["vidu2.0"],
            "durations": (4, 8),
            "duration_values": (4, 8),
            "resolutions": ("360p", "720p", "1080p"),
            "resolution_durations": {
                "360p": (4,),
                "720p": (4, 8),
                "1080p": (4,),
            },
        },
    },
}


def _api_base(base_url: str) -> str:
    return base_url.rstrip("/")


def build_submit_request(
    *,
    prompt: str,
    mode: str,
    media: list[dict],
    ratio: str,
    duration: int,
    resolution: str,
    generate_audio: bool,
    model_name: str,
    api_key: str,
    base_url: str,
) -> tuple[str, dict, dict]:
    """Render the mode-specific official-channel Vidu request."""
    # The official Vidu endpoint has mode-specific validation and payloads.
    # Keep that contract visible in one adapter instead of hiding it in
    # generic helpers that would blur provider rules.
    # pylint: disable=too-many-branches,too-many-statements
    model = model_name.strip()
    try:
        normalized_mode = validate_video_mode("vidu", model, mode)
    except ValueError as exc:
        raise ModelError(str(exc), model_name=model_name) from exc
    spec = _VIDU_DIRECT_MODE_SPECS[normalized_mode].get(model)
    if spec is None:
        raise ModelError(
            f"Vidu model `{model_name}` is not accepted by the official "
            f"{normalized_mode} endpoint",
            model_name=model_name,
        )
    if len(prompt) > VIDU_MAX_PROMPT_CHARS:
        raise ModelError(
            f"Vidu prompts must stay within {VIDU_MAX_PROMPT_CHARS} "
            f"characters, got {len(prompt)}",
            model_name=model_name,
        )
    low, high = spec["durations"]
    duration_values = spec.get("duration_values")
    if (duration_values and duration not in duration_values) or (
        not duration_values and (duration < low or duration > high)
    ):
        duration_rule = (
            f"one of {list(duration_values)}"
            if duration_values
            else f"an integer between {low} and {high}"
        )
        raise ModelError(
            f"Vidu model `{model_name}` duration must be {duration_rule} "
            f"seconds, got {duration}",
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
    resolution_durations = spec.get("resolution_durations", {})
    if resolution_durations and duration not in resolution_durations.get(
        normalized_resolution,
        (),
    ):
        raise ModelError(
            f"Vidu model `{model_name}` does not support {duration}s at "
            f"{normalized_resolution}",
            model_name=model_name,
        )
    ratio_value = ratio or "16:9"
    if normalized_mode != "i2v" and ratio_value not in spec["ratios"]:
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
    if normalized_mode == "t2v" and (images or videos):
        raise ModelError(
            "Vidu text2video does not accept reference media",
            model_name=model_name,
        )
    if normalized_mode == "i2v" and (
        len(images) != 1
        or videos
        or any(item.get("type") != "first_frame" for item in media)
    ):
        raise ModelError(
            "Vidu img2video requires exactly one first-frame image",
            model_name=model_name,
        )
    if normalized_mode == "r2v" and not images and not videos:
        raise ModelError(
            "Vidu reference2video requires at least 1 reference image or video",
            model_name=model_name,
        )
    if normalized_mode == "r2v" and videos and len(images) > 4:
        raise ModelError(
            "viduq2-pro accepts at most 4 reference images together with "
            f"reference videos, got {len(images)}",
            model_name=model_name,
        )
    body: dict = {
        "model": model,
        "prompt": prompt,
        "duration": duration,
        "resolution": normalized_resolution,
    }
    if normalized_mode != "t2v":
        body["images"] = images
    if normalized_mode != "i2v":
        body["aspect_ratio"] = ratio_value
    if normalized_mode == "r2v" and videos:
        body["videos"] = videos
    if spec["audio"]:
        body["audio"] = bool(generate_audio)
    endpoint = {
        "t2v": "text2video",
        "i2v": "img2video",
        "r2v": "reference2video",
    }[normalized_mode]
    url = f"{_api_base(base_url)}/ent/v2/{endpoint}"
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
