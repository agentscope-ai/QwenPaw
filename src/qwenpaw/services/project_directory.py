# -*- coding: utf-8 -*-
"""Resolve and normalize project directories for an agent.

The agent operates on two distinct locations:

* ``workspace_dir`` — the agent's **internal** storage root (config,
  memory, sessions, skills, media, cache). Internal subsystems must
  keep resolving against it, no matter which project is active.
* ``project_dirs`` — the directories the agent **works in**. An ordered
  list; the first entry is the **primary** project directory (the base
  for relative paths in file tools and the default ``cwd`` for shell
  commands). Additional entries are extra project directories bound to
  the chat: fully granted by governance and described in the prompt,
  but never used as a resolution *base* — a relative path only resolves
  against the primary. A resolved *target* landing inside any granted
  root is legitimate (``../docs/x`` may well reach an extra root).

Effective-directory precedence, highest first::

    fork worktree (replaces the primary; the rest is inherited)
    mode pin (Mission snapshots the whole list for the run)
    trusted request override (ACP / cron; becomes the primary)
    per-chat session override (whole list, persisted on the chat)
    agent-level default (a single directory, inherited as primary)
    workspace fallback (nothing configured; primary = workspace)

A path that no longer exists is **surfaced, not dropped**: silently
resetting to another directory would scatter the user's files.
"""

from __future__ import annotations

import logging
import stat as stat_module
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence, Union

from .fs_name_rules import NameRules, platform_name_rules

logger = logging.getLogger(__name__)

PathLike = Union[str, Path]

# Only for paths with no directory entry to identify — see
# :func:`dir_key`, which prefers filesystem identity, and
# :mod:`qwenpaw.services.fs_name_rules` for why the platform is a fallback
# and not the answer.
_FALLBACK_RULES = platform_name_rules()

# Prefixes keeping the two kinds of comparison key in separate spaces. A
# path that exists is never "the same directory" as one that does not, so
# an identity key must not be able to equal a name key.
_IDENTITY_KEY_PREFIX = "id:"
_NAME_KEY_PREFIX = "name:"

# Hard cap on how many directories one chat may bind. Keeps the prompt
# block and the governance rule set bounded no matter what a client
# sends.
MAX_PROJECT_DIRS = 10

# Labels are rendered into the system prompt; long ones are truncated.
MAX_PROJECT_DIR_LABEL_LENGTH = 50

# Provenance of the effective list, highest precedence first. UI and
# audit use these verbatim. ``active_mode`` (not ``mode``) is kept for
# compatibility with the console's source handling.
SOURCE_FORK = "fork"
SOURCE_MODE = "active_mode"
SOURCE_REQUEST = "request"
SOURCE_SESSION = "session"
SOURCE_INHERITED = "inherited"
SOURCE_AGENT = "agent"
SOURCE_WORKSPACE_FALLBACK = "workspace_fallback"

ProjectDirSource = str

# One project directory entry as it appears in chat meta / API
# payloads: a path plus an optional user-facing label.
RawProjectDirEntry = Union[str, Path, dict, Sequence[Any], Any]


def normalize_project_dir(value: str | Path) -> Path:
    """Normalize one configured project directory for the current platform.

    Does **not** require the path to exist — a configured-but-missing
    directory must survive round-trips so the UI can flag it as
    unavailable instead of silently resetting the user's config.
    """
    return Path(value).expanduser().resolve()


def _normalize_optional(raw: Any) -> Optional[Path]:
    """Normalize user input; ``None`` for blank/unusable values."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    return normalize_project_dir(text)


def normalize_project_dir_label(raw: Any) -> Optional[str]:
    """Trim a user-provided label; None/blank becomes None."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    return text[:MAX_PROJECT_DIR_LABEL_LENGTH]


