# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long,too-many-branches,too-many-statements
"""DashScope Bailian VLM wrapper for multimodal understanding.

The Bailian vision API is OpenAI Chat compatible: image inputs use
``image_url`` content parts and video inputs use ``video_url`` content
parts. Local files are transported through the provider-bound channel
right before the request: DashScope models use the official model-bound
temporary upload (``oss://`` URL, 48h TTL, <=1GB) resolved via the
``X-DashScope-OssResourceResolve: enable`` header, while other
OpenAI-compatible providers fall back to inline
``data:<mime>;base64,...`` URLs.
"""

from __future__ import annotations

import asyncio
import base64
import mimetypes
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from models import config as model_config
from models.concurrency import model_slot
from models.media_transport import upload_local_file_to_dashscope_temp
from models.model_capability_cache import get_capability_cache
from utils.exceptions import ModelError
from utils.logger import setup_logger
from utils.paths import local_path_from_file_url, media_path_from_url

logger = setup_logger("model.vlm")

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}


def _mime_for_path(path: Path, fallback: str) -> str:
    return mimetypes.guess_type(path.name)[0] or fallback


def _local_path_from_url(url: str) -> Path | None:
    if url.startswith("/generated/"):
        return media_path_from_url(url)
    if url.startswith("file://"):
        return local_path_from_file_url(url).expanduser().resolve()
    return None


def _data_url(path: Path, fallback_mime: str) -> str:
    size = path.stat().st_size
    max_bytes = model_config.get_vlm_max_inline_bytes()
    if size > max_bytes:
        raise ModelError(
            f"VLM local media inline size limit exceeded: {path.name} is {size} bytes, limit is {max_bytes}",
            model_name=model_config.get_vlm_model_name(),
        )
    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{_mime_for_path(path, fallback_mime)};base64,{encoded}"


def multimodal_media_part(
    url: str,
    media_type: str,
    fps: float = 1.0,
    max_frames: int | None = None,
) -> dict:
    """Build an OpenAI-compatible multimodal content part for a URL/path.

    DashScope documents ``fps`` for the OpenAI-compatible API. It explicitly
    does *not* support a caller-supplied ``max_frames`` on that API surface, so
    the compatibility argument is intentionally not serialized. Callers bound
    long-video sampling through ``fps`` instead. Both options are ignored for
    images.

    Local media keeps its original URL here; ``chat_completion`` transports
    it through the provider-bound channel right before the request.
    """
    media_type = media_type.lower()
    source_url = url
    local_path = _local_path_from_url(url)
    if local_path is not None and (
        not local_path.exists() or not local_path.is_file()
    ):
        raise ModelError(
            f"VLM local media not found: {url}",
            model_name=model_config.get_vlm_model_name(),
        )

    if media_type == "video":
        del max_frames
        return {
            "type": "video_url",
            "video_url": {"url": source_url},
            "fps": fps,
        }
    return {
        "type": "image_url",
        "image_url": {"url": source_url},
    }


def infer_visual_media_type(
    filename: str,
    content_type: str = "",
) -> str | None:
    """Return image/video for media the VLM can inspect, otherwise None."""
    if content_type.startswith("image/"):
        return "image"
    if content_type.startswith("video/"):
        return "video"
    suffix = Path(filename or "").suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix in VIDEO_SUFFIXES:
        return "video"
    return None


_MEDIA_REJECT_PHRASES = (
    "does not support image",
    "does not support video",
    "does not support vision",
    "does not support multimodal",
    "not support image",
    "not support video",
    "not support vision",
    "not support multimodal",
    "unsupported image_url",
    "unsupported video_url",
    "unsupported modality",
    "input modality is not supported",
    "unexpected item type: image_url",
    "unexpected item type: video_url",
)


def _is_media_related_error(text: str) -> bool:
    text_lower = text.lower()
    return any(phrase in text_lower for phrase in _MEDIA_REJECT_PHRASES)


def _is_dashscope_provider(base_url: str) -> bool:
    host = urlparse(base_url).hostname or ""
    return "dashscope" in host


async def _transport_local_media_part(
    part: dict,
    api_key: str,
    model_name: str,
    base_url: str,
) -> tuple[dict, bool]:
    """Replace a local media URL with a provider-transportable URL.

    Returns ``(part, uses_temp_oss)``. DashScope-bound requests use the
    official model-bound temporary upload (cached, 48h TTL, <=1GB); other
    OpenAI-compatible providers fall back to an inline Base64 data URL.
    """
    part_type = part.get("type")
    if part_type not in ("image_url", "video_url"):
        return part, False
    media_obj = part.get(part_type)
    if not isinstance(media_obj, dict):
        return part, False
    url = str(media_obj.get("url") or "")
    local_path = _local_path_from_url(url)
    if local_path is None:
        return part, False
    fallback = "video/mp4" if part_type == "video_url" else "image/png"
    transported = dict(part)
    if _is_dashscope_provider(base_url):
        try:
            resolved = await upload_local_file_to_dashscope_temp(
                local_path,
                api_key=api_key,
                model_name=model_name,
                media_type=_mime_for_path(local_path, fallback),
            )
        except Exception as exc:
            raise ModelError(
                f"VLM local media transport failed for {local_path.name}: {exc}",
                model_name=model_name,
            ) from exc
        transported[part_type] = {**media_obj, "url": resolved}
        return transported, True
    transported[part_type] = {
        **media_obj,
        "url": await asyncio.to_thread(_data_url, local_path, fallback),
    }
    return transported, False


