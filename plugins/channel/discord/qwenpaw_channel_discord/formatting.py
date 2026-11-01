# -*- coding: utf-8 -*-
"""Pure Discord routing, attachment classification and legacy formatting."""

import mimetypes
import re

_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")


def classify_attachment(attachment) -> str:
    """Classify a Discord attachment as image/video/audio/file.

    Priority: attachment.content_type > filename MIME guess > file.
    """
    ctype = (getattr(attachment, "content_type", None) or "").lower()
    filename = getattr(attachment, "filename", "") or ""

    mime = ctype
    if not mime and filename:
        guessed, _ = mimetypes.guess_type(filename)
        mime = (guessed or "").lower()

    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "audio"
    return "file"


def chunk_text(text: str, max_len: int = 2000) -> list[str]:
    """Split *text* into chunks that fit Discord's message limit.

    Splits at newline boundaries to preserve formatting.  If a single
    line exceeds *max_len* it is hard-split at *max_len*.

    Markdown code fences are tracked so that a chunk ending inside an
    open fence gets a closing fence appended and the next chunk gets
    a matching opening fence prepended.  This keeps code blocks
    rendered correctly across split messages.
    """
    if len(text) <= max_len:
        return [text]

    # Reserve space for a closing fence suffix ("\n```") that _flush()
    # may append when a code block spans chunk boundaries.
    fence_close_len = len("\n```")

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    fence_open: str = ""  # e.g. "```python"

    def _flush() -> None:
        nonlocal fence_open
        body = "".join(current).rstrip("\n")
        if fence_open:
            body += "\n```"  # close dangling fence
        chunks.append(body)
        current.clear()

    for line in text.split("\n"):
        line_with_nl = line + "\n"
        stripped = line.strip()

        # Detect fence toggle.
        if _FENCE_RE.match(stripped):
            if fence_open:
                fence_open = ""
            else:
                fence_open = stripped

        # Flush if adding this line would exceed the limit.
        # When inside a code fence, reserve space for the closing
        # suffix that _flush() appends.
        reserved = fence_close_len if fence_open else 0
        if current and current_len + len(line_with_nl) + reserved > max_len:
            saved_fence = fence_open
            _flush()
            current_len = 0
            # Re-open the fence in the next chunk.
            if saved_fence:
                fence_open = saved_fence
                reopener = saved_fence + "\n"
                current.append(reopener)
                current_len += len(reopener)

        # Single line exceeds max_len -> hard-split.
        if len(line_with_nl) > max_len:
            for i in range(0, len(line), max_len):
                end = i + max_len
                chunks.append(line[i:end])
        else:
            current.append(line_with_nl)
            current_len += len(line_with_nl)

    if current:
        chunks.append("".join(current).rstrip("\n"))

    return [c for c in chunks if c.strip()]


def route_from_handle(to_handle: str) -> dict:
    # to_handle format: discord:ch:<channel_id> or discord:dm:<user_id>
    parts = (to_handle or "").split(":")
    if len(parts) >= 3 and parts[0] == "discord":
        kind, ident = parts[1], parts[2]
        if kind == "ch":
            return {"channel_id": ident}
        if kind == "dm":
            return {"user_id": ident}
    return {}


def resolve_session_id(sender_id, meta=None):
    meta = meta or {}
    user_id = meta.get("user_id") or sender_id
    if meta.get("is_dm") or not meta.get("channel_id"):
        return f"discord:dm:{user_id}"
    return f"discord:ch:{meta['channel_id']}"


def build_stream_display_text(stream_type, text, prefix=""):
    if stream_type == "reasoning" and text:
        text = "💭 " + text
    return prefix + "  " + text if prefix and text else text
