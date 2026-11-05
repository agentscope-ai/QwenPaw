# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
"""File search tools: grep (content search) and glob (file discovery)."""

import asyncio
import codecs
import fnmatch
import io
import logging
import os
import re
import threading
from collections import deque
from pathlib import Path
from typing import BinaryIO, Iterator, Optional

from agentscope.message import TextBlock
from agentscope.tool import ToolChunk
from agentscope.message import ToolResultState

from ...config.context import get_tool_base_dir
from ...runtime.tool_registry import tool_descriptor
from .file_io import _resolve_file_path
from .utils import _decode_capped_text_snapshot
from ..utils.file_handling import (
    _FallbackSignals,
    _UTF8_BOM,
    _choose_fallback_decoding,
    _feed_gbk_pair_trails,
    _lossy_saw_three_byte_char,
    _lossy_text_stats,
    single_line_log_value,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BINARY_EXTENSIONS = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".ico",
        ".webp",
        ".svg",
        ".mp3",
        ".mp4",
        ".avi",
        ".mov",
        ".mkv",
        ".flac",
        ".wav",
        ".zip",
        ".tar",
        ".gz",
        ".bz2",
        ".7z",
        ".rar",
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".bin",
        ".dat",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".otf",
        ".pyc",
        ".pyo",
        ".class",
        ".o",
        ".a",
    },
)

_SKIP_DIRS = frozenset(
    {
        ".git",
        ".svn",
        ".hg",
        "node_modules",
        "__pycache__",
        ".tox",
        ".nox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "venv",
        ".eggs",
        "dist",
        "build",
        ".next",
        ".nuxt",
    },
)

_MAX_MATCHES = 200
# Directory scans skip files above this size. An explicit file is not capped.
_MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB
# Reads stay in chunks so a large explicit file is never loaded at once.
_GREP_READ_CHUNK = 64 * 1024
# Strict UTF-8 is probed before the shared fallback choice.
_GREP_UTF8_ENCODINGS = ("utf-8-sig", "utf-8")
# Omitted ``max_bytes`` means the directory cap. ``None`` means no cap.
_GREP_MAX_BYTES_DEFAULT = object()
_MAX_CONTEXT_LINES = 5
_MAX_OUTPUT_CHARS = 50_000  # ~50 KB
_MAX_FILES_SCANNED = 10_000
_GREP_TIMEOUT = 30  # seconds
_GLOB_TIMEOUT = 15  # seconds

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_text_file(path: Path) -> bool:
    """Heuristic: skip known binary extensions and files > 2 MB."""
    if path.suffix.lower() in _BINARY_EXTENSIONS:
        return False
    try:
        if path.stat().st_size > _MAX_FILE_SIZE:
            return False
    except OSError:
        return False
    return True


def _relative_display(target: Path, root: Path) -> str:
    """Relative path with forward slashes (even on Windows)."""
    try:
        return str(target.relative_to(root)).replace(os.sep, "/")
    except ValueError:
        return str(target).replace(os.sep, "/")


def _make_response(text: str) -> ToolChunk:
    return ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS,
        content=[TextBlock(type="text", text=text)],
    )


def _compile_search_pattern(
    pattern: str,
    is_regex: bool,
    flags: int,
) -> "re.Pattern[str]":
    """Compile a grep pattern.

    When *is_regex* is False, the pattern is treated as a literal string.
    Pipe-separated alternatives (``a|b|c``) are supported as OR matching,
    similar to ``grep -E``, with each alternative escaped individually.
    """
    if is_regex:
        expr = pattern
    elif "|" in pattern:
        parts = [part for part in pattern.split("|") if part]
        if not parts:
            expr = re.escape(pattern)
        else:
            expr = "|".join(re.escape(part) for part in parts)
    else:
        expr = re.escape(pattern)
    return re.compile(expr, flags)


def _resolve_search_root(
    path: Optional[str],
    require_dir: bool = False,
) -> "Path | ToolChunk":
    """Resolve and validate a search root path.

    Defaults to the PRIMARY project directory — extra roots are never
    scanned implicitly (they can be searched by explicit path).
    Returns a ``Path`` on success or a ``ToolChunk`` error.
    """
    if path:
        try:
            search_root = Path(_resolve_file_path(path))
        except ValueError as e:
            return _make_response(f"Error: {e}")
    else:
        search_root = get_tool_base_dir()
    try:
        exists = search_root.exists()
    except OSError as e:
        return _make_response(
            f"Error: Cannot access path {search_root} — {e}",
        )
    if not exists:
        return _make_response(
            f"Error: The path {search_root} does not exist.",
        )
    if require_dir and not search_root.is_dir():
        return _make_response(
            f"Error: The path {search_root} is not a directory.",
        )
    return search_root


