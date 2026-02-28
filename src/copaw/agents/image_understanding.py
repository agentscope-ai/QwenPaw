# -*- coding: utf-8 -*-
"""Media understanding prepass runner used by CoPawAgent.

Key improvements over initial version (OpenClaw-aligned):
- Converts file:// URL image blocks to inline base64 before VLM call
- Compresses large images to stay within API size limits
- Uses free-form description prompt instead of rigid JSON
"""

from __future__ import annotations

import base64
import io
import logging
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal
from urllib.parse import urlparse
from urllib.request import url2pathname

from agentscope.message import Msg, TextBlock

from .model_fallback import run_with_vlm_fallback
from .vision_prepass import build_vlm_prepass_prompt, normalize_vlm_prepass_output
from ..providers import ResolvedModelConfig

logger = logging.getLogger(__name__)

DecisionOutcome = Literal["success", "failed", "skipped", "disabled"]
MediaCapability = Literal["image", "audio", "video"]

_IMAGE_MAX_SIDE = 2000
_IMAGE_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
_IMAGE_QUALITY_STEPS = [85, 70, 50]


@dataclass
class MediaUnderstandingAttempt:
    provider_id: str
    model: str
    outcome: Literal["success", "failed", "skipped"]
    reason: str = ""


@dataclass
class MediaUnderstandingDecision:
    outcome: DecisionOutcome
    reason: str = ""
    selected_item_count: int = 0
    capability: MediaCapability = "image"
    attempts: list[MediaUnderstandingAttempt] = field(default_factory=list)


@dataclass
class MediaUnderstandingResult:
    analysis: str | None
    decision: MediaUnderstandingDecision
    used: ResolvedModelConfig | None = None


def get_last_message(msg: Msg | list[Msg] | None) -> Msg:
    if isinstance(msg, list):
        for item in reversed(msg):
            if isinstance(item, Msg):
                return item
    if isinstance(msg, Msg):
        return msg
    return Msg(
        name="user",
        role="user",
        content=[TextBlock(type="text", text="")],
    )


def extract_media_blocks(
    msg: Msg | list[Msg] | None,
    *,
    capability: MediaCapability,
) -> list[dict]:
    source = get_last_message(msg)
    blocks = source.content if isinstance(source.content, list) else []
    return [
        block
        for block in blocks
        if isinstance(block, dict) and block.get("type") == capability
    ]


def select_media_blocks_for_prepass(
    media_blocks: list[dict],
    *,
    mode: str = "first",
    max_items: int = 4,
) -> list[dict]:
    if max_items < 1:
        max_items = 1
    if mode != "all":
        return media_blocks[:1]
    return media_blocks[:max_items]


def _read_file_url(url: str) -> bytes | None:
    """Read a file:// URL or local path and return raw bytes.

    Handles both proper ``file:///C:/path`` and malformed ``file://C:\\path``
    variants common on Windows.
    """
    import re

    parsed = urlparse(url)
    local_path: Path | None = None

    if parsed.scheme == "file":
        try:
            local_path = Path(url2pathname(parsed.path))
        except Exception:
            pass

        if local_path is not None and not local_path.is_absolute():
            # Malformed Windows URL like file://C:\... gets parsed with
            # netloc='C:' and relative path.  Reconstruct from netloc+path.
            combined = (parsed.netloc or "") + (parsed.path or "")
            try:
                local_path = Path(url2pathname(combined))
            except Exception:
                pass

        if local_path is None or not local_path.is_absolute():
            # Last resort: strip the file:// prefix and use raw path
            raw = re.sub(r"^file:/{0,3}", "", url)
            local_path = Path(raw)

    elif parsed.scheme == "" and parsed.netloc == "":
        local_path = Path(url)
    else:
        return None

    try:
        return local_path.read_bytes()
    except Exception:
        logger.debug("Failed to read local file for base64 conversion: %s", url)
        return None


