# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
"""Shared utilities for file and shell tools."""

import io
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any

from ...constant import TRUNCATION_NOTICE_MARKER
from ...utils.io_utils import run_sync_io

logger = logging.getLogger(__name__)


# Default truncation limit
DEFAULT_MAX_BYTES = 50 * 1024

# Maximum file size to read into memory (200MB)
MAX_FILE_READ_BYTES = 200 * 1024 * 1024
TRUNCATION_METADATA_KEY = "qwenpaw_truncation"
MAX_TRUNCATION_NOTICE_BYTES = 1024


def _fit_truncation_notice(notice: str, info: dict[str, Any]) -> str:
    """Keep the user-facing recovery notice within its byte budget."""
    if len(notice.encode("utf-8")) <= MAX_TRUNCATION_NOTICE_BYTES:
        return notice

    if info.get("continuation_mode") == "artifact":
        compact = (
            TRUNCATION_NOTICE_MARKER
            + "\nOversized single line truncated; recovery details are in "
            "qwenpaw_truncation metadata."
            f"\nThe {info['excerpt_bytes']}-byte preview starts at line "
            f"{info['start_line']}. Inspect the saved artifact for the full "
            "content."
        )
    else:
        compact = (
            TRUNCATION_NOTICE_MARKER
            + "\nOutput truncated; recovery details are in "
            "qwenpaw_truncation metadata."
            f"\nTotal lines: {info['total_lines']}; "
            f"excerpt starts at line {info['start_line']} and contains "
            f"{info['excerpt_bytes']} bytes."
            f"\nContinue with read_file at line {info['read_from']}."
        )
    compact_bytes = compact.encode("utf-8")
    if len(compact_bytes) <= MAX_TRUNCATION_NOTICE_BYTES:
        return compact
    return compact_bytes[:MAX_TRUNCATION_NOTICE_BYTES].decode(
        "utf-8",
        errors="ignore",
    )


# pylint: disable=too-many-arguments
def build_truncation_metadata(
    *,
    file_path: str | None,
    file_size_bytes: int | None,
    total_lines: int,
    start_line: int,
    max_bytes: int,
    excerpt_bytes: int,
    read_from: int | None,
    block_index: int = 0,
) -> dict[str, Any]:
    """Build metadata and the matching user-facing truncation notice."""
    info = {
        "version": 1,
        "file_path": file_path,
        "file_size_bytes": file_size_bytes,
        "total_lines": total_lines,
        "start_line": start_line,
        "max_bytes": max_bytes,
        "excerpt_bytes": excerpt_bytes,
        "read_from": read_from,
    }
    if read_from is None:
        info["continuation_mode"] = "artifact"
        notice = (
            TRUNCATION_NOTICE_MARKER + "\nThe output above was truncated."
            f"\nThe full content is saved to the file and contains {total_lines} lines in total."
            f"\nThis excerpt starts at line {start_line} and covers the first {excerpt_bytes} bytes of an oversized line."
            "\nThe remaining content is part of the same oversized line, so line-based continuation is unavailable."
            f'\nInspect the saved artifact at file_path="{file_path or ""}" with a byte- or structure-aware tool.'
        )
    else:
        notice = (
            TRUNCATION_NOTICE_MARKER + "\nThe output above was truncated."
            f"\nThe full content is saved to the file and contains {total_lines} lines in total."
            f"\nThis excerpt starts at line {start_line} and covers the next {excerpt_bytes} bytes."
            "\nIf the current content is not enough, call `read_file` with "
            f'file_path="{file_path or ""}" start_line={read_from} to read more.'
        )
    info["notice"] = _fit_truncation_notice(notice, info)
    return {TRUNCATION_METADATA_KEY: {str(block_index): info}}


def safe_filename_part(value: str | None) -> str:
    """Return a short filesystem-safe filename component."""
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value or "")[:64].strip("._-")
    return safe or "tool-result"


def save_text_output(
    text: str,
    output_dir: Path | str | None,
    *,
    name_hint: str | None = None,
    encoding: str = "utf-8",
) -> str | None:
    """Save full text output under ``output_dir`` and return its path.

    Raises ``OSError`` if the directory cannot be created or the file cannot
    be written, so callers can log context-specific failure details.
    """
    if output_dir is None:
        return None

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    safe_id = safe_filename_part(name_hint)
    path = output_path / f"{safe_id}-{uuid.uuid4().hex}.txt"
    path.write_text(text, encoding=encoding)
    return str(path)


