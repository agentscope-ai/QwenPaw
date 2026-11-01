# -*- coding: utf-8 -*-
"""Bounded Project archives without published render scratch."""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
import sys
from typing import NamedTuple
import zipfile

from domain.errors import BadRequestError
from services.runtime_files.path_safety import is_link_stat
from .models import Project

# Multi-episode Projects include media plus revision history. Keep explicit
# upload/extraction bounds, shared by export, rather than rejecting our own
# archives at the old 2/4 GiB single-film limits.
MAX_ARCHIVE_BYTES = 8 * 1024**3
MAX_EXTRACTED_BYTES = 16 * 1024**3
MAX_MEMBERS = 20000
# Members are copied in bounded chunks so a budget can stop the byte that
# would exceed it before that byte is written, not after.
_COPY_CHUNK_BYTES = 1024 * 1024


class ArchiveLimits(NamedTuple):
    """One call's budget for reading an archive.

    A caller whose payload is far smaller than a Project archive (a SKILL.md
    bundle, say) passes its own numbers instead of inheriting 16 GiB of
    expansion headroom. ``member_bytes`` stays None when a per-member cap
    would only reject attachments the caller discards anyway; the total still
    bounds what reaches disk.
    """

    archive_bytes: int
    extracted_bytes: int
    members: int
    member_bytes: int | None = None


def archive_limits(
    *,
    max_archive_bytes: int | None = None,
    max_extracted_bytes: int | None = None,
    max_members: int | None = None,
    max_member_bytes: int | None = None,
) -> ArchiveLimits:
    """Fill each unset field in from the module constant.

    Resolved at call time rather than through argument defaults so that
    patching a constant still moves the limit, as the import tests rely on.
    """

    return ArchiveLimits(
        archive_bytes=(
            MAX_ARCHIVE_BYTES
            if max_archive_bytes is None
            else max_archive_bytes
        ),
        extracted_bytes=(
            MAX_EXTRACTED_BYTES
            if max_extracted_bytes is None
            else max_extracted_bytes
        ),
        members=MAX_MEMBERS if max_members is None else max_members,
        member_bytes=max_member_bytes,
    )


def _copy_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    target: Path,
    *,
    remaining: int,
    member_bytes: int | None,
) -> int:
    """Copy one member; return the bytes it actually put on disk.

    ``validate_archive`` can only read the sizes an archive declares, and a
    member is free to declare fewer than it carries, so counting what is
    written is what makes the expansion budget real. Reads one byte past the
    cap to refuse an over-budget member before that byte lands, and removes
    the partial file it had already opened.
    """

    cap = remaining if member_bytes is None else min(member_bytes, remaining)
    written = 0
    try:
        with archive.open(info) as source, target.open("wb") as output:
            while True:
                chunk = source.read(min(_COPY_CHUNK_BYTES, cap - written + 1))
                if not chunk:
                    return written
                written += len(chunk)
                if written > cap:
                    raise BadRequestError(
                        "archive member expands beyond its budget: "
                        f"{info.filename!r}",
                    )
                output.write(chunk)
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def extract_archive(
    path: Path,
    destination: Path,
    *,
    limits: ArchiveLimits | None = None,
) -> None:
    """Preserve indexed paths without renaming or merging members."""
    budget = archive_limits() if limits is None else limits
    validate_archive(path, limits=budget)
    base = destination.resolve()
    extracted = 0
    with zipfile.ZipFile(path) as archive:
        seen = set()
        for info in archive.infolist():
            member = PurePosixPath(info.filename)
            if sys.platform == "win32" and any(
                re.search(r'[<>:"\\|?*\x00-\x1f]', part)
                or part.rstrip(" .") != part
                or PureWindowsPath(part).is_reserved()
                for part in member.parts
            ):
                raise BadRequestError(
                    "archive path is not supported on Windows: "
                    f"{info.filename!r}; import on Linux or macOS "
                    "to preserve its media references",
                )
            target = (base / member).resolve()
            if not target.is_relative_to(base):
                raise BadRequestError(
                    "archive entry escapes extraction root: "
                    f"{info.filename!r}",
                )
            if target in seen:
                raise BadRequestError(
                    f"archive contains duplicate path: {info.filename!r}",
                )
            seen.add(target)
            if sys.platform == "win32" and len(str(target)) > 240:
                target = Path("\\\\?\\" + str(target))
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                extracted += _copy_member(
                    archive,
                    info,
                    target,
                    remaining=budget.extracted_bytes - extracted,
                    member_bytes=budget.member_bytes,
                )


