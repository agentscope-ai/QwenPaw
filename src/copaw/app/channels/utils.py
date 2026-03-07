# -*- coding: utf-8 -*-
# pylint: disable=too-many-return-statements
"""
Bridge between channels and AgentApp process: factory to build
ProcessHandler from runner. Shared helpers for channels (e.g. file URL).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse
from urllib.request import url2pathname

from ...constant import WORKING_DIR


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
            path
            and parsed.netloc
            and len(parsed.netloc) == 1
            and os.name == "nt"
        ):
            path = f"{parsed.netloc}:{path}"
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


def _resolve_file_path(file_path: str) -> str:
    """Resolve absolute paths directly; relative paths from ``WORKING_DIR``."""
    path = Path(file_path)
    if path.is_absolute():
        return str(path)
    return str(WORKING_DIR / file_path)


def _check_ffmpeg() -> bool:
    """Check if ffmpeg is available."""
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            check=False,
        )
        return True
    except FileNotFoundError:
        return False


def convert_audio_file_path(
    file_path: str,
    output_format: str = "mp3",
    output_filename: str = "",
) -> tuple[Optional[str], Optional[str]]:
    """Convert a local audio file and return ``(output_path, error)``.

    When no ``output_filename`` is provided, the converted file is written next
    to the input file so channel media stays inside its original media dir.
    """
    if not _check_ffmpeg():
        return None, (
            "ffmpeg is not installed. "
            "Please install ffmpeg (macOS: brew install ffmpeg)."
        )

    file_path = _resolve_file_path(file_path)
    if not os.path.exists(file_path):
        return None, f"The file {file_path} does not exist."
    if not os.path.isfile(file_path):
        return None, f"The path {file_path} is not a file."

    output_format = output_format.lower().strip()
    if output_format not in ("mp3", "wav"):
        return None, (
            f"Unsupported output format '{output_format}'. "
            "Supported formats: mp3, wav"
        )

    input_path = Path(file_path)
    if output_filename:
        output_path = Path(_resolve_file_path(output_filename))
    else:
        output_path = input_path.with_suffix(f".{output_format}")

    try:
        output_path = output_path.resolve()
    except Exception:
        return None, f"Could not resolve output path for {output_path!s}."

    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = ["ffmpeg", "-y", "-i", str(file_path)]
    if output_format == "mp3":
        cmd.extend(["-codec:a", "libmp3lame", "-q:a", "2"])
    else:
        cmd.extend(["-codec:a", "pcm_s16le"])
    cmd.append(str(output_path))

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None, f"ffmpeg conversion failed:\n{result.stderr}"
    if not output_path.exists():
        return None, "ffmpeg ran but output file was not created."
    return str(output_path), None


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