def dir_stat(path: Path) -> tuple[bool, Optional[tuple[int, int]]]:
    """Return ``(is_a_directory, identity)`` for *path* in one syscall.

    ``identity`` is ``(st_dev, st_ino)`` — which directory entry the path
    actually reaches — or ``None`` when the filesystem cannot say.

    Both answers come from a single ``stat()`` because callers want both
    and this runs once per bound directory per resolution. Symlinks are
    followed on purpose: a link to a bound directory *is* that directory,
    and identity is what makes that fall out for free.

    ``st_ino == 0`` is treated as no identity rather than as inode zero.
    Some SMB and FUSE mounts report it for every entry, and taking that at
    face value would make every path on such a mount compare equal — the
    one failure direction that silently discards a directory.
    """
    try:
        info = path.stat()
    except OSError:
        return False, None
    identity = (
        (info.st_dev, info.st_ino)
        if info.st_ino and info.st_dev is not None
        else None
    )
    return stat_module.S_ISDIR(info.st_mode), identity


def dir_key(raw: Any, rules: Optional[NameRules] = None) -> str:
    """Return a stable comparison key for a directory.

    Two paths get the same key exactly when they are the same directory,
    which is what every consumer needs: dedupe of a bound list, the
    governance rule set, the sandbox mount list, Files API membership.

    The key is the directory's **filesystem identity** whenever it has
    one. That is exact rather than heuristic — it is right across case
    folding, Unicode normalization, symlinks, bind mounts and mount
    points, and it needs to know nothing about the platform. Comparing
    path *strings* gets every one of those wrong in one direction or the
    other: fold and two genuinely distinct roots on a case-sensitive
    volume collapse into one, so only one of them is granted; do not fold
    and one directory on a folding volume is bound twice, with two rules,
    two mounts and two Files roots.

    For a path with no entry to identify — a configured directory that
    does not exist yet, which must survive round-trips so the UI can flag
    it — the key falls back to the path string folded under *rules*, or
    the platform guess. That case cannot be answered exactly, and nothing
    is written to a wrong directory on the strength of it, because there
    is no directory there.

    Does not ``resolve()``: callers store the literal path they were given
    (policy rule patterns, sandbox mounts) and the key must stay
    consistent with what they hold. Identity makes resolving unnecessary —
    two spellings of one directory stat to the same entry whether or not
    either was resolved.

    This is filesystem I/O. Call it from a worker thread.
    """
    try:
        path = Path(str(raw)).expanduser()
    except (OSError, TypeError, ValueError):
        return _NAME_KEY_PREFIX + (rules or _FALLBACK_RULES).key(str(raw))
    _, identity = dir_stat(path)
    if identity is not None:
        return f"{_IDENTITY_KEY_PREFIX}{identity[0]}:{identity[1]}"
    return _NAME_KEY_PREFIX + (rules or _FALLBACK_RULES).key(str(path))


def same_dir_normalized(
    a: Path,
    b: Path,
    rules: Optional[NameRules] = None,
) -> bool:
    """Compare two already-normalized directory paths **by name**.

    The name-only fallback for paths that have no filesystem identity to
    compare — a configured directory that does not exist yet. Where both
    directories exist, :func:`dir_key` answers exactly and this does not:
    folding under one set of rules cannot be right for two paths on
    volumes that fold differently, and it is blind to symlinks and mount
    points.

    Does no filesystem access, so a dedupe loop may call it per pair
    without turning an n-entry list into O(n\u00b2) syscalls.
    """
    active = rules or _FALLBACK_RULES
    return active.key(str(a)) == active.key(str(b))


def is_within_normalized(
    target: Path,
    base: Path,
    rules: Optional[NameRules] = None,
) -> bool:
    """Return True when *target* is *base* itself or lives underneath it.

    Containment, unlike identity, has no exact filesystem answer to ask
    for — there is no syscall for "is this entry under that one" — so this
    stays a lexical comparison folded under *rules*, defaulting to the
    platform guess. That is acceptable because the only caller is
    :func:`nested_root_pairs`, which produces a "covered by X" hint for
    the UI: a wrong answer shows or hides a hint. Nothing authorizes on
    it, and nothing drops a root because of it.

    Takes paths that came out of :func:`normalize_project_dir` (a
    :class:`ResolvedProjectDirs` list, say) — passing a raw path here
    compares it unresolved, which is a different question. Does no
    filesystem access.
    """
    try:
        target.relative_to(base)
        return True
    except ValueError:
        pass
    active = rules or _FALLBACK_RULES
    if active.case_sensitive and active.normalization_sensitive:
        # Nothing left to fold, so the exact comparison above was final.
        return False
    # The filesystem folds something, so compare the folded spellings:
    # /Repo/x really is inside /repo here.
    try:
        Path(active.key(str(target))).relative_to(active.key(str(base)))
        return True
    except ValueError:
        return False