def _append_output_line(
    matches: list[str],
    total_chars: int,
    line: str,
) -> tuple[bool, int]:
    """Append *line* to *matches* if limits allow."""
    if len(matches) >= _MAX_MATCHES:
        return False, total_chars
    projected_total = total_chars + len(line) + 1
    if projected_total > _MAX_OUTPUT_CHARS:
        return False, total_chars
    matches.append(line)
    return True, projected_total


def _format_grep_line(
    disp_path: str,
    ln: int,
    content: str,
    is_hit: bool,
    *,
    show_file: bool,
) -> str:
    prefix = ">" if is_hit else " "
    if show_file:
        return f"{disp_path}:{ln}:{prefix} {content}"
    return f"{ln}:{prefix} {content}"


def _emit_file_header_if_needed(
    disp_path: str,
    *,
    show_file: bool,
    single_file: bool,
    headers_emitted: set[str],
    matches: list[str],
    total_chars: int,
) -> tuple[bool, int]:
    """Emit a file header when *show_file* is False and multiple files match."""
    if show_file or single_file or disp_path in headers_emitted:
        return True, total_chars

    if headers_emitted and not (matches and matches[-1] == "---"):
        success, total_chars = _append_output_line(matches, total_chars, "---")
        if not success:
            return False, total_chars

    success, total_chars = _append_output_line(matches, total_chars, disp_path)
    if not success:
        return False, total_chars

    headers_emitted.add(disp_path)
    return True, total_chars


def _emit_match_entries(
    entries: list[tuple[int, str, bool]],
    disp_path: str,
    matches: list[str],
    total_chars: int,
    *,
    show_file: bool,
    single_file: bool,
    headers_emitted: set[str],
) -> tuple[bool, int]:
    """Append a batch of context entries to matches.

    Each entry is a tuple of (line_no, content, is_hit).
    The is_hit flag determines the prefix ('>' for hit, ' ' for context).
    Empty entries list is allowed and will be a no-op.

    Args:
        entries: List of (line_no, content, is_hit) tuples.
        disp_path: Display path for the file.
        matches: List to append formatted entries to (modified in place).
        total_chars: Current character count.

    Returns:
        Tuple of (success, new_total_chars). Success is True if all entries
        were appended, False if limits were reached.
    """
    if not entries:
        return True, total_chars

    success, total_chars = _emit_file_header_if_needed(
        disp_path,
        show_file=show_file,
        single_file=single_file,
        headers_emitted=headers_emitted,
        matches=matches,
        total_chars=total_chars,
    )
    if not success:
        return False, total_chars

    for ln, content, is_hit in entries:
        entry = _format_grep_line(
            disp_path,
            ln,
            content,
            is_hit,
            show_file=show_file,
        )
        success, total_chars = _append_output_line(matches, total_chars, entry)
        if not success:
            return False, total_chars

    return True, total_chars


def _output_context_for_hit(
    hit_line_no: int,
    line_buffer: deque[tuple[int, str]],
    display_path: str,
    context_lines: int,
    matches: list[str],
    total_chars: int,
    *,
    show_file: bool,
    single_file: bool,
    headers_emitted: set[str],
) -> tuple[bool, int]:
    """Output context lines around a hit.

    For each hit, we output lines from (hit - context_lines) to
    (hit + context_lines), clamped to file boundaries. The hit line
    is marked with '>' prefix, others with ' '.

    Uses fast path when hit is found in buffer: direct slice indexing.
    Falls back to range scan for edge cases (e.g., file start/end).

    Args:
        hit_line_no: Line number of the hit.
        line_buffer: Deque of (line_no, content) tuples.
        display_path: Display path for the file.
        context_lines: Number of context lines before/after hit.
        matches: List to append formatted entries to (modified in place).
        total_chars: Current character count.

    Returns:
        Tuple of (success, new_total_chars). Success is False if limits
        were reached during output.
    """
    # Find the index of hit_line_no in the buffer for fast slicing
    # hit_idx is always found since hit_line_no was taken from the buffer
    hit_idx = next(
        idx
        for idx, (line_no, _) in enumerate(line_buffer)
        if line_no == hit_line_no
    )

    slice_start = max(0, hit_idx - context_lines)
    slice_end = min(len(line_buffer), hit_idx + context_lines + 1)

    buffer_slice = list(line_buffer)[slice_start:slice_end]
    entries: list[tuple[int, str, bool]] = [
        (line_no, line_content, line_no == hit_line_no)
        for line_no, line_content in buffer_slice
    ]

    # Batch append all collected entries
    success, total_chars = _emit_match_entries(
        entries,
        display_path,
        matches,
        total_chars,
        show_file=show_file,
        single_file=single_file,
        headers_emitted=headers_emitted,
    )
    if not success:
        return False, total_chars

    # Append separator if needed
    if context_lines > 0:
        success, total_chars = _append_output_line(matches, total_chars, "---")
        if not success:
            return False, total_chars

    return True, total_chars