def _guess_mime(url: str, data: bytes) -> str:
    """Best-effort MIME type for an image."""
    mime, _ = mimetypes.guess_type(url)
    if mime and mime.startswith("image/"):
        return mime
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"GIF8":
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def _compress_image(
    data: bytes,
    mime: str,
    *,
    max_side: int = _IMAGE_MAX_SIDE,
    max_bytes: int = _IMAGE_MAX_BYTES,
) -> tuple[bytes, str]:
    """Resize / re-encode an image to fit within size limits.

    Returns (compressed_bytes, mime_type).  Falls back to original data
    if Pillow is not available or compression fails.
    """
    if len(data) <= max_bytes:
        return data, mime
    try:
        from PIL import Image
    except ImportError:
        logger.debug("Pillow not installed; skipping image compression")
        return data, mime
    try:
        img = Image.open(io.BytesIO(data))
        w, h = img.size
        if max(w, h) > max_side:
            ratio = max_side / max(w, h)
            img = img.resize(
                (int(w * ratio), int(h * ratio)),
                Image.LANCZOS,
            )
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        for quality in _IMAGE_QUALITY_STEPS:
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality)
            out = buf.getvalue()
            if len(out) <= max_bytes:
                return out, "image/jpeg"
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=_IMAGE_QUALITY_STEPS[-1])
        return buf.getvalue(), "image/jpeg"
    except Exception:
        logger.debug("Image compression failed; using original data")
        return data, mime


def _resolve_image_blocks_to_base64(blocks: list[dict]) -> list[dict]:
    """Convert file:// URL image blocks to inline base64 source blocks.

    This is the critical fix: many VLM APIs cannot read file:// URLs.
    We read the file, optionally compress it, and embed as an AgentScope-
    native ``{"type": "base64", "media_type": ..., "data": ...}`` source.
    """
    resolved: list[dict] = []
    for block in blocks:
        source = block.get("source", {})
        if not isinstance(source, dict):
            resolved.append(block)
            continue

        if source.get("type") == "base64" and source.get("data"):
            raw_b64 = source["data"]
            raw_data = base64.b64decode(raw_b64)
            mime = source.get("media_type") or _guess_mime("", raw_data)
            data, final_mime = _compress_image(raw_data, mime)
            if data is raw_data:
                resolved.append(block)
            else:
                b64 = base64.b64encode(data).decode("ascii")
                resolved.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": final_mime, "data": b64},
                })
            continue

        url = ""
        if source.get("type") == "url":
            url = source.get("url", "")

        if not url:
            resolved.append(block)
            continue

        parsed = urlparse(url)
        is_local = parsed.scheme in ("file", "") or (
            parsed.scheme == "" and parsed.netloc == ""
        )
        if not is_local:
            resolved.append(block)
            continue

        raw_data = _read_file_url(url)
        if raw_data is None:
            resolved.append(block)
            continue

        mime = _guess_mime(url, raw_data)
        data, final_mime = _compress_image(raw_data, mime)
        b64 = base64.b64encode(data).decode("ascii")
        resolved.append({
            "type": "image",
            "source": {"type": "base64", "media_type": final_mime, "data": b64},
        })
        logger.debug(
            "Converted file:// image to base64 (%d bytes -> %d bytes)",
            len(raw_data),
            len(data),
        )
    return resolved


def build_prepass_message(
    source: Msg,
    media_blocks: list[dict],
    *,
    capability: MediaCapability,
    prompt_override: str = "",
) -> Msg:
    user_text = source.get_text_content() or ""
    prompt = (
        prompt_override.strip()
        if prompt_override and prompt_override.strip()
        else _build_prompt_by_capability(capability, user_text, len(media_blocks))
    )
    if capability == "image":
        media_blocks = _resolve_image_blocks_to_base64(media_blocks)
    content = [TextBlock(type="text", text=prompt), *media_blocks]
    return Msg(name=source.name, role="user", content=content)


def _build_prompt_by_capability(
    capability: MediaCapability,
    user_text: str,
    selected_count: int,
) -> str:
    if capability == "image":
        return build_vlm_prepass_prompt(
            user_text=user_text,
            selected_image_count=selected_count,
        )
    if capability == "audio":
        return (
            "You are an audio preprocessor. "
            "Transcribe and describe the provided audio concisely.\n"
            "Do NOT answer the user directly — only describe what you hear.\n"
            f"Number of audio clips: {selected_count}\n"
            f"User's task context: {user_text}"
        )
    return (
        "You are a video preprocessor. "
        "Describe the provided video concisely and accurately.\n"
        "Do NOT answer the user directly — only describe what you see and hear.\n"
        f"Number of videos: {selected_count}\n"
        f"User's task context: {user_text}"
    )


def _cap_output_size(analysis: str, max_output_chars: int) -> str:
    if max_output_chars <= 0 or len(analysis) <= max_output_chars:
        return analysis
    return analysis[:max_output_chars - 3] + "..."