def coerce_project_dir_entry(
    raw: RawProjectDirEntry,
) -> Optional[tuple[Path, Optional[str]]]:
    """Coerce one raw entry into ``(path, label)``.

    Accepts the shapes that reach the resolver:

    * plain path strings / ``Path`` objects (no label)
    * ``{"path": ..., "label": ...}`` dicts (meta, API payloads)
    * pydantic entry models (attribute access)
    * ``(path, label)`` sequences

    Returns ``None`` for blank/unusable input.
    """
    if raw is None:
        return None

    label: Any = None
    path_raw: Any = raw

    if isinstance(raw, dict):
        path_raw = raw.get("path")
        label = raw.get("label")
    elif isinstance(raw, (list, tuple)):
        if not raw:
            return None
        path_raw = raw[0]
        label = raw[1] if len(raw) > 1 else None
    elif not isinstance(raw, (str, Path)):
        # Pydantic model or similar: attribute access.
        path_raw = getattr(raw, "path", None)
        label = getattr(raw, "label", None)

    normalized = _normalize_optional(path_raw)
    if normalized is None:
        return None
    return normalized, normalize_project_dir_label(label)


@dataclass(frozen=True)
class NormalizedProjectDir:
    """One coerced entry plus what the single ``stat()`` for it found.

    ``key`` is the :func:`dir_key` comparison key and ``exists`` says
    whether the path is a directory right now. Both are carried rather than
    recomputed because they come from one syscall and every consumer wants
    them: dedupe compares keys, the API reports ``exists``, and the Files
    API membership check compares its candidate against ``key`` without
    touching the filesystem again.
    """

    path: Path
    label: Optional[str]
    key: str
    exists: bool


def normalize_dir_entry(
    raw: RawProjectDirEntry,
) -> Optional[NormalizedProjectDir]:
    """Coerce one raw entry and stat it once. ``None`` if unusable."""
    coerced = coerce_project_dir_entry(raw)
    if coerced is None:
        return None
    path, label = coerced
    exists, identity = dir_stat(path)
    key = (
        f"{_IDENTITY_KEY_PREFIX}{identity[0]}:{identity[1]}"
        if identity is not None
        else _NAME_KEY_PREFIX + _FALLBACK_RULES.key(str(path))
    )
    return NormalizedProjectDir(
        path=path,
        label=label,
        key=key,
        exists=exists,
    )


def normalize_dir_entry_list(raw: Any) -> list[NormalizedProjectDir]:
    """Normalize a raw project-dir list: coerce, dedupe, cap.

    Order is preserved — index 0 is the primary project directory. Dedupe
    keeps the first occurrence (and its label) and compares
    :func:`dir_key` keys, so two spellings collapse exactly when they
    reach the same directory entry — across case folding, Unicode
    normalization, symlinks and mount points alike, and *only* then. A
    string comparison here would either drop one of two genuinely distinct
    roots on a case-sensitive volume or bind one directory twice on a
    folding one.

    Entries beyond ``MAX_PROJECT_DIRS`` are dropped with a warning (the
    API layer rejects oversized lists with 422; truncation here is defense
    in depth only).

    ``None`` (as opposed to an empty list) is treated as an empty list
    here; callers that need to distinguish "absent" from "empty" must
    check before calling.

    One ``stat()`` and one ``resolve()`` per entry, so this must be called
    from a worker thread, never from a coroutine.
    """
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        raw = [raw]

    items = list(raw)
    entries: list[NormalizedProjectDir] = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        entry = normalize_dir_entry(item)
        if entry is None or entry.key in seen:
            continue
        seen.add(entry.key)
        entries.append(entry)
        if len(entries) >= MAX_PROJECT_DIRS:
            # Only a genuine overflow is worth a warning: a list of exactly
            # MAX_PROJECT_DIRS entries loses nothing.
            if items[index + 1 :]:
                logger.warning(
                    "project_dirs: more than %d entries supplied; "
                    "keeping the first %d",
                    MAX_PROJECT_DIRS,
                    MAX_PROJECT_DIRS,
                )
            break
    return entries


