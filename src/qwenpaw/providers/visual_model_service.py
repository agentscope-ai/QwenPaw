# -*- coding: utf-8 -*-
"""Visual model fallback when the primary model is text-only."""

from __future__ import annotations

import base64
import hashlib
import logging
import mimetypes
import time
from collections import OrderedDict
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from agentscope.message import DataBlock, Msg, TextBlock, URLSource

from ..config.config import ModelSlotConfig

logger = logging.getLogger(__name__)

_DEFAULT_PROMPT = (
    "Carefully observe this image and provide a concise, accurate "
    "description of the main content, including scenes, objects, people, "
    "text, and other key information. Keep the final description under "
    "about 150 words. Output only the description text, nothing else."
)
_TX_CACHE: OrderedDict[str, str] = OrderedDict()
_TX_FAIL_CACHE: OrderedDict[str, float] = OrderedDict()
_TX_CACHE_MAX = 128
_TX_FAIL_TTL_SECONDS = 60.0
_VISUAL_ACQUIRE_TIMEOUT_CAP = 20.0
_MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024
_VISUAL_FALLBACK_SUFFIX = " (visual fallback)"


def _safe_attr(obj: Any, name: str) -> Any:
    """Read ``name`` from a dict-like or attribute-bearing object.

    ``ChatResponse`` is a ``dict`` subclass (DictMixin), so the dict path
    is required for model responses. Message blocks are pydantic models.
    """
    if isinstance(obj, dict):
        return obj.get(name)
    try:
        return getattr(obj, name, None)
    except TypeError:
        return None


def _block_type_name(block: Any) -> str | None:
    """Return ``image`` or ``video`` for a 2.0 ``DataBlock``."""
    if getattr(block, "type", None) != "data":
        return None
    source = getattr(block, "source", None)
    mt = getattr(source, "media_type", "") or ""
    if mt.startswith("image/"):
        return "image"
    if mt.startswith("video/"):
        return "video"
    return None


def _block_source_dict(block: Any) -> dict | None:
    """Normalize a ``DataBlock`` source for URL resolution and caching."""
    if getattr(block, "type", None) != "data":
        return None
    source = getattr(block, "source", None)
    if source is None:
        return None
    stype = getattr(source, "type", None)
    mime = getattr(source, "media_type", None) or None
    if stype == "url":
        return {
            "type": "url",
            "url": str(getattr(source, "url", "") or ""),
            "media_type": mime,
        }
    if stype == "base64":
        return {
            "type": "base64",
            "data": getattr(source, "data", "") or "",
            "media_type": mime,
        }
    return None


def _tool_result_output(block: Any) -> list | None:
    if getattr(block, "type", None) != "tool_result":
        return None
    output = getattr(block, "output", None)
    return output if isinstance(output, list) else None


def _msg_has_media(msg: Any) -> bool:
    if not isinstance(msg, Msg) or not isinstance(msg.content, list):
        return False
    for block in msg.content:
        if _block_type_name(block):
            return True
        output = _tool_result_output(block)
        if output:
            for item in output:
                if _block_type_name(item):
                    return True
    return False


def _local_path(url: str) -> Path | None:
    if not url or url.startswith(("http://", "https://", "data:")):
        return None
    try:
        if url.lower().startswith("file:"):
            s = unquote(url.removeprefix("file://"))
            if len(s) >= 3 and s[0] == "/" and s[1].isalpha() and s[2] == ":":
                s = s[1:]
            return Path(s).resolve()
        return Path(url).resolve()
    except Exception:
        return None


def _local_file_data_url(path: Path, media_type: str) -> str | None:
    if not path.is_file():
        return None
    if path.stat().st_size > _MAX_FILE_SIZE_BYTES:
        logger.warning(
            "Visual fallback: skipping oversized %s at '%s'",
            media_type,
            path,
        )
        return None
    mime, _ = mimetypes.guess_type(str(path))
    mime = mime or ("image/jpeg" if media_type == "image" else "video/mp4")
    data = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{data}"


