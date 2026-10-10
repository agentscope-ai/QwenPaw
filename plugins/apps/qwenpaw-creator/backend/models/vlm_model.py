# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long,too-many-branches,too-many-statements
"""VLM wrapper for multimodal understanding.

Supports three API protocols:

* OpenAI-compatible (``/chat/completions``) — DashScope Bailian and most
  providers. Image inputs use ``image_url`` content parts and video inputs
  use ``video_url`` content parts. Local files are transported through the
  provider-bound channel right before the request: DashScope models use the
  official model-bound temporary upload (``oss://`` URL, 48h TTL, <=1GB)
  resolved via the ``X-DashScope-OssResourceResolve: enable`` header, while
  other OpenAI-compatible providers fall back to inline
  ``data:<mime>;base64,...`` URLs.
* Anthropic Messages (``/v1/messages``) — Anthropic Claude and MiniMax.
  Images use ``image`` content blocks with a ``source`` object; videos are
  not supported by the Anthropic Messages API.
* Google Gemini (``/v1beta/models/{model}:generateContent``) — Google
  Gemini. Media uses ``inline_data`` parts; remote media is downloaded
  and inlined because Gemini's ``file_data.file_uri`` only accepts
  Files API / GCS resources, not arbitrary public URLs.
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
from services.runtime_files.safe_remote_download import (
    SafeRemoteDownloadError,
    open_safe_remote_stream,
)
from utils.exceptions import ModelError, redact_url, upstream_status_hint
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


def _inline_base64(path: Path, fallback_mime: str) -> tuple[str, str]:
    """Return ``(mime_type, base64_data)`` for a local file."""
    size = path.stat().st_size
    max_bytes = model_config.get_vlm_max_inline_bytes()
    if size > max_bytes:
        raise ModelError(
            f"VLM local media inline size limit exceeded: {path.name} is {size} bytes, limit is {max_bytes}",
            model_name=model_config.get_vlm_model_name(),
        )
    mime = _mime_for_path(path, fallback_mime)
    data = base64.b64encode(path.read_bytes()).decode("utf-8")
    return mime, data


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


def uses_dashscope_transport() -> bool:
    """True when the configured VLM transports local media through the
    DashScope model-bound temporary OSS upload (48h TTL, <=1GB) instead
    of inline Base64 data URLs."""
    return _is_dashscope_provider(model_config.get_vlm_base_url())


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


# ── Protocol helpers ─────────────────────────────────────────────────────────
# Protocol classification lives in ``models.config`` so every module agrees
# on which gateway speaks which wire format.


def _vlm_url(base_url: str, protocol: str, model_name: str) -> str:
    return model_config.chat_url_for(base_url, protocol, model_name)


def _is_gemini_file_uri(url: str) -> bool:
    """True for URIs the Gemini ``file_data.file_uri`` field accepts.

    Only Files API resources and GCS URIs are valid; arbitrary public
    URLs are rejected by the API with INVALID_ARGUMENT.
    """
    return (
        url.startswith("gs://") or "generativelanguage.googleapis.com" in url
    )


def _download_remote_media_sync(
    url: str,
    fallback_mime: str,
    timeout: float,
) -> tuple[str, str]:
    """Safely download remote media and return ``(mime_type, base64_data)``.

    Gemini only accepts inline media or Files API resources, so remote
    references must be downloaded and inlined before the request.
    """
    max_bytes = model_config.get_vlm_max_inline_bytes()
    with open_safe_remote_stream(
        url,
        max_bytes=max_bytes,
        timeout=timeout,
    ) as remote:
        data = b"".join(remote.iter_raw())
        if not data:
            raise SafeRemoteDownloadError("远程 URL 返回了空内容")
        content_type = remote.media_type
        final_path = urlparse(remote.final_url).path
    mime = (
        content_type
        if content_type.startswith(("image/", "video/"))
        else mimetypes.guess_type(final_path)[0] or fallback_mime
    )
    return mime, base64.b64encode(data).decode("utf-8")


async def _download_remote_media(
    url: str,
    fallback_mime: str,
    timeout: float,
) -> tuple[str, str]:
    """Run the shared synchronous safe downloader off the event loop."""

    return await asyncio.to_thread(
        _download_remote_media_sync,
        url,
        fallback_mime,
        timeout,
    )


# ── Response parsers ─────────────────────────────────────────────────────────


def _parse_openai_response(payload: dict, model_name: str) -> str:
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not choices:
        raise ModelError(
            f"No VLM choices in response: {payload}",
            model_name=model_name,
        )
    choice0 = choices[0] if isinstance(choices[0], dict) else {}
    out_msg = choice0.get("message") or {}
    content_text = out_msg.get("content", "")
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


def _parse_anthropic_response(payload: dict, model_name: str) -> str:
    content_blocks = payload.get("content") or []
    text_parts = [
        block.get("text", "")
        for block in content_blocks
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    content = "\n".join(text_parts)
    if not content.strip():
        raise ModelError(
            f"Empty VLM response: {payload}",
            model_name=model_name,
        )
    return content.strip()


def _parse_gemini_response(payload: dict, model_name: str) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:
        raise ModelError(
            f"No VLM candidates in response: {payload}",
            model_name=model_name,
        )
    candidate = candidates[0] if isinstance(candidates[0], dict) else {}
    content_obj = candidate.get("content") or {}
    parts = content_obj.get("parts") or []
    text_parts = [
        part.get("text", "")
        for part in parts
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    ]
    content = "\n".join(text_parts)
    if not content.strip():
        raise ModelError(
            f"Empty VLM response: {payload}",
            model_name=model_name,
        )
    return content.strip()


# ── Content converters ───────────────────────────────────────────────────────


def _convert_to_anthropic_content(
    openai_content: list[dict],
) -> list[dict]:
    """Convert OpenAI-format content parts to Anthropic Messages format.

    OpenAI ``image_url`` parts become Anthropic ``image`` blocks. Anthropic
    Messages does not accept video input, so callers must fail explicitly
    rather than allowing a visually ungrounded response to look successful.
    """
    result: list[dict] = []
    for part in openai_content:
        if not isinstance(part, dict):
            result.append({"type": "text", "text": str(part)})
            continue
        part_type = part.get("type", "")
        if part_type == "text":
            result.append({"type": "text", "text": part.get("text", "")})
        elif part_type == "image_url":
            image_obj = part.get("image_url") or {}
            url = str(image_obj.get("url") or "")
            if url.startswith("data:"):
                # data:<mime>;base64,<data>
                header, _, b64_data = url.partition(",")
                mime = (
                    header.split(":", 1)[1].split(";")[0]
                    if ":" in header
                    else "image/png"
                )
                result.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime,
                            "data": b64_data,
                        },
                    },
                )
            else:
                result.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "url",
                            "url": url,
                        },
                    },
                )
        elif part_type == "video_url":
            raise ModelError(
                "Anthropic Messages protocol does not support video input; "
                "configure a video-capable VLM protocol or extract frames "
                "before analysis",
                model_name=model_config.get_vlm_model_name(),
                retryable=False,
            )
        else:
            result.append({"type": "text", "text": str(part)})
    return result


def _convert_to_gemini_content(
    openai_content: list[dict],
) -> list[dict]:
    """Convert OpenAI-format content parts to Gemini ``parts`` format."""
    result: list[dict] = []
    for part in openai_content:
        if not isinstance(part, dict):
            result.append({"text": str(part)})
            continue
        part_type = part.get("type", "")
        if part_type == "text":
            result.append({"text": part.get("text", "")})
        elif part_type == "image_url":
            image_obj = part.get("image_url") or {}
            url = str(image_obj.get("url") or "")
            if url.startswith("data:"):
                header, _, b64_data = url.partition(",")
                mime = (
                    header.split(":", 1)[1].split(";")[0]
                    if ":" in header
                    else "image/png"
                )
                result.append(
                    {
                        "inline_data": {"mime_type": mime, "data": b64_data},
                    },
                )
            else:
                # ``file_uri`` only accepts Files API resources
                # (``https://generativelanguage.googleapis.com/v1beta/files/…``)
                # or ``gs://`` URIs. ``_call_gemini_vlm`` downloads and
                # inlines every other remote URL before conversion, so any
                # plain URL reaching here is a programming error.
                if _is_gemini_file_uri(url):
                    result.append(
                        {
                            "file_data": {
                                "mime_type": (
                                    "video/mp4"
                                    if part_type == "video_url"
                                    else "image/png"
                                ),
                                "file_uri": url,
                            },
                        },
                    )
                else:
                    raise ModelError(
                        f"Gemini cannot reference remote media directly: {url}. "
                        "Media must be inlined before conversion.",
                    )
        elif part_type == "video_url":
            video_obj = part.get("video_url") or {}
            url = str(video_obj.get("url") or "")
            if url.startswith("data:"):
                header, _, b64_data = url.partition(",")
                mime = (
                    header.split(":", 1)[1].split(";")[0]
                    if ":" in header
                    else "video/mp4"
                )
                result.append(
                    {
                        "inline_data": {"mime_type": mime, "data": b64_data},
                    },
                )
            else:
                if _is_gemini_file_uri(url):
                    result.append(
                        {
                            "file_data": {
                                "mime_type": "video/mp4",
                                "file_uri": url,
                            },
                        },
                    )
                else:
                    raise ModelError(
                        f"Gemini cannot reference remote media directly: {url}. "
                        "Media must be inlined before conversion.",
                    )
        else:
            result.append({"text": str(part)})
    return result


# ─ Main entry point ─────────────────────────────────────────────────────────


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
    protocol = model_config.get_vlm_protocol()
    # Anthropic and Gemini gateways always authenticate; OpenAI-compatible
    # gateways may serve free keyless models (e.g. OpenCode Zen), so an
    # empty key is only an error for protocols that require one.
    if not api_key and model_config.protocol_requires_api_key(protocol):
        raise ModelError(
            "VLM API key 未配置：协议 "
            f"'{protocol}' 必须提供 API Key（模型: "
            f"'{model_name or '未配置'}'，Base URL: "
            f"'{base_url or '未配置'}'）。请在 Creator 模型配置弹窗中填写 "
            "VLM API Key，或配置 creator_vlm_model.api_key / VLM_API_KEY / "
            "DASHSCOPE_API_KEY / TEXT_API_KEY 环境变量；若使用免 Key 的"
            "免费模型（如 OpenCode Zen *-free），请选择 OpenAI 兼容协议。",
            model_name=model_name,
            retryable=False,
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

    media_parts = [
        p
        for p in content
        if isinstance(p, dict) and p.get("type") in ("image_url", "video_url")
    ]
    video_count = sum(1 for p in media_parts if p.get("type") == "video_url")
    image_count = len(media_parts) - video_count
    logger.info(
        "VLM request start: model=%s protocol=%s images=%d videos=%d max_tokens=%d",
        model_name,
        protocol or "openai",
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
        if model_config.is_anthropic_protocol(protocol):
            payload = await _call_anthropic_vlm(
                content,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=actual_timeout,
                api_key=api_key,
                base_url=base_url,
                model_name=model_name,
            )
        elif model_config.is_gemini_protocol(protocol):
            payload = await _call_gemini_vlm(
                content,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=actual_timeout,
                api_key=api_key,
                base_url=base_url,
                model_name=model_name,
            )
        else:
            payload = await _call_openai_vlm(
                content,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=actual_timeout,
                api_key=api_key,
                base_url=base_url,
                model_name=model_name,
            )
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
            f"VLM 请求失败 [protocol={protocol} model={model_name} "
            f"endpoint={redact_url(_vlm_url(base_url, protocol, model_name))}] "
            f"HTTP {exc.response.status_code}: "
            f"{exc.response.text[:500] or '上游未返回响应体'}"
            + (
                f"。{upstream_status_hint(exc.response.status_code)}"
                if upstream_status_hint(exc.response.status_code)
                else ""
            ),
            model_name=model_name,
            retryable=exc.response.status_code >= 500,
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
        request_url = _vlm_url(base_url, protocol, model_name)
        logger.error(
            "VLM request failed: type=%s repr=%r url=%s timeout=%s elapsed=%.2fs",
            type(exc).__name__,
            exc,
            request_url,
            actual_timeout,
            elapsed,
            exc_info=True,
        )
        raise ModelError(
            f"VLM 请求失败 [protocol={protocol} model={model_name}] "
            f"({type(exc).__name__}): {exc!r} "
            f"endpoint={redact_url(request_url)} timeout={actual_timeout}s",
            model_name=model_name,
        ) from exc

    elapsed = time.perf_counter() - start_ts
    # Parse response based on protocol
    if model_config.is_anthropic_protocol(protocol):
        content_text = _parse_anthropic_response(payload, model_name)
    elif model_config.is_gemini_protocol(protocol):
        content_text = _parse_gemini_response(payload, model_name)
    else:
        content_text = _parse_openai_response(payload, model_name)

    finish_reason = ""
    if isinstance(payload, dict):
        if model_config.is_anthropic_protocol(protocol):
            finish_reason = str(payload.get("stop_reason") or "")
        elif model_config.is_gemini_protocol(protocol):
            candidates = payload.get("candidates") or []
            if candidates and isinstance(candidates[0], dict):
                finish_reason = str(candidates[0].get("finishReason") or "")
        else:
            choices = payload.get("choices") or []
            if choices and isinstance(choices[0], dict):
                finish_reason = str(choices[0].get("finish_reason") or "")

    logger.info(
        "VLM request done: model=%s elapsed=%.2fs output_chars=%d finish_reason=%s",
        model_name,
        elapsed,
        len(content_text),
        finish_reason or "unknown",
    )
    return content_text


# ── Per-protocol callers ─────────────────────────────────────────────────────


async def _call_openai_vlm(
    content: list[dict],
    *,
    system_prompt: str,
    temperature: float,
    max_tokens: int,
    timeout: float,
    api_key: str,
    base_url: str,
    model_name: str,
) -> dict:
    """OpenAI-compatible VLM request (DashScope, DeepSeek, etc.)."""
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
    headers: dict = {
        "Content-Type": "application/json",
        **(
            {"X-DashScope-OssResourceResolve": "enable"}
            if uses_temp_oss
            else {}
        ),
    }
    # Free-tier gateways (e.g. OpenCode Zen ``*-free``) accept requests
    # without an Authorization header; an empty Bearer value would be
    # rejected as an invalid key.
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with model_slot("vlm"):
            response = await client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=body,
            )
    response.raise_for_status()
    return response.json()


async def _call_anthropic_vlm(
    content: list[dict],
    *,
    system_prompt: str,
    temperature: float,
    max_tokens: int,
    timeout: float,
    api_key: str,
    base_url: str,
    model_name: str,
) -> dict:
    """Anthropic Messages API VLM request (Claude, MiniMax)."""
    if any(
        isinstance(item, dict) and item.get("type") == "video_url"
        for item in content
    ):
        raise ModelError(
            "Anthropic Messages protocol does not support video input; "
            "configure a video-capable VLM protocol or extract frames "
            "before analysis",
            model_name=model_name,
            retryable=False,
        )
    # Transport local media to inline base64 for Anthropic format
    provider_content: list[dict] = []
    for item in content:
        normalized = dict(item)
        normalized.pop("max_frames", None)
        normalized.pop("max_frame", None)
        part_type = normalized.get("type", "")
        if part_type in ("image_url", "video_url"):
            media_obj = normalized.get(part_type) or {}
            url = str(media_obj.get("url") or "")
            local_path = _local_path_from_url(url)
            if local_path is not None:
                fallback = "image/png"
                mime, b64_data = await asyncio.to_thread(
                    _inline_base64,
                    local_path,
                    fallback,
                )
                normalized = {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64_data}"},
                }
            # Remote URLs pass through as-is; the converter handles them
        provider_content.append(normalized)

    anthropic_content = _convert_to_anthropic_content(provider_content)
    body: dict = {
        "model": model_name,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": anthropic_content}],
    }
    if system_prompt.strip():
        body["system"] = system_prompt.strip()
    if temperature > 0:
        body["temperature"] = temperature

    headers: dict = {
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
    }
    if api_key:
        headers["x-api-key"] = api_key
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with model_slot("vlm"):
            response = await client.post(
                f"{base_url.rstrip('/')}/v1/messages",
                headers=headers,
                json=body,
            )
    response.raise_for_status()
    return response.json()


async def _call_gemini_vlm(
    content: list[dict],
    *,
    system_prompt: str,
    temperature: float,
    max_tokens: int,
    timeout: float,
    api_key: str,
    base_url: str,
    model_name: str,
) -> dict:
    """Google Gemini VLM request."""
    # Transport local and remote media to inline base64 for Gemini format.
    # ``file_uri`` only accepts Files API / GCS resources, so remote URLs
    # are downloaded and inlined here.
    provider_content: list[dict] = []
    for item in content:
        normalized = dict(item)
        normalized.pop("max_frames", None)
        normalized.pop("max_frame", None)
        part_type = normalized.get("type", "")
        if part_type in ("image_url", "video_url"):
            media_obj = normalized.get(part_type) or {}
            url = str(media_obj.get("url") or "")
            fallback = "video/mp4" if part_type == "video_url" else "image/png"
            local_path = _local_path_from_url(url)
            if local_path is not None:
                mime, b64_data = await asyncio.to_thread(
                    _inline_base64,
                    local_path,
                    fallback,
                )
                normalized = {
                    "type": part_type,
                    part_type: {"url": f"data:{mime};base64,{b64_data}"},
                }
            elif (
                url
                and not url.startswith("data:")
                and not _is_gemini_file_uri(url)
            ):
                try:
                    mime, b64_data = await _download_remote_media(
                        url,
                        fallback,
                        timeout,
                    )
                except SafeRemoteDownloadError as exc:
                    raise ModelError(
                        f"VLM remote media download rejected: {exc}",
                        model_name=model_name,
                        retryable=False,
                    ) from exc
                except httpx.HTTPError as exc:
                    raise ModelError(
                        f"VLM remote media download failed: {exc}",
                        model_name=model_name,
                    ) from exc
                normalized = {
                    "type": part_type,
                    part_type: {"url": f"data:{mime};base64,{b64_data}"},
                }
        provider_content.append(normalized)

    gemini_parts = _convert_to_gemini_content(provider_content)
    contents: list[dict] = [{"role": "user", "parts": gemini_parts}]
    body: dict = {
        "contents": contents,
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    if system_prompt.strip():
        body["systemInstruction"] = {
            "parts": [{"text": system_prompt.strip()}],
        }
    if temperature > 0:
        body["generationConfig"]["temperature"] = temperature

    url = f"{base_url.rstrip('/')}/v1beta/models/{model_name}:generateContent"
    if api_key:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}key={api_key}"

    async with httpx.AsyncClient(timeout=timeout) as client:
        async with model_slot("vlm"):
            response = await client.post(
                url,
                headers={"Content-Type": "application/json"},
                json=body,
            )
    response.raise_for_status()
    return response.json()
