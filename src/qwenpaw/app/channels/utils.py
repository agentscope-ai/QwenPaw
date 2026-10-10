# -*- coding: utf-8 -*-
# pylint: disable=too-many-return-statements
"""
Bridge between channels and agent processing: factory to build
ProcessHandler from runner. Shared helpers for channels (e.g. file URL).
"""
from __future__ import annotations

import os
import re
import asyncio
import base64
import binascii
import logging
import mimetypes
import tempfile
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import AsyncIterator, List, Optional, Tuple
from urllib.parse import urlparse
from urllib.request import url2pathname

logger = logging.getLogger(__name__)

DEFAULT_DATA_URL_MAX_BYTES = 50 * 1024 * 1024
_UNSAFE_MEDIA_NAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_DEFAULT_MEDIA_SUFFIXES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/ogg": ".ogg",
    "video/mp4": ".mp4",
}


class MediaDataError(ValueError):
    """Raised when a data URL cannot be safely decoded."""


@dataclass(frozen=True)
class DataUrlMedia:
    """Decoded media data and its normalized MIME metadata."""

    data: bytes
    media_type: str
    suffix: str

    @property
    def size(self) -> int:
        """Return the decoded byte count."""
        return len(self.data)


@dataclass(frozen=True)
class MaterializedMedia:
    """Upload path and optional display name for an owned temporary file."""

    path: str
    filename: Optional[str] = None