def validate_archive(
    path: Path,
    *,
    limits: ArchiveLimits | None = None,
) -> None:
    """Check every member before extraction or download."""
    budget = archive_limits() if limits is None else limits
    if path.stat().st_size > budget.archive_bytes:
        raise BadRequestError(
            "archive exceeds the " f"{budget.archive_bytes} byte limit",
        )
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > budget.members:
                raise BadRequestError(
                    f"archive holds more than {budget.members} entries",
                )
            total = 0
            for info in members:
                member = PurePosixPath(info.filename)
                if member.is_absolute() or ".." in member.parts:
                    raise BadRequestError(
                        "archive entry escapes the extraction root: "
                        f"{info.filename!r}",
                    )
                if stat.S_ISLNK(info.external_attr >> 16):
                    raise BadRequestError(
                        f"archive entry is a symlink: {info.filename!r}",
                    )
                total += info.file_size
                if total > budget.extracted_bytes:
                    raise BadRequestError(
                        "archive expands beyond the "
                        f"{budget.extracted_bytes} byte import limit",
                    )
    except zipfile.BadZipFile as error:
        raise BadRequestError(f"not a valid zip archive: {error}") from error


def _published_compose_scratch(root: Path, project: Project) -> set[Path]:
    """Only omit successful renders whose immutable output is still indexed."""
    indexed = project.assets.files_by_id
    protected = {
        PurePosixPath(file.relative_uri).parts[2]
        for file in indexed.values()
        if PurePosixPath(file.relative_uri).parts[:2]
        == ("runtime", "task-work")
        and len(PurePosixPath(file.relative_uri).parts) > 2
    }
    disposable = set()
    for record_path in (root / "runtime" / "tasks").glob("*/task.json"):
        try:
            record = json.loads(record_path.read_bytes())
            if (
                record.get("status") != "SUCCEEDED"
                or record.get("kind") != "compose"
                or record_path.parent.name in protected
            ):
                continue
            output = (record.get("result") or {}).get("indexedFile") or {}
            file = indexed.get(output.get("file_id"))
            if (
                file is not None
                and output.get("sha256") == file.sha256
                and (root / file.relative_uri).stat().st_size
                == file.size_bytes
            ):
                disposable.add(
                    root / "runtime" / "task-work" / record_path.parent.name,
                )
        except (OSError, ValueError, TypeError, AttributeError):
            # Unknown, damaged or still-running tasks keep their recovery data.
            continue
    return disposable


def write_project_archive(
    root: Path,
    project: Project,
    destination: Path,
) -> None:
    """Read a best-effort snapshot; never mutate Project or Runtime files."""
    disposable = _published_compose_scratch(root, project)
    try:
        with zipfile.ZipFile(
            destination,
            "w",
            zipfile.ZIP_DEFLATED,
        ) as archive:
            total = 0
            for directory, dirs, files in os.walk(root, followlinks=False):
                current = Path(directory)
                dirs[:] = [
                    name for name in dirs if current / name not in disposable
                ]
                for name in [*dirs, *files]:
                    path = current / name
                    details = path.lstat()
                    mode = details.st_mode
                    if is_link_stat(details) or not (
                        stat.S_ISREG(mode) or stat.S_ISDIR(mode)
                    ):
                        raise BadRequestError(
                            "cannot archive non-regular path: "
                            f"{path.relative_to(root)}",
                        )
                    total += path.stat().st_size if stat.S_ISREG(mode) else 0
                    if (
                        total > MAX_EXTRACTED_BYTES
                        or len(archive.filelist) >= MAX_MEMBERS
                    ):
                        raise BadRequestError(
                            "Project exceeds archive import limits; "
                            "reduce its media/history before exporting",
                        )
                    archive.write(path, path.relative_to(root.parent))
                    if archive.fp.tell() > MAX_ARCHIVE_BYTES:
                        raise BadRequestError(
                            "archive exceeds the "
                            f"{MAX_ARCHIVE_BYTES} byte limit",
                        )
        validate_archive(destination)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