class ToolResultPruner:
    """Shared block-aware pruning for fresh and retained tool results."""

    def __init__(self, output_dir: Path | str | None) -> None:
        self._output_dir = output_dir or None

    @staticmethod
    def _block_type(block: Any) -> str | None:
        if isinstance(block, dict):
            return block.get("type")
        return getattr(block, "type", None)

    @staticmethod
    def _block_text(block: Any) -> str:
        if isinstance(block, dict):
            return block.get("text", "")
        return getattr(block, "text", "") or ""

    @staticmethod
    def _set_block_text(block: Any, text: str) -> None:
        if isinstance(block, dict):
            block["text"] = text
        else:
            block.text = text

    @staticmethod
    def _merge_metadata(
        metadata: dict[str, Any],
        patch: dict[str, Any],
    ) -> None:
        patch_by_block = patch.get(TRUNCATION_METADATA_KEY)
        if not isinstance(patch_by_block, dict):
            return
        current = metadata.setdefault(TRUNCATION_METADATA_KEY, {})
        if isinstance(current, dict):
            current.update(patch_by_block)

    @staticmethod
    def _encode_text(text: str, encoding: str) -> bytes | None:
        try:
            return text.encode(encoding)
        except UnicodeEncodeError:
            return None

    def _save_fresh_text(self, text: str, encoding: str) -> str | None:
        try:
            saved_path = save_text_output(
                text,
                self._output_dir,
                encoding=encoding,
            )
        except OSError as exc:
            logger.warning(
                "Failed to save tool result to file; returning the original "
                "result: %s",
                exc,
            )
            return None
        if saved_path is None:
            logger.warning(
                "Tool result exceeds the pruning limit but no artifact "
                "directory is configured; returning the original result",
            )
        return saved_path

    def prune_output(
        self,
        output: Any,
        *,
        max_bytes: int,
        metadata: dict[str, Any],
        encoding: str = "utf-8",
        fresh_size_slack_bytes: int = 0,
    ) -> tuple[Any, bool]:
        """Prune string or text-block output and merge metadata in place."""
        if isinstance(output, str):
            pruned, patch = self.prune_text(
                output,
                max_bytes=max_bytes,
                metadata=metadata,
                encoding=encoding,
                fresh_size_slack_bytes=fresh_size_slack_bytes,
            )
            self._merge_metadata(metadata, patch)
            return pruned, pruned != output
        if not isinstance(output, list):
            return output, False

        changed = False
        for index, block in enumerate(output):
            if self._block_type(block) != "text":
                continue
            text = self._block_text(block)
            pruned, patch = self.prune_text(
                text,
                max_bytes=max_bytes,
                metadata=metadata,
                encoding=encoding,
                block_index=index,
                fresh_size_slack_bytes=fresh_size_slack_bytes,
            )
            self._merge_metadata(metadata, patch)
            if pruned != text:
                self._set_block_text(block, pruned)
                changed = True
        return output, changed

    def prune_text(
        self,
        text: str,
        *,
        max_bytes: int,
        metadata: dict[str, Any] | None = None,
        encoding: str = "utf-8",
        block_index: int = 0,
        fresh_size_slack_bytes: int = 0,
    ) -> tuple[str, dict[str, Any]]:
        """Prune one text block, preserving fresh content unless saved."""
        if not text:
            return text, {}
        if TRUNCATION_NOTICE_MARKER in text:
            return truncate_text_output(
                text,
                max_bytes=max_bytes,
                metadata=metadata,
                encoding=encoding,
                block_index=block_index,
            )

        text_bytes = self._encode_text(text, encoding)
        if text_bytes is None or (
            len(text_bytes) <= max_bytes + fresh_size_slack_bytes
        ):
            return text, {}

        saved_path = self._save_fresh_text(text, encoding)
        if saved_path is None:
            return text, {}

        candidate, patch = truncate_text_output(
            text,
            start_line=1,
            total_lines=text.count("\n") + 1,
            max_bytes=max_bytes,
            file_path=saved_path,
            file_size_bytes=len(text_bytes),
            encoding=encoding,
            block_index=block_index,
        )
        if TRUNCATION_NOTICE_MARKER not in candidate:
            return text, {}
        return candidate, patch