# ---------------------------------------------------------------------------
# Synchronous workers (run inside asyncio.to_thread)
# ---------------------------------------------------------------------------


class _GrepCancelled(Exception):
    """Raised when *cancel* is set while a file is still being read."""


def _file_exceeds_grep_limit(path: Path) -> bool:
    """Return True when *path* is larger than the directory grep cap.

    Directory walks skip these files. An explicit single-file search
    streams the whole file and does not treat this as truncation.
    Unreadable paths are treated as oversize so a directory walk skips
    them instead of failing the search.
    """
    try:
        return path.stat().st_size > _MAX_FILE_SIZE
    except OSError:
        return True


class _GrepChunkReader:
    """Chunked binary read with a byte cap and cancellation.

    ``hit_eof`` is set once iteration finishes. A cap that lands before
    EOF leaves it false; the extra probe byte is not yielded.
    """

    def __init__(self) -> None:
        self.hit_eof = False

    def iter_chunks(
        self,
        raw: BinaryIO,
        cancel: threading.Event,
        max_bytes: int | None,
    ) -> Iterator[bytes]:
        """Yield pieces of at most ``_GREP_READ_CHUNK`` bytes."""
        read_total = 0
        while max_bytes is None or read_total < max_bytes:
            if cancel.is_set():
                raise _GrepCancelled()
            if max_bytes is None:
                want = _GREP_READ_CHUNK
            else:
                want = min(_GREP_READ_CHUNK, max_bytes - read_total)
            chunk = raw.read(want)
            if not chunk:
                self.hit_eof = True
                return
            read_total += len(chunk)
            yield chunk
            if len(chunk) < want:
                self.hit_eof = True
                return
        if cancel.is_set():
            raise _GrepCancelled()
        if not raw.read(1):
            self.hit_eof = True


def _split_normalized_text(pending: str, text: str) -> tuple[list[str], str]:
    """Split *text* on ``\\n`` only, keeping a partial trailing line.

    ``\\r`` / ``\\r\\n`` are already translated to ``\\n`` by
    ``io.IncrementalNewlineDecoder``. ``str.splitlines`` is not used: it
    also breaks on vertical tab, form feed, and Unicode line separators,
    which text-mode iteration did not.
    """
    if not text:
        return [], pending
    pending += text
    if "\n" not in pending:
        return [], pending
    parts = pending.split("\n")
    tail = parts.pop()
    return [part + "\n" for part in parts], tail


def _iter_decoded_grep_lines(
    raw: BinaryIO,
    encoding: str,
    cancel: threading.Event,
    max_bytes: int | None,
) -> Iterator[str]:
    """Yield lines from *raw* without holding the file as one string.

    ``max_bytes`` is the cap; ``None`` reads until EOF. Pieces are at most
    ``_GREP_READ_CHUNK`` and *cancel* is checked between them. When the
    cap is hit with bytes still left, the trailing incomplete character
    is dropped instead of failing the encoding. At real EOF, bytes still
    buffered (an incomplete UTF-8 BOM does not raise on its own) reject
    this encoding.
    """
    decoder = io.IncrementalNewlineDecoder(
        codecs.getincrementaldecoder(encoding)(),
        translate=True,
    )
    pending = ""
    reader = _GrepChunkReader()
    for chunk in reader.iter_chunks(raw, cancel, max_bytes):
        lines, pending = _split_normalized_text(
            pending,
            decoder.decode(chunk, final=False),
        )
        yield from lines

    lines, pending = _split_normalized_text(
        pending,
        decoder.decode(b"", final=reader.hit_eof),
    )
    yield from lines
    buffered, flag = decoder.getstate()
    if reader.hit_eof:
        # utf-8-sig keeps an incomplete BOM and does not raise on final.
        # A non-empty byte buffer is not the pending-CR flag (bit 0, which
        # does not occupy the buffer). Reject the encoding so the ladder
        # matches the strict shared helper. Capped reads stay final=False
        # and keep the dropped trailing character.
        if buffered:
            raise UnicodeDecodeError(
                encoding,
                buffered,
                0,
                len(buffered),
                "incomplete multibyte sequence",
            )
    elif flag & 1:
        # Bit 0 is IncrementalNewlineDecoder's pending-CR flag. The capped
        # snapshot ends on that CR, so normalize it the same way a full
        # decode would (``\\r`` → ``\\n``).
        pending += "\n"
    if pending:
        yield pending


