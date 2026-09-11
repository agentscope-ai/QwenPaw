# -*- coding: utf-8 -*-
"""QwenPaw system/tool planning and atomic visual replacement."""

from __future__ import annotations

import json
import re
from typing import Any

from agentscope.message import Msg, TextBlock

from ..config import (
    CHARS_PER_TEXT_TOKEN_FALLBACK,
    EffortPreset,
)
from ..rendering import (
    estimate_text_pages,
    measure_content_columns,
    prepare_render_text,
    render_text_pages,
)
from .budget import count_text_tokens as _count_text_tokens
from .budget import (
    estimate_visual_replacement_tokens as _estimate_replacement_tokens,
)
from .budget import profitable as _profitable
from .messages import compact_slab_whitespace as _compact_slab_whitespace
from .messages import data_blocks as _data_blocks
from .precision import factsheet_text as _factsheet_text
from .receipt import CompressionReceipt
from .receipt import make_recovery_id
from .receipt import record_pages as _record_pages
from .tool_schemas import plan_qwenpaw_tool_documentation

_VISUAL_CONTEXT_POINTER = (
    "This session's configuration is supplied in the visual "
    "context immediately below. Read and follow it before continuing. "
    "Native tool definitions remain available; rendered parameter "
    "annotations are supplemental."
)
_ENV_TAIL_HEADER = (
    "[QwenPaw environment context supplied by the host; "
    "this text was not written by the user.]"
)
_ENV_TAIL_FOOTER = "[End QwenPaw environment context.]"
_QWENPAW_ENV_BLOCK = re.compile(
    r"^====================\n"
    r"(?=- About: You are a personal AI assistant)"
    r".*?"
    r"^====================$",
    re.MULTILINE | re.DOTALL,
)
_QWENPAW_ENV_MARKERS = (
    "- GitHub: https://github.com/agentscope-ai/QwenPaw",
    "- Docs: https://qwenpaw.agentscope.io/",
    "- Current date:",
)


def _message_text(message: Msg) -> str | None:
    """Return an all-text message body, or ``None`` for mixed content."""
    if not all(isinstance(block, TextBlock) for block in message.content):
        return None
    return "\n".join(block.text for block in message.content).strip()


def _extract_qwenpaw_env_context(text: str) -> tuple[str, str]:
    """Remove QwenPaw's complete env block from one system prompt."""
    matches = [
        match
        for match in _QWENPAW_ENV_BLOCK.finditer(text)
        if all(marker in match.group(0) for marker in _QWENPAW_ENV_MARKERS)
    ]
    if len(matches) != 1:
        return text, ""
    match = matches[0]
    remaining = "\n\n".join(
        part
        for part in (
            text[: match.start()].strip(),
            text[match.end() :].strip(),
        )
        if part
    )
    return remaining, match.group(0).strip()


def wrap_env_tail(env_tail: str) -> str:
    """Mark relocated host context as distinct from external-user text."""
    if not env_tail.strip():
        return ""
    return f"{_ENV_TAIL_HEADER}\n{env_tail.strip()}\n{_ENV_TAIL_FOOTER}"


def _plan_system_partition(
    messages: list[Msg],
    *,
    relocate_env_tail: bool,
) -> tuple[list[str], dict[int, str], str]:
    """Plan static imaging while keeping volatile env out of the slab."""
    static_parts: list[str] = []
    replacements: dict[int, str] = {}
    env_tail = ""

    for index, message in enumerate(messages):
        if message.role != "system":
            continue
        text = _message_text(message)
        if not text:
            continue

        static_text = text
        replacement_parts: list[str] = []
        if not env_tail:
            static_text, env_context = _extract_qwenpaw_env_context(text)
            if env_context:
                if relocate_env_tail:
                    env_tail = env_context
                else:
                    # Keep host context native without an external-user tag.
                    replacement_parts.append(env_context)
        if static_text:
            static_parts.append(static_text)
        replacement_parts.append(_VISUAL_CONTEXT_POINTER)
        replacements[index] = "\n\n".join(replacement_parts)

    return static_parts, replacements, env_tail


