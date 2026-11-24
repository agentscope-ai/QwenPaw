# -*- coding: utf-8 -*-
"""Release per-Task scratch the moment its content stops being needed.

Provider outputs and local render intermediates are written below
``runtime/task-work/<task_id>/`` while a Task runs, then published into the
content-addressed ``assets/artifacts/`` store.  Once published, or once the
Task reached a terminal state, nothing reads the scratch copy anymore, so it is
released right there instead of accumulating until some later sweep.

Two survivors keep their bytes here on purpose:

* every ``*.json``/``*.jsonl`` document (``spec.json`` describes what the Task
  did, ``provider-tasks.jsonl`` is the paid-task ledger a restart replays);
* the whole work directory of a ``QUARANTINED`` Task, which is the only scene
  an operator has for a result that must not be regenerated.

Releasing is best-effort by contract: a cleanup failure is logged and counted,
never raised into the generation path.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import stat
import threading
from typing import Any

from domain.enums import TERMINAL_TASK_STATUSES, TaskStatus
from services.project_files.assets import AssetFileStore
from services.project_files.models import IndexedFile
from services.runtime_files.atomic_store import AtomicJsonRecordStore
from services.runtime_files.execution_models import TaskRecord
from services.runtime_files.execution_store import ProjectExecutionStore
from services.runtime_files.path_safety import is_link_path, is_link_stat
from utils.logger import setup_logger

logger = setup_logger(__name__)

# Media that only ever exists as a scratch copy.  Documents are excluded by
# extension, so this list never has to be exhaustive to be safe.
MEDIA_SUFFIXES = frozenset(
    {
        ".aac",
        ".avc",
        ".gif",
        ".h264",
        ".jpg",
        ".jpeg",
        ".m4a",
        ".mkv",
        ".mov",
        ".mp3",
        ".mp4",
        ".ogg",
        ".pcm",
        ".png",
        ".prores",
        ".srt",
        ".vtt",
        ".wav",
        ".webp",
    },
)

# Named survivors inside a work directory; ``*.json`` is already excluded.
KEEP_FILE_NAMES = frozenset({"provider-tasks.jsonl"})

BASELINE_FILE_NAME = ".storage-baseline.json"
BASELINE_VERSION = 1

# A terminal Task that quiet for less than this may still be finishing a
# concurrent commit elsewhere, so the crash sweep waits it out.
ORPHAN_RELEASE_GRACE = timedelta(minutes=15)

TaskStore = Any

_DISABLED_VALUES = frozenset({"0", "false", "no", "off"})


def scratch_release_enabled() -> bool:
    """Whether releasing scratch is on; one env var is the emergency switch.

    Killing the feature has to be possible without a code change, because a
    release bug would delete work products: on by default, off on request.
    """

    raw = os.environ.get("CREATOR_SCRATCH_RELEASE_ENABLED", "")
    return raw.strip().casefold() not in _DISABLED_VALUES


@dataclass(frozen=True, slots=True)
class ScratchReleaseResult:
    """What one release removed, for logs and the storage profile."""

    removed_files: int = 0
    removed_bytes: int = 0
    skipped_files: int = 0


@dataclass(frozen=True, slots=True)
class ScratchSweepSummary:
    """Aggregate of a crash-recovery sweep over every discovered Project."""

    projects: int = 0
    released_directories: int = 0
    removed_files: int = 0
    removed_bytes: int = 0


_release_totals = ScratchReleaseResult()
_release_totals_lock = threading.Lock()


def _account_release(result: ScratchReleaseResult) -> ScratchReleaseResult:
    """Track what this process has released, for the storage profile.

    The counter is process-local on purpose: it answers "is the release path
    actually freeing space?" without adding durable state that a Project
    export or a commit would then have to account for.
    """

    global _release_totals  # noqa: PLW0603 - one module-wide aggregate
    with _release_totals_lock:
        _release_totals = ScratchReleaseResult(
            removed_files=_release_totals.removed_files + result.removed_files,
            removed_bytes=_release_totals.removed_bytes + result.removed_bytes,
            skipped_files=_release_totals.skipped_files + result.skipped_files,
        )
    return result


def release_totals() -> ScratchReleaseResult:
    """Files and bytes this process has released since it started."""

    return _release_totals


def _safe_name(value: str, *, label: str) -> str:
    if (
        not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or "\x00" in value
    ):
        raise ValueError(f"Unsafe {label}: {value!r}")
    return value


def task_scratch_dir(project_root: Path, task_id: str) -> Path:
    """Return one Task's work directory below a Project's ``runtime`` tree."""

    return (
        Path(project_root)
        / "runtime"
        / "task-work"
        / _safe_name(task_id, label="task_id")
    )


# Deleting through a path re-resolves every ancestor, so a writer that swaps a
# parent directory for a link after the check still sends the unlink outside
# the Creator data root -- a second realpath lookup only re-observes the same
# race.  A chain of directory handles opened with O_NOFOLLOW pins the tree
# instead: listing and unlinking then act on the same inodes, and a level that
# is, or has just become, a link fails the open.  A platform without that
# primitive refuses to clean rather than deleting through an unpinned path.
_PINNED_OPEN_FLAGS = (
    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
)


def pinned_release_supported() -> bool:
    """Whether directories can be opened here without following a redirect."""

    return hasattr(os, "O_DIRECTORY") and hasattr(os, "O_NOFOLLOW")


def _open_pinned_scratch(scratch_dir: Path) -> int | None:
    """Open one task's scratch as a handle chain that refuses redirects.

    The Creator layout comes first: ``<project>/runtime/task-work/<task>`` with
    ``project.json`` above it as a plain file, so a directory merely named like
    scratch is never reached.  Each level is then opened relative to the
    previous handle, which is what makes a symlink or Windows junction anywhere
    in the chain fail the open instead of redirecting the delete.
    """

    target = Path(scratch_dir)
    if (
        target.parent.name != "task-work"
        or target.parent.parent.name != "runtime"
    ):
        logger.warning(
            "scratch release skipped (not task scratch): %s",
            target,
        )
        return None
    root = target.parent.parent.parent
    try:
        marker = (root / "project.json").lstat()
    except OSError:
        logger.warning(
            "scratch release skipped (no Project marker above): %s",
            target,
        )
        return None
    if is_link_stat(marker) or not stat.S_ISREG(marker.st_mode):
        logger.warning(
            "scratch release skipped (unsafe Project marker): %s",
            root,
        )
        return None
    if not pinned_release_supported():
        logger.warning(
            "scratch release unavailable (cannot pin directories): %s",
            target,
        )
        return None
    held: int | None = None
    for name in (str(root), "runtime", "task-work", target.name):
        try:
            child = os.open(name, _PINNED_OPEN_FLAGS, dir_fd=held)
        except OSError as exc:
            logger.warning(
                "scratch release skipped (unpinnable path): %s: %s",
                name,
                exc,
            )
            if held is not None:
                os.close(held)
            return None
        if held is not None:
            os.close(held)
        held = child
    return held


def _releasable_name(name: str, mode: int) -> bool:
    """Whether one listed entry is media that a release may drop."""

    return (
        stat.S_ISREG(mode)
        and name not in KEEP_FILE_NAMES
        and Path(name).suffix.lower() in MEDIA_SUFFIXES
    )


def _flush_directory(dir_fd: int) -> None:
    """Persist the links removed below one handle; never a failure."""

    try:
        os.fsync(dir_fd)
    except OSError:
        # A platform that refuses fsync on a directory has still dropped the
        # unlink, so this stays a note rather than a failure.
        logger.debug("scratch fsync skipped", exc_info=True)


def _release_pinned_tree(dir_fd: int) -> ScratchReleaseResult:
    """Delete the media below one pinned directory handle, best effort."""

    removed_files = 0
    removed_bytes = 0
    skipped_files = 0
    try:
        entries = sorted(os.scandir(dir_fd), key=lambda entry: entry.name)
    except OSError:
        # A directory that cannot be read is left alone rather than guessed at.
        return ScratchReleaseResult()
    for entry in entries:
        try:
            info = entry.stat(follow_symlinks=False)
        except OSError:
            continue
        if is_link_stat(info):
            continue
        if stat.S_ISDIR(info.st_mode):
            try:
                child_fd = os.open(
                    entry.name,
                    _PINNED_OPEN_FLAGS,
                    dir_fd=dir_fd,
                )
            except OSError:
                skipped_files += 1
                continue
            try:
                below = _release_pinned_tree(child_fd)
            finally:
                os.close(child_fd)
            removed_files += below.removed_files
            removed_bytes += below.removed_bytes
            skipped_files += below.skipped_files
            continue
        if not _releasable_name(entry.name, info.st_mode):
            continue
        try:
            os.unlink(entry.name, dir_fd=dir_fd)
        except OSError as exc:
            skipped_files += 1
            logger.warning(
                "scratch release failed: name=%s error=%s",
                entry.name,
                exc,
            )
            continue
        removed_files += 1
        removed_bytes += info.st_size
    if removed_files:
        _flush_directory(dir_fd)
    return ScratchReleaseResult(
        removed_files=removed_files,
        removed_bytes=removed_bytes,
        skipped_files=skipped_files,
    )


def _releasable_bytes(scratch_dir: Path) -> int:
    """Bytes a release would actually take: media files, kept names aside."""

    total = 0
    for path in _releasable_media(Path(scratch_dir)):
        try:
            total += path.stat(follow_symlinks=False).st_size
        except OSError:
            continue
    return total


def link_asset_into_scratch(
    store: AssetFileStore,
    indexed: IndexedFile,
    destination: Path,
) -> bool:
    """Point one scratch filename at a stored Asset instead of copying it.

    A Task's inputs are the Project's own immutable Artifacts, so a private
    copy doubles media that is already counted on disk.  A hard link shares
    the bytes and costs a directory entry: releasing the scratch name later
    leaves the Asset untouched.  Cross-volume or unsupported filesystems
    return ``False`` so the caller can stream a real copy instead.
    """

    source = store.resolve_verified_path(indexed)
    try:
        os.link(source, destination)
    except OSError as exc:
        logger.info(
            "scratch link unavailable, copying instead: %s (%s)",
            destination,
            exc,
        )
        return False
    return True


def _releasable_media(scratch_dir: Path) -> Iterator[Path]:
    """Yield releasable media files, never following a symlink."""

    pending = [scratch_dir]
    while pending:
        current = pending.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            # A directory we cannot read is left alone rather than guessed at.
            continue
        for entry in entries:
            path = Path(entry.path)
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if is_link_stat(info):
                continue
            if stat.S_ISDIR(info.st_mode):
                pending.append(path)
                continue
            if not stat.S_ISREG(info.st_mode):
                continue
            if path.name in KEEP_FILE_NAMES:
                continue
            if path.suffix.lower() not in MEDIA_SUFFIXES:
                continue
            yield path


def release_scratch_media(
    scratch_dir: Path,
    *,
    reason: str,
) -> ScratchReleaseResult:
    """Delete the media left in one scratch directory, best effort.

    The handle is pinned before the listing runs and the unlink happens through
    that same handle, so swapping a parent directory for a link between the
    check and the delete can no longer send the unlink outside the tree that
    was opened.
    """

    dir_fd = _open_pinned_scratch(Path(scratch_dir))
    if dir_fd is None:
        return ScratchReleaseResult()
    try:
        result = _release_pinned_tree(dir_fd)
    finally:
        os.close(dir_fd)
    if result.removed_files:
        logger.info(
            "scratch released: dir=%s reason=%s files=%s bytes=%s",
            scratch_dir,
            reason,
            result.removed_files,
            result.removed_bytes,
        )
    return _account_release(result)


def release_scratch_file(path: Path, *, reason: str) -> bool:
    """Release one scratch file a pipeline step has just superseded.

    A render step that renames the current film out of the way (mix, loudness
    normalisation) leaves the predecessor behind as a full second copy of the
    whole delivery; it stops being readable the moment the successor lands.

    The emergency switch is honoured here too. This is the one release the
    render pipeline performs by itself, so gating only the terminal and sweep
    entries would keep cutting files after a deployment had asked every
    release to stop.
    """

    target = Path(path)
    if (
        not scratch_release_enabled()
        or target.suffix.lower() not in MEDIA_SUFFIXES
    ):
        return False
    # The predecessor lives directly in one task's scratch, so the same pinned
    # handle the directory release uses applies here too; the unlink below runs
    # relative to that handle, not to a path an ancestor could be swapped into.
    dir_fd = _open_pinned_scratch(target.parent)
    if dir_fd is None:
        return False
    try:
        info = os.stat(target.name, dir_fd=dir_fd, follow_symlinks=False)
        if is_link_stat(info) or not stat.S_ISREG(info.st_mode):
            return False
        size = info.st_size
        os.unlink(target.name, dir_fd=dir_fd)
        _flush_directory(dir_fd)
    except OSError as exc:
        logger.warning(
            "scratch release failed: path=%s reason=%s error=%s",
            target,
            reason,
            exc,
        )
        return False
    finally:
        os.close(dir_fd)
    logger.info(
        "scratch released: file=%s reason=%s bytes=%s",
        target,
        reason,
        size,
    )
    _account_release(ScratchReleaseResult(removed_files=1, removed_bytes=size))
    return True


def is_releasable_terminal_task(task: TaskRecord) -> bool:
    """Whether a Task is finished in a state that frees its scratch."""

    return (
        task.status in TERMINAL_TASK_STATUSES
        and task.status is not TaskStatus.QUARANTINED
    )


def release_finished_task_scratch(
    services: TaskStore,
    task: TaskRecord,
    *,
    reason: str = "task-terminal",
) -> ScratchReleaseResult:
    """Release one finished Task's scratch; running or quarantined keep it."""

    if not scratch_release_enabled():
        return ScratchReleaseResult()
    if not is_releasable_terminal_task(task):
        return ScratchReleaseResult()
    project_root = Path(services.projects.project_root(task.project_id))
    return release_scratch_media(
        task_scratch_dir(project_root, task.task_id),
        reason=reason,
    )