class _GrepStrictProbe:
    """Incremental strict decode that rejects a leftover byte buffer.

    ``utf-8-sig`` keeps an incomplete BOM without raising. A non-empty
    buffer after ``final=True`` is still a failed strict decode.
    """

    def __init__(self, encoding: str) -> None:
        self.decoder = codecs.getincrementaldecoder(encoding)()
        self.ok = True

    def feed(self, chunk: bytes, *, final: bool) -> None:
        """Feed one chunk. Further input is ignored after a failure."""
        if not self.ok:
            return
        try:
            self.decoder.decode(chunk, final=final)
        except UnicodeDecodeError:
            self.ok = False
            return
        if final and self.decoder.getstate()[0]:
            self.ok = False


def _stream_strict_utf8_probes(
    path: Path,
    cancel: threading.Event,
    max_bytes: int | None,
) -> tuple[dict[str, _GrepStrictProbe], bytes]:
    """Feed only strict UTF-8 probes and keep a BOM prefix.

    Reads in ``_GREP_READ_CHUNK`` pieces and stops once every probe has
    failed. The prefix is the leading bytes (at most the UTF-8 BOM) for
    a later fallback decision. This pass does not run GBK pair trails,
    GBK/CP1252 probes, or the lossy UTF-8 ratio.
    """
    probes = {
        encoding: _GrepStrictProbe(encoding)
        for encoding in _GREP_UTF8_ENCODINGS
    }
    prefix = b""
    with open(path, "rb") as raw:
        reader = _GrepChunkReader()
        for chunk in reader.iter_chunks(raw, cancel, max_bytes):
            if len(prefix) < len(_UTF8_BOM):
                prefix += chunk[: len(_UTF8_BOM) - len(prefix)]
            for probe in probes.values():
                probe.feed(chunk, final=False)
            if not any(probe.ok for probe in probes.values()):
                return probes, prefix
        if reader.hit_eof:
            for probe in probes.values():
                probe.feed(b"", final=True)
    return probes, prefix


def _select_grep_fallback_decoding(
    path: Path,
    cancel: threading.Event,
    max_bytes: int | None,
    *,
    bom: bool,
) -> tuple[str, bool]:
    """Pick a legacy or lossy encoding after strict UTF-8 failed.

    Second streaming pass over the same cap. Chunks stay bounded and
    *cancel* is checked between them, so an unlimited file is not loaded
    into one buffer. ``bom`` is the prefix flag from the UTF-8 pass.
    """
    probes = {
        encoding: _GrepStrictProbe(encoding) for encoding in ("gbk", "cp1252")
    }
    lossy = codecs.getincrementaldecoder("utf-8-sig")(errors="replace")
    bad = 0
    good = 0
    saw_non_ascii = False
    saw_three_byte = False
    other = 0
    letters = 0
    unpaired = 0
    pending_lead: int | None = None

    with open(path, "rb") as raw:
        reader = _GrepChunkReader()
        for chunk in reader.iter_chunks(raw, cancel, max_bytes):
            other, letters, unpaired, pending_lead = _feed_gbk_pair_trails(
                chunk,
                other,
                letters,
                unpaired,
                pending_lead,
            )
            for probe in probes.values():
                probe.feed(chunk, final=False)
            text = lossy.decode(chunk, final=False)
            piece_bad, piece_good, piece_saw = _lossy_text_stats(text)
            bad += piece_bad
            good += piece_good
            saw_non_ascii = saw_non_ascii or piece_saw
            saw_three_byte = saw_three_byte or _lossy_saw_three_byte_char(
                text,
            )
        if reader.hit_eof:
            for probe in probes.values():
                probe.feed(b"", final=True)
            text = lossy.decode(b"", final=True)
            piece_bad, piece_good, piece_saw = _lossy_text_stats(text)
            bad += piece_bad
            good += piece_good
            saw_non_ascii = saw_non_ascii or piece_saw
            saw_three_byte = saw_three_byte or _lossy_saw_three_byte_char(
                text,
            )

    # Mirror _signals_for_bytes: accidental 2-byte UTF-8 inside valid GBK
    # (``name=一锘``) must not beat a clean GBK decode.
    if probes["gbk"].ok and not bom and not saw_three_byte:
        saw_non_ascii = False

    choice = _choose_fallback_decoding(
        _FallbackSignals(
            bom=bom,
            bad=bad,
            good=good,
            saw_non_ascii=saw_non_ascii,
            other_trails=other,
            letter_trails=letters,
            unpaired_ascii_letters=unpaired,
            gbk_ok=probes["gbk"].ok,
            cp1252_ok=probes["cp1252"].ok,
        ),
    )
    if choice is None:
        return "latin-1", False
    return choice


