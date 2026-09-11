# -*- coding: utf-8 -*-
"""Successful tool-result selection, paging, and visual replacement."""

from __future__ import annotations

import math
import re
from typing import Any

from agentscope.message import Msg, TextBlock, ToolResultBlock, ToolResultState

from ..config import (
    CANVAS_PADDING,
    CANVAS_WIDTH,
    MAX_IMAGES_PER_TOOL_RESULT,
    EffortPreset,
)
from ..rendering import (
    estimate_text_pages,
    measure_content_columns,
    page_count_for_text,
    prepare_render_text,
    render_rows_per_page,
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


def _is_context_whitespace(char: str) -> bool:
    codepoint = ord(char)
    return (
        0x0009 <= codepoint <= 0x000D
        or codepoint
        in {
            0x0020,
            0x00A0,
            0x1680,
            0x2028,
            0x2029,
            0x202F,
            0x205F,
            0x3000,
            0xFEFF,
        }
        or 0x2000 <= codepoint <= 0x200A
    )


def _trim_context_start(text: str) -> str:
    index = 0
    while index < len(text) and _is_context_whitespace(text[index]):
        index += 1
    return text[index:]


def _ascii_word_boundary_after(text: str, prefix: str) -> bool:
    if not text.startswith(prefix):
        return False
    if len(text) == len(prefix):
        return True
    next_char = text[len(prefix)]
    return not (
        "0" <= next_char <= "9"
        or "A" <= next_char <= "Z"
        or "a" <= next_char <= "z"
        or next_char == "_"
    )


def _visual_rows(text: str, columns: int) -> int:
    """Estimate wrapped visual rows."""
    return sum(
        max(1, math.ceil(len(line) / max(1, columns)))
        for line in text.split("\n")
    )


def _classify_content(text: str) -> str:
    """Classify content for structured or head-tail paging."""
    head = text[:4096]
    stripped = _trim_context_start(head)
    after_object = (
        _trim_context_start(stripped[1:]) if stripped.startswith("{") else ""
    )
    after_array = (
        _trim_context_start(stripped[1:]) if stripped.startswith("[") else ""
    )
    array_starts_value = bool(after_array) and (
        after_array[0] in {'"', "{", "[", "]"}
        or "0" <= after_array[0] <= "9"
        or (
            after_array.startswith("-")
            and len(after_array) > 1
            and "0" <= after_array[1] <= "9"
        )
        or _ascii_word_boundary_after(after_array, "true")
        or _ascii_word_boundary_after(after_array, "false")
        or _ascii_word_boundary_after(after_array, "null")
    )
    yaml_rest = stripped[3:] if stripped.startswith("---") else ""
    yaml_document_marker = (
        bool(yaml_rest)
        and _is_context_whitespace(yaml_rest[0])
        and bool(_trim_context_start(yaml_rest))
    )
    object_starts_value = bool(after_object) and after_object[0] in {'"', "}"}
    explicit_document_start = stripped.startswith(
        ("---\n", "---\r\n", "diff --git "),
    )
    if (
        object_starts_value
        or array_starts_value
        or explicit_document_start
        or yaml_document_marker
    ):
        return "structured"
    lines = [line for line in head.split("\n")[:40] if len(line) > 0]
    if len(lines) >= 4:
        log_line = re.compile(
            r"^(?:\[?(?:DEBUG|INFO|WARN|WARNING|ERROR|TRACE|FATAL)\]?\b|"
            r"\d{4}-\d{2}-\d{2}[T ]?|\d{2}:\d{2}:\d{2}\b)",
            flags=re.ASCII,
        )
        if (
            sum(bool(log_line.search(line)) for line in lines) / len(lines)
            >= 0.3
        ):
            return "log"
    return "other"


def _paging_marker(
    *,
    original_chars: int,
    original_lines: int,
    omitted_chars: int,
    omitted_lines: int,
    head_lines: int,
    tail_lines: int,
    original_images: int,
) -> str:
    shown = (
        f"Showing first {head_lines} lines and last {tail_lines} lines."
        if tail_lines
        else f"Showing first {head_lines} lines (tail elided)."
    )
    return (
        "\n\n[ Visual Compact paging: omitted "
        f"{omitted_lines:,} lines ({omitted_chars:,} chars) of content here. "
        f"Original length: {original_chars:,} chars "
        f"({original_lines:,} lines, ~{original_images:,} images). "
        f"{shown} ]\n\n"
    )


def _truncate_for_budget(  # pylint: disable=R0912,R0915
    text: str,
    max_images: int,
    preset: EffortPreset,
    *,
    shape: str | None = None,
) -> tuple[str, int]:
    """Apply the visual-row and character-bounded head/tail pager."""
    cols = max(
        1,
        (CANVAS_WIDTH - 2 * CANVAS_PADDING) // preset.cell_width,
    )
    rows_per_image = render_rows_per_page(
        preset,
        cols,
    )
    estimated_images = max(
        1,
        math.ceil(_visual_rows(text, cols) / rows_per_image),
        math.ceil(
            len(text) / preset.readable_chars_per_image,
        ),
    )
    if estimated_images <= max_images:
        return text, 0
    total_row_budget = max(8, max_images * rows_per_image - 6)
    total_char_budget = max(
        128,
        max_images * preset.readable_chars_per_image - 512,
    )
    delimiter = "\n" if "\n" in text else "↵"
    lines = text.split(delimiter)
    original_lines = len(lines)
    shape = shape or _classify_content(text)

    def line_rows(line: str) -> int:
        return max(1, math.ceil(len(line) / cols))

    if shape == "structured":
        rows = chars = cut = 0
        for idx, line in enumerate(lines):
            next_rows = line_rows(line)
            next_chars = len(line) + int(idx > 0)
            if (
                rows + next_rows > total_row_budget
                or chars + next_chars > total_char_budget
            ):
                break
            rows += next_rows
            chars += next_chars
            cut = idx + 1
        if cut:
            head = delimiter.join(lines[:cut])
        else:
            cut = 1
            first_line_budget = min(
                total_char_budget,
                total_row_budget * cols,
            )
            head = lines[0][:first_line_budget]
        omitted = len(text) - len(head)
        marker = _paging_marker(
            original_chars=len(text),
            original_lines=original_lines,
            omitted_chars=omitted,
            omitted_lines=max(0, original_lines - cut),
            head_lines=cut,
            tail_lines=0,
            original_images=estimated_images,
        )
        return head + marker, omitted

    head_row_budget = math.floor(total_row_budget * 0.6)
    tail_row_budget = total_row_budget - head_row_budget
    head_char_budget = math.floor(total_char_budget * 0.6)
    tail_char_budget = total_char_budget - head_char_budget
    head_rows = head_chars = head_cut = 0
    for idx, line in enumerate(lines):
        next_rows = line_rows(line)
        next_chars = len(line) + int(idx > 0)
        if (
            head_rows + next_rows > head_row_budget
            or head_chars + next_chars > head_char_budget
        ):
            break
        head_rows += next_rows
        head_chars += next_chars
        head_cut = idx + 1
    if head_cut == 0:
        head_cut = 1
        first_line_budget = min(
            head_char_budget,
            head_row_budget * cols,
        )
        head = lines[0][:first_line_budget]
        if len(lines) == 1:
            remaining = max(
                0,
                len(text) - len(head),
            )
            tail_budget = min(
                tail_char_budget,
                tail_row_budget * cols,
                remaining,
            )
            tail = lines[0][-tail_budget:] if tail_budget else ""
            omitted = max(
                0,
                len(text) - len(head) - len(tail),
            )
            marker = _paging_marker(
                original_chars=len(text),
                original_lines=1,
                omitted_chars=omitted,
                omitted_lines=0,
                head_lines=1,
                tail_lines=int(bool(tail)),
                original_images=estimated_images,
            )
            return head + marker + tail, omitted
        omitted = len(text) - len(head)
        marker = _paging_marker(
            original_chars=len(text),
            original_lines=original_lines,
            omitted_chars=omitted,
            omitted_lines=max(0, original_lines - 1),
            head_lines=1,
            tail_lines=0,
            original_images=estimated_images,
        )
        return head + marker, omitted
    tail_rows = tail_chars = 0
    tail_start = len(lines)
    for idx in range(len(lines) - 1, head_cut - 1, -1):
        line = lines[idx]
        next_rows = line_rows(line)
        next_chars = len(line) + int(idx < len(lines) - 1)
        if (
            tail_rows + next_rows > tail_row_budget
            or tail_chars + next_chars > tail_char_budget
        ):
            break
        tail_rows += next_rows
        tail_chars += next_chars
        tail_start = idx
    head = delimiter.join(lines[:head_cut])
    if tail_start <= head_cut or tail_start >= len(lines):
        omitted = len(text) - len(head)
        marker = _paging_marker(
            original_chars=len(text),
            original_lines=original_lines,
            omitted_chars=omitted,
            omitted_lines=max(0, original_lines - head_cut),
            head_lines=head_cut,
            tail_lines=0,
            original_images=estimated_images,
        )
        return head + marker, omitted
    tail = delimiter.join(lines[tail_start:])
    tail_lines = len(lines) - tail_start
    omitted = len(text) - len(head) - len(tail)
    marker = _paging_marker(
        original_chars=len(text),
        original_lines=original_lines,
        omitted_chars=omitted,
        omitted_lines=max(0, original_lines - head_cut - tail_lines),
        head_lines=head_cut,
        tail_lines=tail_lines,
        original_images=estimated_images,
    )
    return head + marker + tail, omitted


def _must_keep_native(block: ToolResultBlock) -> bool:
    # Recovery is already the exact native escape hatch for visualized source.
    # Re-imaging its output on the immediately following call would create a
    # recovery-of-recovery loop and hide the text the model explicitly asked
    # to inspect. Old recovery turns may still enter a later history image.
    if block.name.casefold() == "recover_visual_context":
        return True
    return False


def compress_tool_results(  # pylint: disable=R0915
    messages: list[Msg],
    receipt: CompressionReceipt,
    pages_left: int,
    preset: EffortPreset,
) -> int:
    """Rewrite eligible results across the copied request in place."""
    min_chars = preset.tool_result_min_chars

    def compress_part(  # pylint: disable=R0911,R0912
        block: ToolResultBlock,
        text: str,
        provenance: str,
    ) -> list[Any] | None:
        nonlocal pages_left
        if pages_left <= 0:
            return None
        if _must_keep_native(block):
            return None
        recovery_id = make_recovery_id(text, "tool_result", provenance)
        sheet = _factsheet_text(text)
        page_budget = min(
            pages_left,
            MAX_IMAGES_PER_TOOL_RESULT,
        )
        compact_source = _compact_slab_whitespace(text)
        source_shape = _classify_content(compact_source)
        rendered_source = prepare_render_text(compact_source)
        if len(rendered_source) < min_chars:
            return None
        render_payload = rendered_source
        render_columns = measure_content_columns(
            render_payload,
            preset,
        )
        if (
            page_count_for_text(
                render_payload,
                preset,
                columns=render_columns,
            )
            > page_budget
        ):
            rendered_source, _ = _truncate_for_budget(
                rendered_source,
                page_budget,
                preset,
                shape=source_shape,
            )
            render_payload = rendered_source
            render_columns = measure_content_columns(
                render_payload,
                preset,
            )
            if (
                page_count_for_text(
                    render_payload,
                    preset,
                    columns=render_columns,
                )
                > page_budget
            ):
                return None
        estimated_pages = estimate_text_pages(
            render_payload,
            preset,
            columns=render_columns,
        )
        if len(estimated_pages) > page_budget:
            return None
        # The original native part is what disappears. Price the complete
        # replacement that survives on the request: rendered pages plus its
        # factsheet and association/recovery marker.
        marker = f"[Visual pages associated with output from {block.name}."
        marker += (
            f" Exact recovery id: {recovery_id}; prefer query=... or a "
            "bounded line range, not the whole source."
        )
        marker += "]"
        replacement_text = "\n".join(part for part in (sheet, marker) if part)
        if not _profitable(
            text,
            render_payload,
            render_columns,
            preset,
            image_count_cap=page_budget,
            replacement_text=replacement_text,
            estimated_pages=estimated_pages,
        ):
            return None
        pages = render_text_pages(
            render_payload,
            preset,
            page_budget,
            columns=render_columns,
        )
        if not pages:
            return None
        # Images lead the tool-result content; native precision text follows.
        output: list[Any] = [*_data_blocks(pages)]
        if sheet:
            output.append(TextBlock(text=sheet))
        # Anthropic keeps this canonical block order, while AgentScope's OpenAI
        # formatter promotes DataBlocks into a following user message.
        # Describe association, not before/after order, so the same
        # ToolResultBlock stays truthful on both wire formats.
        output.append(TextBlock(text=marker))
        _record_pages(
            receipt,
            len(pages),
            text,
            "tool_result",
            provenance,
            source_estimated_tokens=_count_text_tokens(text),
            replacement_estimated_tokens=_estimate_replacement_tokens(
                replacement_text,
                pages,
            ),
        )
        pages_left -= len(pages)
        return output

    # Request orchestration calls this only after frozen history has replaced
    # its owned prefix. Therefore every result visible here belongs to the
    # native frontier and every generated page survives in the final request.
    for msg in messages:
        for block in msg.content:
            if not isinstance(block, ToolResultBlock):
                continue
            if block.state != ToolResultState.SUCCESS:
                continue
            if isinstance(block.output, str):
                replacement = compress_part(block, block.output, block.id)
                if replacement is not None:
                    block.output = replacement
                continue
            if not isinstance(block.output, list):
                continue
            rewritten: list[Any] = []
            for part_index, part in enumerate(block.output):
                if isinstance(part, TextBlock):
                    replacement = compress_part(
                        block,
                        part.text,
                        f"{block.id}:part:{part_index}",
                    )
                    if replacement is not None:
                        rewritten.extend(replacement)
                        continue
                rewritten.append(part)
            block.output = rewritten
    return pages_left
