# -*- coding: utf-8 -*-
"""Serialize AgentScope ``Msg`` blocks into ``conversation_history`` rows."""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from agentscope.message import Msg

from ...._compat.message import LEGACY_MESSAGE_ID_KEY
from ....constant import (
    AUTO_MEMORY_SEARCH_BLOCK_IDS_KEY,
    QWENPAW_MESSAGE_TAG_KEY,
)
from ....runtime.reply_cycle import REPLY_CYCLE_METADATA_KEYS
from ....utils.tool_call_extra import TOOL_CALL_EXTRAS_METADATA_KEY
from ..types import LogEntry
from ...utils.tool_message_utils import (
    dump_block as _dump,
    flatten_output,
    media_ref as _media_ref,
)

_RECORD_KEY = "_scroll_record_key"
_RECORD_ANCHOR = "_scroll_record_anchor"


def message_key(msg: Msg) -> str:
    """Identity of one persisted Msg, not the SDK reply containing it."""
    return (msg.metadata or {}).get(_RECORD_KEY) or msg.id


def assign_message_keys(
    messages: Iterable[Msg],
    lookup_anchor: Callable[[str], str | None],
) -> None:
    """Keep legacy keys; disambiguate repeated reply IDs with a block anchor.

    Metadata survives SDK splitting and session reload. The original durable
    anchor distinguishes a new occurrence after its predecessor was evicted.
    """
    originals: dict[str, str] = {}
    for msg in messages:
        metadata = dict(msg.metadata or {})
        if metadata.get(LEGACY_MESSAGE_ID_KEY) == msg.id:
            metadata[_RECORD_KEY] = metadata[_RECORD_ANCHOR] = msg.id
            msg.metadata = metadata
        if metadata.get(_RECORD_KEY):
            if metadata[_RECORD_KEY] == msg.id:
                originals[msg.id] = metadata[_RECORD_ANCHOR]
            continue
        transient = set(metadata.get(AUTO_MEMORY_SEARCH_BLOCK_IDS_KEY) or ())
        anchor = next(
            (
                b.id for b in msg.content
                if getattr(b, "id", None) and b.id not in transient
            ),
            None,
        )
        anchor = anchor or uuid4().hex
        if msg.id not in originals:
            originals[msg.id] = lookup_anchor(msg.id) or anchor
        metadata[_RECORD_KEY] = (
            msg.id if originals[msg.id] == anchor else f"{msg.id}#msg:{anchor}"
        )
        metadata[_RECORD_ANCHOR] = anchor
        msg.metadata = metadata

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
    at_line_start: bool = True


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
    at_line_start = state.at_line_start
    text = state.pending + text
    state.pending = ""
    # Chunk boundaries are not line boundaries. Track source text, including
    # hidden markers, so a following inline fence remains ordinary content.
    if "\n" in text:
        state.at_line_start = not text.rsplit("\n", 1)[1].strip(" \t")
    elif text.strip(" \t"):
        state.at_line_start = False
    visible: list[str] = []

    while text:
        if state.suppressing:
            close_re = (
                _LEGACY_CLOSE_RE if state.legacy_comment else _PLAIN_CLOSE_RE
            )
            close = close_re.search(text)
            if close is not None:
                text = text[close.end() :]
                at_line_start = False
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
        plain = _PLAIN_START_RE.search(
            text,
            0 if at_line_start or text.startswith("\n") else 1,
        )
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
    state.at_line_start = True
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
        # Persist only protocol metadata required to reconstruct the turn:
        # runtime tags distinguish synthetic stubs from real requests, while
        # provider tool-call extras preserve signatures for exact archives.
        persisted_metadata: dict[str, Any] = {}
        msg_meta = getattr(msg, "metadata", None)
        if isinstance(msg_meta, dict):
            tag = msg_meta.get(QWENPAW_MESSAGE_TAG_KEY)
            if tag:
                persisted_metadata[QWENPAW_MESSAGE_TAG_KEY] = str(tag)
            tool_call_extras = msg_meta.get(
                TOOL_CALL_EXTRAS_METADATA_KEY,
            )
            if isinstance(tool_call_extras, dict):
                persisted_metadata[TOOL_CALL_EXTRAS_METADATA_KEY] = deepcopy(
                    tool_call_extras,
                )
            for key in (*REPLY_CYCLE_METADATA_KEYS, _RECORD_KEY, _RECORD_ANCHOR):
                if key in msg_meta:
                    persisted_metadata[key] = deepcopy(msg_meta[key])
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
                metadata=persisted_metadata,
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