async def run_media_understanding_prepass(
    *,
    msg: Msg | list[Msg] | None,
    capability: MediaCapability,
    enabled: bool,
    attachments_mode: str,
    max_items: int,
    prompt_override: str,
    timeout_seconds: int,
    max_output_chars: int,
    active_vlm_cfg: ResolvedModelConfig | None,
    vlm_fallback_models: list[tuple[ResolvedModelConfig, Any]],
    active_vlm_model: Any | None,
    run_with_runtime_model: Callable[[Any, Msg, int], Awaitable[str]],
) -> MediaUnderstandingResult:
    all_blocks = extract_media_blocks(msg, capability=capability)
    if not all_blocks:
        return MediaUnderstandingResult(
            analysis=None,
            decision=MediaUnderstandingDecision(
                outcome="skipped",
                reason=f"no {capability} blocks",
                capability=capability,
            ),
        )
    if not enabled:
        return MediaUnderstandingResult(
            analysis=None,
            decision=MediaUnderstandingDecision(
                outcome="disabled",
                reason=f"vision.{capability}.enabled=false",
                selected_item_count=0,
                capability=capability,
            ),
        )

    selected_blocks = select_media_blocks_for_prepass(
        all_blocks,
        mode=attachments_mode,
        max_items=max_items,
    )
    if not selected_blocks:
        return MediaUnderstandingResult(
            analysis=None,
            decision=MediaUnderstandingDecision(
                outcome="skipped",
                reason=f"no selected {capability} blocks",
                selected_item_count=0,
                capability=capability,
            ),
        )

    if active_vlm_cfg is None and len(vlm_fallback_models) == 0:
        return MediaUnderstandingResult(
            analysis=None,
            decision=MediaUnderstandingDecision(
                outcome="skipped",
                reason="no VLM configured",
                selected_item_count=len(selected_blocks),
                capability=capability,
            ),
        )

    source = get_last_message(msg)
    vlm_msg = build_prepass_message(
        source,
        selected_blocks,
        capability=capability,
        prompt_override=prompt_override,
    )

    model_map: dict[tuple[str, str], Any] = {}
    if active_vlm_cfg is not None and active_vlm_model is not None:
        model_map[(active_vlm_cfg.provider_id, active_vlm_cfg.model)] = active_vlm_model
    for cfg, model in vlm_fallback_models:
        model_map[(cfg.provider_id, cfg.model)] = model

    fallbacks = [cfg for cfg, _ in vlm_fallback_models]
    if active_vlm_cfg is None:
        primary = fallbacks[0]
        fallbacks = fallbacks[1:]
    else:
        primary = active_vlm_cfg

    async def _run(cfg: ResolvedModelConfig) -> str:
        runtime_model = model_map.get((cfg.provider_id, cfg.model))
        if runtime_model is None:
            raise RuntimeError(
                f"Runtime VLM model missing for {cfg.provider_id}/{cfg.model}",
            )
        raw = await run_with_runtime_model(runtime_model, vlm_msg, timeout_seconds)
        if not raw:
            raise RuntimeError("VLM prepass returned empty analysis")
        normalized = normalize_vlm_prepass_output(raw)
        return _cap_output_size(normalized, max_output_chars)

    try:
        fb_result = await run_with_vlm_fallback(primary, fallbacks, _run)
    except Exception as exc:
        return MediaUnderstandingResult(
            analysis=None,
            decision=MediaUnderstandingDecision(
                outcome="failed",
                reason=str(exc),
                selected_item_count=len(selected_blocks),
                capability=capability,
                attempts=[],
            ),
        )

    attempts = [
        MediaUnderstandingAttempt(
            provider_id=a.provider_id,
            model=a.model,
            outcome="failed",
            reason=a.error,
        )
        for a in fb_result.attempts
    ]
    attempts.append(
        MediaUnderstandingAttempt(
            provider_id=fb_result.used.provider_id,
            model=fb_result.used.model,
            outcome="success",
        ),
    )
    return MediaUnderstandingResult(
        analysis=fb_result.result,
        decision=MediaUnderstandingDecision(
            outcome="success",
            selected_item_count=len(selected_blocks),
            capability=capability,
            attempts=attempts,
        ),
        used=fb_result.used,
    )


async def run_image_understanding_prepass(**kwargs):
    """Backward-compatible wrapper for image-only callers."""
    return await run_media_understanding_prepass(capability="image", **kwargs)


select_image_blocks_for_prepass = select_media_blocks_for_prepass
