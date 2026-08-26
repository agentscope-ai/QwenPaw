# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Google Gemini API Veo video generation protocol.

Endpoints (official REST examples on https://ai.google.dev/gemini-api/docs/veo):

    POST {base}/models/{model}:predictLongRunning   (x-goog-api-key)
    GET  {base}/{operation_name}                    (poll until .done)

The request body is ``{"instances": [...], "parameters": {...}}``:

- text-to-video: ``instances[0].prompt``.
- image-to-video: ``instances[0].image = {"inlineData": {mimeType, data}}``.
- reference generation (Veo 3.1 / 3.1 Fast only): up to three
  ``instances[0].referenceImages`` entries, each
  ``{"image": {"inlineData": ...}, "referenceType": "asset"}``.

Documented parameters: ``aspectRatio`` ("16:9"/"9:16"), ``resolution``
("720p"/"1080p"/"4k"; Lite has no 4k), ``durationSeconds`` ("4"/"6"/"8",
must be "8" with reference images or 1080p/4k output).

Images must be inlined as base64 (the Gemini API accepts no remote image
URLs here). The finished video URI at
``response.generateVideoResponse.generatedSamples[0].video.uri`` requires
API-key auth. The durable poll result keeps that URI credential-free and marks
the required authentication scheme; the shared materializer adds the current
API key as an in-memory request header only while downloading.
"""

from __future__ import annotations

import httpx

from models.video_capabilities import (
    VEO_DURATION_SECONDS,
    VEO_RATIOS,
    VEO_REFERENCE_DURATION_SECONDS,
    VEO_RESOLUTIONS,
)
from utils.exceptions import ModelError
from utils.logger import setup_logger

logger = setup_logger("model.video.veo")

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DOWNLOAD_AUTH = "x-goog-api-key"


def _api_base(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("googleapis.com"):
        base = f"{base}/v1beta"
    return base


def _inline_data_from_data_url(url: str, model_name: str) -> dict:
    """Split a ``data:<mime>;base64,<payload>`` URL into an inlineData Blob."""

    if not url.startswith("data:"):
        raise ModelError(
            "Veo reference media must be inlined as base64 before submit "
            f"(got a non-data URL: {url[:80]})",
            model_name=model_name,
        )
    header, _, payload = url.partition(",")
    mime_type = header[5:].split(";", 1)[0] or "image/png"
    return {"mimeType": mime_type, "data": payload}


def _is_lite(model_name: str) -> bool:
    return "lite" in model_name.casefold()


def build_submit_request(
    *,
    prompt: str,
    mode: str,
    media: list[dict],
    ratio: str,
    duration: int,
    resolution: str,
    model_name: str,
    api_key: str,
    base_url: str,
) -> tuple[str, dict, dict]:
    """Render the predictLongRunning submit request for one Veo task."""

    normalized_ratio = ratio or "16:9"
    if normalized_ratio not in VEO_RATIOS:
        raise ModelError(
            f"Veo aspectRatio must be one of {sorted(VEO_RATIOS)}, "
            f"got {ratio!r}",
            model_name=model_name,
        )
    normalized_resolution = (resolution or "720p").lower()
    if normalized_resolution not in VEO_RESOLUTIONS:
        raise ModelError(
            f"Veo resolution must be one of {sorted(VEO_RESOLUTIONS)}, "
            f"got {resolution!r}",
            model_name=model_name,
        )
    if normalized_resolution == "4k" and _is_lite(model_name):
        raise ModelError(
            "veo-3.1-lite-generate-preview does not support 4k output; "
            "use 720p or 1080p",
            model_name=model_name,
        )
    if duration not in VEO_DURATION_SECONDS:
        raise ModelError(
            f"Veo durationSeconds must be one of "
            f"{sorted(VEO_DURATION_SECONDS)}, got {duration}",
            model_name=model_name,
        )
    reference_items = [
        item for item in media if item.get("type") == "reference_image"
    ]
    first_frame = next(
        (item for item in media if item.get("type") == "first_frame"),
        None,
    )
    requires_eight = bool(reference_items) or normalized_resolution in {
        "1080p",
        "4k",
    }
    if requires_eight and duration != VEO_REFERENCE_DURATION_SECONDS:
        raise ModelError(
            "Veo durationSeconds must be 8 when using reference images "
            f"or 1080p/4k resolutions, got {duration}",
            model_name=model_name,
        )

    instance: dict = {"prompt": prompt}
    if mode == "i2v" and first_frame is not None:
        instance["image"] = {
            "inlineData": _inline_data_from_data_url(
                first_frame["url"],
                model_name,
            ),
        }
    if mode == "r2v":
        instance["referenceImages"] = [
            {
                "image": {
                    "inlineData": _inline_data_from_data_url(
                        item["url"],
                        model_name,
                    ),
                },
                "referenceType": "asset",
            }
            for item in reference_items
        ]
    body = {
        "instances": [instance],
        "parameters": {
            "aspectRatio": normalized_ratio,
            "resolution": normalized_resolution,
            "durationSeconds": str(duration),
        },
    }
    url = f"{_api_base(base_url)}/models/{model_name}:predictLongRunning"
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }
    return url, headers, body


def extract_task_id(payload: dict) -> str:
    """The operation name is the durable task handle for polling."""

    if isinstance(payload, dict):
        return str(payload.get("name") or "").strip()
    return ""


async def check_status(
    task_id: str,
    *,
    api_key: str,
    base_url: str,
    timeout: int,
    model_name: str,
) -> dict:
    """One poll of a Veo long-running operation."""

    url = f"{_api_base(base_url)}/{task_id.lstrip('/')}"
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url, headers={"x-goog-api-key": api_key})
        if resp.status_code >= 400:
            raise ModelError(
                f"Veo operation poll failed with status {resp.status_code}: "
                f"{resp.text[:400]}",
                model_name=model_name,
                retryable=resp.status_code >= 500 or resp.status_code == 429,
            )
        payload = resp.json()
    if not isinstance(payload, dict) or not payload.get("done"):
        return {"task_id": task_id, "status": "RUNNING"}
    error = payload.get("error")
    if isinstance(error, dict):
        return {
            "task_id": task_id,
            "status": "FAILED",
            "error": f"{error.get('code')}: {error.get('message')}",
        }
    response = (
        payload.get("response")
        if isinstance(payload.get("response"), dict)
        else {}
    )
    generate_response = (
        response.get("generateVideoResponse")
        if isinstance(response.get("generateVideoResponse"), dict)
        else {}
    )
    samples = generate_response.get("generatedSamples")
    if isinstance(samples, list) and samples:
        video = (
            samples[0].get("video")
            if isinstance(samples[0], dict)
            and isinstance(samples[0].get("video"), dict)
            else {}
        )
        uri = str(video.get("uri") or "").strip()
        if uri:
            return {
                "task_id": task_id,
                "status": "SUCCEEDED",
                "result_url": uri,
                "download_auth": DOWNLOAD_AUTH,
            }
    return {
        "task_id": task_id,
        "status": "FAILED",
        "error": (
            "Veo operation finished without a video sample: "
            f"{str(generate_response or response)[:400]}"
        ),
    }