def parse_data_url(
    value: str,
    *,
    max_bytes: int = DEFAULT_DATA_URL_MAX_BYTES,
) -> Optional[DataUrlMedia]:
    """Decode a Base64 data URL, or return None for other references."""
    if not isinstance(value, str) or not value.startswith("data:"):
        return None

    try:
        header, encoded = value.split(",", 1)
    except ValueError as exc:
        raise MediaDataError("data URL is missing a payload") from exc

    header_parts = [part.strip().lower() for part in header[5:].split(";")]
    media_type = header_parts[0] or "application/octet-stream"
    if "base64" not in header_parts[1:]:
        raise MediaDataError("data URL is not Base64 encoded")

    compact = "".join(encoded.split())
    if not compact:
        raise MediaDataError("data URL has an empty Base64 payload")
    estimated_size = (len(compact) * 3) // 4
    estimated_size -= compact.endswith("=")
    estimated_size -= compact.endswith("==")
    if estimated_size > max_bytes:
        raise MediaDataError(
            f"data URL exceeds the {max_bytes} byte size limit",
        )

    try:
        data = base64.b64decode(compact, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise MediaDataError("data URL contains invalid Base64") from exc
    if len(data) > max_bytes:
        raise MediaDataError(
            f"data URL exceeds the {max_bytes} byte size limit",
        )

    suffix = mimetypes.guess_extension(media_type, strict=False)
    suffix = suffix or _DEFAULT_MEDIA_SUFFIXES.get(media_type, ".bin")
    return DataUrlMedia(data=data, media_type=media_type, suffix=suffix)


async def parse_data_url_async(
    value: str,
    *,
    max_bytes: int = DEFAULT_DATA_URL_MAX_BYTES,
) -> Optional[DataUrlMedia]:
    """Decode data references in a worker; pass other references through."""
    if not isinstance(value, str) or not value.startswith("data:"):
        return None
    return await asyncio.to_thread(
        parse_data_url,
        value,
        max_bytes=max_bytes,
    )


def data_url_filename(filename_hint: Optional[str], suffix: str) -> str:
    """Choose a display basename independently of the temporary path."""
    name = PureWindowsPath(filename_hint or "").name
    name = _UNSAFE_MEDIA_NAME_RE.sub("_", name).strip(" .")
    if not name:
        return f"file{suffix}"
    return name if Path(name).suffix else f"{name}{suffix}"


def _materialize_data_url(
    value: str,
    directory: Path,
    filename_hint: Optional[str],
    max_bytes: int,
) -> Optional[MaterializedMedia]:
    """Decode and write one owned temporary file in a worker thread."""
    try:
        media = parse_data_url(value, max_bytes=max_bytes)
    except MediaDataError as exc:
        logger.warning(f"media data URL rejected: {exc}")
        return None
    if media is None:
        return None

    directory.mkdir(parents=True, exist_ok=True)
    fd, path = tempfile.mkstemp(
        prefix="outbound_",
        suffix=media.suffix,
        dir=str(directory),
    )
    try:
        with os.fdopen(fd, "wb") as media_file:
            media_file.write(media.data)
        return MaterializedMedia(
            path=path,
            filename=data_url_filename(filename_hint, media.suffix),
        )
    except BaseException:
        _remove_media_file(path)
        raise


def _remove_media_file(path: str) -> None:
    """Remove an owned temporary upload file, tolerating OS errors."""
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


@asynccontextmanager
async def materialize_data_url(
    value: str,
    directory: Path,
    *,
    filename_hint: Optional[str] = None,
    max_bytes: int = DEFAULT_DATA_URL_MAX_BYTES,
) -> AsyncIterator[Optional[MaterializedMedia]]:
    """Prepare media off-loop and clean up only owned temporary files."""
    if not isinstance(value, str) or not value.startswith("data:"):
        yield MaterializedMedia(path=value)
        return

    task = asyncio.create_task(
        asyncio.to_thread(
            _materialize_data_url,
            value,
            directory,
            filename_hint,
            max_bytes,
        ),
    )
    try:
        yield await asyncio.shield(task)
    finally:
        # A cancelled sender must wait for creation before removing the file.
        materialized = await task
        if materialized is not None:
            await asyncio.to_thread(_remove_media_file, materialized.path)


_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")

# Matches a GFM table separator row, e.g. ``| --- | :---: |``.
_TABLE_SEPARATOR_RE = re.compile(
    r"^\s*\|?\s*:?-{3,}:?(\s*\|\s*:?-{3,}:?)*\s*\|?\s*$",
)


def _is_windows_drive(netloc: str) -> bool:
    """Check if netloc looks like a Windows drive letter.

    Handles both the legacy single-letter form (``C``, from
    ``file://C/path``) and the colon form (``C:``, from
    ``file://C:/path``).
    """
    if os.name != "nt" or not netloc:
        return False
    if len(netloc) == 1 and netloc[0].isalpha():
        return True
    if len(netloc) == 2 and netloc[0].isalpha() and netloc[1] == ":":
        return True
    return False


def _is_table_separator(line: str) -> bool:
    """Return True if ``line`` looks like a GFM table separator row."""
    return bool(_TABLE_SEPARATOR_RE.match(line)) and "-" in line


def _split_table_block(
    table_lines: List[str],
    max_len: int,
) -> List[str]:
    """Split a markdown table into chunks, each a complete table.

    Header and separator rows are duplicated into every chunk so the
    output stays renderable on the receiver even when the original
    table exceeds ``max_len``.
    """
    if len(table_lines) < 2:
        return ["\n".join(table_lines)]

    header, separator = table_lines[0], table_lines[1]
    data_rows = table_lines[2:]
    if not data_rows:
        return ["\n".join(table_lines)]

    preamble = header + "\n" + separator
    preamble_len = len(preamble) + 1  # +1 for the \n before first row

    chunks: List[str] = []
    current_rows: List[str] = []
    current_len = preamble_len
    for row in data_rows:
        row_len = len(row) + 1
        if current_rows and current_len + row_len > max_len:
            chunks.append(preamble + "\n" + "\n".join(current_rows))
            current_rows = []
            current_len = preamble_len
        current_rows.append(row)
        current_len += row_len

    if current_rows:
        chunks.append(preamble + "\n" + "\n".join(current_rows))
    return chunks


def _collect_table_lines(
    lines: List[str],
    start: int,
) -> Tuple[List[str], int]:
    """Collect a GFM table starting at ``lines[start]``.

    Returns the table lines and the index of the first line after it.
    """
    table_lines: List[str] = [lines[start], lines[start + 1]]
    cursor = start + 2
    while cursor < len(lines) and "|" in lines[cursor]:
        if _FENCE_RE.match(lines[cursor].strip()):
            break
        table_lines.append(lines[cursor])
        cursor += 1
    return table_lines, cursor


class _SplitBuffer:
    """Accumulator used by :func:`split_text`."""

    def __init__(self, max_len: int) -> None:
        self.max_len = max_len
        self.chunks: List[str] = []
        self._current: List[str] = []
        self._length = 0
        self.fence_open: str = ""

    def _flush(self) -> None:
        """Emit the buffered content, closing an open code fence."""
        body = "".join(self._current).rstrip("\n")
        if self.fence_open:
            body += "\n```"
        self.chunks.append(body)
        self._current.clear()
        self._length = 0

    def _flush_for(self, incoming_len: int) -> None:
        """Flush if appending ``incoming_len`` would overflow ``max_len``."""
        if not self._current or self._length + incoming_len <= self.max_len:
            return
        saved_fence = self.fence_open
        self._flush()
        if saved_fence:
            reopener = saved_fence + "\n"
            self._current.append(reopener)
            self._length = len(reopener)

    def _hard_split_long_line(self, line: str) -> None:
        """Split an oversize single line at ``max_len`` boundaries."""
        for k in range(0, len(line), self.max_len):
            self.chunks.append(line[k : k + self.max_len])

    def emit_line(self, line: str) -> None:
        """Append a source line, hard-splitting if it exceeds ``max_len``."""
        line_with_nl = line + "\n"
        self._flush_for(len(line_with_nl))
        if len(line_with_nl) > self.max_len:
            self._hard_split_long_line(line)
            return
        self._current.append(line_with_nl)
        self._length += len(line_with_nl)

    def emit_table_chunk(self, table_text: str) -> None:
        """Append a self-contained table chunk; emit alone if oversized."""
        block = table_text.rstrip("\n") + "\n"
        if self._current and self._length + len(block) > self.max_len:
            self._flush()
        if len(block) > self.max_len and not self._current:
            self.chunks.append(block.rstrip("\n"))
            return
        self._current.append(block)
        self._length += len(block)

    def finalize(self) -> List[str]:
        """Flush remaining buffered content and return all chunks."""
        if self._current:
            self.chunks.append("".join(self._current).rstrip("\n"))
        return [c for c in self.chunks if c.strip()]


def split_text(text: str, max_len: int = 3000) -> List[str]:
    """Split text into chunks no longer than ``max_len`` characters.

    Splits at newline boundaries to preserve formatting; a single line
    that exceeds ``max_len`` is hard-split.

    Two markdown structures are kept renderable across chunks:

    - **Code fences** (```` ``` ```` / ``~~~``): a chunk ending inside
      an open fence gets a closing fence appended and the next chunk
      gets a matching opening fence prepended.
    - **GFM pipe tables**: a table is treated as an atomic unit and
      only split between data rows; every resulting chunk repeats the
      header and separator so it stays a valid, renderable table
      (otherwise channels like WeChat fall back to plain text).
    """
    if len(text) <= max_len:
        return [text]

    buf = _SplitBuffer(max_len)
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if _FENCE_RE.match(stripped):
            buf.fence_open = "" if buf.fence_open else stripped
            buf.emit_line(line)
            i += 1
            continue

        is_table_start = (
            not buf.fence_open
            and "|" in line
            and i + 1 < len(lines)
            and _is_table_separator(lines[i + 1])
        )
        if is_table_start:
            table_lines, next_i = _collect_table_lines(lines, i)
            for table_chunk in _split_table_block(table_lines, max_len):
                buf.emit_table_chunk(table_chunk)
            i = next_i
            continue

        buf.emit_line(line)
        i += 1

    return buf.finalize()


def file_url_to_local_path(url: str) -> Optional[str]:
    """Convert file:// URL or plain local path to local path string.

    Supports:
    - file:// URL (all platforms): file:///path, file://D:/path,
      file://D:\\path (Windows two-slash).
    - Plain local path: D:\\path, /tmp/foo (no scheme). Pass-through after
      stripping whitespace; no existence check (caller may use Path().exists).

    Returns None only when url is clearly not a local file (e.g. http(s) URL)
    or file URL could not be resolved to a non-empty path.
    """
    if not url or not isinstance(url, str):
        return None
    s = url.strip()
    if not s:
        return None
    parsed = urlparse(s)
    if parsed.scheme == "file":
        path = url2pathname(parsed.path)
        if not path and parsed.netloc:
            path = url2pathname(parsed.netloc.replace("\\", "/"))
        elif (
            path and parsed.netloc and _is_windows_drive(netloc=parsed.netloc)
        ):
            # netloc may be "C:" (new format) or "C" (legacy format)
            drive = (
                parsed.netloc if ":" in parsed.netloc else f"{parsed.netloc}:"
            )
            path = f"{drive}{path}"
        elif path and parsed.netloc and os.name == "nt":
            # UNC: file://server/share/… → \\server\share\…
            path = f"\\\\{parsed.netloc}{path}"
        return path if path else None
    if parsed.scheme in ("http", "https"):
        return None
    if not parsed.scheme:
        return s
    if (
        os.name == "nt"
        and len(parsed.scheme) == 1
        and parsed.path.startswith("\\")
    ):
        return s
    return None