# pylint: disable=too-many-return-statements
# pylint: disable=too-many-arguments
def _truncate_fresh(
    text: str,
    start_line: int,
    total_lines: int,
    max_bytes: int,
    file_path: str | None,
    file_size_bytes: int | None,
    encoding: str,
    block_index: int,
) -> tuple[str, dict[str, Any]]:
    """Truncate fresh text (no prior truncation marker) by bytes with line integrity.

    Slices at the byte boundary and appends a truncation notice with a continuation
    hint so callers know which line to read next.

    An oversized final line gets a bounded preview backed by the saved artifact;
    line-based continuation is intentionally disabled for that preview.
    """
    text_bytes = text.encode(encoding)

    # Under the byte limit — return as-is without any modification.
    if len(text_bytes) <= max_bytes:
        return text, {}

    # Slice at the byte boundary.
    # This can land mid-line. Oversized final lines are kept as bounded,
    # artifact-backed previews below instead of being restored in full.
    truncated = text_bytes[:max_bytes]
    # Decode back to str; errors="ignore" drops any split multi-byte character
    # at the cut boundary without raising an exception.
    result = truncated.decode(encoding, errors="ignore")

    # Count '\n' characters to determine how many complete lines are included.
    # The tail after the final '\n' is a partial line that will be covered by
    # the next read starting at next_line.
    newline_count = result.count("\n")

    # Compute the first line number not yet fully included in this chunk.
    next_line = start_line + max(1, newline_count)

    if newline_count == 0:
        # The preview contains no complete line, even when later lines exist
        # in the source. Advancing to start_line + 1 would silently skip the
        # unshown remainder of the current oversized line, while repeating
        # start_line cannot make progress. Recover from the artifact instead.
        read_from = None
    elif next_line <= total_lines:
        # Truncation fell before the last line — continue reading from next_line.
        read_from = next_line
    elif start_line < total_lines:
        # next_line overshot total_lines, meaning the cut landed inside the last line.
        # Re-read from the start of the last line so the caller gets it in full.
        read_from = total_lines
    else:
        # Keep the bounded preview and direct recovery to the saved artifact;
        # line pagination cannot advance safely from this range.
        read_from = None

    metadata = build_truncation_metadata(
        file_path=file_path,
        file_size_bytes=file_size_bytes or len(text_bytes),
        total_lines=total_lines,
        start_line=start_line,
        max_bytes=max_bytes,
        excerpt_bytes=len(result.encode(encoding)),
        read_from=read_from,
        block_index=block_index,
    )
    info = metadata[TRUNCATION_METADATA_KEY][str(block_index)]
    return result + info["notice"], metadata


def _legacy_truncation_metadata(
    text: str,
    block_index: int,
) -> dict[str, Any]:
    """Recover enough metadata to compact persisted pre-metadata results."""
    notice = text.split(TRUNCATION_NOTICE_MARKER, 1)[1]
    patterns = {
        "total_lines": r"contains (\d+) lines in total",
        "start_line": r"starts at line (\d+)",
        "max_bytes": r"covers the next (\d+) bytes",
        "read_from": r"start_line=(\d+) to read more",
    }
    values = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, notice)
        if not match:
            return {}
        values[key] = int(match.group(1))
    path_match = re.search(
        r'file_path=(?:"(?P<quoted>[^"]*)"|(?P<legacy>.*?)) '
        r"start_line=\d+ to read more",
        notice,
    )
    file_path = None
    if path_match:
        file_path = path_match.group("quoted")
        if file_path is None:
            file_path = path_match.group("legacy")
    return build_truncation_metadata(
        file_path=file_path,
        file_size_bytes=None,
        excerpt_bytes=len(text.split(TRUNCATION_NOTICE_MARKER, 1)[0].encode()),
        total_lines=values["total_lines"],
        start_line=values["start_line"],
        max_bytes=values["max_bytes"],
        read_from=values["read_from"],
        block_index=block_index,
    )