def _select_grep_decoding(
    path: Path,
    cancel: threading.Event,
    max_bytes: int | None,
) -> tuple[str, bool]:
    """Return ``(encoding, lossy)`` for a streaming grep read.

    ``max_bytes is None`` reads the whole file. A cap uses that prefix
    and finalizes decoders only at real EOF, matching
    ``decode_text_bytes_with_encoding_fallback`` on the same bytes.

    Valid UTF-8 returns after one strict pass. GBK pair trails, the
    GBK/CP1252 probes, and the lossy ratio run in a second pass, and
    only when every strict UTF-8 probe has failed.
    """
    probes, prefix = _stream_strict_utf8_probes(path, cancel, max_bytes)
    for encoding in _GREP_UTF8_ENCODINGS:
        if probes[encoding].ok:
            return encoding, False
    return _select_grep_fallback_decoding(
        path,
        cancel,
        max_bytes,
        bom=prefix.startswith(_UTF8_BOM),
    )


def _iter_decoded_grep_lines_lossy(
    raw: BinaryIO,
    cancel: threading.Event,
    max_bytes: int | None,
) -> Iterator[str]:
    """Yield lines with UTF-8-SIG ``errors='replace'``.

    ``max_bytes`` is the cap; ``None`` reads until EOF. ``utf-8-sig``
    drops a leading BOM so a dirty byte after it cannot leave U+FEFF
    in the match text.
    """
    decoder = io.IncrementalNewlineDecoder(
        codecs.getincrementaldecoder("utf-8-sig")(errors="replace"),
        translate=True,
    )
    pending = ""
    reader = _GrepChunkReader()
    for chunk in reader.iter_chunks(raw, cancel, max_bytes):
        lines, pending = _split_normalized_text(
            pending,
            decoder.decode(chunk, final=False),
        )
        yield from lines

    lines, pending = _split_normalized_text(
        pending,
        decoder.decode(b"", final=reader.hit_eof),
    )
    yield from lines
    _buffered, flag = decoder.getstate()
    if (not reader.hit_eof) and (flag & 1):
        pending += "\n"
    if pending:
        yield pending


def _read_capped_grep_snapshot(
    path: Path,
    cancel: threading.Event,
    max_bytes: int,
) -> tuple[bytes, bool]:
    """Read at most *max_bytes*, returning ``(data, hit_eof)``.

    *cancel* is checked between chunks. The extra probe byte that
    distinguishes EOF from a longer file is not part of *data*.
    """
    chunks: list[bytes] = []
    with open(path, "rb") as raw:
        reader = _GrepChunkReader()
        chunks.extend(reader.iter_chunks(raw, cancel, max_bytes))
        hit_eof = reader.hit_eof
    return b"".join(chunks), hit_eof


def _iter_snapshot_lines(text: str) -> Iterator[str]:
    """Yield ``\\n``-terminated lines from already-normalized text.

    Matches ``_split_normalized_text`` and ``io.StringIO``: only ``\\n``
    breaks a line, and a final partial line has no extra newline.
    """
    lines, pending = _split_normalized_text("", text)
    yield from lines
    if pending:
        yield pending


