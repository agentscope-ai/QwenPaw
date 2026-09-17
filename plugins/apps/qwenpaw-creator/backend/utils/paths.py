# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Canonical Creator media paths exposed through the ``/generated`` route.

The HTTP route is a stable transport surface for the current UI.  Its first
path segment always names one of the four on-disk media namespaces; no
``CREATOR_DATA_ROOT/generated`` directory or legacy prefix mapping exists.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
import os
from pathlib import Path
import re
import stat
from urllib.parse import quote, unquote, urlsplit
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_MEDIA_TASK_ID: ContextVar[str | None] = ContextVar(
    "creator_media_task_id",
    default=None,
)
_MEDIA_PROJECT_ID: ContextVar[str | None] = ContextVar(
    "creator_media_project_id",
    default=None,
)
_MEDIA_ROOTS = frozenset({"task-work", "previews", "blobs", "artifacts"})


def _creator_data_root() -> Path:
    """Resolve the sole Creator filesystem data root without an import cycle."""

    from services.storage_root import require_creator_data_root

    return require_creator_data_root()


def _safe_parts(parts: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw in parts:
        value = str(raw or "").strip()
        candidate = Path(value)
        if (
            not value
            or candidate.is_absolute()
            or len(candidate.parts) != 1
            or value in {".", ".."}
        ):
            raise ValueError(f"Unsafe Creator media path segment: {raw!r}")
        normalized.append(value)
    return tuple(normalized)


def _task_id(value: str | None = None) -> str:
    identifier = value or _MEDIA_TASK_ID.get() or "unscoped"
    return _safe_parts((identifier,))[0]


def _require_real_directory(path: Path, *, label: str) -> Path:
    try:
        value = path.lstat()
    except FileNotFoundError as exc:
        raise ValueError(f"{label} does not exist: {path}") from exc
    if stat.S_ISLNK(value.st_mode) or not stat.S_ISDIR(value.st_mode):
        raise ValueError(f"{label} must be a real directory: {path}")
    return path


def _ensure_real_child(parent: Path, name: str, *, label: str) -> Path:
    child = parent / name
    try:
        child.mkdir()
    except FileExistsError:
        pass
    return _require_real_directory(child, label=label)


@contextmanager
def media_task_scope(
    task_id: str,
    *,
    project_id: str | None = None,
) -> Iterator[None]:
    """Bind provider/core scratch writes to one durable Project Task.

    ``project_id`` is optional for compatibility callers.  File-native media
    execution always supplies it so process files live below that Project's
    ``runtime/`` directory.
    """

    token = _MEDIA_TASK_ID.set(_task_id(task_id))
    project_token = _MEDIA_PROJECT_ID.set(
        _safe_parts((project_id,))[0] if project_id is not None else None,
    )
    try:
        yield
    finally:
        _MEDIA_PROJECT_ID.reset(project_token)
        _MEDIA_TASK_ID.reset(token)


def task_work_root(task_id: str | None = None) -> Path:
    project_id = _MEDIA_PROJECT_ID.get()
    data_root = _creator_data_root()
    if project_id is not None:
        project_root = _require_real_directory(
            data_root / project_id,
            label="Project root",
        )
        project_file = project_root / "project.json"
        if project_file.is_symlink() or not project_file.is_file():
            raise ValueError(
                "Project-scoped media scratch requires project.json",
            )
        runtime_root = _require_real_directory(
            project_root / "runtime",
            label="Project runtime",
        )
        task_work = _ensure_real_child(
            runtime_root,
            "task-work",
            label="Project task-work",
        )
    else:
        task_work = _ensure_real_child(
            data_root,
            "task-work",
            label="Creator task-work",
        )
    return _ensure_real_child(
        task_work,
        _task_id(task_id),
        label="Task work root",
    )


def ensure_task_work_subdir(*parts: str, task_id: str | None = None) -> Path:
    path = task_work_root(task_id)
    for part in _safe_parts(tuple(parts)):
        path = _ensure_real_child(path, part, label="Task work subdirectory")
    return path


def previews_root() -> Path:
    root = _creator_data_root() / "previews"
    root.mkdir(parents=True, exist_ok=True)
    return root


def ensure_preview_subdir(*parts: str) -> Path:
    path = previews_root().joinpath(*_safe_parts(tuple(parts)))
    path.mkdir(parents=True, exist_ok=True)
    return path


def unique_task_work_path(
    subdir: str,
    suffix: str,
    prefix: str = "",
    *,
    task_id: str | None = None,
) -> Path:
    """Allocate a unique provider/intermediate path in current Task scratch."""

    clean_suffix = suffix if suffix.startswith(".") else f".{suffix}"
    filename = f"{prefix}{uuid4().hex}{clean_suffix}"
    return ensure_task_work_subdir(subdir, task_id=task_id) / filename


def media_url_for(path: Path) -> str:
    """Return a ``/generated`` URL for a canonical Creator media path."""

    resolved = Path(path).resolve()
    data_root = _creator_data_root().resolve()
    try:
        relative = resolved.relative_to(data_root)
    except ValueError as exc:
        raise ValueError(f"Path is outside CREATOR_DATA_ROOT: {path}") from exc
    if relative.parts and relative.parts[0] in _MEDIA_ROOTS:
        url_parts = relative.parts
    elif len(relative.parts) >= 5 and relative.parts[1:3] == (
        "runtime",
        "task-work",
    ):
        url_parts = ("projects", relative.parts[0], *relative.parts[2:])
    else:
        raise ValueError(
            f"Path is not in a served Creator media namespace: {path}",
        )
    encoded = "/".join(quote(part, safe="") for part in url_parts)
    return f"/generated/{encoded}"


def local_path_from_file_url(url: str) -> Path:
    """Resolve a ``file://`` URL to a local path across platforms.

    Percent-decodes the path, maps ``file:///C:/...`` to a Windows drive
    path, accepts UNC hosts only on Windows, and rejects any other remote
    authority.
    """

    parsed = urlsplit(str(url))
    if parsed.scheme != "file":
        raise ValueError(f"Not a file URL: {url}")
    host = (parsed.netloc or "").strip()
    path = unquote(parsed.path)
    if host and host.casefold() != "localhost":
        if os.name == "nt":
            return Path(f"//{host}{path}")
        raise ValueError(f"file URL names a remote authority: {url}")
    if os.name == "nt" and re.match(r"^/[A-Za-z]:", path):
        path = path[1:]
    return Path(path)


def media_path_from_url(url: str) -> Path:
    """Resolve a canonical local ``/generated/{namespace}/...`` URL."""

    parsed = urlsplit(str(url))
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/generated/")
    ):
        raise ValueError(f"Not a canonical Creator media URL: {url}")
    relative_path = parsed.path.removeprefix("/generated/")
    raw_segments = relative_path.split("/")
    if not relative_path or any(not segment for segment in raw_segments):
        raise ValueError("Creator media URL contains an empty path segment")
    raw_parts = tuple(unquote(part) for part in raw_segments)
    parts = _safe_parts(raw_parts)
    root = _creator_data_root().resolve()
    if parts[0] == "projects":
        if len(parts) < 5 or parts[2] != "task-work":
            raise ValueError("Project media URL must name task-work")
        path = root.joinpath(parts[1], "runtime", *parts[2:]).resolve()
    elif parts[0] in _MEDIA_ROOTS:
        path = root.joinpath(*parts).resolve()
    else:
        raise ValueError(
            "Creator media URL must name a canonical media namespace",
        )
    path.relative_to(root)
    return path
