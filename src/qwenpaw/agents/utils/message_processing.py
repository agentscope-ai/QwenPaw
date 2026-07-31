# -*- coding: utf-8 -*-
"""Message processing utilities for agent communication.

This module handles:
- File and media block processing
- Message content manipulation
- Message validation
"""
import asyncio
import logging
import os
import urllib.parse
from pathlib import Path
from typing import Optional

from agentscope.message import Msg, TextBlock

from ...config import load_config
from .file_handling import download_file_from_base64, download_file_from_url

logger = logging.getLogger(__name__)


async def _process_single_file_block(
    source: dict,
    filename: Optional[str],
) -> Optional[str]:
    """
    Process a single file block and download the file.

    Args:
        source: The source dict containing file information.
        filename: The filename to save.

    Returns:
        The local file path if successful, None otherwise.
    """
    if isinstance(source, dict) and source.get("type") == "base64":
        if "data" in source:
            base64_data = source.get("data", "")
            local_path = await download_file_from_base64(
                base64_data,
                filename,
            )
            logger.debug(
                "Processed base64 file block: %s -> %s",
                filename or "unnamed",
                local_path,
            )
            return local_path

    elif isinstance(source, dict) and source.get("type") == "url":
        url = source.get("url", "")
        if url:
            local_path = await download_file_from_url(
                url,
                filename,
            )
            logger.debug(
                "Processed URL file block: %s -> %s",
                url,
                local_path,
            )
            return local_path

    return None


def _extract_source_and_filename(block: dict, block_type: str):
    """Extract source and filename from a block."""
    if block_type == "file":
        return block.get("source", {}), block.get("filename")

    source = block.get("source", {})
    if not isinstance(source, dict):
        return None, None

    filename = None
    if source.get("type") == "url":
        url = source.get("url", "")
        if url:
            parsed = urllib.parse.urlparse(url)
            filename = os.path.basename(parsed.path) or None

    return source, filename


def _media_type_from_path(path: str) -> str:
    """Infer audio media_type from file path suffix."""
    ext = (os.path.splitext(path)[1] or "").lower()
    return {
        ".amr": "audio/amr",
        ".wav": "audio/wav",
        ".mp3": "audio/mp3",
        ".opus": "audio/opus",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
    }.get(ext, "audio/octet-stream")


# Extensions accepted by the agentscope OpenAIChatFormatter
_FORMATTER_SUPPORTED_AUDIO_EXTS = {".wav", ".mp3"}
_AMR_EXTENSIONS = (".amr", ".amr-wb")
_AMR_FFMPEG_PROBE_PARAMS = ["-analyzeduration", "200M", "-probesize", "200M"]
_WAV_AUDIO_CODEC = "pcm_s16le"


def _convert_audio_to_wav(src_path: str) -> Optional[str]:
    """Convert an audio file to .wav using ffmpeg if the extension is not
    natively supported by the LLM formatter.

    Uses a unique temporary file name to avoid overwriting existing files.

    Returns the path to the converted .wav file, or None if conversion
    failed or was not needed.
    """
    ext = (os.path.splitext(src_path)[1] or "").lower()
    if ext in _FORMATTER_SUPPORTED_AUDIO_EXTS:
        return None  # already supported, no conversion needed

    import subprocess
    import shutil
    import tempfile

    if not shutil.which("ffmpeg"):
        logger.warning(
            "ffmpeg not found; cannot convert %s audio to wav. "
            "Install ffmpeg to enable audio format conversion.",
            ext,
        )
        return None

    # Use a temp file in the same directory to avoid clobbering.
    src_dir = os.path.dirname(src_path) or "."
    fd, dst_path = tempfile.mkstemp(suffix=".wav", dir=src_dir)
    os.close(fd)

    # AMR (AMR-NB/AMR-WB) used by QQ voice messages has non-standard
    # encapsulation; increase analyzeduration and probesize so ffmpeg
    # can correctly detect the codec before decoding.
    amr_extra: list = (
        _AMR_FFMPEG_PROBE_PARAMS if ext in _AMR_EXTENSIONS else []
    )

    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                *amr_extra,
                "-i",
                src_path,
                "-acodec",
                _WAV_AUDIO_CODEC,
                "-ar",
                "16000",
                "-ac",
                "1",
                dst_path,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=30,
            check=True,
        )
        logger.debug("Converted audio %s -> %s", src_path, dst_path)
        return dst_path
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        stderr = getattr(e, "stderr", b"") or b""
        logger.warning(
            "Audio conversion failed for %s: %s\nffmpeg stderr: %s",
            src_path,
            e,
            stderr.decode(errors="replace"),
        )
        # Clean up the temp file on failure.
        try:
            os.unlink(dst_path)
        except OSError:
            pass
        return None


