# -*- coding: utf-8 -*-
"""Safe, bounded filesystem primitives for the unified Files workspace."""

from __future__ import annotations

import base64
import json
import os
import secrets
import stat
import threading
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


DEFAULT_PAGE_SIZE = 200
MAX_PAGE_SIZE = 500
DEFAULT_CHUNK_SIZE = 256 * 1024
MAX_CHUNK_SIZE = 1024 * 1024
MAX_API_PATH_BYTES = 4096

_SKIPPED_NAMES = frozenset(
    {
        ".git",
        ".hypothesis",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "node_modules",
    },
)
_WINDOWS_RESERVED_NAMES = frozenset(
    {
        "aux",
        "con",
        "nul",
        "prn",
        *(f"com{index}" for index in range(1, 10)),
        *(f"lpt{index}" for index in range(1, 10)),
    },
)
_TEXT_EXTENSIONS = frozenset(
    {
        ".bash",
        ".c",
        ".cc",
        ".cpp",
        ".css",
        ".csv",
        ".go",
        ".h",
        ".htm",
        ".html",
        ".ini",
        ".java",
        ".js",
        ".json",
        ".jsx",
        ".less",
        ".log",
        ".md",
        ".mdx",
        ".php",
        ".py",
        ".rb",
        ".rs",
        ".scss",
        ".sh",
        ".sql",
        ".swift",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
    },
)
_IMAGE_EXTENSIONS = frozenset(
    {
        ".bmp",
        ".gif",
        ".ico",
        ".jpeg",
        ".jpg",
        ".png",
        ".svg",
        ".webp",
    },
)
_SAVE_LOCKS = tuple(threading.Lock() for _ in range(64))


class InvalidWorkspacePath(ValueError):
    """Raised when an API path cannot safely resolve below a workspace root."""


class InvalidCursor(ValueError):
    """Raised when a directory cursor is malformed."""


class FileVersionConflict(RuntimeError):
    """Raised when optimistic concurrency detects a changed file."""


def _validate_segment(segment: str, *, portable: bool) -> None:
    """Validate one POSIX API path segment."""
    if not segment or segment in {".", ".."}:
        raise InvalidWorkspacePath("Path contains an invalid segment")
    if "\x00" in segment:
        raise InvalidWorkspacePath("Path contains a null byte")
    if portable and segment.endswith((" ", ".")):
        raise InvalidWorkspacePath(
            "Path segments cannot end with a space or dot",
        )
    if len(segment.encode("utf-8")) > 255:
        raise InvalidWorkspacePath("Path segment is too long")
    windows_stem = segment.split(".", 1)[0].casefold()
    if portable and windows_stem in _WINDOWS_RESERVED_NAMES:
        raise InvalidWorkspacePath("Path uses a reserved Windows name")


def resolve_workspace_path(
    root: Path,
    api_path: str,
    *,
    allow_root: bool = False,
    portable: bool = False,
) -> Path:
    """Resolve a relative POSIX API path below an allowed workspace root."""
    if not isinstance(api_path, str):
        raise InvalidWorkspacePath("Path must be a string")
    if len(api_path.encode("utf-8")) > MAX_API_PATH_BYTES:
        raise InvalidWorkspacePath("Path is too long")
    if "\\" in api_path:
        raise InvalidWorkspacePath("Path must use POSIX separators")
    if api_path.startswith("/") or api_path.startswith("//"):
        raise InvalidWorkspacePath("Absolute paths are not allowed")
    if len(api_path) >= 2 and api_path[1] == ":":
        raise InvalidWorkspacePath("Drive-prefixed paths are not allowed")

    if api_path == "":
        if not allow_root:
            raise InvalidWorkspacePath("Path cannot be empty")
        relative = PurePosixPath()
    else:
        segments = api_path.split("/")
        for segment in segments:
            _validate_segment(segment, portable=portable)
        relative = PurePosixPath(*segments)

    resolved_root = root.resolve()
    resolved_target = (resolved_root / Path(*relative.parts)).resolve()
    try:
        resolved_target.relative_to(resolved_root)
    except ValueError as exc:
        raise InvalidWorkspacePath(
            "Path resolves outside the workspace",
        ) from exc
    return resolved_target


