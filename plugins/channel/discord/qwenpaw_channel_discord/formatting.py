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

    Splits at newline boundaries to preserve formatting. Long lines are
    split within the space available after accounting for code fences.

    Markdown code fences are tracked so that a chunk ending inside an
    open fence gets a closing fence appended and the next chunk gets
    a matching opening fence prepended.  This keeps code blocks
    rendered correctly across split messages.
    """
    if len(text) <= max_len:
        return [text]

    closing_fence = f"\n```"

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    fence_open: str = ""  # e.g. "```python"

    def _flush() -> None:
        nonlocal current_len
        body = "".join(current).removesuffix(f"\n")
        current.clear()
        current_len = 0
        if fence_open:
            body += closing_fence
            reopener = f"{fence_open}\n"
            current.append(reopener)
            current_len = len(reopener)
        chunks.append(body)

    for line in text.split("\n"):
        stripped = line.strip()

        # Determine the state after this line without changing the state
        # used to close and reopen the current chunk during a flush.
        next_fence_open = fence_open
        if _FENCE_RE.match(stripped):
            if fence_open:
                next_fence_open = ""
            else:
                next_fence_open = stripped

        # Count blank lines and omit the trailing separator for other lines.
        line_len = max(1, len(line))
        reserved = len(closing_fence) if next_fence_open else 0
        if current and current_len + line_len + reserved > max_len:
            _flush()

        available = max_len - current_len - reserved
        if len(line) > available:
            if current and fence_open and next_fence_open and available > 0:
                # Only the reopened fence is buffered here.
                start = 0
                while len(line) - start > available:
                    end = start + available
                    current.append(line[start:end])
                    _flush()
                    start = end
                line = line[start:]
            else:
                # Hard-split plain text or a fence that cannot fit.
                current.clear()
                current_len = 0
                chunks.extend(
                    line[start : start + max_len]
                    for start in range(0, len(line), max_len)
                )
                fence_open = next_fence_open
                continue

        fence_open = next_fence_open
        line_with_nl = f"{line}\n"
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