def normalize_project_dir_list(
    raw: Any,
) -> list[tuple[Path, Optional[str]]]:
    """``(path, label)`` view of :func:`normalize_dir_entry_list`.

    Kept for the callers that only forward paths and labels onward (the
    console's pending-dir validator, the chats API's stored list). Callers
    that also want the comparison key or ``exists`` should use
    :func:`normalize_dir_entry_list` and avoid stat-ing a second time.
    """
    return [
        (entry.path, entry.label) for entry in normalize_dir_entry_list(raw)
    ]


def nested_root_pairs(paths: Sequence[Path]) -> list[tuple[int, int]]:
    """Detect nested directories inside a project-dir list.

    Returns ``(child_index, ancestor_index)`` pairs — every case where
    the path at ``child_index`` lives underneath the path at
    ``ancestor_index``. Nested roots are **reported, not rejected**: the
    entry stays in the list and keeps working, and the UI surfaces a
    "covered by X" hint. Governance grants the outer root, which already
    covers the inner one, so the extra grant is redundant rather than
    wrong.

    Nesting is a physical relationship independent of order and of which
    entry is primary.

    Takes **already-normalized** paths and compares them as given — no
    coercion, no dedupe, no ``resolve()``. Callers hold a resolved list
    already (the chats API builds one from :class:`ResolvedProjectDirs`),
    so normalizing here would walk the filesystem a second time, once per
    pair, to learn the nesting of paths it had just resolved. Indices
    refer to *paths*, and therefore line up with the caller's own list.
    """
    pairs: list[tuple[int, int]] = []
    for child_idx, child_path in enumerate(paths):
        for anc_idx, anc_path in enumerate(paths):
            if child_idx == anc_idx:
                continue
            if is_within_normalized(child_path, anc_path):
                pairs.append((child_idx, anc_idx))
    return pairs


@dataclass(frozen=True)
class ResolvedProjectDir:
    """One effective project directory after resolution."""

    path: Path
    label: Optional[str] = None
    exists: bool = True
    # This directory's :func:`dir_key`, taken during resolution from the
    # same ``stat()`` that filled ``exists``. Consumers asking "is this
    # path this entry?" — Files API membership above all — compare their
    # own key against this one instead of comparing path strings, which
    # would admit an unbound directory on a folding volume and reject a
    # bound one on a case-sensitive volume. Empty means the entry was
    # built without a key; comparisons must then fall back to
    # :func:`same_dir_normalized` rather than treat "" as a match.
    key: str = ""


@dataclass(frozen=True)
class ResolvedProjectDirs:
    """The effective project-directory list for one turn.

    ``dirs`` holds only explicitly configured entries; ``[0]`` is the
    primary. When nothing is configured ``dirs`` is empty and the
    primary falls back to ``workspace_dir`` (``source`` says so).
    """

    dirs: tuple[ResolvedProjectDir, ...]
    source: ProjectDirSource
    workspace_dir: Path
    # Snapshot taken once during resolution. A property that probed the
    # filesystem instead would issue a syscall on every ``primary`` /
    # ``primary_path`` access, and those are read repeatedly per turn.
    workspace_exists: bool = True
    # Likewise the workspace's own comparison key, so the fallback primary
    # below is built without touching the filesystem.
    workspace_key: str = ""

    @property
    def is_workspace_fallback(self) -> bool:
        return not self.dirs

    @property
    def primary(self) -> ResolvedProjectDir:
        """The directory tools resolve relative paths against."""
        if self.dirs:
            return self.dirs[0]
        return ResolvedProjectDir(
            path=self.workspace_dir,
            label=None,
            exists=self.workspace_exists,
            key=self.workspace_key,
        )

    @property
    def primary_path(self) -> Path:
        return self.primary.path

    @property
    def paths(self) -> list[Path]:
        return [entry.path for entry in self.dirs]


