# -*- coding: utf-8 -*-
"""Workspace API – download / upload the entire WORKING_DIR as a zip.

Also includes agent file management, language settings, audio/transcription
configuration, running config, and system prompt files.
"""

from __future__ import annotations

import asyncio
import copy
import io
import json
import logging
import mimetypes
import secrets
import shutil
import stat
import tempfile
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Literal
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Body,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import ORJSONResponse, Response, StreamingResponse
from watchfiles import awatch, Change
from pydantic import BaseModel, Field

from ..utils import check_upload_size, safe_join, schedule_agent_reload
from ...config import (
    load_config,
    AgentsRunningConfig,
)
from ...config.utils import mutate_config
from ...config.config import (
    AgentProfileConfig,
    EmbeddingModelConfig,
    load_agent_config,
    save_agent_config,
    update_agent_config_async,
)
from ...agents.memory.embedding_model import (
    embedding_vector_space_fingerprint,
    test_embedding_model,
)
from ...agents.memory.agent_md_manager import AgentMdManager
from ...agents.templates import get_workspace_md_template_id
from ...agents.utils import copy_workspace_md_files
from ...constant import BUILTIN_QA_AGENT_ID, SUPPORTED_AGENT_LANGUAGES
from ...services.fs_name_rules import NameRules, probe_name_rules
from ...services.workspace_files import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_PAGE_SIZE,
    FileVersionConflict,
    InvalidCursor,
    InvalidWorkspacePath,
    MAX_PAGE_SIZE,
    file_etag,
    get_file_metadata,
    list_directory,
    read_file_chunk,
    resolve_workspace_path,
    save_text_file,
)
from ...utils.io_utils import (
    get_path_lock,
    run_async_to_completion,
    run_sync_io,
)
from ..agent_context import (
    get_agent_for_request,
    get_agent_project_dir,
    get_project_dir_for_request,
    get_project_dirs_for_request,
)

router = APIRouter(prefix="/workspace", tags=["workspace"])
logger = logging.getLogger(__name__)
_FILESYSTEM_SEMAPHORE = asyncio.Semaphore(8)
_WATCH_HEARTBEAT_SECONDS = 30.0
_WATCH_POLL_TIMEOUT_MS = 1_000


class MdFileInfo(BaseModel):
    """Markdown file metadata."""

    filename: str = Field(..., description="File name")
    path: str = Field(..., description="File path")
    size: int = Field(..., description="Size in bytes")
    created_time: str = Field(..., description="Created time")
    modified_time: str = Field(..., description="Modified time")


class MdFileContent(BaseModel):
    """Markdown file content."""

    content: str = Field(..., description="File content")


class EmbeddingTestResponse(BaseModel):
    """Result of an AgentScope embedding connectivity request."""

    success: bool
    configured_dimensions: int
    actual_dimensions: int | None = None
    latency_ms: int
    message: str


def _dir_stats(root: Path) -> tuple[int, int]:
    """Return (file_count, total_size) for *root* recursively."""
    count = 0
    size = 0
    if root.is_dir():
        for p in root.rglob("*"):
            if p.is_file():
                count += 1
                size += p.stat().st_size
    return count, size


