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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence, Union

logger = logging.getLogger(__name__)

PathLike = Union[str, Path]

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


class PathEscapeError(ValueError):
    """Raised when a path resolves outside every authorized root."""


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


def same_dir(a: PathLike, b: PathLike) -> bool:
    """Compare two directories, ignoring case and trailing separators.

    On case-insensitive filesystems (macOS, Windows) ``/Repo`` and
    ``/repo`` are the same directory; naive string comparison would
    treat them as distinct and let stale entries survive a re-save.
    """
    left = _normalize_optional(a)
    right = _normalize_optional(b)
    if left is None or right is None:
        return left is right
    return str(left).casefold() == str(right).casefold()


def is_within(path: PathLike, root: PathLike) -> bool:
    """Return True when *path* is *root* itself or lives underneath it.

    Lexical comparison on normalized paths; both sides are already
    ``resolve()``-d by :func:`normalize_project_dir`, so symlinks are
    collapsed as a side effect without dedicated logic.
    """
    target = _normalize_optional(path)
    base = _normalize_optional(root)
    if target is None or base is None:
        return False
    try:
        target.relative_to(base)
        return True
    except ValueError:
        pass
    # Case-insensitive filesystems: /Repo under /repo.
    try:
        Path(str(target).casefold()).relative_to(str(base).casefold())
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


def normalize_project_dir_list(
    raw: Any,
) -> list[tuple[Path, Optional[str]]]:
    """Normalize a raw project-dir list: coerce, dedupe, cap.

    Order is preserved — index 0 is the primary project directory.
    Dedupe keeps the first occurrence (and its label) and is
    case-insensitive via :func:`same_dir`. Entries beyond
    ``MAX_PROJECT_DIRS`` are dropped with a warning (the API layer
    rejects oversized lists with 422; truncation here is defense in
    depth only).

    ``None`` (as opposed to an empty list) is treated as an empty list
    here; callers that need to distinguish "absent" from "empty" must
    check before calling.
    """
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        raw = [raw]

    entries: list[tuple[Path, Optional[str]]] = []
    for item in raw:
        coerced = coerce_project_dir_entry(item)
        if coerced is None:
            continue
        path, label = coerced
        if any(same_dir(path, existing) for existing, _ in entries):
            continue
        entries.append((path, label))
        if len(entries) >= MAX_PROJECT_DIRS:
            logger.warning(
                "project_dirs: more than %d entries supplied; "
                "keeping the first %d",
                MAX_PROJECT_DIRS,
                MAX_PROJECT_DIRS,
            )
            break
    return entries


def detect_nested_roots(entries: Any) -> list[tuple[int, int]]:
    """Detect nested directories inside a project-dir list.

    Returns ``(child_index, ancestor_index)`` pairs — every case where
    the entry at ``child_index`` lives underneath the entry at
    ``ancestor_index``. Nested roots are **reported, not rejected**:
    the UI surfaces a "covered by X" hint and governance de-duplicates
    (only the outermost ancestor is granted/mounted).

    Nesting is a physical relationship independent of order and of
    which entry is primary.
    """
    normalized = normalize_project_dir_list(entries)
    pairs: list[tuple[int, int]] = []
    for child_idx, (child_path, _) in enumerate(normalized):
        for anc_idx, (anc_path, _) in enumerate(normalized):
            if child_idx == anc_idx:
                continue
            if is_within(child_path, anc_path):
                pairs.append((child_idx, anc_idx))
    return pairs


