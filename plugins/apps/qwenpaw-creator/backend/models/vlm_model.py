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
import io
import mimetypes
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from PIL import Image, ImageOps

from models import config as model_config
from models.concurrency import model_slot
from models.output_budget import anthropic_output_limit
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

# Inline images step down this ladder (longest edge in px, JPEG quality)
# until the encoded bytes fit VLM_MAX_INLINE_BYTES. Providers bill vision
# tokens rather than request bytes, so a downscaled image still answers the
# question whereas a hard refusal leaves the understanding record silently
# empty. Mirrors the video clip ladder in services.media.source_observation.
IMAGE_INLINE_LADDER = (
    (2048, 85),
    (1536, 80),
    (1024, 75),
    (768, 70),
)


# What ``mimetypes`` answers for a meaningless suffix such as ``.bin``.  It
# carries no information about the media, so it must not win over a type the
# caller already confirmed.
_GENERIC_MIME = "application/octet-stream"


def _specific_media_type(declared: str) -> str:
    """Return *declared* unless it is the placeholder that says nothing.

    ``application/octet-stream`` is what an upload form fills in for every
    byte it cannot name, so honouring it as a confirmed type defeated the
    family fallback: a suffixless clip left the inline transport labelled
    ``data:application/octet-stream``, the one header both SDK formatters drop
    along with the media itself.  A real declared family is kept; the
    placeholder is read as silence.
    """
    value = (declared or "").strip()
    return "" if value.casefold() == _GENERIC_MIME else value


# The image families Creator inlines, keyed by the signature their bytes
# actually carry.  A label taken from a file name can be wrong in either
# direction — a converter that writes PNG under a ``.jpg`` suffix, or a real
# PNG stored as ``reference-4821.bin`` — and only the bytes settle it.
_IMAGE_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
)


def _sniff_image_mime(head: bytes) -> str:
    """Return the image type *head* starts with, or ``""`` for anything else.

    Only images are sniffed.  Video containers keep their brand at an offset
    behind a size field, and the suffix resolves them well enough that
    guessing here would risk trading a wrong subtype for a worse one.
    """
    for signature, mime in _IMAGE_SIGNATURES:
        if head.startswith(signature):
            return mime
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "image/webp"
    return ""


def _mime_for_path(path: Path, declared: str) -> str:
    """Return the media type to label *path* with.

    The bytes decide when they identify an image; otherwise the extension is
    consulted only when it knows something — a real ``.jpg`` still beats a
    generic declared family, but ``.bin`` ->
    ``application/octet-stream`` must not outrank a confirmed ``image/png``,
    because the data URL header is what survives to the provider —
    ``native_content._data_block`` reads the media type off the URL, and the
    AgentScope formatters drop a block whose type they do not recognise.  A
    wrong subtype costs a re-decode; the placeholder costs the whole image.
    """
    try:
        with path.open("rb") as handle:
            head = handle.read(16)
    except OSError:
        head = b""
    sniffed = _sniff_image_mime(head)
    if sniffed:
        return sniffed
    guessed = mimetypes.guess_type(path.name)[0]
    declared = _specific_media_type(declared)
    if not guessed or guessed == _GENERIC_MIME:
        return declared or _GENERIC_MIME
    return guessed


def _media_declaration(media_obj: dict, part_type: str) -> str:
    """Return the media type a content part carries, or its family.

    Every entry that inlines local media resolves the type through here — the
    OpenAI-compatible transport and the direct Anthropic and Gemini inliners —
    because a declaration honoured on one protocol and hardcoded away on
    another is the same bug wearing a different hat: the outgoing label stops
    describing the bytes and the formatter that trusts it drops the block.
    ``application/octet-stream`` is the placeholder an unnamed upload writes for
    every file, so it counts as saying nothing, and a part that says nothing
    falls back to its family.
    """
    declared = _specific_media_type(
        str(media_obj.get("mediaType") or media_obj.get("media_type") or ""),
    )
    return declared or (
        "video/mp4" if part_type == "video_url" else "image/png"
    )


def _local_path_from_url(url: str) -> Path | None:
    if url.startswith("/generated/"):
        return media_path_from_url(url)
    if url.startswith("file://"):
        return local_path_from_file_url(url).expanduser().resolve()
    return None


# EXIF Orientation values that need a pixel transform. 1 and a missing tag
# both mean the stored pixels are already upright.
_EXIF_ORIENTATION_TAG = 0x0112


def _upright(image: Image.Image) -> Image.Image:
    """Bake EXIF Orientation into the pixels.

    Re-encoding drops the tag, so without this a portrait phone photo reaches
    the VLM lying on its side: the only hint that viewers should rotate it is
    gone from the JPEG we hand over.
    """
    orientation = image.getexif().get(_EXIF_ORIENTATION_TAG)
    if isinstance(orientation, int) and 2 <= orientation <= 8:
        return ImageOps.exif_transpose(image)
    return image