def _media_url(source: dict, media_type: str) -> str | None:
    kind = source.get("type", "")
    if kind == "url":
        url = source.get("url", "")
        if url.startswith(("http://", "https://", "data:")):
            return url
        local = _local_path(url)
        return _local_file_data_url(local, media_type) if local else None
    if kind == "base64":
        data = source.get("data", "")
        if not data:
            return None
        mime = source.get("media_type") or (
            "image/jpeg" if media_type == "image" else "video/mp4"
        )
        return f"data:{mime};base64,{data}"
    return None


def _first_block_text(content: list) -> str:
    for item in content:
        text = getattr(item, "text", None)
        if isinstance(text, str) and text:
            return text
    return ""


def _response_text(response: Any) -> str:
    """Extract assistant text from a ``ChatResponse`` (dict mixin)."""
    if not response:
        return ""
    content = _safe_attr(response, "content")
    if isinstance(content, list):
        return _first_block_text(content)
    return ""


def _media_data_block(
    url: str,
    media_type: str,
    *,
    mime: str | None = None,
) -> DataBlock:
    if not mime:
        if url.startswith("data:"):
            mime = url.split(";", 1)[0].removeprefix("data:")
        else:
            mime, _ = mimetypes.guess_type(url)
    if not mime:
        mime = "image/jpeg" if media_type == "image" else "video/mp4"
    return DataBlock(source=URLSource(url=url, media_type=mime))


def _usage_tokens(usage: Any) -> tuple[int, int]:
    if usage is None:
        return 0, 0
    pt = getattr(usage, "input_tokens", None) or 0
    ct = getattr(usage, "output_tokens", None) or 0
    return int(pt or 0), int(ct or 0)


def _record_visual_usage(
    provider_id: str,
    model_name: str,
    usage: Any,
) -> None:
    pt, ct = _usage_tokens(usage)
    if pt <= 0 and ct <= 0:
        return
    from datetime import date, datetime, timezone

    from ..token_usage import _UsageEvent, get_token_usage_manager

    get_token_usage_manager().enqueue(
        _UsageEvent(
            provider_id=provider_id,
            model_name=f"{model_name}{_VISUAL_FALLBACK_SUFFIX}",
            prompt_tokens=pt,
            completion_tokens=ct,
            date_str=date.today().isoformat(),
            now_iso=datetime.now(tz=timezone.utc).isoformat(
                timespec="seconds",
            ),
        ),
    )


def _retry_configs_from_running(
    running: Any,
) -> tuple[Any, Any]:
    """Build visual-call retry/rate-limit configs (fail-fast vs primary)."""
    from .retry_chat_model import RateLimitConfig, RetryConfig

    return (
        RetryConfig(
            enabled=True,
            max_retries=1,
            backoff_base=running.llm_backoff_base,
            backoff_cap=running.llm_backoff_cap,
        ),
        RateLimitConfig(
            max_concurrent=running.llm_max_concurrent,
            max_qpm=running.llm_max_qpm,
            pause_seconds=running.llm_rate_limit_pause,
            jitter_range=running.llm_rate_limit_jitter,
            acquire_timeout=min(
                float(running.llm_acquire_timeout),
                _VISUAL_ACQUIRE_TIMEOUT_CAP,
            ),
        ),
    )


def _visual_retry_configs(running: Any | None) -> tuple[Any, Any]:
    """Fail-fast retry/rate-limit configs; fall back when running is absent."""
    if running is not None:
        return _retry_configs_from_running(running)
    from .retry_chat_model import RateLimitConfig, RetryConfig

    return (
        RetryConfig(enabled=True, max_retries=1),
        RateLimitConfig(acquire_timeout=_VISUAL_ACQUIRE_TIMEOUT_CAP),
    )


def _cache_key(
    slot: ModelSlotConfig,
    source: dict,
    media_type: str,
) -> str:
    if source.get("type") == "url":
        raw = source.get("url", "")
    else:
        raw = source.get("data", "")
    digest = hashlib.sha256(str(raw).encode()).hexdigest()
    return f"{slot.provider_id}:{slot.model}:{digest}:{media_type}"