async def chat_completion(
    content: list[dict],
    *,
    system_prompt: str = "",
    temperature: float = 0.2,
    max_tokens: int = 1800,
    timeout: float | None = None,
    api_key_override: str | None = None,
    base_url_override: str | None = None,
    model_name_override: str | None = None,
) -> str:
    """Call the configured VLM and return the assistant text."""
    api_key = api_key_override or model_config.get_vlm_api_key()
    base_url = base_url_override or model_config.get_vlm_base_url()
    model_name = model_name_override or model_config.get_vlm_model_name()
    if not api_key:
        raise ModelError(
            "creator_vlm_model.api_key, VLM_API_KEY, DASHSCOPE_API_KEY, or TEXT_API_KEY is required",
            model_name=model_name,
        )

    has_media = any(
        isinstance(p, dict) and p.get("type") in ("image_url", "video_url")
        for p in content
    )
    if has_media and get_capability_cache().get(
        f"vlm:{model_name}",
        "rejects_media",
    ):
        raise ModelError(
            "该模型已知不支持多模态输入",
            model_name=model_name,
        )

    # ``max_frames``/``max_frame`` are DashScope-SDK-only controls. Strip them
    # defensively from OpenAI-compatible content supplied by older durable
    # Tasks while preserving every supported field and the caller's objects.
    # Local media is transported through the provider-bound channel here.
    provider_content: list[dict] = []
    uses_temp_oss = False
    for item in content:
        normalized = dict(item)
        normalized.pop("max_frames", None)
        normalized.pop("max_frame", None)
        normalized, is_temp_oss = await _transport_local_media_part(
            normalized,
            api_key,
            model_name,
            base_url,
        )
        uses_temp_oss = uses_temp_oss or is_temp_oss
        provider_content.append(normalized)

    messages: list[dict] = []
    if system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt.strip()})
    messages.append({"role": "user", "content": provider_content})
    body = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "enable_thinking": False,
    }

    media_parts = [
        p
        for p in content
        if isinstance(p, dict) and p.get("type") in ("image_url", "video_url")
    ]
    video_count = sum(1 for p in media_parts if p.get("type") == "video_url")
    image_count = len(media_parts) - video_count
    logger.info(
        "VLM request start: model=%s images=%d videos=%d max_tokens=%d",
        model_name,
        image_count,
        video_count,
        max_tokens,
    )
    start_ts = time.perf_counter()
    actual_timeout = (
        timeout
        if timeout is not None
        else model_config.get_vlm_timeout_seconds()
    )
    try:
        async with httpx.AsyncClient(timeout=actual_timeout) as client:
            async with model_slot("vlm"):
                response = await client.post(
                    f"{base_url.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        **(
                            {"X-DashScope-OssResourceResolve": "enable"}
                            if uses_temp_oss
                            else {}
                        ),
                    },
                    json=body,
                )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        if has_media and _is_media_related_error(exc.response.text):
            get_capability_cache().learn(
                f"vlm:{model_name}",
                "rejects_media",
                True,
            )
        elapsed = time.perf_counter() - start_ts
        logger.error(
            "VLM request failed: %s %s elapsed=%.2fs",
            exc.response.status_code,
            exc.response.text[:500],
            elapsed,
        )
        raise ModelError(
            f"VLM request failed with status {exc.response.status_code}: {exc.response.text[:500]}",
            model_name=model_name,
        ) from exc
    except ModelError:
        raise
    except Exception as exc:
        if has_media and _is_media_related_error(str(exc)):
            get_capability_cache().learn(
                f"vlm:{model_name}",
                "rejects_media",
                True,
            )
        elapsed = time.perf_counter() - start_ts
        logger.error(
            "VLM request failed: type=%s repr=%r url=%s timeout=%s elapsed=%.2fs",
            type(exc).__name__,
            exc,
            f"{base_url.rstrip('/')}/chat/completions",
            actual_timeout,
            elapsed,
            exc_info=True,
        )
        raise ModelError(
            f"VLM request failed ({type(exc).__name__}): {exc!r} url={base_url.rstrip('/')}/chat/completions",
            model_name=model_name,
        ) from exc

    elapsed = time.perf_counter() - start_ts
    output_chars = 0
    finish_reason = ""
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if choices:
        choice0 = choices[0] if isinstance(choices[0], dict) else {}
        finish_reason = str(choice0.get("finish_reason") or "")
        out_msg = choice0.get("message") or {}
        out_text = out_msg.get("content", "")
        if isinstance(out_text, list):
            out_text = "\n".join(
                part.get("text", "")
                for part in out_text
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            )
        output_chars = len(out_text or "")
    logger.info(
        "VLM request done: model=%s elapsed=%.2fs output_chars=%d finish_reason=%s",
        model_name,
        elapsed,
        output_chars,
        finish_reason or "unknown",
    )
    if not choices:
        raise ModelError(
            f"No VLM choices in response: {payload}",
            model_name=model_name,
        )
    message = choices[0].get("message") or {}
    content_text = message.get("content", "")
    if isinstance(content_text, list):
        text_parts = [
            part.get("text", "")
            for part in content_text
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        ]
        content_text = "\n".join(text_parts)
    if not isinstance(content_text, str) or not content_text.strip():
        raise ModelError(
            f"Empty VLM response: {payload}",
            model_name=model_name,
        )
    return content_text.strip()