@dataclass(frozen=True)
class ResolvedProjectDir:
    """One effective project directory after resolution."""

    path: Path
    label: Optional[str] = None
    exists: bool = True


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
            exists=self.workspace_dir.is_dir(),
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
        entries = normalize_project_dir_list(session_project_dirs)
        source: ProjectDirSource = SOURCE_SESSION
    else:
        entries = normalize_project_dir_list(
            [agent_project_dir] if agent_project_dir else [],
        )
        source = SOURCE_AGENT if entries else SOURCE_WORKSPACE_FALLBACK

    if request_override is not None:
        override = coerce_project_dir_entry(request_override)
        if override is not None:
            entries = [override] + [
                entry
                for entry in entries
                if not same_dir(entry[0], override[0])
            ]
            source = SOURCE_REQUEST

    if mode_override is not None:
        pinned = normalize_project_dir_list(mode_override)
        if pinned:
            entries = pinned
            source = SOURCE_MODE

    if fork_project_dir is not None:
        worktree = _normalize_optional(fork_project_dir)
        if worktree is not None:
            entries = [(worktree, None)] + [
                entry for entry in entries if not same_dir(entry[0], worktree)
            ]
            source = SOURCE_FORK

    dirs = tuple(
        ResolvedProjectDir(path=path, label=label, exists=path.is_dir())
        for path, label in entries
    )
    return ResolvedProjectDirs(
        dirs=dirs,
        source=source,
        workspace_dir=normalized_workspace,
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


def is_within_roots(path: PathLike, roots: Sequence[PathLike]) -> bool:
    """Return True when *path* resolves inside any of the granted roots.

    Reuses the ToolGuard boundary check (``relative_to``-based, so a
    sibling like ``/foo/bar_evil`` is never mistaken for being inside
    ``/foo/bar``; both sides are ``resolve()``-d). Roots that are
    blank or normalize to nothing are skipped.
    """
    if not roots:
        return False
    from ..security.tool_guard.safety_checks import is_path_outside_boundary

    candidate = _normalize_optional(path)
    if candidate is None:
        return False
    for root in roots:
        base = _normalize_optional(root)
        if base is None:
            continue
        if not is_path_outside_boundary(
            candidate,
            base,
            cwd_is_resolved=True,
            path_is_resolved=True,
        ):
            return True
    return False


def resolve_under_roots(
    path: PathLike,
    *,
    roots: Sequence[PathLike],
    primary: PathLike,
) -> Path:
    """Resolve a tool-supplied path under the granted roots.

    * Absolute input is checked against the roots as-is.
    * Relative input is joined to the **primary** directory — extra
      roots are never a resolution base — and the result may still land
      inside any granted root (``../docs/x`` reaching an extra root is
      legitimate).

    Raises:
        PathEscapeError: the resolved path is outside every root.
        ValueError: the input is blank.
    """
    text = str(path).strip()
    if not text:
        raise ValueError("Empty path")
    candidate = Path(text).expanduser()
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        base = _normalize_optional(primary)
        if base is None:
            raise ValueError("No primary directory available")
        resolved = (base / candidate).resolve()
    if not is_within_roots(resolved, roots):
        raise PathEscapeError(
            f"Path {text!r} resolves outside every authorized project "
            f"directory",
        )
    return resolved


# ---------------------------------------------------------------------------
# Project display name
#
# A name for the directory list *as a unit*, separate from the
# per-directory labels. Purely descriptive — it never takes part in
# resolving a path. Session-level only; derived when not typed.
# ---------------------------------------------------------------------------

MAX_PROJECT_NAME_LEN = 60


def normalize_project_name(raw: Any) -> Optional[str]:
    """Coerce a project display name; ``None`` when blank or unusable."""
    if not isinstance(raw, str):
        return None
    name = raw.strip()
    if not name:
        return None
    return name[:MAX_PROJECT_NAME_LEN]


def session_project_name_from_meta(meta: Optional[dict]) -> Optional[str]:
    """Read the per-chat project display name override, if any."""
    if not isinstance(meta, dict):
        return None
    runtime_context = meta.get("runtime_context")
    if not isinstance(runtime_context, dict):
        return None
    return normalize_project_name(runtime_context.get("project_name"))


def default_project_name(entries: Any) -> Optional[str]:
    """Derive a display name from the directory list.

    The primary entry's label, else its basename, so the UI always has
    something to show without persisting a name nobody typed.
    """
    normalized = normalize_project_dir_list(entries)
    if not normalized:
        return None
    path, label = normalized[0]
    if label:
        return label
    return path.name or str(path)


def resolve_project_name(
    *,
    entries: Any,
    session_name: Optional[str] = None,
) -> Optional[str]:
    """Pick the display name to show for a project.

    A session-set name wins; otherwise a name is derived from the
    primary entry so the UI is never blank.
    """
    normalized = normalize_project_name(session_name)
    if normalized:
        return normalized
    return default_project_name(entries)


# ---------------------------------------------------------------------------
# Chat metadata readers
# ---------------------------------------------------------------------------


def session_project_dir(meta: dict[str, Any] | None) -> str | None:
    """Read the controlled Session project override from Chat metadata.

    Legacy single-value reader kept for existing call sites; only the
    ``runtime_context`` namespace is trusted.
    """
    if not isinstance(meta, dict):
        return None
    runtime_context = meta.get("runtime_context")
    if not isinstance(runtime_context, dict):
        return None
    value = runtime_context.get("project_dir")
    return value if isinstance(value, str) and value.strip() else None


def session_project_dirs_from_meta(meta: Optional[dict]) -> Optional[list]:
    """Read the per-chat project-directory override from chat metadata.

    Returns the persisted list (possibly empty), or ``None`` when the
    chat has no override and should inherit the agent default. Entries
    are normalized on the way out so callers get clean data even if the
    stored metadata predates the list format (a legacy singular
    ``project_dir`` string is read as a single-entry list).
    """
    if not isinstance(meta, dict):
        return None
    runtime_context = meta.get("runtime_context")
    if not isinstance(runtime_context, dict):
        return None

    stored = runtime_context.get("project_dirs")
    if stored is not None:
        if not isinstance(stored, list):
            stored = [stored]
        return [
            {"path": str(path), "label": label}
            for path, label in normalize_project_dir_list(stored)
        ]

    legacy = runtime_context.get("project_dir")
    if isinstance(legacy, str) and legacy.strip():
        entries = normalize_project_dir_list([legacy])
        if entries:
            return [
                {"path": str(path), "label": label}
                for path, label in entries
            ]
    return None


def describe_for_audit(
    resolved: ResolvedProjectDirs,
    workspace_dir: PathLike,
) -> dict[str, Any]:
    """Build the directory context recorded on audit events."""
    primary = resolved.primary
    return {
        "workspace_dir": str(_normalize_optional(workspace_dir) or ""),
        "project_dir": str(primary.path),
        "project_dir_source": resolved.source,
        "project_dir_exists": primary.exists,
        "project_dirs": [str(entry.path) for entry in resolved.dirs],
    }


__all__ = [
    "MAX_PROJECT_DIRS",
    "MAX_PROJECT_DIR_LABEL_LENGTH",
    "MAX_PROJECT_NAME_LEN",
    "PathEscapeError",
    "ResolvedProjectDir",
    "ResolvedProjectDirs",
    "SOURCE_AGENT",
    "SOURCE_FORK",
    "SOURCE_INHERITED",
    "SOURCE_MODE",
    "SOURCE_REQUEST",
    "SOURCE_SESSION",
    "SOURCE_WORKSPACE_FALLBACK",
    "coerce_project_dir_entry",
    "default_project_name",
    "describe_for_audit",
    "detect_nested_roots",
    "is_within",
    "is_within_roots",
    "normalize_project_dir",
    "normalize_project_dir_label",
    "normalize_project_dir_list",
    "normalize_project_name",
    "resolve_effective_project_dir",
    "resolve_effective_project_dirs",
    "resolve_project_name",
    "resolve_under_roots",
    "same_dir",
    "session_project_dir",
    "session_project_dirs_from_meta",
    "session_project_name_from_meta",
]