def _remember_success(cache_key: str, text: str) -> None:
    _TX_FAIL_CACHE.pop(cache_key, None)
    _TX_CACHE[cache_key] = text
    _TX_CACHE.move_to_end(cache_key)
    if len(_TX_CACHE) > _TX_CACHE_MAX:
        _TX_CACHE.popitem(last=False)


def _remember_failure(cache_key: str) -> None:
    _TX_FAIL_CACHE[cache_key] = time.monotonic()
    _TX_FAIL_CACHE.move_to_end(cache_key)
    if len(_TX_FAIL_CACHE) > _TX_CACHE_MAX:
        _TX_FAIL_CACHE.popitem(last=False)


def _recently_failed(cache_key: str) -> bool:
    failed_at = _TX_FAIL_CACHE.get(cache_key)
    if failed_at is None:
        return False
    if time.monotonic() - failed_at > _TX_FAIL_TTL_SECONDS:
        _TX_FAIL_CACHE.pop(cache_key, None)
        return False
    _TX_FAIL_CACHE.move_to_end(cache_key)
    return True


def _is_multimodal_fallback_hint(block: Any) -> bool:
    """True for main's view_media multimodal-unsupported text hint."""
    if getattr(block, "type", None) != "text":
        return False
    text = getattr(block, "text", None)
    if not isinstance(text, str):
        return False
    lowered = text.lower()
    return (
        text.startswith("[Note:")
        and "multimodal input" in lowered
        and "cannot analyze" in lowered
    )


def _wrap_visual_chat_model(
    chat_model: Any,
    provider_id: str,
    *,
    running: Any | None = None,
) -> Any:
    """Apply the same Retry/RateLimit wrapper used for the primary model."""
    from .retry_chat_model import RetryChatModel

    # Collapse agentscope's inner retry loop; RetryChatModel owns retries.
    if hasattr(chat_model, "max_retries"):
        chat_model.max_retries = 0
    # Used by RetryChatModel.model_key for rate-limiter bucketing.
    if getattr(chat_model, "_provider_id", None) is None:
        # pylint: disable=protected-access
        chat_model._provider_id = provider_id

    retry_config, rate_limit_config = _visual_retry_configs(running)
    return RetryChatModel(
        chat_model,
        retry_config=retry_config,
        rate_limit_config=rate_limit_config,
    )


def _is_async_iterable(response: Any) -> bool:
    """True for async generators; safe on ``ChatResponse`` (dict mixin)."""
    # ``hasattr`` / ``getattr`` on DictMixin can raise KeyError for missing
    # keys, so inspect the type instead of the instance.
    aiter_fn = getattr(type(response), "__aiter__", None)
    return callable(aiter_fn)


async def _consume_transcription_response(
    response: Any,
) -> tuple[str, Any]:
    """Return ``(text, usage)`` from a streaming or non-streaming response."""
    last_usage: Any = None
    if _is_async_iterable(response):
        text = ""
        async for chunk in response:
            part = _response_text(chunk)
            if part:
                text = part
            usage = _safe_attr(chunk, "usage")
            if usage is not None:
                last_usage = usage
        return text.strip(), last_usage
    return _response_text(response).strip(), _safe_attr(response, "usage")


async def _invoke_visual_transcription(
    source: dict,
    slot: ModelSlotConfig,
    media_type: str,
    *,
    running: Any | None = None,
) -> str | None:
    """Call the visual model once; return transcription text or ``None``."""
    url = _media_url(source, media_type)
    if not url:
        logger.warning(
            "Visual fallback: cannot resolve %s for %s/%s",
            media_type,
            slot.provider_id,
            slot.model,
        )
        return None

    from .provider_manager import ProviderManager

    provider = ProviderManager.get_instance().get_provider(slot.provider_id)
    if not provider:
        return None
    chat_model = _wrap_visual_chat_model(
        provider.get_chat_model_instance(slot.model),
        slot.provider_id,
        running=running,
    )
    messages = [
        Msg(
            name="user",
            role="user",
            content=[
                TextBlock(type="text", text=_DEFAULT_PROMPT),
                _media_data_block(
                    url,
                    media_type,
                    mime=source.get("media_type"),
                ),
            ],
        ),
    ]
    try:
        text, last_usage = await _consume_transcription_response(
            await chat_model(messages),
        )
        _record_visual_usage(slot.provider_id, slot.model, last_usage)
    except Exception as exc:
        logger.warning(
            "Visual fallback: %s/%s call failed: %s",
            slot.provider_id,
            slot.model,
            exc,
        )
        return None
    if not text:
        logger.warning(
            "Visual fallback: %s/%s returned empty transcription",
            slot.provider_id,
            slot.model,
        )
        return None
    return text