def _local_file_url(path: str) -> str:
    """Build a ``file://`` URL without percent-encoding non-ASCII chars."""
    return "file://" + str(Path(path).resolve())


def _update_block_with_local_path(
    block: dict,
    block_type: str,
    local_path: str,
) -> dict:
    """Update block with downloaded local path."""
    if block_type == "file":
        block["source"] = local_path
        if not block.get("filename"):
            block["filename"] = os.path.basename(local_path)
    else:
        if block_type == "audio":
            block["source"] = {
                "type": "url",
                "url": _local_file_url(local_path),
                "media_type": _media_type_from_path(local_path),
            }
        else:
            block["source"] = {
                "type": "url",
                "url": _local_file_url(local_path),
            }
    return block


def _handle_download_failure(block_type: str) -> Optional[dict]:
    """Handle download failure based on block type."""
    if block_type == "file":
        return {
            "type": "text",
            "text": "[Error: Unknown file source type or empty data]",
        }
    logger.debug("Failed to download %s block, keeping original", block_type)
    return None


async def _process_audio_block(
    message_content: list,
    index: int,
    local_path: str,
    block: dict,
) -> bool:
    """Handle an audio block according to the configured audio_mode.

    Modes:
      - ``"auto"`` (default): try transcription; if it succeeds, replace
        the audio block with the transcribed text and suppress file
        metadata.  If transcription fails (no provider, missing deps,
        API error), show a file-uploaded placeholder instead.  Audio is
        never sent directly to the model in this mode.
      - ``"native"``: send the audio block directly to the model
        (convert via ffmpeg if needed).  No transcription is attempted.
        If the file format is unsupported and conversion fails, a text
        placeholder is shown instead.

    Returns:
        True if the audio was fully handled (transcribed or sent natively)
        — the "file downloaded" notification will be suppressed.
        False if transcription failed — the notification is kept so the
        LLM knows the file path.
    """
    from .audio_transcription import transcribe_audio

    audio_mode = load_config().agents.audio_mode

    if audio_mode == "native":
        converted = await asyncio.to_thread(
            _convert_audio_to_wav,
            local_path,
        )
        ext = (os.path.splitext(local_path)[1] or "").lower()
        if converted:
            audio_path = converted
        elif ext in _FORMATTER_SUPPORTED_AUDIO_EXTS:
            # Already a supported format, no conversion needed.
            audio_path = local_path
        else:
            # Unsupported format and conversion failed — show placeholder
            # instead of sending an unsupported audio block to the model.
            message_content[index] = {
                "type": "text",
                "text": (
                    "[Voice message]: (audio conversion failed, "
                    "install ffmpeg to enable native audio)"
                ),
            }
            return True
        block["source"] = {
            "type": "url",
            "url": _local_file_url(audio_path),
            "media_type": _media_type_from_path(audio_path),
        }
        return True

    # "auto": attempt transcription.
    text = await transcribe_audio(local_path)
    if text:
        message_content[index] = {
            "type": "text",
            "text": f"[Voice message]: {text}",
        }
        return True

    # Transcription failed — show file-uploaded placeholder.
    message_content[index] = {
        "type": "text",
        "text": "[Voice message]: (audio file received)",
    }
    return False


async def _process_single_block(
    message_content: list,
    index: int,
    block: dict,
) -> Optional[str]:
    """
    Process a single file or media block.

    Returns:
        Optional[str]: The local path if download was successful,
        None otherwise.
    """
    block_type = block.get("type")
    if not isinstance(block_type, str):
        return None

    source, filename = _extract_source_and_filename(block, block_type)
    if source is None:
        return None

    # Normalize: when source is "base64" but data is a local path (e.g.
    # DingTalk voice returns path), treat as url only if under allowed dir.
    if (
        block_type == "audio"
        and isinstance(source, dict)
        and source.get("type") == "base64"
    ):
        data = source.get("data")
        if isinstance(data, str) and os.path.isfile(data):
            block["source"] = {
                "type": "url",
                "url": _local_file_url(data),
                "media_type": _media_type_from_path(data),
            }
            source = block["source"]

    try:
        local_path = await _process_single_file_block(source, filename)

        if local_path:
            if block_type == "audio":
                # Audio blocks need transcription or format conversion
                # depending on the configured audio_mode.
                _update_block_with_local_path(block, block_type, local_path)
                handled = await _process_audio_block(
                    message_content,
                    index,
                    local_path,
                    block,
                )
                if handled:
                    # Audio was transcribed or sent natively; suppress the
                    # "file downloaded" notification that would follow.
                    return None
            else:
                message_content[index] = _update_block_with_local_path(
                    block,
                    block_type,
                    local_path,
                )
            logger.debug(
                "Updated %s block with local path: %s",
                block_type,
                local_path,
            )
            return local_path
        else:
            error_block = _handle_download_failure(block_type)
            if error_block:
                message_content[index] = error_block
            return None

    except Exception as e:
        logger.error("Failed to process %s block: %s", block_type, e)
        if block_type == "file":
            message_content[index] = {
                "type": "text",
                "text": f"[Error: Failed to download file - {e}]",
            }
        return None