def resolve_effective_project_dirs(
    workspace_dir: PathLike,
    *,
    agent_project_dir: Optional[str] = None,
    session_project_dirs: Optional[Any] = None,
    request_override: Optional[Any] = None,
    mode_override: Optional[Any] = None,
    fork_project_dir: Optional[PathLike] = None,
) -> ResolvedProjectDirs:
    """Resolve the effective project-directory list for a request.

    Precedence, highest first:

    1. ``fork_project_dir`` — a forked subagent's worktree replaces the
       primary; the remaining entries are inherited.
    2. ``mode_override`` — a running mode (Mission) snapshots the whole
       list at start so a mid-run session switch cannot move it.
    3. ``request_override`` — a trusted per-run path (ACP / cron) that
       becomes the primary; the rest is inherited.
    4. ``session_project_dirs`` — per-chat override list. ``None``
       means "not set" (inherit the agent default).
    5. ``agent_project_dir`` — the agent-level default (a **single**
       directory; agent-level lists do not exist).
    6. Workspace fallback when nothing is configured.

    Raises:
        ValueError: workspace_dir is empty or not absolute.
    """
    normalized_workspace = _normalize_optional(workspace_dir)
    if normalized_workspace is None or not normalized_workspace.is_absolute():
        raise ValueError(f"Invalid workspace_dir: {workspace_dir!r}")

    if session_project_dirs is not None:
        entries = normalize_dir_entry_list(session_project_dirs)
        source: ProjectDirSource = SOURCE_SESSION
    else:
        entries = normalize_dir_entry_list(
            [agent_project_dir] if agent_project_dir else [],
        )
        source = SOURCE_AGENT if entries else SOURCE_WORKSPACE_FALLBACK

    if request_override is not None:
        override = normalize_dir_entry(request_override)
        if override is not None:
            # Dedupe by comparison key: the override and the inherited
            # entries were each stat-ed once on the way in, so this is
            # exact and costs no further syscalls.
            entries = [override] + [
                entry for entry in entries if entry.key != override.key
            ]
            source = SOURCE_REQUEST

    if mode_override is not None:
        pinned = normalize_dir_entry_list(mode_override)
        if pinned:
            entries = pinned
            source = SOURCE_MODE

    if fork_project_dir is not None:
        worktree = normalize_dir_entry(fork_project_dir)
        if worktree is not None:
            entries = [worktree] + [
                entry for entry in entries if entry.key != worktree.key
            ]
            source = SOURCE_FORK

    # Re-apply the cap after the prepending overrides above: a request or
    # fork override pushed onto an already-full list would otherwise return
    # MAX_PROJECT_DIRS + 1 entries, and every entry past the cap still
    # earns its own governance ALLOW rule and writable sandbox mount.
    # Truncating from the tail keeps the primary and drops the least
    # significant roots.
    if len(entries) > MAX_PROJECT_DIRS:
        logger.warning(
            "project_dirs: %d effective entries exceed the cap; "
            "keeping the first %d",
            len(entries),
            MAX_PROJECT_DIRS,
        )
        entries = entries[:MAX_PROJECT_DIRS]

    # ``exists`` and ``key`` were both filled by the single stat() each
    # entry got during normalization, so building these costs nothing.
    dirs = tuple(
        ResolvedProjectDir(
            path=entry.path,
            label=entry.label,
            exists=entry.exists,
            key=entry.key,
        )
        for entry in entries
    )
    # One stat for the workspace, always. The fallback primary needs it, and
    # so does every caller that has to answer "is this bound entry the agent
    # workspace?" — the Files switcher collapses such an entry onto its own
    # ``workspace`` root, and comparing the two paths as strings is what used
    # to split one directory into two roots with two sets of editor tabs.
    # It is the agent's own storage, so the syscall is local and hot.
    workspace_exists, workspace_identity = dir_stat(normalized_workspace)
    workspace_key = (
        f"{_IDENTITY_KEY_PREFIX}"
        f"{workspace_identity[0]}:{workspace_identity[1]}"
        if workspace_identity is not None
        else _NAME_KEY_PREFIX + _FALLBACK_RULES.key(str(normalized_workspace))
    )
    return ResolvedProjectDirs(
        dirs=dirs,
        source=source,
        workspace_dir=normalized_workspace,
        workspace_exists=workspace_exists,
        workspace_key=workspace_key,
    )


