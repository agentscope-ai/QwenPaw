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
# wrapper is tolerated here. The inner text never contains ⟧.
_HEADLINE_RE = re.compile(
    r"^[ \t]*(?:<!--)?[ \t]*⟦[ \t]*(.+?)[ \t]*⟧[ \t]*(?:-->)?[ \t]*$",
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


def flatten_output(output: Any) -> str | None:
    """Flatten a ToolResultBlock.output (str | list[block]) to text."""
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
        # need none.
        headline = extract_headline(text) if msg.role == "assistant" else None
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