def terminal_release_listener(
    services: TaskStore,
) -> Callable[[TaskRecord], None]:
    """Build the hook an execution store calls on a terminal transition.

    The store announces state changes after dropping its locks; the policy of
    which files stop mattering stays here, because only the media domain knows
    the difference between scratch and a durable record.
    """

    def notify(task: TaskRecord) -> None:
        release_finished_task_scratch(services, task)

    return notify


def _baseline_store(
    project_root: Path,
) -> AtomicJsonRecordStore[dict[str, Any]]:
    return AtomicJsonRecordStore(
        Path(project_root) / "runtime" / BASELINE_FILE_NAME,
        None,
    )


def _parse_baseline(stored: dict[str, Any] | None) -> datetime | None:
    if not stored:
        return None
    raw = stored.get("since")
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def read_scratch_baseline(project_root: Path) -> datetime | None:
    """Return when this Project started being managed, if it ever was."""

    try:
        stored = _baseline_store(Path(project_root)).read_or_none()
    except OSError:
        return None
    return _parse_baseline(stored)


def remember_scratch_baseline(
    project_root: Path,
    *,
    now: datetime,
) -> datetime:
    """Record the baseline once, keeping the first recorded moment.

    Everything that predates the baseline is history this feature must not
    rewrite: those Projects stay at their pre-upgrade size and serve as the
    before/after reference for the new, self-cleaning layout.
    """

    store = _baseline_store(Path(project_root))
    try:
        created = store.try_create(
            {"version": BASELINE_VERSION, "since": now.isoformat()},
        )
    except OSError as exc:
        logger.warning(
            "scratch baseline cannot be recorded: %s (%s)",
            store.path,
            exc,
        )
        return now
    if created is not None:
        return now
    parsed = _parse_baseline(store.read_or_none())
    return parsed or now


