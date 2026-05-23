# -*- coding: utf-8 -*-
"""Sandbox view ↔ host path translation.

Holds DataPaw's path conversion core. ``PathContext`` describes the two
in-sandbox mount points (``/workspace`` plus an optional ``/skills``)
mapped to host directories, and exposes two resolution entry points
that differ by *caller scenario*:

- ``to_host``: sandbox tool entry. Translates a sandbox-view path
  (``/workspace/...``, ``/skills/...``, or a path relative to the current
  node cwd) into a host absolute path. Strict rules: empty string is
  rejected, foreign absolute paths are rejected, ``..`` escapes are
  rejected.
- ``resolve_artifact_path``: REST / artifact / HTML rewrite entry. The
  input may be a ``/workspace/...`` path or a host absolute path (when
  the sandbox subsystem is off, ``ArtifactItem.path`` itself may hold a
  host absolute path). Never raises, does not recognize ``/skills`` and
  does not prefix ``current_rel_path``; callers must use ``contains()``
  to gate against escapes themselves.

Auxiliary methods:

- ``to_virtual``: host path → sandbox view; returns ``None`` if outside
  any known mount.
- ``normalize_command``: rewrite recognized host prefixes inside a shell
  command string to their sandbox-view equivalents.
- ``contains``: check whether a host path is still under ``mount_dir``;
  the escape-check fallback for ``resolve_artifact_path`` callers.

Plus two host-side root helpers:

- ``default_artifacts_root``: default artifacts root when the sandbox is
  off / not attached (``workspace_dir/artifacts`` or
  ``WORKING_DIR/workspaces/{agent_id}/artifacts``).
- ``shared_artifacts_root``: same fallback chain with an optional
  ``mount_override`` for callers that need to point elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from qwenpaw.constant import WORKING_DIR

from .i18n import tr


ARTIFACTS_DIR_NAME = "artifacts"


def default_artifacts_root(
    agent_id: str,
    workspace_dir: Path | None = None,
) -> Path:
    """Default host artifacts root when the sandbox is off / unattached.

    With ``workspace_dir`` given: ``{workspace_dir}/artifacts``.
    Otherwise: ``{WORKING_DIR}/workspaces/{agent_id}/artifacts``.
    """
    if workspace_dir is not None:
        return (
            Path(workspace_dir).expanduser() / ARTIFACTS_DIR_NAME
        ).resolve()
    return (
        WORKING_DIR / "workspaces" / agent_id / ARTIFACTS_DIR_NAME
    ).resolve()


def shared_artifacts_root(
    agent_id: str,
    workspace_dir: Path | None = None,
    mount_override: Path | None = None,
) -> Path:
    """Workspace-shared artifacts root (sandbox on/off share the same value).

    With ``mount_override`` set: return it expanded and resolved.
    Otherwise: delegate to :func:`default_artifacts_root`.

    Sandbox-off callers should pass ``mount_override=None`` and skip the
    detour through ``SandboxConfig`` entirely.
    """
    if mount_override is not None:
        return Path(mount_override).expanduser().resolve()
    return default_artifacts_root(agent_id, workspace_dir)


def _replace_path_token(command: str, old: str, new: str) -> tuple[str, bool]:
    """Conservative path-token substitution inside a shell command string."""
    old = old.rstrip("/")
    if not old or old == "/" or old not in command:
        return command, False
    return command.replace(old, new.rstrip("/") or "/"), True


@dataclass(frozen=True)
class PathContext:
    """Bi-directional converter between sandbox view and host paths.

    Attributes:
        mount_dir: Host directory mounted at ``/workspace``.
        skills_dir: Host directory mounted at ``/skills``; when ``None``,
            the ``/skills`` prefix is not recognized (``to_host`` treats
            those paths like any other absolute path and rejects them).
        skills_target: Literal mount-point inside the sandbox for skills;
            defaults to ``"/skills"``.
        current_rel_path: Sandbox current-node cwd, relative to
            ``mount_dir``. ``to_host`` prefixes this onto relative inputs.
        lang: Locale tag for LLM-facing error messages returned by
            :meth:`to_host` (``"zh"`` / ``"en"``); defaults to ``"zh"``.
            Developer-facing strings (logger, exception detail) are
            English regardless.
    """

    mount_dir: Path
    skills_dir: Path | None = None
    skills_target: str = "/skills"
    current_rel_path: str = ""
    lang: str = "zh"

    def __post_init__(self) -> None:
        object.__setattr__(self, "mount_dir", Path(self.mount_dir).resolve())
        if self.skills_dir is not None:
            object.__setattr__(
                self,
                "skills_dir",
                Path(self.skills_dir).resolve(),
            )

    @property
    def _skills_target_norm(self) -> str:
        return (self.skills_target or "/skills").rstrip("/") or "/skills"

    # --- sandbox view → host -----------------------------------------------

    def to_host(self, virtual_path: str) -> tuple[Path, str | None]:
        """Translate a sandbox-view path to a host absolute path.

        Returns ``(host_abs_path, error_msg)``: success is ``(Path, None)``,
        failure is ``(Path(""), error_msg)``.

        Dispatch by prefix:
        - Empty string → rejected.
        - ``/skills`` / ``/skills/...`` → :meth:`_resolve_skills`.
        - ``/workspace`` / ``/workspace/...`` → :meth:`_resolve_workspace`.
        - Any other absolute path → rejected (caller should use a relative
          path or a ``/workspace/`` prefix).
        - Relative path → :meth:`_resolve_relative` (prefixed with
          ``current_rel_path``).

        External / artifact callers (which may legitimately pass host
        absolute paths) should use :meth:`resolve_artifact_path` instead.
        """
        fp = str(virtual_path or "").strip()
        if not fp:
            return Path(""), tr("path.empty", self.lang)

        skills_target = self._skills_target_norm
        if fp == skills_target or fp.startswith(f"{skills_target}/"):
            return self._resolve_skills(fp)

        if fp == "/workspace" or fp.startswith("/workspace/"):
            return self._resolve_workspace(fp)

        if fp.startswith("/"):
            return Path(""), tr(
                "path.absolute_forbidden",
                self.lang,
                fp=fp,
            )

        return self._resolve_relative(fp)

    def _resolve_skills(self, fp: str) -> tuple[Path, str | None]:
        """Resolve a ``/skills`` or ``/skills/...`` sandbox-view path.

        Caller has already verified the prefix. Rejects when ``skills_dir``
        is unset and when the resolved path escapes ``skills_dir``.
        """
        skills_target = self._skills_target_norm
        if self.skills_dir is None:
            return Path(""), tr(
                "path.skills_unmounted",
                self.lang,
                target=skills_target,
            )
        raw_rel = fp[len(skills_target) :].lstrip("/")
        candidate = (self.skills_dir / raw_rel).resolve()
        if not candidate.is_relative_to(self.skills_dir):
            return Path(""), tr(
                "path.skills_escape",
                self.lang,
                fp=fp,
                resolved=candidate,
                root=self.skills_dir,
            )
        return candidate, None

    def _resolve_workspace(self, fp: str) -> tuple[Path, str | None]:
        """Resolve a ``/workspace`` or ``/workspace/...`` sandbox-view path.

        Caller has already verified the prefix. Rejects when the resolved
        path escapes ``mount_dir``.
        """
        if fp == "/workspace":
            return self.mount_dir, None
        raw_rel = fp[len("/workspace/") :].lstrip("/")
        candidate = (self.mount_dir / raw_rel).resolve()
        if not candidate.is_relative_to(self.mount_dir):
            return Path(""), tr(
                "path.workspace_escape",
                self.lang,
                fp=fp,
                resolved=candidate,
                root=self.mount_dir,
            )
        return candidate, None

    def _resolve_relative(self, fp: str) -> tuple[Path, str | None]:
        """Resolve a relative sandbox-view path against ``current_rel_path``.

        Caller has already verified that ``fp`` is non-empty and does not
        start with ``/``. If ``fp`` already starts with ``current_rel_path``,
        the prefix is not duplicated. Rejects escapes from ``mount_dir``.
        """
        base_rel = self.current_rel_path.strip().strip("/")
        if base_rel and (fp == base_rel or fp.startswith(f"{base_rel}/")):
            raw_rel = fp
        elif base_rel:
            raw_rel = f"{base_rel}/{fp}"
        else:
            raw_rel = fp
        candidate = (self.mount_dir / raw_rel).resolve()
        if not candidate.is_relative_to(self.mount_dir):
            return Path(""), tr(
                "path.workspace_escape",
                self.lang,
                fp=fp,
                resolved=candidate,
                root=self.mount_dir,
            )
        return candidate, None

    # --- host → sandbox view -----------------------------------------------

    def to_virtual(self, host_path: str | Path) -> str | None:
        """Host path → sandbox view; ``None`` if outside known mounts."""
        if not host_path:
            return None
        try:
            p = Path(host_path).resolve()
        except (OSError, ValueError):
            return None

        if self.skills_dir is not None:
            try:
                rel = p.relative_to(self.skills_dir)
            except ValueError:
                pass
            else:
                rel_str = str(rel)
                if rel_str == ".":
                    return self._skills_target_norm
                return f"{self._skills_target_norm}/{rel_str}"

        try:
            rel = p.relative_to(self.mount_dir)
        except ValueError:
            return None
        rel_str = str(rel)
        return "/workspace" if rel_str == "." else f"/workspace/{rel_str}"

    def normalize_command(self, command: str) -> tuple[str, bool]:
        """Rewrite known host prefixes in a shell command to sandbox paths."""
        normalized = command
        changed = False
        if self.skills_dir is not None:
            normalized, did = _replace_path_token(
                normalized,
                str(self.skills_dir),
                self._skills_target_norm,
            )
            changed = changed or did
        normalized, did = _replace_path_token(
            normalized,
            str(self.mount_dir),
            "/workspace",
        )
        changed = changed or did
        return normalized, changed

    # --- Artifact path resolution (external / REST entry) ------------------

    def resolve_artifact_path(self, path: str) -> Path:
        """Resolve an artifact path to a host ``Path`` (external / REST entry).

        Differs from :meth:`to_host` by intended caller: this entry
        accepts paths supplied via the artifact index, REST routes, or
        HTML rewriting, which may be ``/workspace/...`` *or* host
        absolute paths (in non-sandbox mode ``ArtifactItem.path`` is the
        host absolute path itself). It never raises, never recognizes
        ``/skills``, and never prefixes ``current_rel_path``; callers
        should defend against escapes with :meth:`contains`.

        Sandbox tools must use :meth:`to_host` instead.
        """
        fp = str(path or "").strip()
        if not fp:
            return self.mount_dir
        candidate = Path(fp)
        if candidate.is_absolute() and not (
            fp == "/workspace" or fp.startswith("/workspace/")
        ):
            return candidate.resolve()
        if fp == "/workspace":
            return self.mount_dir
        if fp.startswith("/workspace/"):
            fp = fp[len("/workspace/") :]
        return (self.mount_dir / fp.lstrip("/")).resolve()

    def contains(self, path: Path) -> bool:
        """Return ``True`` iff ``path`` is still under ``mount_dir``."""
        return Path(path).resolve().is_relative_to(self.mount_dir)