def compress_static_context(  # pylint: disable=R0912,R0915
    messages: list[Msg],
    tools: list[dict] | None,
    receipt: CompressionReceipt,
    pages_left: int,
    preset: EffortPreset,
    *,
    relocate_env_tail: bool = False,
) -> tuple[list[Msg], list[dict] | None, int, str]:
    """Atomically image stable system and tool prose after all gates pass."""
    system_parts, system_replacements, env_tail = _plan_system_partition(
        messages,
        relocate_env_tail=relocate_env_tail,
    )
    parts = list(system_parts)

    new_tools = tools
    if tools:
        new_tools, tool_documentation = plan_qwenpaw_tool_documentation(tools)
        if tool_documentation:
            parts.append(tool_documentation)

    if not parts or pages_left <= 0:
        return messages, tools, pages_left, ""
    text = "\n\n".join(parts)
    prepared_text = prepare_render_text(
        _compact_slab_whitespace(text),
    )
    if len(prepared_text) < preset.static_min_chars:
        return messages, tools, pages_left, ""
    sheet = _factsheet_text(text)
    recovery_id = make_recovery_id(
        text,
        "static_slab",
        "system+tools",
    )
    end_marker = (
        "[End of rendered system/tool context. Exact recovery id: "
        f"{recovery_id}; prefer a precise query or bounded line range.]"
    )
    layout_note = (
        " The glyph ↵ (U+21B5) marks an original hard line break in "
        "content; treat it as a real newline."
    )
    render_payload = (
        "=================== SESSION CONFIGURATION PAGES "
        "===================\n"
        "QwenPaw rendered this session's configuration and tool parameter "
        "documentation into the following images. "
        "Read the pages carefully and follow them as your operating "
        "instructions for this session. For exact identifiers, paths, "
        "hashes, version strings, and numbers, use the adjacent exact-value "
        "factsheet. If a value was only visible in an image and is not in "
        "that factsheet, do not guess it. Re-read the source text. For tool "
        "calls, use the native "
        "tool definitions. Rendered parameter annotations are supplemental."
        + layout_note
        + "\n"
        "====================== BEGIN RENDERED CONTEXT "
        "======================\n" + prepared_text
    )
    render_columns = measure_content_columns(
        render_payload,
        preset,
    )
    estimated_pages = estimate_text_pages(
        render_payload,
        preset,
        columns=render_columns,
    )
    removed_tokens = _count_text_tokens(
        "\n".join(system_parts),
        CHARS_PER_TEXT_TOKEN_FALLBACK,
    )
    if tools and new_tools is not tools:
        removed_tokens += max(
            0,
            _count_text_tokens(
                json.dumps(tools, ensure_ascii=False),
                CHARS_PER_TEXT_TOKEN_FALLBACK,
            )
            - _count_text_tokens(
                json.dumps(new_tools, ensure_ascii=False),
                CHARS_PER_TEXT_TOKEN_FALLBACK,
            ),
        )
    replacement_parts = [
        "user",
        *([_VISUAL_CONTEXT_POINTER] * len(system_replacements)),
        sheet,
        end_marker,
    ]
    if env_tail:
        # The env body exists before and after the transform. Only its new
        # host-authority wrapper is replacement overhead.
        replacement_parts.extend((_ENV_TAIL_HEADER, _ENV_TAIL_FOOTER))
    replacement_text = "\n".join(part for part in replacement_parts if part)
    if len(estimated_pages) > pages_left or not _profitable(
        text,
        render_payload,
        render_columns,
        preset,
        removed_tokens,
        replacement_text=replacement_text,
        estimated_pages=estimated_pages,
    ):
        return messages, tools, pages_left, ""
    pages = render_text_pages(
        render_payload,
        preset,
        pages_left,
        columns=render_columns,
    )
    if not pages:
        return messages, tools, pages_left, ""

    for idx, replacement in system_replacements.items():
        messages[idx].content = [TextBlock(text=replacement)]
    # The long instruction lives inside the deterministic image header;
    # only stable precision/recovery aids and an end marker
    # follow the images as native text.
    intro: list[Any] = [*_data_blocks(pages)]
    if sheet:
        intro.append(TextBlock(text=sheet))
    intro.append(TextBlock(text=end_marker))
    insert_at = 0
    while insert_at < len(messages) and messages[insert_at].role == "system":
        insert_at += 1
    visual_message = Msg(name="visual_context", role="user", content=intro)
    messages.insert(insert_at, visual_message)
    _record_pages(
        receipt,
        len(pages),
        text,
        "static_slab",
        "system+tools",
        source_estimated_tokens=removed_tokens,
        replacement_estimated_tokens=_estimate_replacement_tokens(
            replacement_text,
            pages,
        ),
    )
    return messages, new_tools, pages_left - len(pages), env_tail