def _retruncate(
    text: str,
    max_bytes: int,
    metadata: dict[str, Any] | None,
    encoding: str,
    block_index: int,
) -> tuple[str, dict[str, Any]]:
    """Re-truncate text that was previously truncated (contains TRUNCATION_NOTICE_MARKER).

    Metadata is authoritative. Text parsing is only used to migrate persisted
    results created before truncation metadata was introduced.
    """
    current = dict(metadata or {})
    by_block = current.get(TRUNCATION_METADATA_KEY)
    if not isinstance(by_block, dict):
        by_block = {}
    info = by_block.get(str(block_index))
    if not isinstance(info, dict):
        legacy = _legacy_truncation_metadata(text, block_index)
        legacy_by_block = legacy.get(TRUNCATION_METADATA_KEY, {})
        info = legacy_by_block.get(str(block_index))
    if not isinstance(info, dict):
        return text, {}

    try:
        start_line = int(str(info.get("start_line")))
        total_lines = int(str(info.get("total_lines")))
    except (TypeError, ValueError):
        return text, {}
    if start_line < 1 or total_lines < start_line:
        return text, {}

    old_notice = info.get("notice", "")
    original_content = (
        text[: -len(old_notice)]
        if old_notice and text.endswith(old_notice)
        else text.split(TRUNCATION_NOTICE_MARKER, 1)[0]
    )

    text_bytes = original_content.encode(encoding)

    if len(text_bytes) <= max_bytes:
        return text, {}

    # Re-slice to the new byte limit.
    # Because every line is assumed to be shorter than DEFAULT_MAX_BYTES, the cut
    # always falls somewhere mid-line, so at least one complete line is preserved.
    truncated_bytes = text_bytes[:max_bytes]
    # errors="ignore" silently drops any incomplete multi-byte character at the cut boundary.
    result = truncated_bytes.decode(encoding, errors="ignore")
    # Each '\n' in result corresponds to one fully-included line;
    # anything after the last '\n' is a partial line that was cut off.
    newline_count = result.count("\n")

    # The next read should start at the line immediately after all complete lines.
    # max(1, ...) guards against a zero-newline preview.
    next_line = start_line + max(1, newline_count)
    read_from = (
        None if info.get("continuation_mode") == "artifact" else next_line
    )
    updated = build_truncation_metadata(
        file_path=info.get("file_path"),
        file_size_bytes=info.get("file_size_bytes"),
        total_lines=total_lines,
        start_line=start_line,
        max_bytes=max_bytes,
        excerpt_bytes=len(result.encode(encoding)),
        read_from=read_from,
        block_index=block_index,
    )
    updated_info = updated[TRUNCATION_METADATA_KEY][str(block_index)]
    return result + updated_info["notice"], updated


# pylint: disable=too-many-arguments
def truncate_text_output(
    text: str,
    start_line: int = 1,
    total_lines: int = 0,
    max_bytes: int = DEFAULT_MAX_BYTES,
    file_path: str | None = None,
    file_size_bytes: int | None = None,
    metadata: dict[str, Any] | None = None,
    encoding: str = "utf-8",
    block_index: int = 0,
) -> tuple[str, dict[str, Any]]:
    """Truncate file output by bytes with line integrity.

    If text is under byte limit, return as-is.
    If over limit, truncate at the last complete line that fits,
    allowing the next read to start from a fresh line.

    Dispatches to :func:`_truncate_fresh` for text seen for the first time, or to
    :func:`_retruncate` when the text already contains a TRUNCATION_NOTICE_MARKER
    from a previous pass.

    Args:
        text: The output text to truncate.
        start_line: The starting line number (1-based). Ignored when text already
            contains a truncation notice (values are parsed from the notice instead).
        total_lines: Total lines in the original file. Ignored when text already
            contains a truncation notice (values are parsed from the notice instead).
        max_bytes: Maximum size in bytes.
        file_path: Optional file path to include in the truncation notice.
        encoding: Character encoding used for byte-length calculation and decoding.

    Returns:
        A ``(text, metadata_patch)`` tuple. The patch is empty when no
        truncation was needed.
    """
    if not text:
        return text, {}
    if max_bytes <= 0:
        return text, {}

    try:
        if TRUNCATION_NOTICE_MARKER in text:
            return _retruncate(
                text,
                max_bytes=max_bytes,
                metadata=metadata,
                encoding=encoding,
                block_index=block_index,
            )
        else:
            return _truncate_fresh(
                text,
                start_line=start_line,
                total_lines=total_lines,
                max_bytes=max_bytes,
                file_path=file_path,
                file_size_bytes=file_size_bytes,
                encoding=encoding,
                block_index=block_index,
            )
    except Exception:
        logger.warning(
            "truncate_text_output failed, returning original text",
            exc_info=True,
        )
        return text, {}


