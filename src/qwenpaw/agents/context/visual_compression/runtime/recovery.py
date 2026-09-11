# -*- coding: utf-8 -*-
"""Turn-local source storage and exact visual-context recovery tool."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import logging
import time
from typing import Any

from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolChunk

logger = logging.getLogger(__name__)
_DEFAULT_MAX_CHARS = 12_000
_EXACT_TEXT_BEGIN = "[BEGIN EXACT TEXT]"
_EXACT_TEXT_END = "[END EXACT TEXT]"
_NUMBERED_LINES_BEGIN = "[BEGIN NUMBERED LINES]"
_NUMBERED_LINES_END = "[END NUMBERED LINES]"


def _normalize_integer_argument(
    name: str,
    value: int | str | None,
) -> int | None:
    """Normalize a model-supplied decimal integer without hiding bad input."""
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        digits = stripped[1:] if stripped.startswith("-") else stripped
        if digits and digits.isascii() and digits.isdigit():
            return int(stripped)
    raise ValueError(
        f"Invalid {name}: expected a JSON integer, got {value!r}.",
    )


def _original_offset_from_casefold(
    value: str,
    folded_offset: int,
) -> int:
    """Map an offset in ``value.casefold()`` back to the source string."""
    consumed = 0
    for index, char in enumerate(value):
        next_consumed = consumed + len(char.casefold())
        if folded_offset < next_consumed:
            return index
        consumed = next_consumed
    return len(value)


def _exact_page(  # pylint: disable=R0913
    block_id: str,
    value: str,
    cursor: int,
    max_chars: int,
    *,
    match_char: int | None = None,
    metadata: str | None = None,
) -> str:
    """Return one bounded, directly sliceable source-text page."""
    total = len(value)
    end = min(total, cursor + max_chars)
    while True:
        next_cursor = str(end) if end < total else "none"
        match = f" match_char={match_char}" if match_char is not None else ""
        extra = f" {metadata}" if metadata else ""
        header = (
            f"Visual source {block_id}: start_char={cursor} end_char={end} "
            f"total_chars={total} next_cursor={next_cursor}{match}{extra}\n"
            f"{_EXACT_TEXT_BEGIN}\n"
        )
        footer = f"\n{_EXACT_TEXT_END}"
        result = f"{header}{value[cursor:end]}{footer}"
        excess = len(result) - max_chars
        if excess <= 0 or end <= cursor:
            return result
        end = max(cursor, end - excess)


def _render_numbered_lines(
    block_id: str,
    metadata: str,
    lines: list[str],
    selected: list[int],
) -> str:
    """Render whole physical lines with explicit completeness metadata."""
    body = "".join(f"{idx + 1}: {lines[idx]}" for idx in selected)
    trailing_newline = "" if not body or body.endswith(("\n", "\r")) else "\n"
    return (
        f"Visual source {block_id}: {metadata}\n"
        f"{_NUMBERED_LINES_BEGIN}\n"
        f"{body}{trailing_newline}"
        f"{_NUMBERED_LINES_END}"
    )


def _line_start_offsets(lines: list[str]) -> list[int]:
    """Return each physical line's Unicode-character start offset."""
    offsets: list[int] = []
    offset = 0
    for line in lines:
        offsets.append(offset)
        offset += len(line)
    return offsets


def _line_range_excerpt(  # pylint: disable=R0913,R0914
    block_id: str,
    value: str,
    lines: list[str],
    start: int,
    end: int,
    max_chars: int,
    *,
    source_continues: bool = False,
) -> str:
    """Return a whole-line range page with an explicit continuation line."""
    requested = list(range(start - 1, end))
    selected: list[int] = []
    best: str | None = None
    for idx in requested:
        candidate = [*selected, idx]
        complete = len(candidate) == len(requested) and not source_continues
        next_line = "none" if complete else str(idx + 2)
        metadata = (
            f"mode=line_range returned_start_line={candidate[0] + 1} "
            f"returned_end_line={candidate[-1] + 1} "
            f"total_lines={len(lines)} "
            f"complete={'true' if complete else 'false'} "
            f"next_start_line={next_line}"
        )
        rendered = _render_numbered_lines(
            block_id,
            metadata,
            lines,
            candidate,
        )
        if len(rendered) > max_chars:
            break
        selected = candidate
        best = rendered
    if best is not None:
        return best

    line_offset = _line_start_offsets(lines)[start - 1]
    return _exact_page(
        block_id,
        value,
        line_offset,
        max_chars,
        metadata=(
            f"mode=line_range current_line={start} requested_end_line={end} "
            f"total_lines={len(lines)} continuation=cursor"
        ),
    )


