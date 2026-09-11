# -*- coding: utf-8 -*-
"""AgentScope message serialization and text normalization."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterable

from agentscope.message import (
    Base64Source,
    DataBlock,
    Msg,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
)

from ..config import ROLE_MARK_ASSISTANT, ROLE_MARK_USER
from .budget import count_text_tokens

if TYPE_CHECKING:
    from ..rendering import RenderedPage

_FRESHNESS_HINT = re.compile(
    r"\(file state is current in your\s+context — no need to Read it back\)",
)
_STALE_FRESHNESS_NOTE = (
    "(state as of this PRIOR turn — the file may have changed since; "
    "Read it again before editing)"
)


def _state_value(state: Any) -> str:
    """Return the stable wire value for either an enum or normalized string."""
    return str(getattr(state, "value", state))


@dataclass(frozen=True)
class MediaInventory:
    """Native media that visual compression must preserve."""

    images: int = 0
    audio: int = 0
    video: int = 0
    files: int = 0
    unknown: int = 0


def media_kind(block: DataBlock) -> str:
    """Classify an AgentScope data block without provider assumptions."""
    media_type = str(getattr(block.source, "media_type", "") or "").lower()
    if media_type.startswith("image/"):
        return "image"
    if media_type.startswith("audio/"):
        return "audio"
    if media_type.startswith("video/"):
        return "video"
    if media_type.startswith("application/") or media_type.startswith("text/"):
        return "file"
    return "unknown"


def message_data_blocks(message: Msg) -> list[DataBlock]:
    """Return top-level and tool-result media carried by one message."""
    result: list[DataBlock] = []
    for block in message.content:
        if isinstance(block, DataBlock):
            result.append(block)
        elif isinstance(block, ToolResultBlock) and isinstance(
            block.output,
            list,
        ):
            result.extend(
                item for item in block.output if isinstance(item, DataBlock)
            )
    return result


def inspect_media(messages: Iterable[Msg]) -> MediaInventory:
    """Inventory original request media before synthetic pages are inserted."""
    counts = {
        "image": 0,
        "audio": 0,
        "video": 0,
        "file": 0,
        "unknown": 0,
    }
    for message in messages:
        for block in message_data_blocks(message):
            counts[media_kind(block)] += 1
    return MediaInventory(
        images=counts["image"],
        audio=counts["audio"],
        video=counts["video"],
        files=counts["file"],
        unknown=counts["unknown"],
    )


def message_has_native_media(message: Msg) -> bool:
    """Whether history must stop before this opaque canonical message."""
    return bool(message_data_blocks(message))


def user_text(message: Msg) -> str:
    """Return only native user text, never attachment placeholders."""
    return "\n\n".join(
        block.text for block in message.content if isinstance(block, TextBlock)
    )


def data_blocks(pages: Iterable[RenderedPage]) -> list[DataBlock]:
    return [
        DataBlock(
            source=Base64Source(
                data=base64.b64encode(page.png).decode("ascii"),
                media_type="image/png",
            ),
            name=f"visual-context-{idx + 1}.png",
        )
        for idx, page in enumerate(pages)
    ]


def block_text(block: Any) -> str:
    if isinstance(block, TextBlock):
        return block.text
    if isinstance(block, DataBlock):
        return f"[{media_kind(block)}]"
    if isinstance(block, ToolCallBlock):
        return (
            f"[tool_call id={block.id} name={block.name} "
            f"state={_state_value(block.state)}]\n{block.input}"
        )
    if isinstance(block, ToolResultBlock):
        output = block.output
        if isinstance(output, str):
            inner = _FRESHNESS_HINT.sub(
                _STALE_FRESHNESS_NOTE,
                output,
            )
        else:
            parts = []
            for item in output:
                if isinstance(item, TextBlock):
                    parts.append(item.text)
                elif isinstance(item, DataBlock):
                    parts.append(f"[{media_kind(item)}]")
            inner = _FRESHNESS_HINT.sub(
                _STALE_FRESHNESS_NOTE,
                "\n".join(parts),
            )
        return (
            f"[tool_result id={block.id} name={block.name} "
            f"state={_state_value(block.state)}]\n{inner}"
        )
    # Old thinking/reasoning is deliberately absent from rendered history;
    # the recent native tail retains protocol-relevant reasoning state.
    return ""


def message_body(msg: Msg) -> str:
    return "\n\n".join(
        filter(None, (block_text(block) for block in msg.content)),
    )


def message_segments(msg: Msg, turn: int) -> tuple[str, str]:
    """Serialize one turn and its width-identical role-color slots."""
    groups: list[tuple[str, list[str]]] = []
    for block in msg.content:
        text = block_text(block)
        if not text:
            continue
        # AgentScope stores a complete ReAct lifecycle in one assistant Msg,
        # but its formatters lower ToolResultBlocks to the user/tool side of
        # the wire protocol. Preserve that ordered ownership in the rendered
        # transcript instead of relabeling the whole carrier as user.
        role = (
            "user"
            if isinstance(block, ToolResultBlock)
            else ("assistant" if msg.role == "assistant" else "user")
        )
        if not groups or groups[-1][0] != role:
            groups.append((role, []))
        groups[-1][1].append(text)

    text_segments: list[str] = []
    slot_segments: list[str] = []
    for role, parts in groups:
        body = "\n\n".join(parts)
        opening = f'<{role} t="{turn}">'
        closing = f"</{role}>"
        mark = ROLE_MARK_ASSISTANT if role == "assistant" else ROLE_MARK_USER
        text_segments.append(f"{opening}\n{body}\n{closing}")
        slot_body = body.replace(ROLE_MARK_USER, "\x03").replace(
            ROLE_MARK_ASSISTANT,
            "\x03",
        )
        slot_segments.append(
            f"{mark * len(opening)}\n{slot_body}\n{mark * len(closing)}",
        )
    return "\n\n".join(text_segments), "\n\n".join(slot_segments)


def estimate_native_message_tokens(
    messages: list[Msg],
    tools: list[dict] | None,
    chars_per_token: float = 4.0,
) -> int:
    """Estimate native tokens removed by a history replacement."""
    parts: list[str] = []
    for msg in messages:
        parts.append(msg.role)
        parts.extend(block_text(block) for block in msg.content)
    if tools:
        parts.append(json.dumps(tools, ensure_ascii=False))
    return count_text_tokens("\n".join(parts), chars_per_token)


def compact_slab_whitespace(text: str) -> str:
    """Normalize slab text before rendering while preserving line structure."""
    normalized = "\n".join(line.rstrip(" \t") for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", normalized)


__all__ = [
    "block_text",
    "compact_slab_whitespace",
    "data_blocks",
    "estimate_native_message_tokens",
    "inspect_media",
    "MediaInventory",
    "media_kind",
    "message_data_blocks",
    "message_has_native_media",
    "message_body",
    "message_segments",
    "user_text",
]
