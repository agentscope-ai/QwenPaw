# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
"""Shared utilities for file and shell tools."""

import logging
import re
import uuid
from pathlib import Path
from typing import Any

import aiofiles
import aiofiles.os

from ...constant import TRUNCATION_NOTICE_MARKER

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
    read_from: int,
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

    Returns the original text unchanged when it fits within max_bytes, or when the
    last line itself exceeds max_bytes (unhandled edge case).
    """
    text_bytes = text.encode(encoding)

    # Under the byte limit — return as-is without any modification.
    if len(text_bytes) <= max_bytes:
        return text, {}

    # Slice at the byte boundary.
    # Assuming every single line is shorter than DEFAULT_MAX_BYTES, this cut always
    # lands mid-line, guaranteeing at least one complete line before the boundary.
    # Lines that exceed DEFAULT_MAX_BYTES are not handled and may be skipped entirely.
    truncated = text_bytes[:max_bytes]
    # Decode back to str; errors="ignore" drops any split multi-byte character
    # at the cut boundary without raising an exception.
    result = truncated.decode(encoding, errors="ignore")

    # Count '\n' characters to determine how many complete lines are included.
    # The tail after the final '\n' is a partial line that will be covered by
    # the next read starting at next_line.
    newline_count = result.count("\n")

    # Compute the first line number not yet fully included in this chunk.
    # max(1, ...) prevents next_line from equaling start_line when a single line
    # exceeds max_bytes (newline_count == 0), which would make the caller retry
    # the same range indefinitely.
    next_line = start_line + max(1, newline_count)

    if next_line <= total_lines:
        # Truncation fell before the last line — continue reading from next_line.
        read_from = next_line
    elif start_line < total_lines:
        # next_line overshot total_lines, meaning the cut landed inside the last line.
        # Re-read from the start of the last line so the caller gets it in full.
        read_from = total_lines
    else:
        # start_line == total_lines: the last line itself exceeds DEFAULT_MAX_BYTES.
        # This case is outside our handled range — return without a truncation notice.
        return result, {}

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
    # max(1, ...) guards against the theoretical zero-newline case
    # (impossible when every line is shorter than DEFAULT_MAX_BYTES).
    next_line = start_line + max(1, newline_count)
    updated = build_truncation_metadata(
        file_path=info.get("file_path"),
        file_size_bytes=info.get("file_size_bytes"),
        total_lines=total_lines,
        start_line=start_line,
        max_bytes=max_bytes,
        excerpt_bytes=len(result.encode(encoding)),
        read_from=next_line,
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


async def read_file_safe(
    file_path: str,
    max_bytes: int = MAX_FILE_READ_BYTES,
) -> str:
    """Read file with Unicode error handling and memory protection.

    Args:
        file_path: Path to the file.
        max_bytes: Maximum bytes to read into memory (default 1GB).

    Returns:
        File content as string (up to max_bytes).
    """
    stat_result = await aiofiles.os.stat(file_path)
    read_size = min(stat_result.st_size, max_bytes)

    # Use utf-8-sig to auto-remove BOM if present, compatible with plain utf-8
    try:
        async with aiofiles.open(
            file_path,
            "r",
            encoding="utf-8-sig",
        ) as f:
            return await f.read(read_size)
    except UnicodeDecodeError:
        async with aiofiles.open(
            file_path,
            "r",
            encoding="utf-8-sig",
            errors="ignore",
        ) as f:
            return await f.read(read_size)