def _iter_grep_lines(
    path: Path,
    cancel: threading.Event,
    max_bytes: object = _GREP_MAX_BYTES_DEFAULT,
) -> Iterator[str]:
    """Yield text lines using the shared utf-8 → gbk/cp1252 choice.

    Omitted *max_bytes* uses ``_MAX_FILE_SIZE`` (directory scans). ``None``
    streams an explicit file with no byte cap. A cap reads that prefix
    once, decodes it with the shared helpers, and splits the text. An
    unlimited UTF-8 file is streamed twice (choose, then yield). A
    non-UTF-8 file uses one more pass for the legacy fallback. None of
    these passes holds the whole file.
    """
    limit: int | None
    if max_bytes is _GREP_MAX_BYTES_DEFAULT:
        limit = _MAX_FILE_SIZE
    elif max_bytes is None or isinstance(max_bytes, int):
        limit = max_bytes
    else:
        raise TypeError("max_bytes must be an int or None")

    if limit is not None:
        snapshot, hit_eof = _read_capped_grep_snapshot(path, cancel, limit)
        text = _decode_capped_text_snapshot(
            snapshot,
            file_name=path,
            truncated=not hit_eof,
        )
        yield from _iter_snapshot_lines(text)
        return

    chosen, lossy_utf8 = _select_grep_decoding(path, cancel, None)
    if lossy_utf8:
        logger.debug(
            "File %s read with lossy UTF-8 (mostly valid)",
            single_line_log_value(path),
        )
    elif chosen not in ("utf-8", "utf-8-sig"):
        logger.debug(
            "File %s read with encoding: %s",
            single_line_log_value(path),
            chosen,
        )

    with open(path, "rb") as raw:
        if lossy_utf8:
            yield from _iter_decoded_grep_lines_lossy(raw, cancel, None)
        else:
            yield from _iter_decoded_grep_lines(raw, chosen, cancel, None)


def _walk_and_grep(  # noqa: C901  pylint: disable=too-many-branches,too-many-locals,too-many-statements
    search_root: Path,
    regex: "re.Pattern[str]",
    context_lines: int,
    cancel: threading.Event,
    include_pattern: "str | None",
    show_file: bool = True,
) -> tuple[list[str], str]:
    """Walk *search_root*, grep every text file, return ``(lines, status)``.

    *cancel* is checked frequently; when set the worker stops and returns
    whatever it has so far.  *status* is one of ``"ok"``, ``"truncated:…"``
    or ``"timeout"``.
    """
    context_lines = min(max(context_lines, 0), _MAX_CONTEXT_LINES)
    single_file = search_root.is_file()

    matches: list[str] = []
    total_chars = 0
    status = "ok"
    headers_emitted: set[str] = set()

    if single_file:
        file_iter: list[Path] = [search_root]
    else:
        file_iter = []
        for dirpath, dirnames, filenames in os.walk(
            search_root,
            followlinks=False,
        ):
            if cancel.is_set():
                status = "timeout"
                break
            dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
            for fname in filenames:
                fp = Path(dirpath) / fname
                if not _is_text_file(fp):
                    continue
                if include_pattern and not fnmatch.fnmatch(
                    fname,
                    include_pattern,
                ):
                    continue
                file_iter.append(fp)
                if len(file_iter) >= _MAX_FILES_SCANNED:
                    break
            if len(file_iter) >= _MAX_FILES_SCANNED:
                break
        file_iter.sort()

    # Sliding window size: context_lines before + hit + context_lines after
    window_size = context_lines * 2 + 1
    middle_idx = context_lines

    for file_path in file_iter:
        if cancel.is_set():
            status = "timeout"
            break

        display_path = (
            file_path.name
            if single_file
            else _relative_display(file_path, search_root)
        )

        # Sliding window holds (line_no, line_content) tuples
        sliding_window: deque[tuple[int, str]] = deque(maxlen=window_size)
        # Indices in window where matches occurred, ordered by position
        hit_indices: list[int] = []

        try:
            # Directory walks skip files above 2 MB. An explicit file is
            # streamed in full so a match past that cap is not missed.
            if not single_file and _file_exceeds_grep_limit(file_path):
                continue
            line_no = 0
            max_bytes = None if single_file else _MAX_FILE_SIZE
            for line in _iter_grep_lines(file_path, cancel, max_bytes):
                if line_no % 1000 == 0 and cancel.is_set():
                    status = "timeout"
                    break

                line_no = line_no + 1
                line_content = line.rstrip("\n").rstrip("\r")
                is_match = bool(regex.search(line_content))

                sliding_window.append((line_no, line_content))
                if is_match:
                    hit_indices.append(len(sliding_window) - 1)

                if len(sliding_window) == window_size:
                    # Process hits that are before the middle of the window.
                    # These hits have collected their full context (context_lines after).
                    while hit_indices and hit_indices[0] < middle_idx:
                        hit_line = sliding_window[hit_indices.pop(0)][0]
                        success, total_chars = _output_context_for_hit(
                            hit_line,
                            sliding_window,
                            display_path,
                            context_lines,
                            matches,
                            total_chars,
                            show_file=show_file,
                            single_file=single_file,
                            headers_emitted=headers_emitted,
                        )
                        if not success:
                            status = (
                                f"truncated: match limit ({_MAX_MATCHES})"
                                if len(matches) >= _MAX_MATCHES
                                else f"truncated: output size limit (~{_MAX_OUTPUT_CHARS // 1000}KB)"
                            )
                            break

                    if status != "ok":
                        break
                    # Process the middle position hit if any.
                    # At this point, the hit has context_lines before and after.
                    if hit_indices and hit_indices[0] == middle_idx:
                        hit_line = sliding_window[hit_indices.pop(0)][0]
                        success, total_chars = _output_context_for_hit(
                            hit_line,
                            sliding_window,
                            display_path,
                            context_lines,
                            matches,
                            total_chars,
                            show_file=show_file,
                            single_file=single_file,
                            headers_emitted=headers_emitted,
                        )
                        if not success:
                            status = (
                                f"truncated: match limit ({_MAX_MATCHES})"
                                if len(matches) >= _MAX_MATCHES
                                else f"truncated: output size limit (~{_MAX_OUTPUT_CHARS // 1000}KB)"
                            )
                            break
                    # Slide the window forward by removing the oldest line.
                    # Adjust remaining hit indices to match new positions.
                    sliding_window.popleft()
                    hit_indices = [i - 1 for i in hit_indices if i > 0]

            if status != "ok":
                break

            # Process any remaining hits in the buffer after EOF.
            # These are hits that never became the middle of a full window
            # (e.g., hits near file start or end).
            for hit_idx in hit_indices:
                hit_line_no = sliding_window[hit_idx][0]
                success, total_chars = _output_context_for_hit(
                    hit_line_no,
                    sliding_window,
                    display_path,
                    context_lines,
                    matches,
                    total_chars,
                    show_file=show_file,
                    single_file=single_file,
                    headers_emitted=headers_emitted,
                )
                if not success:
                    status = (
                        f"truncated: match limit ({_MAX_MATCHES})"
                        if len(matches) >= _MAX_MATCHES
                        else f"truncated: output size limit (~{_MAX_OUTPUT_CHARS // 1000}KB)"
                    )
                    break

        except _GrepCancelled:
            status = "timeout"
            break
        except (OSError, UnicodeDecodeError):
            continue

        if status != "ok":
            break

    return matches, status


