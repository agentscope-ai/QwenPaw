# -*- coding: utf-8 -*-
"""Serialize AgentScope ``Msg`` blocks into ``conversation_history`` rows."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from agentscope.message import Msg

from ....constant import QWENPAW_MESSAGE_TAG_KEY
from ..types import LogEntry

# The model echoes a milestone as a fenced single line: ``⟦ text ⟧`` (rare
# brackets U+27E6 / U+27E7, chosen to almost never collide with code, markdown,
# or diff hunks). Older prompts wrapped the fence in an HTML comment, so the
# parser keeps accepting that legacy form even though new prompts use only the
# plain fence.
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
# Display cleanup is deliberately more tolerant than index extraction. If a
# model starts a final headline but mixes it with provider tool-protocol tokens
# or never closes the fence, hide that trailing protocol line without treating
# it as a valid index entry (issue #6240).
_TRAILING_HEADLINE_RE = re.compile(
    rf"(?:<!--[ \t]*{_OPEN}|(?:^|\n)[ \t]*{_OPEN})[^\r\n]*\Z",
)
_HEADLINE_MAX = 2000  # safety ceiling; prompts still ask for concise headlines
_LEGACY_START_RE = re.compile(r"<!--\s*[⟦〚]")
_PLAIN_START_RE = re.compile(r"(?:^|\n)[ \t]*[⟦〚]")
_LEGACY_CLOSE_RE = re.compile(r"[⟧〛]\s*-->")
_PLAIN_CLOSE_RE = re.compile(r"[⟧〛]")


@dataclass
class HeadlineDeltaState:
    """Per-output-stream state for hiding a chunked headline protocol."""

    pending: str = ""
    suppressing: bool = False
    legacy_comment: bool = False


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
    """Return a valid ``⟦ … ⟧`` headline, otherwise ``None``."""
    if text:
        m = _HEADLINE_RE.search(text)
        if m and m.group(1).strip():
            return m.group(1).strip()[:_HEADLINE_MAX]
    return None


def strip_headline(text: str | None) -> str | None:
    """Remove Scroll's headline protocol line for display.

    Complete fences remain extractable by :func:`extract_headline`. A malformed
    trailing fence is also removed from display but is intentionally not
    indexed. The live context and persisted row keep the original text; this
    function only cleans channel/console output.
    """
    if not text:
        return text
    m = _HEADLINE_RE.search(text)
    if not m or not m.group(1).strip():
        m = _TRAILING_HEADLINE_RE.search(text)
        if not m:
            return text
    start, end = m.span()  # one line: ``.`` never crosses a newline
    cleaned = text[:start] + text[end:]
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)  # collapse blank line left
    return cleaned.strip()


def strip_headline_delta(
    text: str,
    *,
    state: HeadlineDeltaState | None = None,
) -> tuple[str, HeadlineDeltaState]:
    """Hide one streamed headline fragment and return its updated state.

    SSE content events carry deltas rather than the complete assistant text.
    Both the opening and closing markers may straddle chunk boundaries, so
    ambiguous trailing prefixes are buffered until the next delta.

    Headlines are a trailing protocol line, so any text after their opening
    fence in the same delta is intentionally hidden.
    """
    state = state or HeadlineDeltaState()
    text = state.pending + text
    state.pending = ""
    visible: list[str] = []

    while text:
        if state.suppressing:
            close_re = (
                _LEGACY_CLOSE_RE if state.legacy_comment else _PLAIN_CLOSE_RE
            )
            close = close_re.search(text)
            if close is not None:
                text = text[close.end() :]
                state.suppressing = False
                state.legacy_comment = False
                continue
            if state.legacy_comment:
                close_start = max(text.rfind("⟧"), text.rfind("〛"))
                if close_start >= 0 and _possible_legacy_close_prefix(
                    text[close_start:],
                ):
                    state.pending = text[close_start:]
            return "".join(visible), state

        legacy = _LEGACY_START_RE.search(text)
        plain = _PLAIN_START_RE.search(text)
        starts = [
            (match.start(), match.end(), is_legacy)
            for match, is_legacy in ((legacy, True), (plain, False))
            if match is not None
        ]
        if starts:
            start, end, is_legacy = min(starts, key=lambda item: item[0])
            visible.append(text[:start])
            text = text[end:]
            state.suppressing = True
            state.legacy_comment = is_legacy
            continue

        prefix_start = text.rfind("<")
        if prefix_start >= 0 and _possible_legacy_start_prefix(
            text[prefix_start:],
        ):
            visible.append(text[:prefix_start])
            state.pending = text[prefix_start:]
            return "".join(visible), state

        visible.append(text)
        break

    return "".join(visible), state


def flush_headline_delta(state: HeadlineDeltaState) -> str:
    """Finalize one stream, releasing only an unconfirmed marker prefix."""
    visible = "" if state.suppressing else state.pending
    state.pending = ""
    state.suppressing = False
    state.legacy_comment = False
    return visible


def _possible_legacy_start_prefix(value: str) -> bool:
    marker = "<!--"
    if len(value) < len(marker):
        return marker.startswith(value)
    return value.startswith(marker) and not value[len(marker) :].strip()


def _possible_legacy_close_prefix(value: str) -> bool:
    if not value or value[0] not in "⟧〛":
        return False
    suffix = value[1:]
    marker_start = next(
        (index for index, char in enumerate(suffix) if not char.isspace()),
        len(suffix),
    )
    return "-->".startswith(suffix[marker_start:])


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
        # Persist the runtime tag (loop_continuation / auto_continue / …) so
        # durable rows keep the "this user msg is a synthetic stub, not a
        # request" signal — the recall layer's active-turn floor anchors on
        # real requests only and needs it in SQL.
        tag = None
        msg_meta = getattr(msg, "metadata", None)
        if isinstance(msg_meta, dict):
            tag = msg_meta.get(QWENPAW_MESSAGE_TAG_KEY)
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
                metadata=({QWENPAW_MESSAGE_TAG_KEY: str(tag)} if tag else {}),
                created_at=created_at,
            ),
        )
    for b in results:
        block_metadata = (
            b.get("metadata")
            if isinstance(b, dict)
            else getattr(b, "metadata", None)
        )
        entries.append(
            LogEntry(
                kind="tool_result",
                role=msg.role,
                name=getattr(b, "name", None),
                content=flatten_output(getattr(b, "output", None)),
                tool_call_id=getattr(b, "id", None),
                tool_state=_state_value(getattr(b, "state", None)),
                blocks=[_dump(b)],
                metadata=(
                    dict(block_metadata)
                    if isinstance(block_metadata, dict)
                    else {}
                ),
                created_at=created_at,
            ),
        )
    return entries
