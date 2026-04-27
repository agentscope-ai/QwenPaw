# -*- coding: utf-8 -*-
# pylint: disable=too-many-return-statements
"""
Bridge between channels and AgentApp process: factory to build
ProcessHandler from runner. Shared helpers for channels (e.g. file URL).
"""
from __future__ import annotations

import os
import re
from typing import Any, List, Optional
from urllib.parse import urlparse
from urllib.request import url2pathname

_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")


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


def split_text(text: str, max_len: int = 3000) -> List[str]:
    """Split text into chunks that fit within max_len characters.

    Splits at newline boundaries to preserve formatting. If a single
    line exceeds max_len it is hard-split at max_len.

    Markdown code fences are tracked so that a chunk ending inside an
    open fence gets a closing fence appended and the next chunk gets
    a matching opening fence prepended, keeping code blocks rendered
    correctly across split messages.
    """
    if len(text) <= max_len:
        return [text]

    chunks: List[str] = []
    current: List[str] = []
    current_len = 0
    fence_open: str = ""

    def _flush() -> None:
        nonlocal fence_open
        body = "".join(current).rstrip("\n")
        if fence_open:
            body += "\n```"
        chunks.append(body)
        current.clear()

    for line in text.split("\n"):
        line_with_nl = line + "\n"
        stripped = line.strip()

        if _FENCE_RE.match(stripped):
            if fence_open:
                fence_open = ""
            else:
                fence_open = stripped

        if current and current_len + len(line_with_nl) > max_len:
            saved_fence = fence_open
            _flush()
            current_len = 0
            if saved_fence:
                fence_open = saved_fence
                reopener = saved_fence + "\n"
                current.append(reopener)
                current_len += len(reopener)

        if len(line_with_nl) > max_len:
            for i in range(0, len(line), max_len):
                chunks.append(line[i : i + max_len])
        else:
            current.append(line_with_nl)
            current_len += len(line_with_nl)

    if current:
        chunks.append("".join(current).rstrip("\n"))

    return [c for c in chunks if c.strip()]


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