def _walk_and_glob(
    search_root: Path,
    pattern: str,
    cancel: threading.Event,
) -> tuple[list[str], bool]:
    """Iterate ``search_root.glob(pattern)`` with cancellation support.

    Returns ``(result_lines, truncated)``.
    """
    results: list[str] = []
    truncated = False

    try:
        for entry in search_root.glob(pattern):
            if cancel.is_set():
                break
            try:
                parts = entry.relative_to(search_root).parts
            except ValueError:
                parts = ()
            if any(p in _SKIP_DIRS for p in parts):
                continue
            display_path = _relative_display(entry, search_root)
            suffix = "/" if entry.is_dir() else ""
            results.append(f"{display_path}{suffix}")
            if len(results) >= _MAX_MATCHES:
                truncated = True
                break
    except OSError:
        pass

    results.sort()
    return results, truncated


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------


@tool_descriptor(
    requires_sandbox=("file_read",),
    async_execution=True,
    tool_type="file",
    target_param="path",
    policy_name="Grep",
    default_policy="allow",
    policy_reason="Content search (global)",
    decision_model_local_read=True,
    ui_description="Search file contents by pattern",
    ui_icon="🔍",
)
async def grep_search(
    pattern: str,
    path: Optional[str] = None,
    is_regex: bool = False,
    case_sensitive: bool = True,
    context_lines: int = 0,
    include_pattern: Optional[str] = None,
    show_file: bool = True,
) -> ToolChunk:
    """Search file contents by pattern, recursively. Relative paths resolve
    from the project directory. Output format: ``path:line_number: content``.

    When *show_file* is False, each match line omits the file path prefix
    (``line_number:> content``).  For multi-file searches, the file path
    is printed once before that file's matches, with ``---`` separating
    file groups.

    Args:
        pattern (`str`):
            Search string (or regex when *is_regex* is True).
        path (`str`, optional):
            File or directory to search in.  Defaults to the project
            directory.
        is_regex (`bool`, optional):
            Treat *pattern* as a regular expression.  Defaults to False.
        case_sensitive (`bool`, optional):
            Case-sensitive matching.  Defaults to True.
        context_lines (`int`, optional):
            Context lines before and after each match (like grep -C).
            Defaults to 0.  Capped at 5.
        include_pattern (`str`, optional):
            Only search files whose **name** matches this glob
            (e.g. ``"*.py"``).  Defaults to None (all text files).
        show_file (`bool`, optional):
            Include the file path on every output line.  Defaults to True.
            When False, multi-file results group matches by file with the
            path shown once per file and ``---`` between file groups.
    """
    if not pattern:
        return _make_response("Error: No search `pattern` provided.")

    root_or_err = _resolve_search_root(path)
    if isinstance(root_or_err, ToolChunk):
        return root_or_err
    search_root: Path = root_or_err

    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        regex = _compile_search_pattern(pattern, is_regex, flags)
    except re.error as e:
        return _make_response(f"Error: Invalid regex pattern — {e}")

    cancel = threading.Event()

    def _worker() -> tuple[list[str], str]:
        try:
            return _walk_and_grep(
                search_root,
                regex,
                context_lines,
                cancel,
                include_pattern,
                show_file,
            )
        except Exception as exc:
            return [], f"error: {exc}"

    try:
        from ...tool_calls import cancellable_wait

        match_lines, status = await cancellable_wait(
            asyncio.to_thread(_worker),
            fallback_secs=_GREP_TIMEOUT,
            as_kill_deadline=True,
        )
    except (asyncio.TimeoutError, asyncio.CancelledError):
        cancel.set()
        await asyncio.sleep(0.05)
        return _make_response(
            f"Error: Search timed out after {_GREP_TIMEOUT}s. "
            f"Try narrowing the search path or using a more specific pattern.",
        )

    if status.startswith("error:"):
        result = f"Error: grep failed — {status}"
    elif status.startswith("truncated:"):
        # Even if no matches were appended (e.g., first match exceeded limit),
        # we should report truncation, not "No matches found"
        reason = status.split(":", 1)[1].strip()
        if match_lines:
            result = "\n".join(match_lines)
            result += (
                f"\n\n(Results truncated due to {reason}. "
                f"Try narrowing the search path or using a more specific pattern.)"
            )
        else:
            result = (
                f"Results truncated due to {reason}. "
                f"Try narrowing the search path or using a more specific pattern."
            )
    elif not match_lines:
        result = f"No matches found for pattern: {pattern}"
    else:
        result = "\n".join(match_lines)
        if status == "timeout":
            result += (
                f"\n\n(Partial results — search timed out after {_GREP_TIMEOUT}s. "
                f"Try narrowing the search scope.)"
            )

    return _make_response(result)