def _query_excerpt(  # pylint: disable=R0913,R0914
    block_id: str,
    value: str,
    lines: list[str],
    query: str,
    start: int,
    end: int,
    max_chars: int,
) -> str:
    """Return matching whole lines and context with explicit result totals."""
    needle = query.casefold()
    matched = [
        idx for idx in range(start - 1, end) if needle in lines[idx].casefold()
    ]
    if not matched:
        return (
            f"No exact line containing {query!r} in {block_id} between "
            f"lines {start} and {end}; source has {len(lines)} lines. "
            "Try a shorter query."
        )

    selected: set[int] = set()
    best: str | None = None
    while True:
        target = next((idx for idx in matched if idx not in selected), None)
        if target is None:
            break
        candidate = selected | set(
            range(max(start - 1, target - 2), min(end, target + 3)),
        )
        visible_matches = [idx for idx in matched if idx in candidate]
        next_match = next(
            (idx for idx in matched if idx not in candidate),
            None,
        )
        metadata = (
            f"mode=query search_start_line={start} search_end_line={end} "
            f"total_matching_lines={len(matched)} "
            f"returned_matching_lines={len(visible_matches)} "
            f"total_lines={len(lines)} "
            f"complete={'true' if next_match is None else 'false'} "
            f"next_start_line="
            f"{'none' if next_match is None else next_match + 1}"
        )
        rendered = _render_numbered_lines(
            block_id,
            metadata,
            lines,
            sorted(candidate),
        )
        if len(rendered) > max_chars:
            break
        selected = candidate
        best = rendered
        if next_match is None:
            break
    if best is not None:
        return best

    first_match = matched[0]
    first_line = lines[first_match]
    folded_match = first_line.casefold().find(needle)
    line_match = _original_offset_from_casefold(
        first_line,
        max(0, folded_match),
    )
    match_char = _line_start_offsets(lines)[first_match] + line_match
    window_start = max(0, match_char - max_chars // 3)
    query_next_line = str(matched[1] + 1) if len(matched) > 1 else "none"
    return _exact_page(
        block_id,
        value,
        window_start,
        max_chars,
        match_char=match_char,
        metadata=(
            f"mode=query match_line={first_match + 1} "
            f"search_start_line={start} search_end_line={end} "
            f"total_matching_lines={len(matched)} "
            f"query_next_start_line={query_next_line} continuation=cursor"
        ),
    )


class TurnRecoveryStore:
    """Exact visual sources shared by one agent turn.

    The runtime heartbeat advances the agent stream in short-lived asyncio
    tasks, so task-local state such as ``ContextVar`` cannot bridge a model
    call and its subsequent tool call.  A store instance is instead created
    by ``AgentBuilder`` and shared explicitly by the visual middleware and
    recovery tool for the lifetime of one ``Runtime.run``.
    """

    def __init__(self) -> None:
        self._blocks: dict[str, str] = {}

    def replace(self, blocks: list[dict[str, Any]]) -> None:
        """Atomically replace sources exposed by the current model request."""
        self._blocks = {
            str(item.get("id")): str(item.get("text", ""))
            for item in blocks
            if item.get("id")
        }

    def clear(self) -> None:
        """Expire all sources from the preceding model request."""
        self._blocks = {}

    def recover(self, block_id: str) -> str | None:
        """Return one exact source block while this turn remains active."""
        return self._blocks.get(block_id)

    def excerpt(  # pylint: disable=R0911,R0912,R0913,R0914
        self,
        block_id: str,
        *,
        query: str | None = None,
        start_line: int | None = None,
        end_line: int | None = None,
        cursor: int | None = None,
        max_chars: int = _DEFAULT_MAX_CHARS,
    ) -> str:
        """Return a bounded excerpt without recreating a huge context loop."""
        if not block_id:
            return "Invalid block_id: expected a non-empty string."
        if query == "":
            return "Invalid query: expected a non-empty substring."
        if start_line is not None and start_line < 1:
            return "Invalid start_line: expected a value >= 1."
        if end_line is not None and end_line < 1:
            return "Invalid end_line: expected a value >= 1."

        value = self.recover(block_id)
        if value is None:
            return f"Unknown or expired visual context id: {block_id}"
        if cursor is not None and (
            query is not None or start_line is not None or end_line is not None
        ):
            return (
                "Invalid recovery arguments: cursor cannot be combined with "
                "query, start_line, or end_line."
            )
        if cursor is not None:
            if cursor < 0 or cursor > len(value):
                return (
                    f"Invalid cursor: {cursor}; expected a Unicode character "
                    f"offset from 0 to {len(value)}."
                )
            return _exact_page(
                block_id,
                value,
                cursor,
                max_chars,
            )

        lines = value.splitlines(keepends=True)
        if query:
            if not lines:
                return (
                    f"No exact line containing {query!r} in {block_id}; "
                    "source has 0 lines."
                )
            search_start = max(
                1,
                int(start_line) if start_line is not None else 1,
            )
            if search_start > len(lines):
                return (
                    f"Invalid start_line: {search_start}; source has "
                    f"{len(lines)} lines."
                )
            search_end = min(
                len(lines),
                int(end_line) if end_line is not None else len(lines),
            )
            if search_end < search_start:
                return (
                    f"Invalid query line range: "
                    f"{search_start}..{search_end}"
                )
            return _query_excerpt(
                block_id,
                value,
                lines,
                query,
                search_start,
                search_end,
                max_chars,
            )
        if start_line is not None or end_line is not None:
            start = max(
                1,
                int(start_line) if start_line is not None else 1,
            )
            if start > len(lines):
                return (
                    f"Invalid start_line: {start}; source has "
                    f"{len(lines)} lines."
                )
            end = min(
                len(lines),
                (int(end_line) if end_line is not None else start + 199),
            )
            if end < start:
                return f"Invalid line range: {start}..{end}"
            return _line_range_excerpt(
                block_id,
                value,
                lines,
                start,
                end,
                max_chars,
                source_continues=(end_line is None and end < len(lines)),
            )
        if len(value) <= max_chars:
            return value
        head = "".join(
            f"{idx + 1}: {line}" for idx, line in enumerate(lines[:30])
        )
        tail_start = max(30, len(lines) - 15)
        tail = "".join(
            f"{idx + 1}: {lines[idx]}" for idx in range(tail_start, len(lines))
        )
        return (
            f"Visual source {block_id} has {len(lines)} lines and "
            f"{len(value)} chars. Full recovery is intentionally not returned "
            "in one tool result because that would recreate the compressed "
            "context. Call again with query=..., start_line/end_line, or "
            "cursor=0 for exact Unicode-text paging.\n\n"
            f"[HEAD]\n{head}\n\n[TAIL]\n{tail}"
        )[:max_chars]


def make_recover_visual_context_tool(
    store: TurnRecoveryStore,
) -> Callable[..., Awaitable[ToolChunk]]:
    """Bind the built-in recovery tool to one turn-local store."""

    async def recover_visual_context(
        block_id: str,
        query: str | None = None,
        start_line: int | str | None = None,
        end_line: int | str | None = None,
        cursor: int | str | None = None,
        **unexpected: Any,
    ) -> ToolChunk:
        """Recover exact source text represented by a visual context block.

        Use this only when an image is ambiguous or the task requires a
        verbatim value that is absent from the adjacent exact-token factsheet.

        Args:
            block_id: The ``vctx_...`` recovery id shown next to a visual
                block.
            query: Preferred exact substring to find; returns matching lines
                with bounded context and explicit result totals. For normal
                exact search, pass only block_id and query. Add start_line or
                end_line only to intentionally restrict the search.
            start_line: Optional 1-based line-range or query-search start.
                Use a JSON integer such as 290, not the string ``"290"``.
            end_line: Optional 1-based line-range or query-search end. A
                line-range request without end_line returns at most 200
                requested lines before response-size paging is applied. Use
                a JSON integer, not a quoted number.
            cursor: Optional 0-based Unicode character offset for exact
                source-text paging. The response supplies ``next_cursor``;
                do not combine this with query or line-range arguments. Use
                a JSON integer, not a quoted number.
        """
        if unexpected:
            names = ", ".join(sorted(unexpected))
            return ToolChunk(
                is_last=True,
                state=ToolResultState.ERROR,
                content=[
                    TextBlock(
                        text=(
                            "Invalid recovery arguments: unexpected "
                            f"parameter(s): {names}."
                        ),
                    ),
                ],
            )
        try:
            start_line = _normalize_integer_argument(
                "start_line",
                start_line,
            )
            end_line = _normalize_integer_argument("end_line", end_line)
            cursor = _normalize_integer_argument("cursor", cursor)
        except ValueError as error:
            return ToolChunk(
                is_last=True,
                state=ToolResultState.ERROR,
                content=[TextBlock(text=str(error))],
            )
        started = time.perf_counter()
        source = store.recover(block_id)
        text = store.excerpt(
            block_id,
            query=query,
            start_line=start_line,
            end_line=end_line,
            cursor=cursor,
        )
        if text.startswith("Invalid "):
            outcome = "invalid_request"
        elif source is None:
            outcome = "expired"
        elif query and text.startswith("No exact line containing"):
            outcome = "no_match"
        else:
            outcome = "success"
        state = (
            ToolResultState.ERROR
            if outcome in {"expired", "invalid_request"}
            else ToolResultState.SUCCESS
        )
        mode = (
            "cursor"
            if cursor is not None
            else (
                "query"
                if query
                else (
                    "line_range"
                    if start_line is not None or end_line is not None
                    else "bounded_default"
                )
            )
        )
        logger.debug(
            "Visual Compact recovery: block_id=%s outcome=%s mode=%s "
            "source_chars=%d returned_chars=%d query_chars=%d elapsed_ms=%.1f",
            block_id,
            outcome,
            mode,
            len(source or ""),
            len(text),
            len(query or ""),
            (time.perf_counter() - started) * 1000,
        )
        return ToolChunk(
            is_last=True,
            state=state,
            content=[TextBlock(text=text)],
        )

    return recover_visual_context


__all__ = [
    "TurnRecoveryStore",
    "make_recover_visual_context_tool",
]