def _decode_text_bytes(content: bytes) -> str:
    """Decode a binary snapshot the same way ``read_file_safe`` does."""
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("utf-8-sig", errors="ignore")


def _read_file_bytes_sync(file_path: str, max_bytes: int) -> bytes:
    """Read one byte snapshot from a single opened file handle."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(file_path)
    if not path.is_file():
        raise IsADirectoryError(file_path)
    with path.open("rb") as file:
        read_size = min(os.fstat(file.fileno()).st_size, max_bytes)
        return file.read(read_size)


def _read_file_safe_sync(
    file_path: str,
    max_bytes: int,
) -> str:
    """Read one byte snapshot and normalize newlines to LF."""
    content = _read_file_bytes_sync(file_path, max_bytes)
    text = _decode_text_bytes(content)
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _read_file_native_sync(
    file_path: str,
    max_bytes: int,
) -> str:
    """Read one byte snapshot and keep ``\\n``, ``\\r\\n``, and ``\\r``."""
    content = _read_file_bytes_sync(file_path, max_bytes)
    return _decode_text_bytes(content)


async def read_file_safe(
    file_path: str,
    max_bytes: int = MAX_FILE_READ_BYTES,
) -> str:
    """Read one consistent file snapshot without blocking the event loop.

    Args:
        file_path: Path to the file.
        max_bytes: Maximum bytes to read into memory (default 1GB).

    Returns:
        File content as string (up to max_bytes).
    """
    return await run_sync_io(_read_file_safe_sync, file_path, max_bytes)


async def read_file_native(
    file_path: str,
    max_bytes: int = MAX_FILE_READ_BYTES,
) -> str:
    """Read a snapshot without collapsing newline sequences.

    ``read_file_safe`` folds every ending to ``\\n`` for callers that show
    text to the model. ``edit_file`` uses this form so untouched lines can
    be written back with the endings they had on disk.
    """
    return await run_sync_io(_read_file_native_sync, file_path, max_bytes)


def _to_lf(text: str) -> str:
    """Fold ``\\r\\n`` and lone ``\\r`` to ``\\n``."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _single_newline_style(text: str) -> str | None:
    """Return the only line ending in *text*, or None when styles mix.

    A file with no line endings reports ``\\n``. Callers can then keep
    using one style for the whole snapshot, which matches a uniform
    LF, CRLF, or CR file after a find-and-replace.
    """
    if "\r" not in text:
        return "\n"
    stripped = text.replace("\r\n", "")
    has_crlf = len(stripped) != len(text)
    has_lone_cr = "\r" in stripped
    has_lone_lf = "\n" in stripped
    if has_crlf + has_lone_cr + has_lone_lf > 1:
        return None
    if has_crlf:
        return "\r\n"
    if has_lone_cr:
        return "\r"
    return "\n"


def _apply_newline_style(text: str, newline: str) -> str:
    """Rewrite LF-oriented *text* so every break uses *newline*."""
    normalized = _to_lf(text)
    if newline == "\n":
        return normalized
    return normalized.replace("\n", newline)


def _next_line_ending(text: str, start: int) -> tuple[int, str] | None:
    """First line ending at or after *start*, as ``(index, ending)``."""
    limit = len(text)
    carriage = text.find("\r", start)
    line_feed = text.find("\n", start)
    if carriage < 0 and line_feed < 0:
        return None
    if carriage < 0 or (line_feed >= 0 and line_feed < carriage):
        return line_feed, "\n"
    if carriage + 1 < limit and text[carriage + 1] == "\n":
        return carriage, "\r\n"
    return carriage, "\r"