@tool_descriptor(
    requires_sandbox=("file_read",),
    async_execution=True,
    tool_type="file",
    target_param="path",
    pattern_param="pattern",
    policy_name="Glob",
    default_policy="allow",
    policy_reason="File listing (global)",
    decision_model_local_read=True,
    ui_description="Find files matching a glob pattern",
    ui_icon="📁",
)
async def glob_search(
    pattern: str,
    path: Optional[str] = None,
) -> ToolChunk:
    """Find files matching a glob pattern (e.g. ``"*.py"``, ``"**/*.json"``).
    Relative paths resolve from the project directory.

    Args:
        pattern (`str`):
            Glob pattern to match.
        path (`str`, optional):
            Root directory to search from.  Defaults to the project
            directory.
    """
    if not pattern:
        return _make_response("Error: No glob `pattern` provided.")

    root_or_err = _resolve_search_root(path, require_dir=True)
    if isinstance(root_or_err, ToolChunk):
        return root_or_err
    search_root: Path = root_or_err

    cancel = threading.Event()

    def _worker() -> tuple[list[str], bool]:
        try:
            return _walk_and_glob(search_root, pattern, cancel)
        except Exception:
            return [], False

    try:
        from ...tool_calls import cancellable_wait

        results, truncated = await cancellable_wait(
            asyncio.to_thread(_worker),
            fallback_secs=_GLOB_TIMEOUT,
            as_kill_deadline=True,
        )
    except (asyncio.TimeoutError, asyncio.CancelledError):
        cancel.set()
        await asyncio.sleep(0.05)
        return _make_response(
            f"Error: Glob search timed out after {_GLOB_TIMEOUT}s. "
            f"Try a more specific pattern or narrower search path.",
        )

    if not results:
        return _make_response(f"No files matched pattern: {pattern}")

    text = "\n".join(results)
    if truncated:
        text += f"\n\n(Results truncated at {_MAX_MATCHES} entries.)"

    return _make_response(text)