def resolve_effective_project_dir(
    workspace_dir: Path,
    agent_project_dir: str | None = None,
    session_override: str | None = None,
    trusted_override: str | None = None,
    active_mode_override: str | None = None,
    fork_project_dir: str | None = None,
) -> tuple[Path, str]:
    """Resolve one immutable project directory snapshot and its source.

    Thin single-value wrapper over :func:`resolve_effective_project_dirs`
    kept for existing call sites; returns ``(primary_path, source)``.
    """
    resolved = resolve_effective_project_dirs(
        workspace_dir,
        agent_project_dir=agent_project_dir,
        session_project_dirs=(
            [session_override]
            if isinstance(session_override, str) and session_override.strip()
            else None
        ),
        request_override=trusted_override,
        mode_override=(
            [active_mode_override]
            if isinstance(active_mode_override, str)
            and active_mode_override.strip()
            else None
        ),
        fork_project_dir=fork_project_dir,
    )
    return resolved.primary_path, resolved.source


# ---------------------------------------------------------------------------
# Chat metadata readers
# ---------------------------------------------------------------------------


def session_project_dir(meta: dict[str, Any] | None) -> str | None:
    """Read the controlled Session project override from Chat metadata.

    Single-value view kept for existing call sites: the primary entry
    of the persisted list (a legacy scalar ``project_dir`` is read as a
    one-entry list). Only the ``runtime_context`` namespace is trusted.
    """
    dirs = session_project_dirs_from_meta(meta)
    if not dirs:
        return None
    return dirs[0]["path"]


def session_project_dirs_raw_from_meta(meta: Optional[dict]) -> Optional[list]:
    """Read the per-chat override **without** normalizing the entries.

    Returns the stored list (possibly empty), or ``None`` when the chat
    has no override and should inherit the agent default. A legacy
    singular ``project_dir`` string reads as a single-entry list. Only
    the controlled ``runtime_context`` namespace is trusted.

    For callers that only forward the value to
    :func:`resolve_effective_project_dirs`, which normalizes everything
    it is handed: normalizing here as well would ``resolve()`` every
    directory twice per turn. Callers that hand the entries to the API or
    the UI want :func:`session_project_dirs_from_meta` instead.
    """
    if not isinstance(meta, dict):
        return None
    runtime_context = meta.get("runtime_context")
    if not isinstance(runtime_context, dict):
        return None

    stored = runtime_context.get("project_dirs")
    if stored is not None:
        return stored if isinstance(stored, list) else [stored]

    legacy = runtime_context.get("project_dir")
    if isinstance(legacy, str) and legacy.strip():
        return [legacy]
    return None


def session_project_dirs_from_meta(meta: Optional[dict]) -> Optional[list]:
    """Read the per-chat project-directory override from chat metadata.

    Returns the persisted list (possibly empty), or ``None`` when the
    chat has no override and should inherit the agent default. Entries
    are normalized on the way out so callers get clean data even if the
    stored metadata predates the list format.
    """
    stored = session_project_dirs_raw_from_meta(meta)
    if stored is None:
        return None
    return [
        {"path": str(path), "label": label}
        for path, label in normalize_project_dir_list(stored)
    ]


__all__ = [
    "MAX_PROJECT_DIRS",
    "MAX_PROJECT_DIR_LABEL_LENGTH",
    "NameRules",
    "NormalizedProjectDir",
    "ResolvedProjectDir",
    "ResolvedProjectDirs",
    "SOURCE_AGENT",
    "SOURCE_FORK",
    "SOURCE_INHERITED",
    "SOURCE_MODE",
    "SOURCE_REQUEST",
    "SOURCE_SESSION",
    "SOURCE_WORKSPACE_FALLBACK",
    "dir_key",
    "dir_stat",
    "is_within_normalized",
    "nested_root_pairs",
    "normalize_dir_entry",
    "normalize_dir_entry_list",
    "normalize_project_dir",
    "normalize_project_dir_list",
    "resolve_effective_project_dir",
    "resolve_effective_project_dirs",
    "same_dir_normalized",
    "session_project_dir",
    "session_project_dirs_from_meta",
    "session_project_dirs_raw_from_meta",
]