def stamp_scratch_baseline(project_root: Path) -> datetime:
    """Record the reclaim baseline when a Project first gains scratch.

    ``release_orphaned_scratch`` only runs at startup, so a Project that
    arrives after boot -- by creation, copy, an archive import or an example
    install -- would otherwise be stamped on the *next* start. Tasks that ran
    there before that then look older than their own baseline and get filed
    as pre-upgrade history for good, which is exactly the leftover this
    feature exists to collect.

    Allocators call this before writing a first byte, so the baseline stays
    later than anything a Project came with -- imported history keeps its
    protected treatment -- and earlier than anything this build can abandon.
    """

    return remember_scratch_baseline(
        Path(project_root),
        now=datetime.now(timezone.utc),
    )


def _scratch_directories(task_work: Path) -> list[Path]:
    try:
        entries = sorted(
            (item for item in os.scandir(task_work)),
            key=lambda item: item.name,
        )
    except OSError:
        return []
    return [
        Path(item.path)
        for item in entries
        if item.is_dir(follow_symlinks=False)
        and not is_link_stat(item.stat(follow_symlinks=False))
    ]


def release_orphaned_scratch(
    services: TaskStore,
    *,
    now: datetime | None = None,
    grace: timedelta = ORPHAN_RELEASE_GRACE,
) -> ScratchSweepSummary:
    """Collect the scratch a crash left behind after a Task already finished.

    This is the only sweep in the design and it is deliberately narrow: it
    releases a directory solely when its Task reached a releasable terminal
    state after the Project baseline and has not been touched since.  The event
    path normally deletes these files long before a sweep runs, so the sweep
    exists only for the window where the process died mid-release.
    """

    moment = now or datetime.now(timezone.utc)
    if not scratch_release_enabled():
        return ScratchSweepSummary()
    executions = ProjectExecutionStore(services.root)
    projects = 0
    released_directories = 0
    removed_files = 0
    removed_bytes = 0
    for project_id in services.projects.discover_project_ids():
        projects += 1
        project_root = Path(services.projects.project_root(project_id))
        baseline = remember_scratch_baseline(project_root, now=moment)
        task_work = project_root / "runtime" / "task-work"
        directories = {
            item.name: item for item in _scratch_directories(task_work)
        }
        if not directories:
            continue
        try:
            tasks: Iterable[TaskRecord] = executions.list_tasks(project_id)
        except Exception:  # noqa: BLE001 - a sweep never breaks startup
            logger.warning(
                "scratch sweep skipped unreadable tasks: project=%s",
                project_id,
                exc_info=True,
            )
            continue
        for task in tasks:
            directory = directories.get(task.task_id)
            if directory is None:
                continue
            if not is_releasable_terminal_task(task):
                continue
            if task.updated_at < baseline:
                continue
            if moment - task.updated_at < grace:
                continue
            result = release_scratch_media(directory, reason="orphan-sweep")
            if result.removed_files:
                released_directories += 1
                removed_files += result.removed_files
                removed_bytes += result.removed_bytes
    return ScratchSweepSummary(
        projects=projects,
        released_directories=released_directories,
        removed_files=removed_files,
        removed_bytes=removed_bytes,
    )


