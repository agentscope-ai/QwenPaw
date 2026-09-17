# -*- coding: utf-8 -*-
"""Bounded Project archives without published render scratch."""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import stat
import sys
import zipfile

from domain.errors import BadRequestError
from .models import Project

# Multi-episode Projects include media plus revision history. Keep explicit
# upload/extraction bounds, shared by export, rather than rejecting our own
# archives at the old 2/4 GiB single-film limits.
MAX_ARCHIVE_BYTES = 8 * 1024**3
MAX_EXTRACTED_BYTES = 16 * 1024**3
MAX_MEMBERS = 20000


def extract_archive(path: Path, destination: Path) -> None:
    """Preserve indexed paths without renaming or merging members."""
    validate_archive(path)
    base = destination.resolve()
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
                with archive.open(info) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)


def validate_archive(path: Path) -> None:
    """Check every member before extraction or download."""
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise BadRequestError(
            "archive exceeds the " f"{MAX_ARCHIVE_BYTES} byte limit",
        )
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > MAX_MEMBERS:
                raise BadRequestError(
                    f"archive holds more than {MAX_MEMBERS} entries",
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
                if total > MAX_EXTRACTED_BYTES:
                    raise BadRequestError(
                        "archive expands beyond the "
                        f"{MAX_EXTRACTED_BYTES} byte import limit",
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
                    mode = path.lstat().st_mode
                    if stat.S_ISLNK(mode) or not (
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
