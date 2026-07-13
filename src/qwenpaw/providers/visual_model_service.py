# -*- coding: utf-8 -*-
"""Visual model fallback when the primary model is text-only."""

from __future__ import annotations

import base64
import hashlib
import logging
import mimetypes
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
    "text, and other key information. Output only the description text, "
    "nothing else."
)
_TX_CACHE: OrderedDict[str, str] = OrderedDict()
_TX_CACHE_MAX = 128
_MEDIA = frozenset({"image", "video"})
_MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024
_VISUAL_FALLBACK_SUFFIX = " (visual fallback)"


def _safe_attr(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name)
    try:
        return getattr(obj, name, None)
    except (AttributeError, KeyError, TypeError):
        return None


def _block_type_name(block: Any) -> str | None:
    """Return ``image`` or ``video`` for dict or 2.0 DataBlock media."""
    if isinstance(block, dict):
        btype = block.get("type", "")
        return btype if btype in _MEDIA else None
    btype = getattr(block, "type", None)
    if btype in _MEDIA:
        return btype
    if btype == "data":
        source = getattr(block, "source", None)
        mt = getattr(source, "media_type", "") or ""
        if mt.startswith("image/"):
            return "image"
        if mt.startswith("video/"):
            return "video"
    return None


def _block_source_dict(block: Any) -> dict | None:
    """Normalize media block source for ``_transcribe``."""
    if isinstance(block, dict):
        btype = block.get("type", "")
        if btype not in _MEDIA:
            return None
        source = block.get("source")
        return source if isinstance(source, dict) else None
    if getattr(block, "type", None) == "data":
        source = getattr(block, "source", None)
        if source is None:
            return None
        return {"type": "url", "url": str(getattr(source, "url", ""))}
    return None


def _tool_result_output(block: Any) -> list | None:
    if _safe_attr(block, "type") != "tool_result":
        return None
    output = _safe_attr(block, "output")
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
        mime = "image/jpeg" if media_type == "image" else "video/mp4"
        return f"data:{mime};base64,{source.get('data', '')}"
    return None


def _first_block_text(content: list) -> str:
    for item in content:
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            return item["text"]
        inner = _safe_attr(item, "text")
        if isinstance(inner, str) and inner:
            return inner
    return ""


def _response_text(response: Any) -> str:
    if not response:
        return ""
    if isinstance(response, str):
        return response
    text = _safe_attr(response, "text")
    if isinstance(text, str) and text:
        return text
    content = _safe_attr(response, "content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return _first_block_text(content)
    return ""


def _media_data_block(url: str, media_type: str) -> DataBlock:
    mime, _ = mimetypes.guess_type(url)
    if url.startswith("data:"):
        mime = url.split(";", 1)[0].removeprefix("data:")
    if not mime:
        mime = "image/jpeg" if media_type == "image" else "video/mp4"
    return DataBlock(source=URLSource(url=url, media_type=mime))


def _usage_tokens(usage: Any) -> tuple[int, int]:
    if usage is None:
        return 0, 0
    if isinstance(usage, dict):
        pt = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
        ct = usage.get("output_tokens") or usage.get("completion_tokens") or 0
        return int(pt or 0), int(ct or 0)
    pt = (
        getattr(usage, "input_tokens", None)
        or getattr(usage, "prompt_tokens", None)
        or 0
    )
    ct = (
        getattr(usage, "output_tokens", None)
        or getattr(usage, "completion_tokens", None)
        or 0
    )
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
    from .retry_chat_model import RateLimitConfig, RetryConfig

    return (
        RetryConfig(
            enabled=running.llm_retry_enabled,
            max_retries=running.llm_max_retries,
            backoff_base=running.llm_backoff_base,
            backoff_cap=running.llm_backoff_cap,
        ),
        RateLimitConfig(
            max_concurrent=running.llm_max_concurrent,
            max_qpm=running.llm_max_qpm,
            pause_seconds=running.llm_rate_limit_pause,
            jitter_range=running.llm_rate_limit_jitter,
            acquire_timeout=running.llm_acquire_timeout,
        ),
    )


def get_visual_model_slot() -> ModelSlotConfig | None:
    """Return the current agent's visual-model slot, or ``None`` if unset."""
    try:
        from ..app.agent_context import get_current_agent_id
        from ..config.config import load_agent_config

        agent_id = get_current_agent_id()
        if not agent_id:
            return None
        slot = load_agent_config(agent_id).visual_model
        if not slot or not slot.provider_id or not slot.model:
            return None
        return slot
    except Exception:
        return None


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

    retry_config = None
    rate_limit_config = None
    if running is not None:
        retry_config, rate_limit_config = _retry_configs_from_running(running)

    return RetryChatModel(
        chat_model,
        retry_config=retry_config,
        rate_limit_config=rate_limit_config,
    )


async def _consume_transcription_response(
    response: Any,
) -> tuple[str, Any]:
    """Return ``(text, usage)`` from a streaming or non-streaming response."""
    last_usage: Any = None
    if hasattr(response, "__aiter__"):
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


async def _transcribe(
    source: dict,
    slot: ModelSlotConfig,
    media_type: str,
    *,
    running: Any | None = None,
) -> str | None:
    raw = source.get("url", "") if source.get("type") == "url" else str(source)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    cache_key = f"{slot.provider_id}:{slot.model}:{digest}:{media_type}"
    if cache_key in _TX_CACHE:
        _TX_CACHE.move_to_end(cache_key)
        return _TX_CACHE[cache_key]

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
                _media_data_block(url, media_type),
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

    _TX_CACHE[cache_key] = text
    if len(_TX_CACHE) > _TX_CACHE_MAX:
        _TX_CACHE.popitem(last=False)
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
            for item in output:
                sub = await _replace_block(item, slot, running=running)
                new_output.append(sub or item)
            if isinstance(block, dict):
                out.append({**block, "output": new_output})
            else:
                block.output = new_output
                out.append(block)
            continue
        out.append(block)
    return out


async def apply_visual_fallback_to_messages(msgs: list) -> list:
    """Transcribe media blocks before sending to a text-only primary model."""
    if not any(_msg_has_media(m) for m in msgs):
        return msgs

    from ..agents.prompt import get_active_model_supports_multimodal
    from ..app.agent_context import get_current_agent_id
    from ..config.config import load_agent_config

    if get_active_model_supports_multimodal():
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
    out = []
    for msg in msgs:
        if _msg_has_media(msg):
            copied = Msg.from_dict(deepcopy(msg.to_dict()))
            copied.content = await _rewrite_content(
                copied.content,
                slot,
                running=running,
            )
            out.append(copied)
        else:
            out.append(msg)
    return out
