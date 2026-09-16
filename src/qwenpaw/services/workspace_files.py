# -*- coding: utf-8 -*-
"""Safe, bounded filesystem primitives for the unified Files workspace."""

from __future__ import annotations

import base64
import json
import os
import secrets
import stat
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID

from ..access.agent_repository import AgentResourceRole
from ..constant import WORKING_DIR
from ..workspaces.resolver import WorkspaceKind, WorkspaceResolver
from ..workspaces.layout import (
    ARTIFACTS_DIRECTORY,
    LEGACY_ARTIFACTS_DIRECTORY,
)


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


@dataclass(frozen=True, slots=True)
class FilesRootAccess:
    """Files 页面一个明确目录来源的授权结果。"""

    path: Path
    kind: str
    read_only: bool
    workspace_key: str | None = None


@dataclass(frozen=True, slots=True)
class FilesWorkspaceAccess:
    """项目运行目录与 Agent 配置目录的独立权限。"""

    project: FilesRootAccess
    workspace: FilesRootAccess


def resolve_private_task_directory(
    *,
    actor_user_id: UUID,
    agent_id: str,
    conversation_id: str,
    working_dir: Path | None = None,
) -> Path:
    """从服务端身份和会话标识派生私有产物目录，拒绝路径片段注入。"""
    user_id = UUID(str(actor_user_id))
    chat_id = UUID(str(conversation_id))
    resolver = WorkspaceResolver(working_dir=working_dir or WORKING_DIR)
    runtime = resolver.resolve(
        kind=WorkspaceKind.USER_RUNTIME,
        resource_id=agent_id,
        actor_user_id=user_id,
    )
    resolver.ensure_standard_directories(runtime)
    if (runtime.path / ARTIFACTS_DIRECTORY / str(chat_id)).is_symlink():
        raise InvalidWorkspacePath("Task directory cannot be a symlink")
    task = resolve_workspace_path(runtime.path, f"{ARTIFACTS_DIRECTORY}/{chat_id}")
    task.mkdir(parents=True, exist_ok=True)
    return task


def resolve_files_workspace_access(
    *,
    agent_id: str,
    agent_workspace: Path,
    agent_project: Path,
    actor_user_id: UUID | None,
    access_role: AgentResourceRole,
    historical_read_only: bool = False,
    working_dir: Path | None = None,
    agent_workspace_kind: str = "draft",
) -> FilesWorkspaceAccess:
    """从可信身份和 Agent 角色解析 Files 页的两个目录根。"""
    if access_role is AgentResourceRole.USER and not historical_read_only:
        if actor_user_id is None:
            raise ValueError("authenticated_user_required")
        resolver = WorkspaceResolver(working_dir=working_dir or WORKING_DIR)
        runtime = resolver.resolve(
            kind=WorkspaceKind.USER_RUNTIME,
            resource_id=agent_id,
            actor_user_id=actor_user_id,
        )
        resolver.ensure_standard_directories(runtime)
        return FilesWorkspaceAccess(
            project=FilesRootAccess(
                path=runtime.path,
                kind=runtime.kind.value,
                read_only=False,
                workspace_key=runtime.workspace_key,
            ),
            workspace=FilesRootAccess(
                path=Path(agent_workspace),
                kind=agent_workspace_kind,
                read_only=True,
                workspace_key=str(agent_workspace),
            ),
        )

    read_only = historical_read_only
    project_path = Path(agent_project)
    return FilesWorkspaceAccess(
        project=FilesRootAccess(
            path=project_path,
            kind="legacy",
            read_only=read_only,
            workspace_key=str(agent_project),
        ),
        workspace=FilesRootAccess(
            path=Path(agent_workspace),
            kind=agent_workspace_kind,
            read_only=read_only,
            workspace_key=str(agent_workspace),
        ),
    )


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
        if (
            segments[0] == ARTIFACTS_DIRECTORY
            and not (root / ARTIFACTS_DIRECTORY).exists()
            and (root / LEGACY_ARTIFACTS_DIRECTORY).is_dir()
        ):
            segments[0] = LEGACY_ARTIFACTS_DIRECTORY
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
            temporary.write_text(content, encoding="utf-8")
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