def _zip_directory(root: Path) -> io.BytesIO:
    """Create an in-memory zip archive of *root* and return the buffer.

    All files **and** directories (including empty ones) are included.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in sorted(root.rglob("*")):
            arcname = entry.relative_to(root).as_posix()
            if entry.is_file():
                zf.write(entry, arcname)
            elif entry.is_dir():
                # Zip spec: directory entries end with '/'
                zf.write(entry, arcname + "/")
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# Agent File Management Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/files",
    response_model=list[MdFileInfo],
    summary="List working files",
    description="List all working files (uses active agent)",
)
async def list_working_files(
    request: Request,
) -> list[MdFileInfo]:
    """List working directory markdown files."""
    try:
        workspace = await get_agent_for_request(request)
        workspace_manager = AgentMdManager(
            str(workspace.workspace_dir),
            agent_id=workspace.agent_id,
        )
        files = [
            MdFileInfo.model_validate(file)
            for file in workspace_manager.list_working_mds()
        ]
        return files
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/files/{md_name}",
    response_model=MdFileContent,
    summary="Read a working file",
    description="Read a working markdown file (uses active agent)",
)
async def read_working_file(
    md_name: str,
    request: Request,
) -> MdFileContent:
    """Read a working directory markdown file."""
    try:
        workspace = await get_agent_for_request(request)
        workspace_manager = AgentMdManager(
            str(workspace.workspace_dir),
            agent_id=workspace.agent_id,
        )
        content = workspace_manager.read_working_md(md_name)
        return MdFileContent(content=content)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put(
    "/files/{md_name}",
    response_model=dict,
    summary="Write a working file",
    description="Create or update a working file (uses active agent)",
)
async def write_working_file(
    md_name: str,
    body: MdFileContent,
    request: Request,
) -> dict:
    """Write a working directory markdown file."""
    try:
        workspace = await get_agent_for_request(request)
        workspace_manager = AgentMdManager(
            str(workspace.workspace_dir),
            agent_id=workspace.agent_id,
        )
        workspace_manager.write_working_md(md_name, body.content)
        return {"written": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Coding Mode – full file-tree + file watcher (SSE)
# ---------------------------------------------------------------------------

_SKIP_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        "__pycache__",
        ".venv",
        "node_modules",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".hypothesis",
    },
)


def _should_skip(rel_parts: tuple[str, ...]) -> bool:
    return any(p.startswith(".") or p in _SKIP_NAMES for p in rel_parts)


def _is_skipped_name(name: str) -> bool:
    return name.startswith(".") or name in _SKIP_NAMES


def _list_all_files(workspace_dir: Path) -> list[dict]:
    """Recursively list all non-hidden workspace files.

    Uses ``os.walk(topdown=True)`` and prunes ``dirnames`` in place so that
    we never descend into ``node_modules`` / ``.venv`` / ``.git`` etc. — the
    previous ``Path.rglob('*')`` walked them fully and filtered after the
    fact, which is the dominant cost on real projects. Each file is stat'd
    exactly once. Paths are returned with POSIX ``/`` separators so the
    frontend ``buildTree`` (which splits on ``/``) works on Windows too.
    """
    files: list[dict] = []
    root = str(workspace_dir)
    try:
        for dirpath, dirnames, filenames in os.walk(root, topdown=True):
            # Prune in place — must mutate, not rebind, for os.walk to honor.
            dirnames[:] = sorted(
                d for d in dirnames if not _is_skipped_name(d)
            )
            rel_dir = os.path.relpath(dirpath, root)
            for name in sorted(filenames):
                if _is_skipped_name(name):
                    continue
                full = os.path.join(dirpath, name)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                rel = (
                    name
                    if rel_dir == "."
                    else f"{rel_dir}/{name}".replace(os.sep, "/")
                )
                files.append(
                    {
                        "filename": rel,
                        "path": rel,
                        "size": st.st_size,
                        "modified_time": datetime.fromtimestamp(
                            st.st_mtime,
                            tz=timezone.utc,
                        ).isoformat(),
                    },
                )
    except Exception:
        pass
    return files


# Prefix selecting a non-primary bound project directory by absolute path,
# e.g. ``project:/Users/me/docs``. The path is carried rather than an index
# because the bound list is reorderable ("make primary"): an index would let a
# persisted editor tab silently start pointing at a different directory.
_EXTRA_PROJECT_ROOT_PREFIX = "project:"


async def _resolve_extra_project_root(
    request: Request,
    workspace: Any,
    raw_path: str,
) -> Path:
    """Resolve one bound project directory selected by absolute path.

    The membership check is the authorization boundary for the Files API: a
    path is served only when it is one of the directories this chat actually
    bound. Anything else is rejected outright — never silently downgraded to
    the primary, which would make an out-of-bounds request look like it
    succeeded against the wrong directory.

    Membership is decided by :func:`dir_key`: the candidate is keyed in a
    worker thread and the loop compares strings, touching the filesystem
    not at all. Two things depend on that split.

    The loop must do no I/O. The obvious spelling —
    ``same_dir(candidate, entry.path)`` — resolves *both* sides on every
    iteration, so ten bound directories cost twenty ``resolve()`` calls on
    the event loop per Files request, half of them re-resolving
    ``entry.path``, which ``ResolvedProjectDirs`` already canonicalized.
    One stalled SMB or FUSE mount in the list would then stall every other
    request the process is serving.

    And the comparison must be by directory identity, not by path text. A
    string comparison decides membership on spelling: fold case and an
    unbound ``/srv/REPO`` is served as ``/srv/repo`` on a case-sensitive
    volume; do not fold and a bound directory reached by a symlink, a
    mount alias or a ``..`` detour is refused with 403. Identity is right
    in both directions without knowing anything about the volume.

    A configured directory that does not exist has no identity, so its key
    is its path text and the comparison degrades to the old spelling-based
    one — acceptable, because there is nothing there to serve either way.
    """
    from ...services.project_directory import dir_key

    candidate = raw_path.strip()
    if not candidate:
        raise HTTPException(status_code=400, detail="root path is empty")

    resolved = await get_project_dirs_for_request(request, workspace)
    candidate_key = await run_sync_io(dir_key, candidate)
    for entry in resolved.dirs:
        # An entry built without a key would otherwise match the empty
        # string; only a real key can grant membership.
        if entry.key and entry.key == candidate_key:
            return entry.path
    # The workspace is a legitimate root, but it has its own ``root=workspace``
    # selector; accepting it here too would let one root be addressed two ways.
    raise HTTPException(
        status_code=403,
        detail="Not a bound project directory",
    )


async def _resolve_files_root(
    request: Request,
    workspace: Any,
    root: str,
) -> Path:
    """Resolve the selected project or agent configuration directory.

    Accepted values:

    * ``workspace`` — the agent's own storage root
    * ``project`` — the PRIMARY bound project directory
    * ``project:<absolute path>`` — any other directory bound to this chat
    """
    if root == "workspace":
        return workspace.workspace_dir
    if root == "project":
        return await get_project_dir_for_request(request, workspace)
    if root.startswith(_EXTRA_PROJECT_ROOT_PREFIX):
        return await _resolve_extra_project_root(
            request,
            workspace,
            root[len(_EXTRA_PROJECT_ROOT_PREFIX) :],
        )
    raise HTTPException(
        status_code=400,
        detail="root must be project, project:<path> or workspace",
    )


@router.get(
    "/tree",
    summary="List one workspace directory page",
)
async def list_workspace_tree(
    request: Request,
    path: str = Query(default=""),
    cursor: str | None = Query(default=None),
    root: str = Query(default="project"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
    ),
) -> dict:
    """List immediate children without materializing the full project."""
    workspace = await get_agent_for_request(request)
    files_root = await _resolve_files_root(request, workspace, root)
    try:
        async with _FILESYSTEM_SEMAPHORE:
            return await asyncio.to_thread(
                list_directory,
                files_root,
                path,
                cursor,
                limit,
            )
    except InvalidCursor as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InvalidWorkspacePath as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise HTTPException(
            status_code=404,
            detail="Directory not found",
        ) from exc


@router.get(
    "/file-metadata",
    summary="Read workspace file metadata",
)
async def read_workspace_file_metadata(
    request: Request,
    path: str = Query(...),
    root: str = Query(default="project"),
) -> dict:
    """Return file metadata before content is requested."""
    workspace = await get_agent_for_request(request)
    files_root = await _resolve_files_root(request, workspace, root)
    try:
        async with _FILESYSTEM_SEMAPHORE:
            return await asyncio.to_thread(
                get_file_metadata,
                files_root,
                path,
            )
    except InvalidWorkspacePath as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (FileNotFoundError, OSError) as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc


@router.get(
    "/file-content",
    summary="Read a bounded workspace text chunk",
)
async def read_workspace_file_content(
    request: Request,
    path: str = Query(...),
    root: str = Query(default="project"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=DEFAULT_CHUNK_SIZE, ge=1),
) -> dict:
    """Read text by byte range with UTF-8 boundary protection."""
    workspace = await get_agent_for_request(request)
    files_root = await _resolve_files_root(request, workspace, root)
    try:
        async with _FILESYSTEM_SEMAPHORE:
            return await asyncio.to_thread(
                read_file_chunk,
                files_root,
                path,
                offset,
                limit,
            )
    except InvalidWorkspacePath as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=416, detail=str(exc)) from exc
    except FileVersionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail="File changed while it was being read",
        ) from exc
    except (FileNotFoundError, OSError) as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc


@router.put(
    "/file-content",
    summary="Save workspace text with optimistic concurrency",
)
async def write_workspace_file_content(
    request: Request,
    path: str = Query(...),
    root: str = Query(default="project"),
    body: dict = Body(...),
) -> dict:
    """Atomically save text when the supplied ETag still matches."""
    content = body.get("content")
    if not isinstance(content, str):
        raise HTTPException(status_code=422, detail="content must be a string")
    workspace = await get_agent_for_request(request)
    files_root = await _resolve_files_root(request, workspace, root)
    try:
        async with _FILESYSTEM_SEMAPHORE:
            return await asyncio.to_thread(
                save_text_file,
                files_root,
                path,
                content,
                request.headers.get("if-match"),
            )
    except InvalidWorkspacePath as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileVersionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail="File changed on disk",
        ) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/file-download",
    summary="Stream one workspace file",
)
async def download_workspace_file(
    request: Request,
    path: str = Query(...),
    root: str = Query(default="project"),
) -> StreamingResponse:
    """Stream one safe workspace file without buffering it in memory."""
    workspace = await get_agent_for_request(request)
    files_root = await _resolve_files_root(request, workspace, root)

    def _resolve_download() -> tuple[Path, os.stat_result, str, str]:
        target = resolve_workspace_path(files_root, path)
        info = target.stat()
        filename = target.name.replace('"', "")
        media_type = (
            mimetypes.guess_type(filename)[0] or "application/octet-stream"
        )
        return target, info, filename, media_type

    try:
        async with _FILESYSTEM_SEMAPHORE:
            target, info, filename, media_type = await asyncio.to_thread(
                _resolve_download,
            )
        if not stat.S_ISREG(info.st_mode):
            raise FileNotFoundError(path)
    except InvalidWorkspacePath as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (FileNotFoundError, OSError) as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc

    def _stream_file(chunk_size: int = 256 * 1024):
        with target.open("rb") as handle:
            while chunk := handle.read(chunk_size):
                yield chunk

    quoted_filename = quote(filename)
    if quoted_filename == filename:
        content_disposition = f'attachment; filename="{filename}"'
    else:
        content_disposition = f"attachment; filename*=utf-8''{quoted_filename}"
    return StreamingResponse(
        _stream_file(),
        media_type=media_type,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Disposition": content_disposition,
            "Content-Length": str(info.st_size),
            "ETag": file_etag(info),
        },
    )


@router.get(
    "/html-file-uri",
    summary="Resolve one workspace HTML file for the desktop browser",
)
async def resolve_workspace_html_file_uri(
    request: Request,
    path: str = Query(...),
    root: str = Query(default="project"),
) -> dict:
    """Return the URI of one validated HTML file in the selected workspace."""
    workspace = await get_agent_for_request(request)
    files_root = await _resolve_files_root(request, workspace, root)

    def _resolve_html() -> Path:
        target = resolve_workspace_path(files_root, path)
        if target.suffix.lower() not in {".html", ".htm"}:
            raise InvalidWorkspacePath("Path must reference an HTML file")
        if not target.is_file():
            raise FileNotFoundError(path)
        return target

    try:
        async with _FILESYSTEM_SEMAPHORE:
            target = await asyncio.to_thread(_resolve_html)
    except InvalidWorkspacePath as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (FileNotFoundError, OSError) as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc

    return {"uri": target.as_uri()}


def _reserve_path(target: Path) -> bool:
    """Atomically reserve one upload target without truncating a file."""
    try:
        descriptor = os.open(
            target,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
    except FileExistsError:
        return False
    os.close(descriptor)
    return True


def _reserve_upload_targets(
    upload_targets: list[tuple[UploadFile, str, Path]],
    conflict: str | None,
) -> tuple[list[tuple[UploadFile, str, Path | None, Path]], set[Path]]:
    """Atomically allocate all non-overwrite upload destinations."""
    allocated: list[tuple[UploadFile, str, Path | None, Path]] = []
    reservations: set[Path] = set()
    try:
        for upload, filename, target in upload_targets:
            if conflict == "overwrite":
                allocated.append((upload, filename, target, target))
                continue
            if _reserve_path(target):
                reservations.add(target)
                allocated.append((upload, filename, target, target))
                continue
            if conflict == "skip":
                allocated.append((upload, filename, None, target))
                continue
            if conflict != "rename":
                raise FileExistsError(filename)
            for index in range(1, 10_000):
                candidate = target.with_name(
                    f"{target.stem} ({index}){target.suffix}",
                )
                if _reserve_path(candidate):
                    reservations.add(candidate)
                    allocated.append((upload, filename, candidate, target))
                    break
            else:
                raise OSError("Unable to allocate a conflict-free filename")
    except BaseException:
        for reservation in reservations:
            reservation.unlink(missing_ok=True)
        raise
    return allocated, reservations


def _write_reserved_upload(upload: UploadFile, target: Path) -> int:
    """Copy one upload and atomically replace its reserved target."""
    temporary = target.with_name(
        f".{target.name}.{secrets.token_hex(6)}.qwenpaw.tmp",
    )
    size = 0
    try:
        upload.file.seek(0)
        with temporary.open("wb") as handle:
            while chunk := upload.file.read(256 * 1024):
                size += len(chunk)
                handle.write(chunk)
            handle.flush()
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return size


def _cleanup_upload_reservations(reservations: set[Path]) -> None:
    """Remove placeholders that were not replaced by completed uploads."""
    for reservation in reservations:
        reservation.unlink(missing_ok=True)


def _filesystem_name_rules(directory: Path) -> tuple[bool, bool]:
    """Detect case and Unicode normalization sensitivity for a directory.

    Thin wrapper over the shared probe: the temp-file technique this used
    to implement inline now lives in
    :mod:`qwenpaw.services.fs_name_rules`, unchanged in behaviour. It stays
    a write probe because the question here is about names that do *not*
    exist yet — would these two uploads collide? — which nothing that
    inspects existing entries can answer.

    Project-directory comparison deliberately does **not** use this. There
    the directories exist, so ``dir_key`` asks which entry each path
    reaches and gets an exact answer; a name-rules guess would be both
    weaker and, for a mount point, wrong.
    """
    rules = probe_name_rules(directory)
    return rules.case_sensitive, rules.normalization_sensitive


def _upload_name_key(
    filename: str,
    *,
    case_sensitive: bool,
    normalization_sensitive: bool,
) -> str:
    """Build a filename comparison key matching the target filesystem."""
    return NameRules(
        case_sensitive=case_sensitive,
        normalization_sensitive=normalization_sensitive,
    ).key(filename)


def _prepare_upload_targets(
    directory: Path,
    files: list[UploadFile],
) -> tuple[list[tuple[UploadFile, str, Path]], list[str]]:
    """Validate upload names and collect conflicts before writing files."""
    upload_targets: list[tuple[UploadFile, str, Path]] = []
    seen_names: set[str] = set()
    conflicts: list[str] = []
    case_sensitive, normalization_sensitive = _filesystem_name_rules(
        directory,
    )
    for upload in files:
        filename = upload.filename or ""
        if "/" in filename or "\\" in filename:
            raise HTTPException(
                status_code=400,
                detail="Upload filename must not contain a path",
            )
        try:
            target = resolve_workspace_path(
                directory,
                filename,
                portable=True,
            )
        except InvalidWorkspacePath as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        comparable_name = _upload_name_key(
            filename,
            case_sensitive=case_sensitive,
            normalization_sensitive=normalization_sensitive,
        )
        if target.exists() or comparable_name in seen_names:
            conflicts.append(filename)
        seen_names.add(comparable_name)
        upload_targets.append((upload, filename, target))
    return upload_targets, conflicts


@router.post(
    "/file-upload",
    summary="Stream ordinary files into one workspace directory",
)
async def upload_workspace_files(
    request: Request,
    files: list[UploadFile] = File(...),
    path: str = Query(default=""),
    root: str = Query(default="project"),
    conflict: str | None = Query(default=None),
) -> dict:
    """Upload files, requesting a policy only when names conflict."""
    if conflict is not None and conflict not in {
        "overwrite",
        "skip",
        "rename",
    }:
        raise HTTPException(
            status_code=400,
            detail="conflict must be overwrite, skip, or rename",
        )
    workspace = await get_agent_for_request(request)
    files_root = await _resolve_files_root(request, workspace, root)

    def _resolve_directory() -> Path:
        directory = resolve_workspace_path(
            files_root,
            path,
            allow_root=True,
        )
        if not directory.is_dir():
            raise NotADirectoryError(path)
        return directory

    try:
        directory = await asyncio.to_thread(_resolve_directory)
    except InvalidWorkspacePath as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise HTTPException(
            status_code=404,
            detail="Upload directory not found",
        ) from exc

    upload_targets, conflicts = await asyncio.to_thread(
        _prepare_upload_targets,
        directory,
        files,
    )

    if conflicts and conflict is None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "upload_conflict",
                "files": conflicts,
            },
        )

    try:
        allocated, reservations = await asyncio.to_thread(
            _reserve_upload_targets,
            upload_targets,
            conflict,
        )
    except FileExistsError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "upload_conflict",
                "files": [str(exc)],
            },
        ) from exc

    results: list[dict] = []
    try:
        for upload, filename, target, requested_target in allocated:
            if target is None:
                results.append(
                    {
                        "name": filename,
                        "path": requested_target.relative_to(
                            files_root,
                        ).as_posix(),
                        "status": "skipped",
                    },
                )
                continue
            async with _FILESYSTEM_SEMAPHORE:
                size = await asyncio.to_thread(
                    _write_reserved_upload,
                    upload,
                    target,
                )
                reservations.discard(target)

            results.append(
                {
                    "name": filename,
                    "path": target.relative_to(files_root).as_posix(),
                    "size": size,
                    "status": "uploaded",
                },
            )
    finally:
        await asyncio.to_thread(
            _cleanup_upload_reservations,
            reservations,
        )
    return {"files": results}


@router.get(
    "/code-files",
    summary="List all workspace files (Coding Mode)",
)
async def list_code_files(request: Request) -> list[dict]:
    """List every non-hidden file in the active coding project directory."""
    workspace = await get_agent_for_request(request)
    return await asyncio.to_thread(
        lambda: _list_all_files(get_agent_project_dir(workspace)),
    )


_CODE_FILE_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
_BINARY_FILE_MAX_BYTES = 50 * 1024 * 1024  # 50 MB

_MIME_MAP: dict[str, str] = {
    # Images
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "svg": "image/svg+xml",
    "ico": "image/x-icon",
    "bmp": "image/bmp",
    # Documents
    "pdf": "application/pdf",
    # Data
    "csv": "text/csv",
}


@router.get(
    "/binary-files/{file_path:path}",
    summary="Serve a binary workspace file (images, PDFs) for preview",
)
async def read_binary_file(
    file_path: str,
    request: Request,
) -> StreamingResponse:
    """Return the raw bytes of *file_path* with the appropriate Content-Type.

    Intended for the IDE preview panel (images, PDFs, CSV).
    Rejects files that are not in ``_MIME_MAP`` or exceed 50 MB.
    """
    workspace = await get_agent_for_request(request)
    target = await asyncio.to_thread(
        lambda: safe_join(get_agent_project_dir(workspace), file_path),
    )

    ext = target.suffix.lstrip(".").lower()
    mime = _MIME_MAP.get(ext)
    if mime is None:
        raise HTTPException(
            status_code=415,
            detail=f"Preview not supported for .{ext} files",
        )

    try:
        size = await asyncio.to_thread(lambda: target.stat().st_size)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if size > _BINARY_FILE_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File too large for preview ({size // 1024 // 1024} MB"
                f" > {_BINARY_FILE_MAX_BYTES // 1024 // 1024} MB limit)"
            ),
        )

    def _iter_chunks(chunk_size: int = 64 * 1024):
        with open(target, "rb") as fh:
            while True:
                data = fh.read(chunk_size)
                if not data:
                    break
                yield data

    return StreamingResponse(
        _iter_chunks(),
        media_type=mime,
        headers={"Content-Length": str(size)},
    )


def _file_etag(stat_result: os.stat_result) -> str:
    """Build a weak ETag from mtime+size — cheap and good enough for IDE."""
    return f'W/"{stat_result.st_mtime_ns}-{stat_result.st_size}"'


@router.get(
    "/code-files/{file_path:path}",
    summary="Read any workspace file (Coding Mode)",
)
async def read_code_file(file_path: str, request: Request):
    """Return the text content of *file_path* inside the workspace.

    Adds a weak ETag (mtime_ns + size) so repeat opens of an unchanged file
    short-circuit to ``304 Not Modified`` and skip the read entirely.
    Returns HTTP 413 if the file exceeds ``_CODE_FILE_MAX_BYTES`` (5 MB) to
    avoid flooding the browser with huge binary or log files.
    """
    workspace = await get_agent_for_request(request)
    target = await asyncio.to_thread(
        lambda: safe_join(get_agent_project_dir(workspace), file_path),
    )

    def _stat() -> os.stat_result:
        return target.stat()

    try:
        st = await asyncio.to_thread(_stat)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not stat.S_ISREG(st.st_mode):
        raise HTTPException(status_code=404, detail="File not found")

    etag = _file_etag(st)
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})

    if st.st_size > _CODE_FILE_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File too large to open in editor "
                f"({st.st_size // 1024 // 1024} MB"
                f" > {_CODE_FILE_MAX_BYTES // 1024 // 1024} MB limit)"
            ),
        )

    def _read() -> str:
        return target.read_text(encoding="utf-8", errors="replace")

    try:
        content = await asyncio.to_thread(_read)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ORJSONResponse(
        {"path": file_path, "content": content},
        headers={"ETag": etag},
    )


@router.put(
    "/code-files/{file_path:path}",
    summary="Write any workspace file (Coding Mode)",
)
async def write_code_file(
    file_path: str,
    request: Request,
    body: dict = Body(...),
) -> dict:
    """Overwrite *file_path* inside the workspace with the provided content.

    Request body::

        {"content": "<new file content>"}
    """
    workspace = await get_agent_for_request(request)
    target = await asyncio.to_thread(
        lambda: safe_join(get_agent_project_dir(workspace), file_path),
    )
    content = body.get("content", "")
    if not isinstance(content, str):
        raise HTTPException(status_code=422, detail="content must be a string")

    def _write() -> int:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8"))
        return target.stat().st_size

    try:
        size = await asyncio.to_thread(_write)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"path": file_path, "size": size}


@router.get(
    "/watch",
    summary="SSE stream for agent workspace file changes",
)
async def watch_workspace_files(
    request: Request,
    root: str = Query(default="project"),
) -> StreamingResponse:
    """Server-Sent Events that emit file-change notifications.

    Each SSE payload has the form::

        {"type": "file_change", "events": [{"change": "modified", "path": "..."}]}  # noqa: E501

    A heartbeat comment (``": heartbeat"``) is sent every 30 s when idle.
    """
    workspace = await get_agent_for_request(request)
    watch_dir = await _resolve_files_root(request, workspace, root)

    return StreamingResponse(
        workspace_watch_events(request, watch_dir),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def workspace_watch_events(
    request: Request,
    watch_dir: Path,
) -> AsyncIterator[str]:
    """Yield workspace file changes without cancelling the watcher on idle."""
    yield 'data: {"type": "connected"}\n\n'
    watcher = awatch(
        watch_dir,
        rust_timeout=_WATCH_POLL_TIMEOUT_MS,
        yield_on_timeout=True,
    )
    last_emit = asyncio.get_running_loop().time()
    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                raw_changes = await watcher.__anext__()
            except (
                StopAsyncIteration,
                asyncio.CancelledError,
                GeneratorExit,
            ):
                break

            events = []
            for change_type, path in raw_changes:
                try:
                    rel = Path(path).relative_to(watch_dir)
                except ValueError:
                    continue
                if _should_skip(rel.parts):
                    continue
                change_name = (
                    "added"
                    if change_type is Change.added
                    else "deleted"
                    if change_type is Change.deleted
                    else "modified"
                )
                events.append(
                    {"change": change_name, "path": rel.as_posix()},
                )

            now = asyncio.get_running_loop().time()
            if events:
                payload = json.dumps(
                    {"type": "file_change", "events": events},
                    ensure_ascii=False,
                )
                yield f"data: {payload}\n\n"
                last_emit = now
            elif now - last_emit >= _WATCH_HEARTBEAT_SECONDS:
                yield ": heartbeat\n\n"
                last_emit = now
    except (asyncio.CancelledError, GeneratorExit):
        pass
    finally:
        try:
            await watcher.aclose()
        except Exception:
            pass


@router.get(
    "/memory",
    response_model=list[MdFileInfo],
    summary="List memory files",
    description="List all memory files (uses active agent)",
)
async def list_memory_files(
    request: Request,
    section: Literal["daily", "digest"] | None = Query(default=None),
) -> list[MdFileInfo]:
    """List memory directory markdown files."""
    try:
        workspace = await get_agent_for_request(request)
        workspace_manager = AgentMdManager(
            str(workspace.workspace_dir),
            agent_id=workspace.agent_id,
        )
        raw_files = await asyncio.to_thread(
            workspace_manager.list_memory_mds,
            section,
        )
        files = [MdFileInfo.model_validate(file) for file in raw_files]
        return files
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/memory/{md_path:path}",
    response_model=MdFileContent,
    summary="Read a memory file",
    description="Read a memory markdown file (uses active agent)",
)
async def read_memory_file(
    md_path: str,
    request: Request,
    section: Literal["daily", "digest"] | None = Query(default=None),
) -> MdFileContent:
    """Read a memory directory markdown file."""
    try:
        workspace = await get_agent_for_request(request)
        workspace_manager = AgentMdManager(
            str(workspace.workspace_dir),
            agent_id=workspace.agent_id,
        )
        content = await asyncio.to_thread(
            workspace_manager.read_memory_md,
            md_path,
            section,
        )
        return MdFileContent(content=content)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put(
    "/memory/{md_path:path}",
    response_model=dict,
    summary="Write a memory file",
    description="Create or update a memory file (uses active agent)",
)
async def write_memory_file(
    md_path: str,
    body: MdFileContent,
    request: Request,
    section: Literal["daily", "digest"] | None = Query(default=None),
) -> dict:
    """Write a memory directory markdown file."""
    try:
        workspace = await get_agent_for_request(request)
        workspace_manager = AgentMdManager(
            str(workspace.workspace_dir),
            agent_id=workspace.agent_id,
        )
        await asyncio.to_thread(
            workspace_manager.write_memory_md,
            md_path,
            body.content,
            section,
        )
        return {"written": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/language",
    summary="Get agent language",
    description="Get the language setting for agent MD files.",
)
async def get_agent_language(request: Request) -> dict:
    """Get agent language setting for current agent."""
    workspace = await get_agent_for_request(request)
    agent_config = load_agent_config(workspace.agent_id)
    return {
        "language": agent_config.language,
        "agent_id": workspace.agent_id,
    }


@router.put(
    "/language",
    summary="Update agent language",
    description=(
        "Update the language for agent MD files. "
        "Optionally copies MD files for the new language to agent workspace."
    ),
)
async def put_agent_language(
    request: Request,
    body: dict = Body(
        ...,
        description='Language setting, e.g. {"language": "id"}',
    ),
) -> dict:
    """
    Update agent language and optionally re-copy MD files to agent workspace.
    """
    language = (body.get("language") or "").strip().lower()
    valid = SUPPORTED_AGENT_LANGUAGES
    if language not in valid:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid language '{language}'. "
                f"Must be one of: {', '.join(sorted(valid))}"
            ),
        )

    workspace = await get_agent_for_request(request)
    agent_id = workspace.agent_id

    agent_config = load_agent_config(agent_id)
    old_language = agent_config.language

    agent_config.language = language
    save_agent_config(agent_id, agent_config)

    copied_files: list[str] = []
    if old_language != language:
        copied_files = copy_workspace_md_files(
            language,
            workspace.workspace_dir,
            md_template_id=get_workspace_md_template_id(
                agent_config.template_id
                or ("qa" if agent_id == BUILTIN_QA_AGENT_ID else None),
            ),
            only_if_missing=False,
        )

    return {
        "language": language,
        "copied_files": copied_files,
        "agent_id": agent_id,
    }


@router.get(
    "/audio-mode",
    summary="Get audio mode",
    description=(
        "Get the audio handling mode for incoming voice messages. "
        'Values: "auto", "native".'
    ),
)
async def get_audio_mode() -> dict:
    """Get audio mode setting."""
    config = load_config()
    return {"audio_mode": config.agents.audio_mode}


@router.put(
    "/audio-mode",
    summary="Update audio mode",
    description=(
        "Update how incoming audio/voice messages are handled. "
        '"auto": transcribe if provider available, else file placeholder; '
        '"native": send audio directly to model (may need ffmpeg).'
    ),
)
async def put_audio_mode(
    body: dict = Body(
        ...,
        description='Audio mode, e.g. {"audio_mode": "auto"}',
    ),
) -> dict:
    """Update audio mode setting."""
    raw = body.get("audio_mode")
    audio_mode = (str(raw) if raw is not None else "").strip().lower()
    valid = {"auto", "native"}
    if audio_mode not in valid:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid audio_mode '{audio_mode}'. "
                f"Must be one of: {', '.join(sorted(valid))}"
            ),
        )

    def apply_audio_mode(config: Any) -> None:
        config.agents.audio_mode = audio_mode

    await run_sync_io(mutate_config, apply_audio_mode)
    return {"audio_mode": audio_mode}


@router.get(
    "/transcription-provider-type",
    summary="Get transcription provider type",
    description=(
        "Get the transcription provider type. "
        'Values: "disabled", "whisper_api", "local_whisper".'
    ),
)
async def get_transcription_provider_type() -> dict:
    """Get transcription provider type setting."""
    config = load_config()
    return {
        "transcription_provider_type": (
            config.agents.transcription_provider_type
        ),
    }


@router.put(
    "/transcription-provider-type",
    summary="Set transcription provider type",
    description=(
        "Set the transcription provider type. "
        '"disabled": no transcription; '
        '"whisper_api": remote Whisper endpoint; '
        '"local_whisper": locally installed openai-whisper.'
    ),
)
async def put_transcription_provider_type(
    body: dict = Body(
        ...,
        description=(
            "Provider type, e.g. "
            '{"transcription_provider_type": "whisper_api"}'
        ),
    ),
) -> dict:
    """Set the transcription provider type."""
    raw = body.get("transcription_provider_type")
    provider_type = (str(raw) if raw is not None else "").strip().lower()
    valid = {"disabled", "whisper_api", "local_whisper"}
    if provider_type not in valid:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid transcription_provider_type '{provider_type}'. "
                f"Must be one of: {', '.join(sorted(valid))}"
            ),
        )

    def apply_provider_type(config: Any) -> None:
        config.agents.transcription_provider_type = provider_type

    await run_sync_io(mutate_config, apply_provider_type)
    return {"transcription_provider_type": provider_type}


@router.get(
    "/local-whisper-status",
    summary="Check local whisper availability",
    description=(
        "Check whether the local whisper provider can be used. "
        "Returns availability of ffmpeg and openai-whisper."
    ),
)
async def get_local_whisper_status() -> dict:
    """Check local whisper dependencies."""
    from ...agents.utils.audio_transcription import (
        check_local_whisper_available,
    )

    return check_local_whisper_available()


@router.get(
    "/transcription-providers",
    summary="List transcription providers",
    description=(
        "List providers capable of audio transcription (Whisper API). "
        "Returns available providers and the configured selection."
    ),
)
async def get_transcription_providers() -> dict:
    """List transcription-capable providers and configured selection."""
    from ...agents.utils.audio_transcription import (
        get_configured_transcription_provider_id,
        list_transcription_providers,
    )

    return {
        "providers": list_transcription_providers(),
        "configured_provider_id": (get_configured_transcription_provider_id()),
    }


@router.put(
    "/transcription-provider",
    summary="Set transcription provider",
    description=(
        "Set the provider to use for audio transcription. "
        'Use empty string "" to unset.'
    ),
)
async def put_transcription_provider(
    body: dict = Body(
        ...,
        description=(
            'Provider ID, e.g. {"provider_id": "openai"} '
            'or {"provider_id": ""} to unset'
        ),
    ),
) -> dict:
    """Set the transcription provider."""
    provider_id = (body.get("provider_id") or "").strip()

    def apply_provider(config: Any) -> None:
        config.agents.transcription_provider_id = provider_id

    await run_sync_io(mutate_config, apply_provider)
    return {"provider_id": provider_id}


@router.post(
    "/transcribe",
    summary="Transcribe audio to text",
    description=(
        "Transcribe an uploaded audio file "
        "using the configured Whisper provider. "
        "Returns the transcribed text."
    ),
)
async def post_transcribe_audio(
    file: UploadFile = File(..., description="Audio file to transcribe"),
) -> dict:
    """Transcribe uploaded audio file using configured Whisper provider."""
    from ...agents.utils.audio_transcription import transcribe_audio

    # Check transcription is enabled
    config = load_config()
    provider_type = config.agents.transcription_provider_type
    if provider_type == "disabled":
        raise HTTPException(
            status_code=400,
            detail={
                "code": "TRANSCRIPTION_DISABLED",
                "message": (
                    "Transcription is disabled. "
                    "Configure a transcription provider in Settings."
                ),
            },
        )

    # Validate file type
    allowed_extensions = {
        ".webm",
        ".mp4",
        ".m4a",
        ".wav",
        ".mp3",
        ".ogg",
        ".flac",
    }
    suffix = (
        os.path.splitext(file.filename or "audio.webm")[1].lower() or ".webm"
    )
    if suffix not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "UNSUPPORTED_FILE_TYPE",
                "message": (
                    f"Unsupported file type: {suffix}. "
                    f"Allowed: {', '.join(sorted(allowed_extensions))}"
                ),
            },
        )

    data = await file.read()
    check_upload_size(data)

    # Save uploaded file to temp directory
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(data)
        tmp_path = tmp.name

    try:
        text = await transcribe_audio(tmp_path)
        if text is None:
            raise HTTPException(
                status_code=500,
                detail="Transcription failed. Check provider configuration.",
            )
        return {"text": text}
    finally:
        # Clean up temp file
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@router.post(
    "/embedding/test",
    response_model=EmbeddingTestResponse,
    summary="Test embedding configuration",
    description=(
        "Create an AgentScope embedding model, perform a real request, and "
        "validate the returned dimensions"
    ),
)
async def test_embedding_configuration(
    embedding_config: EmbeddingModelConfig = Body(...),
    request: Request = None,
) -> EmbeddingTestResponse:
    """Test unsaved embedding settings and stage the model for hot apply."""
    workspace = await get_agent_for_request(request)
    memory_manager = workspace.memory_manager
    if memory_manager is not None and hasattr(
        memory_manager,
        "test_and_stage_embedding",
    ):
        result = await memory_manager.test_and_stage_embedding(
            embedding_config,
        )
    else:
        _model, result = await test_embedding_model(embedding_config)

    message = result.message
    if embedding_config.api_key:
        message = message.replace(embedding_config.api_key, "***")
    return EmbeddingTestResponse(
        success=result.success,
        configured_dimensions=result.configured_dimensions,
        actual_dimensions=result.actual_dimensions,
        latency_ms=result.latency_ms,
        message=message,
    )


@router.get(
    "/running-config",
    response_model=AgentsRunningConfig,
    summary="Get agent running config",
    description="Get running configuration for active agent",
)
async def get_agents_running_config(
    request: Request,
) -> AgentsRunningConfig:
    """Get agent running configuration."""
    workspace = await get_agent_for_request(request)
    agent_config = await run_sync_io(load_agent_config, workspace.agent_id)
    running = agent_config.running or AgentsRunningConfig()
    running.approval_level = getattr(agent_config, "approval_level", "AUTO")
    return running


class _ConfigRollbackConflict(RuntimeError):
    """Raised when a field changed again after this request persisted it."""

    def __init__(self, paths: list[str]):
        super().__init__("configuration changed concurrently")
        self.paths = paths


def _conditionally_restore_config_changes(
    current: BaseModel,
    before: BaseModel,
    submitted: BaseModel,
) -> None:
    """Three-way rollback without overwriting unrelated concurrent edits."""
    candidate = current.model_copy(deep=True)
    conflicts: list[str] = []

    def restore(
        target: BaseModel,
        old: BaseModel,
        saved: BaseModel,
        prefix: str,
    ) -> None:
        for name in type(saved).model_fields:
            old_value = getattr(old, name)
            saved_value = getattr(saved, name)
            if old_value == saved_value:
                continue
            current_value = getattr(target, name)
            path = f"{prefix}.{name}" if prefix else name
            if (
                isinstance(current_value, BaseModel)
                and isinstance(old_value, BaseModel)
                and isinstance(saved_value, BaseModel)
                and type(current_value) is type(old_value) is type(saved_value)
            ):
                restore(current_value, old_value, saved_value, path)
            elif current_value == saved_value:
                setattr(target, name, copy.deepcopy(old_value))
            else:
                conflicts.append(path)

    restore(candidate, before, submitted, "")
    if conflicts:
        raise _ConfigRollbackConflict(conflicts)
    for field_name in type(current).model_fields:
        setattr(current, field_name, getattr(candidate, field_name))


async def _apply_embedding_runtime(
    memory_manager: Any,
    embedding_config: EmbeddingModelConfig,
    agent_id: str,
    *,
    force_reload: bool = False,
) -> bool:
    """Apply an embedding config to a running memory manager."""
    if not force_reload and hasattr(memory_manager, "apply_tested_embedding"):
        try:
            if await memory_manager.apply_tested_embedding(embedding_config):
                return True
        except Exception as exc:
            logger.warning(
                "Embedding hot update failed for agent '%s': %s",
                agent_id,
                exc,
                exc_info=True,
            )
            # An exception is an integration/runtime failure, not the normal
            # "reload required" result.  Return failure so the caller rolls
            # back the persisted config before restoring the old runtime.
            return False
    if hasattr(memory_manager, "reload_embedding_config"):
        try:
            return bool(await memory_manager.reload_embedding_config())
        except Exception as exc:
            logger.warning(
                "Embedding runtime reload failed for agent '%s': %s",
                agent_id,
                exc,
                exc_info=True,
            )
    return False


async def _rollback_embedding_update(
    agent_id: str,
    memory_manager: Any,
    before: BaseModel,
    submitted: BaseModel,
) -> None:
    """Roll back persistence and runtime after an embedding update fails."""
    rollback_conflict: _ConfigRollbackConflict | None = None

    def rollback_config(current_config: BaseModel) -> None:
        _conditionally_restore_config_changes(
            current_config,
            before,
            submitted,
        )

    try:
        await update_agent_config_async(agent_id, rollback_config)
    except _ConfigRollbackConflict as exc:
        rollback_conflict = exc

    runtime_restored = False
    if hasattr(memory_manager, "reload_embedding_config"):
        try:
            runtime_restored = bool(
                await memory_manager.reload_embedding_config(),
            )
        except Exception:
            logger.exception(
                "Failed to restore the previous embedding runtime "
                "for agent '%s'",
                agent_id,
            )

    raise HTTPException(
        status_code=409 if rollback_conflict else 503,
        detail={
            "message": (
                "Embedding configuration was not applied; "
                + (
                    "rollback was skipped because the configuration "
                    "changed concurrently"
                    if rollback_conflict
                    else "the persisted changes were rolled back"
                )
            ),
            "persisted": rollback_conflict is not None,
            "runtime_applied": False,
            "runtime_restored": runtime_restored,
            "conflicts": rollback_conflict.paths if rollback_conflict else [],
        },
    )


@router.put(
    "/running-config",
    response_model=AgentsRunningConfig,
    summary="Update agent running config",
    description="Update running configuration for active agent",
)
async def put_agents_running_config(
    running_config: AgentsRunningConfig = Body(
        ...,
        description="Updated agent running configuration",
    ),
    request: Request = None,
) -> AgentsRunningConfig:
    """Update agent running configuration."""
    workspace = await get_agent_for_request(request)
    memory_manager = workspace.memory_manager
    workspace_dir = getattr(workspace, "workspace_dir", ".")
    config_path = Path(workspace_dir) / "agent.json"
    async with get_path_lock(config_path):
        old_agent_config = None
        embedding_changed = False
        memory_manager_backend_changed = False
        restores_indexed_space = False
        new_embedding_config = (
            running_config.reme_light_memory_config.embedding_model_config
        )
        new_memory_manager_backend = running_config.memory_manager_backend

        def persist_running_config(agent_config):
            nonlocal old_agent_config, embedding_changed
            nonlocal memory_manager_backend_changed
            nonlocal restores_indexed_space
            old_agent_config = agent_config.model_copy(deep=True)
            old_running_config = agent_config.running or AgentsRunningConfig()
            memory_manager_backend_changed = (
                old_running_config.memory_manager_backend
                != new_memory_manager_backend
            )
            old_memory_config = old_running_config.reme_light_memory_config
            old_embedding_config = old_memory_config.embedding_model_config
            vector_space_changed = embedding_vector_space_fingerprint(
                old_embedding_config,
            ) != embedding_vector_space_fingerprint(new_embedding_config)
            new_memory_config = running_config.reme_light_memory_config
            indexed_config = old_memory_config.pending_reindex_embedding_config
            matches_existing_index = bool(
                old_memory_config.needs_reindex
                and indexed_config is not None
                and embedding_vector_space_fingerprint(new_embedding_config)
                == embedding_vector_space_fingerprint(indexed_config),
            )
            restores_indexed_space = matches_existing_index
            if matches_existing_index:
                new_memory_config.needs_reindex = False
                new_memory_config.pending_reindex_embedding_config = None
            else:
                new_memory_config.needs_reindex = (
                    old_memory_config.needs_reindex or vector_space_changed
                )
                new_memory_config.pending_reindex_embedding_config = (
                    indexed_config
                )
            if vector_space_changed and not old_memory_config.needs_reindex:
                new_memory_config.pending_reindex_embedding_config = (
                    old_embedding_config.model_copy(deep=True)
                )
            embedding_changed = old_embedding_config != new_embedding_config
            if (
                embedding_changed
                and not memory_manager_backend_changed
                and new_memory_manager_backend == "remelight"
                and memory_manager is not None
                and getattr(memory_manager, "is_reindexing", False) is True
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Embedding configuration cannot change while the "
                        "memory index is rebuilding"
                    ),
                )
            if running_config.approval_level is not None:
                agent_config.approval_level = running_config.approval_level
            running_config.approval_level = None
            agent_config.running = running_config

        async def persist_apply_and_schedule() -> AgentProfileConfig:
            agent_config = await update_agent_config_async(
                workspace.agent_id,
                persist_running_config,
            )

            if (
                embedding_changed
                and not memory_manager_backend_changed
                and new_memory_manager_backend == "remelight"
                and memory_manager is not None
            ):
                embedding_updated = await _apply_embedding_runtime(
                    memory_manager,
                    new_embedding_config,
                    workspace.agent_id,
                    force_reload=restores_indexed_space,
                )
                if not embedding_updated:
                    assert old_agent_config is not None
                    await _rollback_embedding_update(
                        workspace.agent_id,
                        memory_manager,
                        old_agent_config,
                        agent_config,
                    )

            schedule_agent_reload(request, workspace.agent_id)
            return agent_config

        agent_config = await run_async_to_completion(
            persist_apply_and_schedule(),
        )

    running_config.approval_level = agent_config.approval_level
    return running_config


@router.get(
    "/system-prompt-files",
    response_model=list[str],
    summary="Get system prompt files",
    description="Get system prompt files for active agent",
)
async def get_system_prompt_files(
    request: Request,
) -> list[str]:
    """Get list of enabled system prompt files."""
    workspace = await get_agent_for_request(request)
    agent_config = load_agent_config(workspace.agent_id)
    return agent_config.system_prompt_files or []


@router.put(
    "/system-prompt-files",
    response_model=list[str],
    summary="Update system prompt files",
    description="Update system prompt files for active agent",
)
async def put_system_prompt_files(
    files: list[str] = Body(
        ...,
        description="Markdown filenames to load into system prompt",
    ),
    request: Request = None,
) -> list[str]:
    """Update list of enabled system prompt files."""
    workspace = await get_agent_for_request(request)
    agent_config = load_agent_config(workspace.agent_id)
    agent_config.system_prompt_files = files
    save_agent_config(workspace.agent_id, agent_config)

    schedule_agent_reload(request, workspace.agent_id)

    return files


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_zip_data(data: bytes, workspace_dir: Path) -> None:
    """Ensure *data* is a valid zip without path-traversal entries."""
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is not a valid zip archive",
        )
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in zf.namelist():
            resolved = (workspace_dir / name).resolve()
            if not str(resolved).startswith(str(workspace_dir)):
                raise HTTPException(
                    status_code=400,
                    detail=f"Zip contains unsafe path: {name}",
                )


def _extract_and_merge_zip(data: bytes, workspace_dir: Path) -> None:
    """Extract zip data and merge into workspace_dir (blocking operation)."""
    tmp_dir = None
    try:
        tmp_dir = Path(tempfile.mkdtemp(prefix="qwenpaw_upload_"))
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            zf.extractall(tmp_dir)

        top_entries = list(tmp_dir.iterdir())
        extract_root = tmp_dir
        if len(top_entries) == 1 and top_entries[0].is_dir():
            extract_root = top_entries[0]

        workspace_dir.mkdir(parents=True, exist_ok=True)

        for item in extract_root.iterdir():
            dest = workspace_dir / item.name
            if item.is_file():
                shutil.copy2(item, dest)
            else:
                if dest.exists() and dest.is_file():
                    dest.unlink()
                shutil.copytree(item, dest, dirs_exist_ok=True)
    finally:
        if tmp_dir and tmp_dir.is_dir():
            shutil.rmtree(tmp_dir, ignore_errors=True)


def _validate_and_extract_zip(data: bytes, workspace_dir: Path) -> None:
    """Validate and extract zip data (blocking operation)."""
    _validate_zip_data(data, workspace_dir)
    _extract_and_merge_zip(data, workspace_dir)


# ---------------------------------------------------------------------------
# Workspace Download/Upload Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/download",
    summary="Download workspace as zip",
    description=(
        "Package the entire agent workspace into a zip archive and stream "
        "it back as a downloadable file."
    ),
    responses={
        200: {
            "content": {"application/zip": {}},
            "description": "Zip archive of agent workspace",
        },
    },
)
async def download_workspace(request: Request):
    """Stream agent workspace as a zip file."""

    agent = await get_agent_for_request(request)
    workspace_dir = agent.workspace_dir

    if not workspace_dir.is_dir():
        raise HTTPException(
            status_code=404,
            detail=f"Workspace does not exist: {workspace_dir}",
        )

    buf = await asyncio.to_thread(_zip_directory, workspace_dir)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"qwenpaw_workspace_{agent.agent_id}_{timestamp}.zip"

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.post(
    "/upload",
    response_model=dict,
    summary="Upload zip and merge into workspace",
    description=(
        "Upload a zip archive.  Paths present in the zip are merged into "
        "agent workspace (files overwritten, dirs merged).  Paths not in "
        "the zip are left unchanged (e.g. qwenpaw.db, runtime dirs). "
        "Download packs the entire workspace; upload only "
        "overwrites/merges zip contents."
    ),
)
async def upload_workspace(
    request: Request,
    file: UploadFile = File(
        ...,
        description="Zip archive to merge into agent workspace",
    ),
) -> dict:
    """
    Merge uploaded zip contents into agent workspace (overwrite, not clear).
    """

    if file.content_type and file.content_type not in (
        "application/zip",
        "application/x-zip-compressed",
        "application/octet-stream",
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Expected a zip file, got content-type: {file.content_type}"
            ),
        )

    agent = await get_agent_for_request(request)
    workspace_dir = agent.workspace_dir
    data = await file.read()

    try:
        await asyncio.to_thread(_validate_and_extract_zip, data, workspace_dir)
        return {"success": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to merge workspace: {exc}",
        ) from exc


@router.get("/commands/available")
async def get_available_commands(request: Request):
    """Return all slash commands registered for the workspace.

    Merges built-in system commands with plugin-registered ones
    so the frontend can dynamically populate the slash menu.
    """
    agent = await get_agent_for_request(request)
    registry = getattr(
        getattr(agent, "plugins", None),
        "slash_command_registry",
        None,
    )
    commands = []
    if registry is not None:
        for name in registry.names():
            match = registry.resolve(f"/{name}")
            desc = ""
            category = ""
            if match:
                spec, _ = match
                desc = spec.help_text or ""
                category = spec.category or ""
            commands.append(
                {
                    "name": name,
                    "description": desc,
                    "category": category,
                },
            )
    return ORJSONResponse({"commands": commands})
