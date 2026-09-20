# -*- coding: utf-8 -*-
"""Complete-turn history buffering and deterministic sealed image batches."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Any

from agentscope.message import (
    DataBlock,
    Msg,
    TextBlock,
    ThinkingBlock,
    ToolCallBlock,
    ToolResultBlock,
)

from .....constant import (
    QWENPAW_MESSAGE_TAG_KEY,
    SYNTHETIC_USER_MESSAGE_TAGS,
    SCROLL_MEMORY_MESSAGE_TAG,
)
from ..config import (
    CANVAS_PADDING,
    CANVAS_WIDTH,
    CHARS_PER_TEXT_TOKEN_FALLBACK,
    HISTORY_BATCH_MIN_PAGES,
    HISTORY_MIN_TAIL_PAGE_FILL,
    HISTORY_KEEP_RECENT_TURNS,
    EffortPreset,
)
from ..rendering import (
    RenderedPage,
    count_render_cells,
    estimate_text_pages,
    prepare_render_text,
    render_rows_per_page,
    render_text_pages,
)
from .budget import profitable as _profitable
from .budget import (
    estimate_visual_replacement_tokens as _estimate_replacement_tokens,
)
from .messages import data_blocks as _data_blocks
from .messages import (
    estimate_native_message_tokens as _estimate_native_message_tokens,
)
from .messages import message_has_native_media
from .messages import message_segments as _message_segments
from .precision import factsheet_text as _factsheet_text
from .receipt import CompressionReceipt
from .receipt import record_pages as _record_pages

_HISTORY_SAFE_BLOCKS = (
    TextBlock,
    DataBlock,
    ThinkingBlock,
    ToolCallBlock,
    ToolResultBlock,
)


@dataclass(frozen=True)
class HistoryPlan:
    """A pure, protocol-closed ownership decision over canonical messages."""

    first: int
    ends: tuple[int, ...]


@dataclass(frozen=True)
class _HistoryBatch:
    """One sealed batch, prepared without rendering or persistent state."""

    end: int
    source_text: str
    render_text: str
    slot_text: str
    estimated_pages: tuple[RenderedPage, ...]
    min_page_rows: int


def _real_user_indices(
    messages: list[Msg],
    context_message_ids: frozenset[str],
) -> list[int]:
    """Find canonical user turns, excluding request-only and synthetic cues."""
    indices = []
    for index, message in enumerate(messages):
        if message.role != "user" or message.name == "visual_history":
            continue
        if message.id not in context_message_ids:
            continue
        metadata = (
            message.metadata if isinstance(message.metadata, dict) else {}
        )
        if metadata.get(
            QWENPAW_MESSAGE_TAG_KEY,
        ) in SYNTHETIC_USER_MESSAGE_TAGS | {SCROLL_MEMORY_MESSAGE_TAG}:
            continue
        indices.append(index)
    return indices


def _message_history_safe(message: Msg) -> bool:
    """Stop before AgentScope blocks this serializer cannot represent."""
    return not message_has_native_media(message) and all(
        isinstance(block, _HISTORY_SAFE_BLOCKS) for block in message.content
    )


def _protocol_closed_ends(
    messages: list[Msg],
    start: int,
    cutoff: int,
) -> tuple[int, ...]:
    """Return safe boundaries without separating tool calls from results."""
    open_calls: set[str] = set()
    ends = []
    for index in range(start, cutoff):
        if not _message_history_safe(messages[index]):
            break
        invalid = False
        for block in messages[index].content:
            if isinstance(block, ToolCallBlock):
                if block.id in open_calls:
                    invalid = True
                    break
                open_calls.add(block.id)
            elif isinstance(block, ToolResultBlock):
                if block.id not in open_calls:
                    invalid = True
                    break
                open_calls.remove(block.id)
        if invalid:
            break
        if not open_calls:
            ends.append(index + 1)
    return tuple(ends)


def plan_history(
    messages: list[Msg],
    *,
    context_message_ids: frozenset[str],
) -> HistoryPlan | None:
    """Choose an immutable prefix without mutating or rendering messages."""
    users = _real_user_indices(messages, context_message_ids)
    if len(users) <= HISTORY_KEEP_RECENT_TURNS:
        return None
    recent_start = users[-HISTORY_KEEP_RECENT_TURNS]

    def eligible(message: Msg) -> bool:
        metadata = (
            message.metadata if isinstance(message.metadata, dict) else {}
        )
        return (
            message.role != "system"
            and message.id in context_message_ids
            and metadata.get(QWENPAW_MESSAGE_TAG_KEY)
            != SCROLL_MEMORY_MESSAGE_TAG
        )

    # A leading fragment without its real user request stays native.
    first = users[0]
    # Keep cues and request-only messages in place; select one continuous run.
    end = first
    while end < len(messages) and eligible(messages[end]):
        end += 1
    # Recent-turn protection is independent of image density and tool count.
    turn_ends = set(users[1:])
    ends = tuple(
        boundary
        for boundary in _protocol_closed_ends(
            messages,
            first,
            min(end, recent_start),
        )
        if boundary in turn_ends
    )
    return HistoryPlan(first=first, ends=ends) if ends else None


def _history_batches(
    messages: list[Msg],
    plan: HistoryPlan,
    pages_left: int,
    preset: EffortPreset,
) -> list[_HistoryBatch]:
    """Replay earliest fill-based turn boundaries; never repack old batches."""
    serialized = [
        _message_segments(message)
        for message in messages[plan.first : plan.ends[-1]]
    ]

    columns = (CANVAS_WIDTH - 2 * CANVAS_PADDING) // preset.cell_width
    rows_per_page = render_rows_per_page(preset, columns)
    min_page_rows = ceil(rows_per_page * HISTORY_MIN_TAIL_PAGE_FILL)
    min_batch_rows = ceil(rows_per_page * HISTORY_BATCH_MIN_PAGES)
    separator = prepare_render_text("\n\n")
    separator_cells = count_render_cells(separator)

    batches = []
    source_parts: list[str] = []
    rendered_parts: list[str] = []
    slot_parts: list[str] = []
    buffer_chars = buffer_cells = 0
    previous_end = plan.first
    used_pages = 0
    for end in plan.ends:
        pending_start = len(rendered_parts)
        for text, slot in serialized[
            previous_end - plan.first : end - plan.first
        ]:
            if not text:
                continue
            rendered = prepare_render_text(text)
            if rendered_parts:
                buffer_chars += len(separator)
            buffer_chars += len(rendered)
            source_parts.append(text)
            rendered_parts.append(rendered)
            slot_parts.append(slot)
        previous_end = end
        if not rendered_parts:
            continue

        # Large buffers go straight to layout. Smaller buffers accumulate
        # only new glyph widths; no growing prefix is repeatedly measured.
        if columns > 1 and buffer_chars < columns * (min_batch_rows - 1) + 1:
            for index in range(pending_start, len(rendered_parts)):
                if index:
                    buffer_cells += separator_cells
                buffer_cells += count_render_cells(rendered_parts[index])
            # Glyphs occupy one or two cells, so every wrapped row except
            # the last uses at least columns - 1 cells. Page reflow can only
            # remove rows at these widths. This upper bound cannot skip an
            # eligible batch; the full estimator still decides admission.
            upper_rows = (buffer_cells + columns - 2) // (columns - 1)
            if upper_rows < min_batch_rows:
                continue

        # Serialized messages have non-whitespace role delimiters, so their
        # normalization is independent across the two-newline separator.
        rendered = separator.join(rendered_parts)
        pages = tuple(
            estimate_text_pages(
                rendered,
                preset,
                min_page_rows=min_page_rows,
            ),
        )
        if not pages:
            continue
        rows = sum(
            (page.height - 2 * CANVAS_PADDING) // preset.line_height
            for page in pages
        )
        if rows < min_batch_rows:
            continue
        # Admission uses total content, not average page occupancy. The
        # renderer balances short tails within this batch before it freezes.
        if used_pages + len(pages) > pages_left:
            break
        batches.append(
            _HistoryBatch(
                end=end,
                source_text="\n\n".join(source_parts),
                render_text=rendered,
                slot_text=prepare_render_text("\n\n".join(slot_parts)),
                estimated_pages=pages,
                min_page_rows=min_page_rows,
            ),
        )
        used_pages += len(pages)
        source_parts.clear()
        rendered_parts.clear()
        slot_parts.clear()
        buffer_chars = buffer_cells = 0
    return batches


def _history_intro() -> str:
    """Return stable framing for one range-global visual history message."""
    return (
        "EARLIER TURNS OF THIS CONVERSATION. The following pages contain "
        "prior messages in chronological order and may continue across "
        "page boundaries. The current request follows this history."
    )


_HISTORY_OUTRO = (
    "END EARLIER VISUAL HISTORY. Use the factsheet when available for exact "
    "values. If earlier details or constraints are unclear, retrieve source "
    "passages with recall_context. Continue with the latest user request "
    "in the native messages."
)


def compress_history(  # pylint: disable=R0912,R0915
    messages: list[Msg],
    receipt: CompressionReceipt,
    pages_left: int,
    preset: EffortPreset,
    *,
    context_message_ids: frozenset[str],
) -> tuple[list[Msg], int]:
    """Replace a protocol-closed frozen prefix with append-stable images."""
    if pages_left <= 0:
        return messages, pages_left
    plan = plan_history(
        messages,
        context_message_ids=context_message_ids,
    )
    if plan is None:
        return messages, pages_left
    first = plan.first
    intro = _history_intro()
    minimum_text = "\n".join(("user", intro, _HISTORY_OUTRO))
    batches = _history_batches(messages, plan, pages_left, preset)
    # Profitability is not monotone. Fall back only at sealed batch boundaries.
    for count in range(len(batches), 0, -1):
        selected = batches[:count]
        collapsed_end = selected[-1].end
        estimated_pages = [
            page for batch in selected for page in batch.estimated_pages
        ]
        source_estimated_tokens = _estimate_native_message_tokens(
            messages[first:collapsed_end],
            CHARS_PER_TEXT_TOKEN_FALLBACK,
        )
        # Factsheets can only add cost. Reject impossible candidates before
        # joining and scanning their source for exact identifiers.
        if not _profitable(
            source_estimated_tokens,
            minimum_text,
            estimated_pages,
        ):
            continue
        source_text = "\n\n".join(batch.source_text for batch in selected)
        sheet = _factsheet_text(source_text)
        replacement_text = "\n".join(
            part for part in ("user", intro, sheet, _HISTORY_OUTRO) if part
        )
        if _profitable(
            source_estimated_tokens,
            replacement_text,
            estimated_pages,
        ):
            break
    else:
        return messages, pages_left

    # Commit the request replacement only after the complete range renders.
    all_pages = []
    for batch in selected:
        pages = render_text_pages(
            batch.render_text,
            preset,
            len(batch.estimated_pages),
            batch.slot_text,
            min_page_rows=batch.min_page_rows,
        )
        if len(pages) != len(batch.estimated_pages) or any(
            (page.width, page.height) != (estimate.width, estimate.height)
            for page, estimate in zip(pages, batch.estimated_pages)
        ):
            return messages, pages_left
        all_pages.extend(pages)

    content: list[Any] = [TextBlock(text=intro)]
    content.extend(_data_blocks(all_pages))
    if sheet:
        content.append(TextBlock(text=sheet))
    content.append(TextBlock(text=_HISTORY_OUTRO))

    _record_pages(
        receipt,
        len(all_pages),
        source_text,
        "history",
        source_estimated_tokens=source_estimated_tokens,
        replacement_estimated_tokens=_estimate_replacement_tokens(
            replacement_text,
            all_pages,
        ),
    )

    collapsed = Msg(name="visual_history", role="user", content=content)
    return (
        messages[:first] + [collapsed] + messages[collapsed_end:],
        pages_left - len(all_pages),
    )


__all__ = ["HistoryPlan", "compress_history", "plan_history"]