def _flatten_alpha(image: Image.Image) -> Image.Image:
    """Composite transparent pixels onto white before dropping the alpha.

    ``convert("RGB")`` discards the alpha channel and keeps whatever the
    encoder stored underneath the transparent pixels — usually black. UI
    captures and scanned documents are exactly the images that outgrow the
    inline budget, so without this a transparent-background page reaches the
    VLM as pale text on black, the one rendering it reads worst.

    A colour key counts as transparency too: ``tRNS`` is legal on RGB and L
    PNGs, and PIL applies it inside ``convert("RGBA")`` — measured on Pillow
    10, the declared floor, and on 13: a black key over black pixels yields
    alpha 0 and flattens to white, while a key that does not match the pixel
    keeps alpha 255.  The fast path therefore has to test for the key and not
    for the mode alone.
    """
    keyed = "transparency" in image.info
    if image.mode == "RGB" and not keyed:
        return image
    has_alpha = image.mode in {"RGBA", "LA"} or (
        keyed and image.mode in {"P", "RGB", "L"}
    )
    if not has_alpha:
        return image.convert("RGB")
    rgba = image.convert("RGBA")
    flat = Image.new("RGB", rgba.size, (255, 255, 255))
    flat.paste(rgba, mask=rgba.getchannel("A"))
    return flat


def _downscale_image_to_budget(path: Path, max_bytes: int) -> bytes | None:
    """Re-encode *path* down the ladder until it fits *max_bytes*.

    Returns ``None`` when the file is not a decodable image, or when even the
    smallest rung stays over budget, so callers keep their existing refusal.

    The catch below is deliberately broad, and narrowing it would be a
    regression: PIL raises ``DecompressionBombError`` for a file over its
    pixel ceiling, and that type derives from ``Exception`` rather than
    ``OSError``, so an ``(OSError, ValueError)`` clause would let an
    oversized screenshot escape instead of reaching the refusal.
    """
    try:
        with Image.open(path) as image:
            image.load()
            image = _upright(image)
            image = _flatten_alpha(image)
            for max_edge, quality in IMAGE_INLINE_LADDER:
                frame = image.copy()
                frame.thumbnail((max_edge, max_edge), Image.LANCZOS)
                buffer = io.BytesIO()
                frame.save(
                    buffer,
                    format="JPEG",
                    quality=quality,
                    optimize=True,
                )
                payload = buffer.getvalue()
                if len(payload) <= max_bytes:
                    return payload
    except Exception as exc:  # pylint: disable=broad-except
        logger.info("inline downscale unavailable for %s (%s)", path.name, exc)
        return None
    return None


def _inline_payload(path: Path, fallback_mime: str) -> tuple[str, bytes]:
    """Return ``(mime, bytes)`` for *path*, downscaled to fit the budget."""
    max_bytes = model_config.get_vlm_max_inline_bytes()
    size = path.stat().st_size
    if size <= max_bytes:
        return _mime_for_path(path, fallback_mime), path.read_bytes()
    downscaled = _downscale_image_to_budget(path, max_bytes)
    if downscaled is None:
        raise ModelError(
            f"VLM local media inline size limit exceeded: {path.name} is "
            f"{size} bytes, limit is {max_bytes}. A non-DashScope provider "
            "inlines media as Base64 and cannot fetch a DashScope OSS URL; "
            "raise VLM_MAX_INLINE_BYTES, shorten or downscale the source, "
            "or point the VLM at a DashScope endpoint.",
            model_name=model_config.get_vlm_model_name(),
        )
    logger.info(
        "inlined %s as a downscaled JPEG: %d bytes exceeds the %d-byte VLM "
        "inline budget, re-encoded to %d bytes",
        path.name,
        size,
        max_bytes,
        len(downscaled),
    )
    return "image/jpeg", downscaled


def _data_url(path: Path, fallback_mime: str) -> str:
    mime, payload = _inline_payload(path, fallback_mime)
    encoded = base64.b64encode(payload).decode("utf-8")
    return f"data:{mime};base64,{encoded}"


def _inline_base64(path: Path, fallback_mime: str) -> tuple[str, str]:
    """Return ``(mime_type, base64_data)`` for a local file."""
    mime, payload = _inline_payload(path, fallback_mime)
    return mime, base64.b64encode(payload).decode("utf-8")


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


def _is_dashscope_provider(base_url: str, protocol: str = "") -> bool:
    host = urlparse(base_url).hostname or ""
    if "dashscope" in host:
        return True
    # A MaaS deployment serves the same API but never spells ``dashscope`` in
    # its host; classifying it as a generic gateway would drop local media to
    # the inline Base64 budget instead of the 1GB temporary OSS upload. The
    # host, though, only proves the wire format — the upload is a separate
    # credential: a Token Plan key is refused by the Bailian upload API, see
    # ``video_model._resolve_reference_media_url``, so a MaaS endpoint earns
    # the ``oss://`` route only when it is not being reached as Token Plan.
    if not model_config.is_maas_endpoint(base_url):
        return False
    return not model_config.is_token_plan_protocol(
        protocol or model_config.get_vlm_protocol(),
    )


