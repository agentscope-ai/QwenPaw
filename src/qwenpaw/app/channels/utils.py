# -*- coding: utf-8 -*-
# pylint: disable=too-many-return-statements
"""
Bridge between channels and AgentApp process: factory to build
ProcessHandler from runner. Shared helpers for channels (e.g. file URL).
"""
from __future__ import annotations

import os
import re
from typing import Any, List, Optional, Tuple
from urllib.parse import urlparse
from urllib.request import url2pathname

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


def make_process_from_runner(runner: Any):
    """
    Use runner.stream_query as the channel's process.

    Each channel does: native -> build_agent_request_from_native()
        -> process(request) -> send on each completed message.
    process is runner.stream_query, same as AgentApp's /process endpoint.

    Usage::
        process = make_process_from_runner(runner)
        manager = ChannelManager.from_env(process)
    """
    return runner.stream_query