# pylint: disable=too-many-return-statements
def _coerce_block_to_dict(
    block,
) -> dict | None:
    """Convert a Pydantic block (or dict) to a dict for processing.

    Returns ``None`` for blocks that are not file/media types.
    For 2.0 ``DataBlock``, maps ``type="data"`` back to the concrete
    media category (``"image"``/``"audio"``/``"video"``) so downstream
    helpers recognise it.
    """
    if isinstance(block, dict):
        return block

    btype = getattr(block, "type", None)
    if btype == "data":
        source = getattr(block, "source", None)
        if source is None:
            return None
        mt = getattr(source, "media_type", "") or ""
        main = mt.split("/")[0]
        if main not in ("image", "audio", "video"):
            # Generic data block (e.g. application/*) — treat as file
            main = "file"
        src_dict: dict = {}
        src_type = getattr(source, "type", None)
        if src_type == "url":
            url_str = str(getattr(source, "url", ""))
            if url_str.startswith("file://"):
                url_str = url_str.removeprefix("file://")
            src_dict = {"type": "url", "url": url_str, "media_type": mt}
        elif src_type == "base64":
            src_dict = {
                "type": "base64",
                "data": getattr(source, "data", ""),
                "media_type": mt,
            }
        else:
            return None
        return {
            "type": main,
            "source": src_dict,
            "filename": getattr(block, "name", None),
        }

    if btype in ("file", "image", "audio", "video"):
        if hasattr(block, "model_dump"):
            return block.model_dump()
        return None

    return None


def _resolve_data_block_path(block) -> tuple[str, str] | None:
    """Return ``(local_path, display_name)`` for a Pydantic DataBlock file URL.

    Extracts ``file://`` URLs from :class:`agentscope.message.DataBlock`
    (produced by the console upload flow) and sanitizes the user-visible
    display name via :func:`_sanitize_display_filename`.  Returns ``None``
    for non-file DataBlocks (remote URLs, in-memory Base64Source, etc.) so
    callers can skip non-downloadable entries without branching.
    """
    source = getattr(block, "source", None)
    url = str(getattr(source, "url", "")) if source else ""
    if not url.startswith("file://"):
        return None
    local_path = url.removeprefix("file://")
    display_name = _sanitize_display_filename(
        getattr(block, "name", None),
        local_path,
    )
    return local_path, display_name


def _resolve_legacy_block_path(
    block: dict, local_path: str
) -> tuple[str, str] | None:
    """Resolve the 1.x dict-block path into ``(local_path, display_name)``."""
    display_name = _sanitize_display_filename(
        block.get("name"),
        local_path,
    )
    return local_path, display_name


def _build_upload_hint(local_path: str, display_name: str, lang: str) -> str:
    """Build the user-facing "file downloaded" prompt hint.

    When ``display_name`` differs from the filesystem basename (the usual
    case for console UUID-prefixed media storage), both are shown so the
    model has the semantic filename the user uploaded AND the concrete
    local path to read from.  When they match, only the path is shown,
    preserving exact historical behavior for the unaffected majority.
    """
    basename = Path(local_path).name
    if lang == "zh":
        if display_name and basename != display_name:
            return "用户上传文件“" f"{display_name}”，已经下载到 " f"{local_path}"
        return f"用户上传文件，已经下载到 {local_path}"
    if display_name and basename != display_name:
        return (
            f'User uploaded a file "{display_name}", '
            f"downloaded to {local_path}"
        )
    return f"User uploaded a file, downloaded to {local_path}"