def _first_line_ending(text: str, start: int, end: int) -> str | None:
    """First line ending that starts in ``text[start:end]``."""
    found = _next_line_ending(text, start)
    if found is None or found[0] >= end:
        return None
    return found[1]


def _last_line_ending(text: str, end: int) -> str | None:
    """Rightmost line ending that starts before *end*."""
    carriage = text.rfind("\r", 0, end)
    line_feed = text.rfind("\n", 0, end)
    if carriage < 0 and line_feed < 0:
        return None
    if line_feed > carriage:
        if line_feed > 0 and text[line_feed - 1] == "\r":
            return "\r\n"
        return "\n"
    if carriage + 1 < len(text) and text[carriage + 1] == "\n":
        return "\r\n"
    return "\r"


def _newline_style_for_span(original: str, start: int, end: int) -> str:
    """Choose the line ending for breaks introduced by a replacement.

    Use the first line ending inside ``original[start:end]``. If that
    span has none, use the ending of the line that contains the match
    (the next ending after *end*, else the previous one). A pure CRLF
    or CR file therefore stays uniform when the match itself has no
    break. A file with no line endings uses LF.
    """
    found = _first_line_ending(original, start, end)
    if found:
        return found
    found = _first_line_ending(original, end, len(original))
    if found:
        return found
    return _last_line_ending(original, start) or "\n"


class _LineEndingCursor:
    """Remember the next line ending while spans move left to right.

    :meth:`style_for` matches :func:`_newline_style_for_span`. The first
    ending at or after a span start decides the style, and that answer
    stays valid through the ending's index. Matches on one line then
    reuse it instead of scanning the suffix again.
    """

    def __init__(self, text: str) -> None:
        self._text = text
        self._limit = len(text)
        self._from = 0
        self._pos = -1
        self._style = "\n"
        self._cached = False

    def style_for(self, start: int, end: int) -> str:
        """Return the line ending to use for ``text[start:end]``."""
        if self._cached and self._from <= start <= self._pos:
            return self._style
        self._style = _newline_style_for_span(self._text, start, end)
        found = _next_line_ending(self._text, start)
        if found is None:
            self._pos = self._limit
        else:
            self._pos = found[0]
        self._from = start
        self._cached = True
        return self._style


def _restyle_newlines(new_text: str, newline: str) -> str:
    """Apply *newline* to breaks inside *new_text*.

    *new_text* is LF-oriented: existing ``\r\n`` and lone ``\r`` are
    folded to ``\n`` first so one intended break cannot become two.
    """
    return _apply_newline_style(new_text, newline)


def _split_line_at(text: str, start: int) -> tuple[str, str, int]:
    """Return ``(content, ending, next_index)`` for the line at *start*."""
    carriage = text.find("\r", start)
    line_feed = text.find("\n", start)
    if carriage < 0 and line_feed < 0:
        return text[start:], "", len(text)
    if carriage < 0 or (line_feed >= 0 and line_feed < carriage):
        return text[start:line_feed], "\n", line_feed + 1
    if carriage + 1 < len(text) and text[carriage + 1] == "\n":
        return text[start:carriage], "\r\n", carriage + 2
    return text[start:carriage], "\r", carriage + 1


def _advance_lf_offset(
    original: str,
    orig_index: int,
    norm_index: int,
    target: int,
) -> tuple[int, int]:
    """Advance an LF-view cursor to *target* and return the new indexes.

    ``\\r\\n`` counts as one character on the LF view. *target* is an
    offset in ``0..len(lf_view)`` and must not precede *norm_index*.
    Runs without ``\\r`` are skipped in one search because those
    characters are one-to-one. The cursor moves forward only, so one
    replace can map each match as it is found.
    """
    limit = len(original)
    while norm_index < target and orig_index < limit:
        if original[orig_index] != "\r":
            budget = target - norm_index
            window_end = orig_index + budget
            next_cr = original.find("\r", orig_index, window_end)
            if next_cr < 0:
                step = min(budget, limit - orig_index)
                orig_index += step
                norm_index += step
            else:
                gap = next_cr - orig_index
                orig_index = next_cr
                norm_index += gap
            continue
        if orig_index + 1 < limit and original[orig_index + 1] == "\n":
            orig_index += 2
        else:
            orig_index += 1
        norm_index += 1
    return orig_index, norm_index


