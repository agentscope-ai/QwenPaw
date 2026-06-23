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
from typing import Any, Optional
from urllib.parse import unquote

from agentscope.message import Msg

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


def _msg_has_media(msg: Any) -> bool:
    if not isinstance(msg, Msg) or not isinstance(msg.content, list):
        return False
    for block in msg.content:
        if not isinstance(block, dict):
            continue
        if block.get("type") in _MEDIA:
            return True
        if block.get("type") == "tool_result":
            for item in block.get("output") or []:
                if isinstance(item, dict) and item.get("type") in _MEDIA:
                    return True
    return False


def _local_path(url: str) -> Optional[Path]:
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


def _local_file_data_url(path: Path, media_type: str) -> Optional[str]:
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


def _media_url(source: dict, media_type: str) -> Optional[str]:
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


def _response_text(response: Any) -> str:
    if isinstance(response, str):
        return response
    for name in ("text", "content"):
        val = (
            getattr(response, name, None)
            if not isinstance(response, dict)
            else response.get(name)
        )
        if isinstance(val, str) and val:
            return val
        if isinstance(val, list):
            for item in val:
                if isinstance(item, dict) and isinstance(
                    item.get("text"),
                    str,
                ):
                    return item["text"]
    return ""


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


async def _chat_text(
    model: Any,
    messages: list,
    *,
    provider_id: str = "",
    model_name: str = "",
) -> str:
    response = await model(messages)
    last_usage: Any = None
    if hasattr(response, "__aiter__"):
        text = ""
        async for chunk in response:
            part = _response_text(chunk)
            if part:
                text = part
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                last_usage = usage
        result = text.strip()
    else:
        last_usage = getattr(response, "usage", None)
        result = _response_text(response).strip()
    if provider_id and model_name:
        _record_visual_usage(provider_id, model_name, last_usage)
    return result


def _visual_model_slot(agent_id: str) -> Optional[ModelSlotConfig]:
    from ..config.config import load_agent_config

    cfg = load_agent_config(agent_id)
    slot = cfg.visual_model if cfg else None
    if not slot or not slot.provider_id or not slot.model:
        return None
    return slot


async def _transcribe(
    source: dict,
    slot: ModelSlotConfig,
    media_type: str,
) -> Optional[str]:
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
    chat_model = provider.get_chat_model_instance(slot.model)
    media_part = (
        {"type": "video_url", "video_url": {"url": url}}
        if media_type == "video"
        else {"type": "image_url", "image_url": {"url": url}}
    )
    messages = [
        {
            "role": "user",
            "content": [{"type": "text", "text": _DEFAULT_PROMPT}, media_part],
        },
    ]
    try:
        text = await _chat_text(
            chat_model,
            messages,
            provider_id=slot.provider_id,
            model_name=slot.model,
        )
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


async def _replace_block(block: dict, slot: ModelSlotConfig) -> Optional[dict]:
    btype, source = block.get("type", ""), block.get("source")
    if btype not in _MEDIA or not isinstance(source, dict):
        return None
    desc = (
        await _transcribe(source, slot, btype) or "(transcription unavailable)"
    )
    return {
        "type": "text",
        "text": f"[{btype.capitalize()} description: {desc}]",
    }


async def _rewrite_content(content: list, slot: ModelSlotConfig) -> list:
    out = []
    for block in content:
        if not isinstance(block, dict):
            out.append(block)
            continue
        replaced = await _replace_block(block, slot)
        if replaced:
            out.append(replaced)
            continue
        if block.get("type") == "tool_result" and isinstance(
            block.get("output"),
            list,
        ):
            new_output = []
            for item in block["output"]:
                sub = (
                    await _replace_block(item, slot)
                    if isinstance(item, dict)
                    else None
                )
                new_output.append(sub or item)
            out.append({**block, "output": new_output})
            continue
        out.append(block)
    return out


async def apply_visual_fallback_to_messages(msgs: list) -> list:
    """Transcribe media blocks before sending to a text-only primary model."""
    if not any(_msg_has_media(m) for m in msgs):
        return msgs

    from ..agents.prompt import get_active_model_supports_multimodal
    from ..app.agent_context import get_current_agent_id

    if get_active_model_supports_multimodal():
        return msgs

    try:
        agent_id = get_current_agent_id()
        slot = _visual_model_slot(agent_id) if agent_id else None
    except Exception:
        return msgs
    if not slot:
        return msgs

    logger.info(
        "Transcribing media blocks using visual model: %s/%s",
        slot.provider_id,
        slot.model,
    )
    out = []
    for msg in msgs:
        if isinstance(msg.content, list) and _msg_has_media(msg):
            copied = Msg.from_dict(deepcopy(msg.to_dict()))
            copied.content = await _rewrite_content(copied.content, slot)
            out.append(copied)
        else:
            out.append(msg)
    return out