async def process_file_and_media_blocks_in_message(msg) -> None:
    """Process file and media blocks (file, image, audio, video) in messages.

    Downloads to local and updates paths/URLs.  Handles both dict blocks
    (1.x) and Pydantic block objects (2.0 ``DataBlock``).
    """
    messages = (
        [msg] if isinstance(msg, Msg) else msg if isinstance(msg, list) else []
    )

    for message in messages:
        if not isinstance(message, Msg):
            continue

        if not isinstance(message.content, list):
            continue

        downloaded_files = []

        for i, block in enumerate(message.content):
            if not isinstance(block, dict):
                resolved = _resolve_data_block_path(block)
                if resolved is not None:
                    downloaded_files.append((i, *resolved))
                continue

            block_dict = _coerce_block_to_dict(block)
            if block_dict is None:
                continue

            block_type = block_dict.get("type")
            if block_type not in ["file", "image", "audio", "video"]:
                continue

            local_path = await _process_single_block(
                message.content,
                i,
                block_dict,
            )
            if local_path:
                downloaded_files.append(
                    (i, *_resolve_legacy_block_path(block_dict, local_path)),
                )

        if downloaded_files:
            lang = load_config().agents.language
            for i, local_path, display_name in reversed(downloaded_files):
                text = _build_upload_hint(local_path, display_name, lang)
                message.content.insert(
                    i + 1,
                    TextBlock(type="text", text=text),
                )


def _sanitize_display_filename(
    raw_name: Optional[str],
    fallback_path: str,
) -> str:
    """Return a filename safe for inline prompt injection.

    ``raw_name`` comes from the untrusted client-supplied ``DataBlock.name``
    / ``dict["name"]`` field.  We collapse any control characters, vertical
    whitespace, and bidirectional overrides that could mislead the LLM (or
    break prompt layout), and trim the result to a reasonable fixed
    display width so a single huge filename can't dominate the context
    window.

    Falls back to ``basename(fallback_path)`` when the caller has no
    display name or after sanitization nothing useful remains.
    This keeps storage paths intact while surfacing the original user
    filename in prompt hints — resolving Issue #6453 where CJK display
    names were being dropped entirely because only the UUID-prefixed
    media path was shown.
    """
    name = raw_name if isinstance(raw_name, str) else ""
    # URL-percent CJK names (sometimes produced by multipart uploads when
    # the browser pre-escapes filenames without RFC 5987 encoding) are
    # unquoted here so the user-facing prompt shows the original glyphs.
    if name and ("%" in name):
        try:
            name = urllib.parse.unquote(name, errors="strict")
        except ValueError:
            pass
    if name:
        # Remove every C0/C1 control character, vertical whitespace,
        # bidirectional formatting (LRO/RLO/LRE/RLE/PDF), and the
        # replacement character itself — anything that can scramble a
        # one-line prompt.
        cleaned = "".join(
            ch
            for ch in name
            if not (
                ord(ch) < 0x20
                or 0x7F <= ord(ch) <= 0x9F
                or ch
                in (
                    "\u202a",
                    "\u202b",
                    "\u202c",
                    "\u202d",
                    "\u202e",
                    "\u200e",
                    "\u200f",
                    "\ufeff",
                    "\ufffc",
                    "\ufffd",
                )
                or ch in ("\r", "\n", "\v", "\f")
            )
        ).strip()
        # Collapse interior runs of whitespace to a single SP so filenames
        # that were accidentally encoded with embedded newlines / tabs
        # don't span multiple prompt lines.
        cleaned = " ".join(cleaned.split())
        if len(cleaned) > 120:
            stem = cleaned[:112]
            suffix = cleaned[-8:]
            cleaned = f"{stem}…{suffix}"
        if cleaned:
            return cleaned
    return Path(fallback_path).name


def is_first_user_interaction(messages: list) -> bool:
    """Check if this is the first user interaction.

    Args:
        messages: List of Msg objects from memory.

    Returns:
        bool: True if this is the first user message with no assistant
              responses.
    """
    system_prompt_count = sum(1 for msg in messages if msg.role == "system")
    non_system_messages = messages[system_prompt_count:]

    user_msg_count = sum(
        1 for msg in non_system_messages if msg.role == "user"
    )
    assistant_msg_count = sum(
        1 for msg in non_system_messages if msg.role == "assistant"
    )

    return user_msg_count == 1 and assistant_msg_count == 0


def prepend_to_message_content(msg, guidance: str) -> None:
    """Prepend guidance text to message content.

    Handles both dict blocks and Pydantic TextBlock objects.
    """
    if isinstance(msg.content, str):
        msg.content = guidance + "\n\n" + msg.content
        return

    if not isinstance(msg.content, list):
        return

    for block in msg.content:
        btype = (
            block.get("type")
            if isinstance(block, dict)
            else getattr(block, "type", None)
        )
        if btype == "text":
            if isinstance(block, dict):
                block["text"] = guidance + "\n\n" + block.get("text", "")
            else:
                block.text = guidance + "\n\n" + (block.text or "")
            return

    msg.content.insert(0, TextBlock(type="text", text=guidance))