def _join_preserving_lf_breaks(left: str, right: str) -> str:
    """Join *left* and *right* without collapsing a lone CR and a lone LF.

    A real CRLF is never split, so a span ending in ``\\r`` is a lone CR
    and a span starting with ``\\n`` is a lone LF. Insert one ``\\n``
    between them so the LF view keeps both breaks.
    """
    if left.endswith("\r") and right.startswith("\n"):
        return left + "\n" + right
    return left + right


def _write_preserving_lf_breaks(
    buffer: io.StringIO,
    tail: str,
    part: str,
) -> str:
    """Write *part* and return the last character now at the end.

    Empty parts are skipped so a deleted match cannot hide a lone CR
    from the following LF. The inserted break comes from
    :func:`_join_preserving_lf_breaks` and is decided from the touching
    characters only.
    """
    if not part:
        return tail
    head = part[:1]
    boundary = _join_preserving_lf_breaks(tail, head)
    inserted = boundary[len(tail) : len(boundary) - len(head)]
    if inserted:
        buffer.write(inserted)
    buffer.write(part)
    return part[-1]


def _concat_preserving_lf_breaks(parts: list[str]) -> str:
    """Join *parts* in order with :func:`_join_preserving_lf_breaks`.

    Empty parts are skipped. Otherwise a deleted match would hide a lone
    CR from the following LF and ``"".join`` would merge them into one
    CRLF.
    """
    buffer = io.StringIO()
    tail = ""
    for part in parts:
        tail = _write_preserving_lf_breaks(buffer, tail, part)
    text = buffer.getvalue()
    buffer.close()
    return text


def _line_endings_in_span(text: str, start: int, end: int) -> list[str]:
    """Line endings that start in ``text[start:end]``, in order.

    ``\\r\\n`` is one ending. A CR at the last index stays a lone CR
    when the following LF lies outside the span.
    """
    endings: list[str] = []
    index = start
    while index < end:
        carriage = text.find("\r", index, end)
        line_feed = text.find("\n", index, end)
        if carriage < 0 and line_feed < 0:
            break
        if carriage < 0 or (line_feed >= 0 and line_feed < carriage):
            endings.append("\n")
            index = line_feed + 1
            continue
        if carriage + 1 < end and text[carriage + 1] == "\n":
            endings.append("\r\n")
            index = carriage + 2
            continue
        endings.append("\r")
        index = carriage + 1
    return endings


def _apply_positional_endings(normalized_new: str, endings: list[str]) -> str:
    """Give each LF in *normalized_new* the ending in the same position.

    A lone CR must not join the next LF into one CRLF. That happens
    when an ending is ``\\r`` and the next piece starts with ``\\n``,
    including consecutive endings ``\\r`` then ``\\n``. The same
    boundary rule as :func:`_join_preserving_lf_breaks` keeps both.
    """
    if all(ending == "\n" for ending in endings):
        return normalized_new
    pieces = normalized_new.split("\n")
    parts: list[str] = []
    for index, piece in enumerate(pieces):
        if index:
            parts.append(endings[index - 1])
        parts.append(piece)
    return _concat_preserving_lf_breaks(parts)


def _cached_restyle(
    normalized_new: str,
    style: str,
    cache: dict[str, str],
) -> str:
    """Rewrite every break in *normalized_new* as *style*, reusing *cache*."""
    cached = cache.get(style)
    if cached is not None:
        return cached
    if style == "\n" or "\n" not in normalized_new:
        cached = normalized_new
    else:
        cached = normalized_new.replace("\n", style)
    cache[style] = cached
    return cached


def _restyle_mixed_replacement(
    original: str,
    start: int,
    end: int,
    normalized_new: str,
    old_breaks: int,
    new_breaks: int,
    cache: dict[str, str],
    styles: _LineEndingCursor,
) -> str:
    """Style *normalized_new* for the match ``original[start:end]``.

    The same LF-view break count reuses that span's endings in order.
    The first break in the replacement takes the first original ending.
    A different count uses one style from *styles*. That lookup matches
    :func:`_newline_style_for_span` and keeps the current line's ending
    so later matches on the line do not scan the suffix again.
    """
    if new_breaks == old_breaks:
        if new_breaks == 0:
            return normalized_new
        endings = _line_endings_in_span(original, start, end)
        if len(endings) == new_breaks:
            return _apply_positional_endings(normalized_new, endings)
    style = styles.style_for(start, end)
    return _cached_restyle(normalized_new, style, cache)


