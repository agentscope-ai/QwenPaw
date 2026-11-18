# -*- coding: utf-8 -*-
"""Bounded Project archives without published render scratch."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
import sys
from typing import NamedTuple
from uuid import uuid4
import zipfile

from domain.errors import BadRequestError
from services.runtime_files.atomic_store import atomic_replace_path
from services.runtime_files.path_safety import is_link_stat
from .models import Project

logger = logging.getLogger("qwenpaw.creator.project_files.archive")


def _log_safe(value: object) -> str:
    """Neutralize CR/LF in archive-provided values before logging."""
    return str(value).replace("\r", "\\r").replace("\n", "\\n")


# Multi-episode Projects include media plus revision history. Keep explicit
# upload/extraction bounds, shared by export, rather than rejecting our own
# archives at the old 2/4 GiB single-film limits.
MAX_ARCHIVE_BYTES = 8 * 1024**3
MAX_EXTRACTED_BYTES = 16 * 1024**3
MAX_MEMBERS = 20000
# Members are copied in bounded chunks so a budget can stop the byte that
# would exceed it before that byte is written, not after.
_COPY_CHUNK_BYTES = 1024 * 1024

# Windows forbids these characters in a single path component, reserves a
# handful of device names, and silently strips trailing spaces and dots at
# the shell layer even though the file APIs keep them. Archives produced
# on Linux/macOS routinely embed an id such as ``source:<uuid>`` inside
# the source-intelligence layout; aborting extraction over one such member
# throws away every other file in the bundle, so we rewrite the offending
# component instead and reconcile the Project registry to match.
_WINDOWS_FORBIDDEN = re.compile(r'[<>:"\\|?*\x00-\x1f]')


def _is_windows_illegal_part(part: str) -> bool:
    return (
        _WINDOWS_FORBIDDEN.search(part) is not None
        or part.rstrip(" .") != part
        or PureWindowsPath(part).is_reserved()
    )


def _sanitize_windows_part(part: str) -> str:
    """Map one POSIX component to a Windows-legal equivalent.

    Deterministic and idempotent: already-legal names pass through
    untouched, forbidden characters become underscores, trailing spaces
    and dots are stripped, a name that resolves to a reserved device gets
    a leading underscore, and a fully-stripped result falls back to a
    single underscore so the component never disappears.
    """

    sanitized = _WINDOWS_FORBIDDEN.sub("_", part).rstrip(" .")
    if not sanitized:
        sanitized = "_"
    if PureWindowsPath(sanitized).is_reserved():
        sanitized = f"_{sanitized}"
    return sanitized


def _sanitize_member(member: PurePosixPath) -> PurePosixPath:
    return PurePosixPath(*(_sanitize_windows_part(p) for p in member.parts))


def _rewrite_project_relative_uris(project_json: Path) -> int:
    """Reconcile IndexedFile.relative_uri with the on-disk layout.

    Only the registry path field is touched; logical identifiers such as
    ``source_id``, the ``sources.items`` dict keys and the ``order``
    arrays are JSON-internal and legal on every platform. Returns how
    many entries changed, so the caller can log the summary once. The
    rewrite is published through a same-directory temp file plus
    ``atomic_replace_path``: a crash mid-rewrite must never leave the
    example flow a truncated registry it would publish on ``is_file()``.
    """

    try:
        data = json.loads(project_json.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        # Substitutions already happened on disk; a registry we cannot
        # reconcile would leave dangling relative_uris, so make the skip
        # observable instead of silent.
        logger.warning(
            "skipped Windows relative_uri rewrite, project.json is "
            "unreadable or unparseable: %s (%s)",
            _log_safe(project_json),
            exc,
        )
        return 0
    if not isinstance(data, dict):
        return 0
    assets = data.get("assets")
    if not isinstance(assets, dict):
        return 0
    files_by_id = assets.get("files_by_id")
    if not isinstance(files_by_id, dict):
        return 0
    changed = 0
    for entry in files_by_id.values():
        if not isinstance(entry, dict):
            continue
        uri = entry.get("relative_uri")
        if not isinstance(uri, str) or not uri:
            continue
        rewritten = "/".join(
            _sanitize_windows_part(part) for part in uri.split("/")
        )
        if rewritten != uri:
            entry["relative_uri"] = rewritten
            changed += 1
    if not changed:
        return 0
    # Match the canonical on-disk form (serialization.canonical_json_bytes
    # with pretty=True): indent=2 plus a final newline.
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    temporary = project_json.with_suffix(f".{uuid4().hex}.tmp")
    try:
        temporary.write_text(payload, encoding="utf-8")
        atomic_replace_path(temporary, project_json)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return changed


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
    """Preserve indexed paths without renaming or merging members.

    On Windows a member whose path cannot be represented is rewritten to
    a legal name and every :class:`IndexedFile.relative_uri` that still
    points at the original spelling is reconciled in ``project.json``.
    An archive that would collide with itself after that rewrite is
    still refused: that is real corruption, not a platform limitation.
    """
    budget = archive_limits() if limits is None else limits
    validate_archive(path, limits=budget)
    base = destination.resolve()
    extracted = 0
    substitutions: dict[PurePosixPath, PurePosixPath] = {}
    with zipfile.ZipFile(path) as archive:
        seen: dict[Path, str] = {}
        for info in archive.infolist():
            member = PurePosixPath(info.filename)
            if sys.platform == "win32" and any(
                _is_windows_illegal_part(part) for part in member.parts
            ):
                sanitized = _sanitize_member(member)
                if sanitized != member:
                    substitutions[member] = sanitized
                    member = sanitized
            target = (base / member).resolve()
            if not target.is_relative_to(base):
                raise BadRequestError(
                    "archive entry escapes extraction root: "
                    f"{info.filename!r}",
                )
            previous = seen.get(target)
            if previous is not None:
                if previous == info.filename:
                    raise BadRequestError(
                        f"archive contains duplicate path: {info.filename!r}",
                    )
                raise BadRequestError(
                    "archive paths collide after Windows sanitization: "
                    f"{previous!r} and {info.filename!r} both map to "
                    f"{member.as_posix()!r}; re-export the project from "
                    "Linux or macOS to preserve its media references",
                )
            seen[target] = info.filename
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
    if substitutions:
        _report_windows_substitutions(substitutions)
        for project_json in base.glob("*/project.json"):
            rewritten = _rewrite_project_relative_uris(project_json)
            if rewritten:
                logger.info(
                    "reconciled %d IndexedFile.relative_uri entries in %s "
                    "after Windows path sanitization",
                    rewritten,
                    project_json,
                )


def _report_windows_substitutions(
    substitutions: dict[PurePosixPath, PurePosixPath],
) -> None:
    """Log one summary line instead of one warning per archived member.

    A source-intelligence directory typically carries one JSON sidecar,
    but a Project copied from a Linux host can also nest media under the
    same unrepresentable folder; the user only needs to know that the
    rewrite happened and which top-level folders moved.
    """

    sample = sorted(
        (
            f"{_log_safe(original.as_posix())} -> {rewritten.as_posix()}"
            for original, rewritten in substitutions.items()
        ),
    )
    shown = sample[:5]
    tail = f" (+{len(sample) - len(shown)} more)" if len(sample) > 5 else ""
    logger.warning(
        "extracted %d archive member(s) to Windows-safe names: %s%s",
        len(substitutions),
        "; ".join(shown),
        tail,
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