async def _transcribe(
    source: dict,
    slot: ModelSlotConfig,
    media_type: str,
    *,
    running: Any | None = None,
) -> str | None:
    cache_key = _cache_key(slot, source, media_type)
    if cache_key in _TX_CACHE:
        _TX_CACHE.move_to_end(cache_key)
        return _TX_CACHE[cache_key]
    if _recently_failed(cache_key):
        return None

    text = await _invoke_visual_transcription(
        source,
        slot,
        media_type,
        running=running,
    )
    if text is None:
        _remember_failure(cache_key)
        return None

    _remember_success(cache_key, text)
    logger.info(
        "Visual fallback: transcribed %s via %s/%s",
        media_type,
        slot.provider_id,
        slot.model,
    )
    return text


async def _replace_block(
    block: Any,
    slot: ModelSlotConfig,
    *,
    running: Any | None = None,
) -> Any | None:
    media_type = _block_type_name(block)
    if not media_type:
        return None
    source = _block_source_dict(block)
    if not source:
        return None
    desc = await _transcribe(source, slot, media_type, running=running)
    if not desc:
        # Keep the original media block so downstream strip/normalization
        # can handle it the same way as when visual fallback is absent.
        return None
    return TextBlock(
        type="text",
        text=f"[{media_type.capitalize()} description: {desc}]",
    )


async def _rewrite_content(
    content: list,
    slot: ModelSlotConfig,
    *,
    running: Any | None = None,
) -> list:
    out = []
    for block in content:
        replaced = await _replace_block(block, slot, running=running)
        if replaced:
            out.append(replaced)
            continue
        output = _tool_result_output(block)
        if output is not None:
            new_output = []
            replaced_media = False
            for item in output:
                sub = await _replace_block(item, slot, running=running)
                if sub is not None:
                    replaced_media = True
                    new_output.append(sub)
                else:
                    new_output.append(item)
            if replaced_media:
                new_output = [
                    item
                    for item in new_output
                    if not _is_multimodal_fallback_hint(item)
                ]
            block.output = new_output
            out.append(block)
            continue
        out.append(block)
    return out


async def apply_visual_fallback_to_messages(msgs: list) -> list:
    """Transcribe media blocks before sending to a text-only primary model."""
    from ..agents.prompt import get_active_model_supports_multimodal
    from ..app.agent_context import get_current_agent_id
    from ..config.config import load_agent_config

    # Native multimodal models never need transcription; skip history scan.
    if get_active_model_supports_multimodal():
        return msgs

    media_indices = [i for i, m in enumerate(msgs) if _msg_has_media(m)]
    if not media_indices:
        return msgs

    try:
        agent_id = get_current_agent_id()
        if not agent_id:
            return msgs
        cfg = load_agent_config(agent_id)
        slot = cfg.visual_model
        if not slot or not slot.provider_id or not slot.model:
            return msgs
        running = cfg.running
    except Exception:
        return msgs

    logger.info(
        "Transcribing media blocks using visual model: %s/%s",
        slot.provider_id,
        slot.model,
    )
    out = list(msgs)
    for i in media_indices:
        msg = msgs[i]
        copied = Msg.from_dict(deepcopy(msg.to_dict()))
        copied.content = await _rewrite_content(
            copied.content,
            slot,
            running=running,
        )
        out[i] = copied
    return out
