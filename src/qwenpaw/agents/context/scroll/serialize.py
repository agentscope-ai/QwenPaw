# -*- coding: utf-8 -*-
"""Serialize AgentScope ``Msg`` blocks into ``conversation_history`` rows."""
from __future__ import annotations

import re
from typing import Any

from agentscope.message import Msg

from ..types import LogEntry

# The model echoes a milestone as a fenced single line: ``⟦ text ⟧`` (rare
# brackets U+27E6 / U+27E7, chosen to almost never collide with code, markdown,
# or diff hunks). The fence is normally wrapped in an HTML comment
# (``<!-- ⟦ … ⟧ -->``) so it stays invisible in the rendered chat; the optional
# wrapper is tolerated here.
#
# Qwen routinely substitutes the visually-identical white square brackets
# U+301A/U+301B (``〚 〛``) for the intended U+27E6/U+27E7 (``⟦ ⟧``). Accept both
# pairs on each side so a lookalike fence is still stripped from display and
# captured into the index rather than leaking as a visible comment. The inner
# text never contains a closing bracket of either variant.
_OPEN = r"[⟦〚]"
_CLOSE = r"[⟧〛]"
_HEADLINE_RE = re.compile(
    rf"^[ \t]*(?:<!--)?[ \t]*{_OPEN}[ \t]*(.+?)[ \t]*{_CLOSE}"
    rf"[ \t]*(?:-->)?[ \t]*$",
    re.MULTILINE,
)
_HEADLINE_MAX = 200  # chars — a headline is an index entry, not a paragraph


def _dump(block: Any) -> dict:
    fn = getattr(block, "model_dump", None)
    if callable(fn):
        try:
            out = fn(mode="json")
        except Exception:  # noqa: BLE001
            out = fn()
        return out if isinstance(out, dict) else {"value": out}
    return {"repr": str(block)}


def _media_ref(bd: dict) -> str | None:
    """Render one ``DataBlock`` dump as a compact, searchable text reference.

    ``[image: <url>]`` / ``[file: <name> — <url>]`` so a media-bearing turn
    still lands in ``content`` (and its FTS index) and comes back through
    recall — which is text-only and would otherwise see an empty string. A
    base64 source NEVER inlines its payload: only ``name``/``media_type`` is
    shown, so ``content`` stays small even when the block carries raw bytes.
    """
    if not isinstance(bd, dict) or bd.get("type") != "data":
        return None
    src = bd.get("source") or {}
    media_type = src.get("media_type") or ""
    kind = media_type.split("/", 1)[0] if "/" in media_type else "file"
    if kind not in ("image", "audio", "video"):
        kind = "file"
    ref = (
        src.get("url")
        if src.get("type") == "url"
        else f"<{media_type or 'binary'}>"
    )
    name = bd.get("name")
    if name and ref:
        return f"[{kind}: {name} — {ref}]"
    return f"[{kind}: {name or ref or '?'}]"


def flatten_output(output: Any) -> str | None:
    """Flatten a ToolResultBlock.output (str | list[block]) to text.

    Non-text blocks (an image a tool returned) collapse to a ``_media_ref``
    placeholder rather than vanishing, so the result stays recallable.
    """
    if output is None:
        return None
    if isinstance(output, str):
        return output
    parts: list[str] = []
    for block in output:
        bd = block if isinstance(block, dict) else _dump(block)
        text = bd.get("text")
        if text:
            parts.append(text)
        else:
            ref = _media_ref(bd)
            if ref:
                parts.append(ref)
    return "\n".join(parts) if parts else None


def _state_value(state: Any) -> str | None:
    if state is None:
        return None
    if isinstance(state, str):
        return state
    return getattr(state, "value", state)


def extract_headline(text: str | None) -> str | None:
    """The turn's durable index line: the model's own ``⟦ … ⟧`` fence, or None.

    Headlines are *milestone* markers the model emits deliberately — most turns
    carry none. A turn with no fence does not become a leaf of the eviction
    index; it stays durably stored and recallable by ``seq`` range or
    ``ms.search``, just not listed in the map. There is intentionally no
    extractive fallback.
    """
    if text:
        m = _HEADLINE_RE.search(text)
        if m and m.group(1).strip():
            return m.group(1).strip()[:_HEADLINE_MAX]
    return None


def strip_headline(text: str | None) -> str | None:
    """Remove the headline line for display, keeping it in context/index.

    Deletes exactly the line :func:`extract_headline` matched (same first
    match, by span) — so a line is hidden iff it became the index entry. The
    headline stays verbatim in the live context and persisted row; this only
    cleans the text rendered to channels/console, where ``<!-- … -->`` shows.
    """
    if not text:
        return text
    m = _HEADLINE_RE.search(text)
    if not m or not m.group(1).strip():
        return text
    start, end = m.span()  # one line: ``.`` never crosses a newline
    cleaned = text[:start] + text[end:]
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)  # collapse blank line left
    return cleaned.strip()


def msg_to_entries(msg: Msg) -> list[LogEntry]:
    """Map one ``Msg`` to one or more durable ``LogEntry`` rows.

    The assistant text/thinking/tool-call blocks become a single ``model_turn``
    (or ``context_msg`` for user) row; each ``tool_result`` block becomes its
    own ``tool_result`` row whose ``content`` is the flattened output (so it is
    recallable by ``tool_call_id``).
    """
    non_result = [
        b for b in msg.content if getattr(b, "type", None) != "tool_result"
    ]
    results = [
        b for b in msg.content if getattr(b, "type", None) == "tool_result"
    ]
    created_at = getattr(msg, "created_at", None)
    entries: list[LogEntry] = []

    if non_result or not results:
        name = tool_call_id = None
        tool_input = None
        for b in non_result:
            if getattr(b, "type", None) == "tool_call":
                # Scalar columns describe the turn's tool call (the last one,
                # if several); the full set is always in ``blocks``. ``input``
                # is the call's arguments (a dict or a raw JSON string) — kept
                # so ``recall_tool`` can show *what* was called, not just the
                # result. ``append()`` JSON-encodes a dict; a str passes thru.
                name = getattr(b, "name", None)
                tool_call_id = getattr(b, "id", None)
                tool_input = getattr(b, "input", None)
        dumped = [_dump(b) for b in non_result]
        text = msg.get_text_content() or ""
        # Headline only on the model's own turns; user/placeholder rows
        # need none. Computed from the model's own text, before media refs
        # are appended, so a placeholder line can't be mistaken for a fence.
        headline = extract_headline(text) if msg.role == "assistant" else None
        # Append a text reference for any media/file block so a turn that
        # carried only an image isn't stored (and recalled) as empty content.
        media = [r for r in (_media_ref(b) for b in dumped) if r]
        if media:
            joined = "\n".join(media)
            text = f"{text}\n{joined}".strip() if text else joined
        entries.append(
            LogEntry(
                kind="model_turn"
                if msg.role == "assistant"
                else "context_msg",
                role=msg.role,
                name=name,
                content=text,
                tool_call_id=tool_call_id,
                tool_input=tool_input,
                headline=headline,
                blocks=dumped or None,
                created_at=created_at,
            ),
        )
    for b in results:
        entries.append(
            LogEntry(
                kind="tool_result",
                role=msg.role,
                name=getattr(b, "name", None),
                content=flatten_output(getattr(b, "output", None)),
                tool_call_id=getattr(b, "id", None),
                tool_state=_state_value(getattr(b, "state", None)),
                blocks=[_dump(b)],
                created_at=created_at,
            ),
        )
    return entries