def _replace_empty_pattern(original: str, new_text: str) -> str:
    """Insert *new_text* at every LF-view boundary.

    Matches ``str.replace("", new_text)`` on the LF view. ``\\r\\n`` is
    a single boundary, so nothing is inserted between CR and LF.
    Inserted breaks use the ending of the line that contains the point.
    """
    if new_text == "":
        return original
    if original == "":
        return _restyle_newlines(new_text, "\n")

    parts: list[str] = []
    last_style = "\n"
    index = 0
    limit = len(original)
    while index < limit:
        content, ending, index = _split_line_at(original, index)
        style = ending or last_style
        if ending:
            last_style = ending
        styled = _restyle_newlines(new_text, style)
        for char in content:
            parts.append(styled)
            parts.append(char)
        parts.append(styled)
        if ending:
            parts.append(ending)
    if original.endswith(("\n", "\r")):
        parts.append(_restyle_newlines(new_text, last_style))
    return _concat_preserving_lf_breaks(parts)


def _replace_mixed_newlines(
    original: str,
    old_text: str,
    new_text: str,
) -> str | None:
    """Replace *old_text* without rewriting untouched line endings.

    Each LF-view match is mapped and emitted before the next one is
    found, so the match list and offset table are not retained. A
    replacement with the same number of breaks reuses the matched
    span's endings in order. A different count looks up the line's
    ending once per line instead of rescanning the suffix per match.
    """
    normalized = _to_lf(original)
    if old_text == "":
        return _replace_empty_pattern(original, new_text)

    old_len = len(old_text)
    found_at = normalized.find(old_text)
    if found_at < 0:
        return None

    normalized_new = _to_lf(new_text)
    new_breaks = normalized_new.count("\n")
    old_breaks = old_text.count("\n")
    fallback_styles: dict[str, str] = {}
    styles = _LineEndingCursor(original)
    buffer = io.StringIO()
    tail = ""
    orig_index = 0
    norm_index = 0
    while found_at >= 0:
        gap_start = orig_index
        orig_index, norm_index = _advance_lf_offset(
            original,
            orig_index,
            norm_index,
            found_at,
        )
        orig_start = orig_index
        match_end = found_at + old_len
        orig_index, norm_index = _advance_lf_offset(
            original,
            orig_index,
            norm_index,
            match_end,
        )
        tail = _write_preserving_lf_breaks(
            buffer,
            tail,
            original[gap_start:orig_start],
        )
        tail = _write_preserving_lf_breaks(
            buffer,
            tail,
            _restyle_mixed_replacement(
                original,
                orig_start,
                orig_index,
                normalized_new,
                old_breaks,
                new_breaks,
                fallback_styles,
                styles,
            ),
        )
        found_at = normalized.find(old_text, match_end)
    _write_preserving_lf_breaks(
        buffer,
        tail,
        original[orig_index:],
    )
    text = buffer.getvalue()
    buffer.close()
    return text


def replace_text_preserving_newlines(
    original: str,
    old_text: str,
    new_text: str,
) -> str | None:
    """Replace *old_text* and keep each untouched line's ending.

    *old_text* is matched against an LF view, because model text uses
    ``\\n`` the same way ``read_file`` reports it. Untouched regions are
    copied from *original*. Returns None when *old_text* is absent.

    A file that already uses a single ending (or none) is rewritten with
    that ending, including breaks inside *new_text*. A mixed file keeps
    each original ending. When *new_text* has the same number of LF-view
    breaks as the match, those endings are reused in order. A different
    count styles every new break from the replaced span.
    """
    style = _single_newline_style(original)
    if style is None:
        return _replace_mixed_newlines(original, old_text, new_text)

    normalized = _to_lf(original)
    if old_text not in normalized:
        return None
    # Fold new_text before replace. A trailing lone CR must not join the
    # next untouched LF and collapse into one break inside _to_lf.
    replaced = normalized.replace(old_text, _to_lf(new_text))
    return _apply_newline_style(replaced, style)