def _encode_cursor(offset: int) -> str:
    payload = json.dumps(
        {"offset": offset},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        padded = f"{cursor}{'=' * (-len(cursor) % 4)}"
        payload = base64.urlsafe_b64decode(padded.encode("ascii"))
        value = json.loads(payload.decode("utf-8"))
        offset = value["offset"]
        if not isinstance(offset, int) or offset < 0:
            raise ValueError
        return offset
    except (KeyError, TypeError, ValueError, UnicodeError) as exc:
        raise InvalidCursor("Invalid directory cursor") from exc


def _preview_kind(path: Path, mode: int) -> str:
    if stat.S_ISDIR(mode):
        return "directory"
    suffix = path.suffix.casefold()
    if suffix in _IMAGE_EXTENSIONS:
        return "image"
    if suffix == ".pdf":
        return "pdf"
    if suffix == ".csv":
        return "csv"
    if suffix in _TEXT_EXTENSIONS or not suffix:
        return "text"
    return "binary"


def _modified_at(info: os.stat_result) -> str:
    """Return an ISO-8601 UTC timestamp for a stat result."""
    return datetime.fromtimestamp(
        info.st_mtime,
        tz=timezone.utc,
    ).isoformat()


def list_directory(
    root: Path,
    api_path: str,
    cursor: str | None,
    limit: int,
) -> dict[str, Any]:
    """List one directory page using ``os.scandir``."""
    directory = resolve_workspace_path(root, api_path, allow_root=True)
    if not directory.is_dir():
        raise NotADirectoryError(api_path)
    offset = _decode_cursor(cursor)
    page_size = min(max(limit, 1), MAX_PAGE_SIZE)
    entries: list[dict[str, Any]] = []

    with os.scandir(directory) as scanner:
        for entry in scanner:
            if entry.name.startswith(".") or entry.name in _SKIPPED_NAMES:
                continue
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            kind = (
                "directory" if entry.is_dir(follow_symlinks=False) else "file"
            )
            relative = (
                PurePosixPath(api_path, entry.name).as_posix()
                if api_path
                else entry.name
            )
            entries.append(
                {
                    "kind": kind,
                    "modified_at": _modified_at(info),
                    "name": entry.name,
                    "path": relative,
                    "preview_kind": _preview_kind(
                        Path(entry.name),
                        info.st_mode,
                    ),
                    "size": info.st_size if kind == "file" else None,
                },
            )

    entries.sort(
        key=lambda item: (
            item["kind"] != "directory",
            item["name"].casefold(),
            item["name"],
        ),
    )
    page = entries[offset : offset + page_size]
    next_offset = offset + len(page)
    has_more = next_offset < len(entries)
    return {
        "directory": api_path,
        "entries": page,
        "has_more": has_more,
        "next_cursor": _encode_cursor(next_offset) if has_more else None,
    }


def file_etag(info: os.stat_result) -> str:
    """Build a weak file version from size and nanosecond modification time."""
    return f'W/"{info.st_mtime_ns}-{info.st_size}"'


def get_file_metadata(root: Path, api_path: str) -> dict[str, Any]:
    """Return metadata without reading file content."""
    target = resolve_workspace_path(root, api_path)
    info = target.stat()
    if not stat.S_ISREG(info.st_mode):
        raise FileNotFoundError(api_path)
    return {
        "etag": file_etag(info),
        "modified_at": _modified_at(info),
        "path": api_path,
        "preview_kind": _preview_kind(target, info.st_mode),
        "size": info.st_size,
    }


def read_file_chunk(
    root: Path,
    api_path: str,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    """Read a bounded text chunk and preserve UTF-8 character boundaries."""
    target = resolve_workspace_path(root, api_path)
    chunk_limit = min(max(limit, 1), MAX_CHUNK_SIZE)

    with target.open("rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise FileNotFoundError(api_path)
        if offset < 0 or offset > info.st_size:
            raise ValueError("Offset is outside the file")
        handle.seek(offset)
        raw = handle.read(chunk_limit)
        actual_start = offset
        while raw and actual_start > 0 and raw[0] & 0xC0 == 0x80:
            raw = raw[1:]
            actual_start += 1
        while raw and actual_start + len(raw) < info.st_size:
            try:
                content = raw.decode("utf-8")
                break
            except UnicodeDecodeError as exc:
                if exc.reason != "unexpected end of data":
                    content = raw.decode("utf-8", errors="replace")
                    break
                extra = handle.read(1)
                if not extra:
                    content = raw.decode("utf-8", errors="replace")
                    break
                raw += extra
        else:
            content = raw.decode("utf-8", errors="replace")
        final_info = os.fstat(handle.fileno())

    if file_etag(final_info) != file_etag(info):
        raise FileVersionConflict(api_path)

    next_offset = actual_start + len(raw)
    return {
        "content": content,
        "encoding": "utf-8",
        "eof": next_offset >= info.st_size,
        "etag": file_etag(info),
        "limit": len(raw),
        "next_offset": next_offset,
        "offset": actual_start,
        "path": api_path,
        "truncated": next_offset < info.st_size,
    }


def save_text_file(
    root: Path,
    api_path: str,
    content: str,
    expected_etag: str | None,
) -> dict[str, Any]:
    """Atomically save text after an optional optimistic concurrency check."""
    target = resolve_workspace_path(root, api_path)
    save_lock = _SAVE_LOCKS[hash(target) % len(_SAVE_LOCKS)]
    with save_lock:
        exists = target.exists()
        if expected_etag is not None:
            if not exists:
                raise FileVersionConflict(api_path)
            current = file_etag(target.stat())
            if expected_etag != current:
                raise FileVersionConflict(api_path)
        elif not exists:
            target = resolve_workspace_path(root, api_path, portable=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        token = secrets.token_hex(8)
        temporary = target.with_name(f".{target.name}.{token}.qwenpaw.tmp")
        try:
            temporary.write_bytes(content.encode("utf-8"))
            os.replace(temporary, target)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        info = target.stat()
        return {
            "etag": file_etag(info),
            "path": api_path,
            "size": info.st_size,
        }