def uses_dashscope_transport() -> bool:
    """True when the configured VLM transports local media through the
    DashScope model-bound temporary OSS upload (48h TTL, <=1GB) instead
    of inline Base64 data URLs."""
    return _is_dashscope_provider(model_config.get_vlm_base_url())


async def transport_local_media_url(
    local_path: Path,
    *,
    api_key: str,
    model_name: str,
    media_type: str = "",
) -> str:
    """Return a URL for *local_path* that the configured VLM can ingest.

    Callers that assemble multimodal parts themselves — the file-native
    Specialist media pipeline — never reach ``_call_openai_vlm``, so the
    provider decision has to happen where the part is created. DashScope
    uploads to the model-bound temporary OSS and yields a public URL; every
    other OpenAI-compatible gateway receives an inline Base64 data URL,
    because it cannot fetch DashScope's OSS object and answers the DashScope
    upload credential with 401.
    """
    declared = _specific_media_type(media_type)
    fallback = declared or (
        "video/mp4"
        if local_path.suffix.lower() in VIDEO_SUFFIXES
        else "image/png"
    )
    if uses_dashscope_transport():
        return await upload_local_file_to_dashscope_temp(
            local_path,
            api_key=api_key,
            model_name=model_name,
            media_type=declared or _mime_for_path(local_path, fallback),
        )
    return await asyncio.to_thread(_data_url, local_path, fallback)


async def _transport_local_media_part(
    part: dict,
    api_key: str,
    model_name: str,
    base_url: str,
    protocol: str = "",
) -> tuple[dict, bool]:
    """Replace a local media URL with a provider-transportable URL.

    Returns ``(part, uses_temp_oss)``. DashScope-bound requests use the
    official model-bound temporary upload (cached, 48h TTL, <=1GB); other
    OpenAI-compatible providers fall back to an inline Base64 data URL.

    *protocol* names the credential these bytes are uploaded with. Pass it
    whenever *base_url* comes from a section other than the VLM: the upload
    identity is a property of the key, so deciding it from the VLM's own
    protocol sent a borrowed Token Plan credential to the Bailian upload API
    that refuses it, and only changing the unrelated VLM section could undo
    that.
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
    # Honour a type the part already declares, the way native_content does,
    # through the same rule the direct Anthropic and Gemini inliners use.
    fallback = _media_declaration(media_obj, part_type)
    transported = dict(part)
    if _is_dashscope_provider(base_url, protocol):
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
    timeout: float | None = None,
    api_key_override: str | None = None,
    base_url_override: str | None = None,
    model_name_override: str | None = None,
    protocol_override: str | None = None,
) -> str:
    """Call the configured VLM and return the assistant text.

    A caller that substitutes another section's credential (the grounding
    verifier reuses the LLM's Token Plan key) has to name that section's
    protocol too, because the wire format and the media upload identity both
    belong to the credential being spent, not to the VLM slot.
    """
    api_key = api_key_override or model_config.get_vlm_api_key()
    base_url = base_url_override or model_config.get_vlm_base_url()
    model_name = model_name_override or model_config.get_vlm_model_name()
    protocol = protocol_override or model_config.get_vlm_protocol()
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
        "VLM request start: model=%s protocol=%s images=%d videos=%d",
        model_name,
        protocol or "openai",
        image_count,
        video_count,
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
                timeout=actual_timeout,
                api_key=api_key,
                base_url=base_url,
                model_name=model_name,
                protocol=protocol,
            )
    except httpx.HTTPStatusError as exc:
        if has_media and _is_media_related_error(exc.response.text):
            get_capability_cache().learn(
                f"vlm:{model_name}",
                "rejects_media",
                True,
            )
        if model_config.is_temperature_unsupported_error(exc.response.text):
            model_config.learn_temperature_unsupported(model_name)
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
        if model_config.is_temperature_unsupported_error(str(exc)):
            model_config.learn_temperature_unsupported(model_name)
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
    timeout: float,
    api_key: str,
    base_url: str,
    model_name: str,
    protocol: str = "",
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
            protocol,
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
        "enable_thinking": False,
    }
    if model_config.chat_temperature(model_name, temperature) is None:
        body.pop("temperature", None)
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
                fallback = _media_declaration(media_obj, part_type)
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
        "messages": [{"role": "user", "content": anthropic_content}],
        "max_tokens": await anthropic_output_limit(
            model_name,
            base_url=base_url,
            api_key=api_key,
        ),
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
            fallback = _media_declaration(media_obj, part_type)
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
        "generationConfig": {},
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