def _directory_bytes(path: Path) -> tuple[int, float]:
    """Total regular-file bytes below one directory, and its newest mtime."""

    total = 0
    newest = 0.0
    pending = [path]
    while pending:
        current = pending.pop()
        try:
            newest = max(newest, current.stat().st_mtime)
            entries = list(os.scandir(current))
        except OSError:
            continue
        for entry in entries:
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            newest = max(newest, info.st_mtime)
            if entry.is_dir(follow_symlinks=False):
                pending.append(Path(entry.path))
            elif stat.S_ISREG(info.st_mode):
                total += info.st_size
    return total, newest


def _child_directories(path: Path) -> list[Path]:
    try:
        entries = list(os.scandir(path))
    except OSError:
        return []
    return sorted(
        (
            Path(item.path)
            for item in entries
            if item.is_dir(follow_symlinks=False)
        ),
        key=lambda item: item.name,
    )


def project_storage_profile(
    services: TaskStore,
    *,
    now: datetime | None = None,
    include_orphans: bool = False,
) -> dict[str, Any]:
    """Measure what Projects keep, split by the release baseline.

    ``du`` cannot answer the two questions this feature is about: how much of a
    Project is scratch that will be released, and how much is legacy content
    that must stay untouched.  Anything older than a Project's baseline is
    reported as legacy, so an upgraded install shows the old and the new layout
    side by side rather than silently rewriting history.
    """

    moment = now or datetime.now(timezone.utc)
    executions = ProjectExecutionStore(services.root)
    totals = {
        "taskWorkBytes": 0,
        "taskWorkLegacyBytes": 0,
        "taskWorkReclaimableBytes": 0,
        "transactionsBytes": 0,
        "transactionsLegacyBytes": 0,
        "orphanBytes": 0,
    }
    projects: list[dict[str, Any]] = []
    for project_id in services.projects.discover_project_ids():
        root = Path(services.projects.project_root(project_id))
        baseline = read_scratch_baseline(root)
        try:
            finished = {
                task.task_id: task
                for task in executions.list_tasks(project_id)
            }
        except (
            Exception
        ):  # noqa: BLE001 - a report must not fail on one Project
            logger.warning(
                "storage profile skipped unreadable tasks: project=%s",
                project_id,
                exc_info=True,
            )
            finished = {}
        measured: dict[str, int] = dict.fromkeys(totals, 0)
        task_work = root / "runtime" / "task-work"
        # A redirected scratch tree is never measured: walking it would read
        # files that live outside the Creator data root.
        for directory in (
            [] if is_link_path(task_work) else _child_directories(task_work)
        ):
            size, newest = _directory_bytes(directory)
            task = finished.get(directory.name)
            stamp = task.updated_at if task is not None else _utc(newest)
            if baseline is None or stamp < baseline:
                measured["taskWorkLegacyBytes"] += size
                continue
            measured["taskWorkBytes"] += size
            if (
                task is not None
                and is_releasable_terminal_task(task)
                and moment - task.updated_at >= ORPHAN_RELEASE_GRACE
            ):
                # What a release would actually take: the kept documents and
                # non-media files stay in taskWorkBytes only.
                measured["taskWorkReclaimableBytes"] += _releasable_bytes(
                    directory,
                )
        for directory in _child_directories(root / "runtime" / "transactions"):
            size, newest = _directory_bytes(directory)
            if baseline is None or _utc(newest) < baseline:
                measured["transactionsLegacyBytes"] += size
            else:
                measured["transactionsBytes"] += size
        if include_orphans:
            measured["orphanBytes"] = _orphan_bytes(services, project_id, root)
        for key, value in measured.items():
            totals[key] += value
        projects.append(
            {
                "projectId": project_id,
                "baselineAt": baseline.isoformat() if baseline else None,
                **measured,
            },
        )
    released = release_totals()
    return {
        "dataRoot": str(services.root),
        "generatedAt": moment.isoformat(),
        "scratchReleaseEnabled": scratch_release_enabled(),
        "releasedFiles": released.removed_files,
        "releasedBytes": released.removed_bytes,
        "totals": totals,
        "projects": projects,
    }


def _utc(seconds: float) -> datetime:
    try:
        return datetime.fromtimestamp(seconds, timezone.utc)
    except (OSError, OverflowError, ValueError):
        return datetime.fromtimestamp(0, timezone.utc)


def _orphan_bytes(services: TaskStore, project_id: str, root: Path) -> int:
    """Bytes of Asset files the Project index no longer references."""

    try:
        snapshot = services.projects.read(project_id)
        scan = AssetFileStore(root).scan_orphans(snapshot.project.assets)
    except Exception:  # noqa: BLE001 - an orphan report is advisory only
        logger.warning(
            "storage profile skipped orphan scan: project=%s",
            project_id,
            exc_info=True,
        )
        return 0
    return sum(candidate.size_bytes for candidate in scan.candidates)
