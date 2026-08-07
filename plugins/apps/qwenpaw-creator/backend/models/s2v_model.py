# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Digital-human lip-sync client for DashScope Wan2.2-S2V.

Protocol-aligned thin client (手法 A), transcribed from the upstream
``wan_s2v.py`` tool and the Bailian API reference:

- ``detect_face``: POST ``{base}/services/aigc/image2video/face-detect``
  with ``{"model": <detect model>, "input": {"image_url"}}`` — synchronous
  and free; always run before the billed submission.
- ``submit_s2v_task``: async POST
  ``{base}/services/aigc/image2video/video-synthesis/`` with
  ``input={"image_url","audio_url"}`` and
  ``parameters={"resolution": "480P"|"720P"}``; polled through the shared
  ``/tasks/{task_id}`` API by the existing R2V poller.

Local media is transported through DashScope model-bound temporary storage
(``oss://`` + resolve header), the same channel the video model uses.
"""

from __future__ import annotations

import asyncio
import io
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

import httpx
from PIL import Image

from models import config as model_config
from models.media_transport import upload_local_file_to_dashscope_temp
from models.provider_tasks import note_provider_task
from utils.exceptions import ModelError
from utils.logger import setup_logger
from utils.paths import media_path_from_url

logger = setup_logger("model.s2v")

S2V_RESOLUTIONS = frozenset({"480P", "720P"})
# Portrait constraint from the official reference: each side 400-7000px.
S2V_MIN_EDGE_PIXELS = 400
S2V_MAX_EDGE_PIXELS = 7000

_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
# A billed submission may have been accepted before an ambiguous server
# error, so only an outright rejection (rate limit) may be retried.
_SUBMIT_RETRY_STATUS = frozenset({429})
_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 2.0

# wan2.2-s2v-detect expresses "this portrait is unusable" as HTTP 400 with
# an ``InvalidFile.*`` code (NoHuman, BodyProportion, ...) rather than as a
# 200 with ``check_pass: false``. Measured against the live endpoint; both
# shapes are handled so the verdict never surfaces as a transport error.
_DETECT_VERDICT_STATUS = frozenset({400})
_DETECT_VERDICT_CODE_PREFIX = "invalidfile"


@dataclass(frozen=True, slots=True)
class FaceDetectResult:
    passed: bool
    reason: str = ""
    humanoid: bool = False


def _endpoint(suffix: str) -> str:
    base = model_config.get_s2v_base_url().rstrip("/")
    return f"{base}/{suffix.lstrip('/')}"


def _require_key() -> str:
    key = model_config.get_s2v_api_key()
    if not key:
        raise ModelError(
            "creator_s2v_model.api_key or S2V_API_KEY is required",
            model_name=model_config.get_s2v_model_name(),
        )
    return key


def validate_portrait_image_bytes(content: bytes) -> None:
    """Enforce the wan2.2-s2v portrait constraint (each side 400-7000px)."""

    try:
        with Image.open(io.BytesIO(content)) as image:
            width, height = image.size
    except Exception as exc:
        raise ValueError("portrait image cannot be decoded") from exc
    if (
        min(width, height) < S2V_MIN_EDGE_PIXELS
        or max(width, height) > S2V_MAX_EDGE_PIXELS
    ):
        raise ValueError(
            f"portrait image must be {S2V_MIN_EDGE_PIXELS}-"
            f"{S2V_MAX_EDGE_PIXELS}px per side, got {width}x{height}",
        )


def normalize_s2v_resolution(resolution: str) -> str:
    value = (resolution or "480P").strip().upper() or "480P"
    if value not in S2V_RESOLUTIONS:
        raise ModelError(
            f"S2V resolution must be one of {sorted(S2V_RESOLUTIONS)}, "
            f"got {resolution!r}",
            model_name=model_config.get_s2v_model_name(),
        )
    return value


async def resolve_s2v_media_url(
    url: str,
    *,
    validate_portrait: bool,
    model_name: str,
) -> str:
    """Return a provider-resolvable URL for one s2v input.

    Public HTTP(S)/OSS URLs pass through; ``file://`` and ``/generated/``
    media is uploaded to DashScope model-bound temporary storage (48h TTL).
    ``model_name`` must be the model that will *consume* the URL: a
    temporary upload only resolves for the model its policy was issued for
    (see :mod:`models.media_transport`), so the free detect call uploads
    against the detect model and generation against ``wan2.2-s2v``.
    """

    value = url.strip()
    if value.startswith(("http://", "https://", "oss://")):
        return value
    if value.startswith("/generated/"):
        media_path = media_path_from_url(value)
    elif value.startswith("file://"):
        media_path = Path(urlparse(value).path)
    else:
        raise ModelError(
            "S2V media must be /generated, file://, http(s):// or oss:// "
            f"before provider-bound transport: {value[:120]}",
            model_name=model_name,
        )
    if validate_portrait:
        try:
            validate_portrait_image_bytes(media_path.read_bytes())
        except ValueError as exc:
            raise ModelError(str(exc), model_name=model_name) from exc
    media_type = (
        mimetypes.guess_type(media_path.name)[0] or "application/octet-stream"
    )
    return await upload_local_file_to_dashscope_temp(
        media_path,
        api_key=_require_key(),
        model_name=model_name,
        media_type=media_type,
    )


async def _post_json(
    url: str,
    *,
    payload: dict,
    extra_headers: dict | None = None,
    retry_statuses: frozenset[int] = _RETRY_STATUS,
    verdict_statuses: frozenset[int] = frozenset(),
) -> dict:
    """POST one S2V request, retrying only the given statuses.

    ``retry_statuses`` is deliberately caller-supplied: a free, idempotent
    detect may retry server errors, while a billed submission must not —
    the provider can create (and bill) the task before answering 5xx, so a
    retry would buy the same clip twice under one durable submit claim.

    ``verdict_statuses`` are statuses whose body is a meaningful answer
    rather than a failure (the detect model reports an unusable portrait as
    HTTP 400); their parsed body is returned to the caller.
    """

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_require_key()}",
        "X-DashScope-OssResourceResolve": "enable",
        **(extra_headers or {}),
    }
    timeout_seconds = model_config.get_s2v_timeout_seconds()
    model_name = model_config.get_s2v_model_name()
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30, read=timeout_seconds),
    ) as client:
        for attempt in range(1, _RETRY_ATTEMPTS + 1):
            response = await client.post(url, headers=headers, json=payload)
            if (
                response.status_code in retry_statuses
                and attempt < _RETRY_ATTEMPTS
            ):
                wait = _RETRY_BACKOFF_SECONDS * attempt
                logger.warning(
                    "S2V request got HTTP %d (attempt %d/%d), retrying in %.0fs",
                    response.status_code,
                    attempt,
                    _RETRY_ATTEMPTS,
                    wait,
                )
                await asyncio.sleep(wait)
                continue
            if response.status_code in verdict_statuses:
                try:
                    return dict(response.json())
                except ValueError:
                    pass
            if response.status_code >= 400:
                raise ModelError(
                    f"S2V request failed (HTTP {response.status_code}): "
                    f"{response.text[:400]}",
                    model_name=model_name,
                )
            return response.json()
    raise ModelError("S2V request retries exhausted", model_name=model_name)


def _detect_verdict_from_error(data: Mapping[str, Any]) -> str | None:
    """Reason text when an error body is really a detect rejection."""

    code = str(data.get("code") or "").strip()
    if not code:
        return None
    if not code.casefold().startswith(_DETECT_VERDICT_CODE_PREFIX):
        # A genuine bad request (InvalidParameter, InvalidApiKey, ...) is a
        # failure, not a portrait verdict.
        return None
    message = str(data.get("message") or "").strip()
    return f"[{code}] {message}" if message else f"[{code}]"


async def detect_face(image_url: str) -> FaceDetectResult:
    """Free synchronous portrait suitability check; always run first."""

    detect_model = model_config.get_s2v_detect_model_name()
    resolved_url = await resolve_s2v_media_url(
        image_url,
        validate_portrait=True,
        model_name=detect_model,
    )
    data = await _post_json(
        _endpoint("services/aigc/image2video/face-detect"),
        payload={
            "model": detect_model,
            "input": {"image_url": resolved_url},
        },
        verdict_statuses=_DETECT_VERDICT_STATUS,
    )
    rejection = _detect_verdict_from_error(data)
    if rejection is not None:
        # Unusable portrait: a verdict, not a failure. Nothing was billed.
        logger.info("S2V face detect: passed=False reason=%s", rejection)
        return FaceDetectResult(passed=False, reason=rejection)
    if "output" not in data and data.get("code"):
        raise ModelError(
            f"S2V face detect failed: {data.get('code')} "
            f"{str(data.get('message') or '')[:200]}",
            model_name=detect_model,
        )
    output = data.get("output") if isinstance(data.get("output"), dict) else {}
    passed = bool(output.get("check_pass"))
    humanoid = bool(output.get("humanoid"))
    reason = ""
    if not passed:
        code = str(output.get("code") or "").strip()
        message = str(output.get("message") or "").strip()
        reason = (
            f"[{code}] {message}" if code else (message or "check_pass=false")
        )
        # Common upstream failure causes: multiple people, side face,
        # blurry, occluded, unsupported style.
    logger.info(
        "S2V face detect: passed=%s humanoid=%s reason=%s",
        passed,
        humanoid,
        reason or "-",
    )
    return FaceDetectResult(passed=passed, reason=reason, humanoid=humanoid)


async def submit_s2v_task(
    image_url: str,
    audio_url: str,
    resolution: str = "480P",
) -> str:
    """Submit one wan2.2-s2v lip-sync task and return its task_id."""

    if not audio_url or not audio_url.strip():
        raise ModelError(
            "S2V generation requires an audio_url (audioAssetRef)",
            model_name=model_config.get_s2v_model_name(),
        )
    normalized_resolution = normalize_s2v_resolution(resolution)
    model_name = model_config.get_s2v_model_name()
    resolved_image = await resolve_s2v_media_url(
        image_url,
        validate_portrait=True,
        model_name=model_name,
    )
    resolved_audio = await resolve_s2v_media_url(
        audio_url,
        validate_portrait=False,
        model_name=model_name,
    )
    data = await _post_json(
        _endpoint("services/aigc/image2video/video-synthesis/"),
        payload={
            "model": model_name,
            "input": {
                "image_url": resolved_image,
                "audio_url": resolved_audio,
            },
            "parameters": {"resolution": normalized_resolution},
        },
        extra_headers={"X-DashScope-Async": "enable"},
        # Never retry an ambiguous 5xx: the clip may already be billed.
        retry_statuses=_SUBMIT_RETRY_STATUS,
    )
    output = data.get("output") if isinstance(data.get("output"), dict) else {}
    task_id = str(output.get("task_id") or data.get("task_id") or "").strip()
    if not task_id:
        raise ModelError(
            f"No task_id in S2V response: {data}",
            model_name=model_name,
        )
    # The task is billed on acceptance; record it before returning so an
    # interrupted poll leaves a retrievable reference.
    note_provider_task(
        provider_task_id=task_id,
        model=model_name,
        kind="s2v_generation",
    )
    logger.info("S2V task submitted | task_id=%s", task_id)
    return task_id


async def check_s2v_task_status(task_id: str) -> dict:
    """Poll one wan2.2-s2v task; result shape mirrors the video poller."""

    model_name = model_config.get_s2v_model_name()
    url = _endpoint(f"tasks/{task_id}")
    timeout_seconds = model_config.get_s2v_timeout_seconds()
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30, read=timeout_seconds),
        ) as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {_require_key()}"},
            )
            response.raise_for_status()
            data = response.json()
    except httpx.TimeoutException:
        raise ModelError(
            "S2V task status check timed out",
            model_name=model_name,
        ) from None
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        raise ModelError(
            f"S2V task status check failed with status {status_code}",
            model_name=model_name,
            retryable=status_code >= 500 or status_code == 429,
        ) from exc

    output = data.get("output") if isinstance(data.get("output"), dict) else {}
    status = str(output.get("task_status") or "UNKNOWN").upper()
    result: dict = {"task_id": task_id, "status": status}
    if status == "SUCCEEDED":
        results = (
            output.get("results")
            if isinstance(output.get("results"), dict)
            else {}
        )
        video_url = str(
            results.get("video_url") or output.get("video_url") or "",
        )
        result["result_url"] = video_url
        logger.info(
            "S2V task succeeded | task_id=%s url=%s",
            task_id,
            video_url[:80],
        )
    elif status == "FAILED":
        message = str(
            output.get("message") or output.get("code") or "Task failed",
        )
        result["error"] = message
        logger.warning("S2V task failed | task_id=%s: %s", task_id, message)
    return result


__all__ = [
    "S2V_MAX_EDGE_PIXELS",
    "S2V_MIN_EDGE_PIXELS",
    "S2V_RESOLUTIONS",
    "FaceDetectResult",
    "check_s2v_task_status",
    "detect_face",
    "normalize_s2v_resolution",
    "resolve_s2v_media_url",
    "submit_s2v_task",
    "validate_portrait_image_bytes",
]
