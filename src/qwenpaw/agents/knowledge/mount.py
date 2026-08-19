# -*- coding: utf-8 -*-
"""Mount shared knowledge bases into an agent workspace as ``knowledge/``."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from .store import ensure_kb, kb_root, validate_kb_id

logger = logging.getLogger(__name__)


class KnowledgeMountError(RuntimeError):
    """Raised when workspace→knowledge mount cannot be established."""


def _is_junction_or_symlink(path: Path) -> bool:
    """Return True if path is a symlink or Windows directory junction.

    Uses ``GetFileAttributesW`` (not ``path.exists()``) for the junction
    check so a *dangling* junction — whose target has been deleted but
    whose reparse point still sits on disk — is still recognized as a
    link. ``path.exists()`` follows the link and would return False for
    a dangling junction, hiding it.
    """
    if path.is_symlink():
        return True
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            GetFileAttributesW = ctypes.windll.kernel32.GetFileAttributesW
            GetFileAttributesW.argtypes = [wintypes.LPCWSTR]
            GetFileAttributesW.restype = wintypes.DWORD
            attrs = GetFileAttributesW(str(path))
            FILE_ATTRIBUTE_REPARSE_POINT = 0x400
            if attrs != 0xFFFFFFFF and attrs & FILE_ATTRIBUTE_REPARSE_POINT:
                return True
        except Exception:
            return False
    return False


def _resolve_mount_target(path: Path) -> Path | None:
    """Best-effort resolve of a mount link to its target directory."""
    try:
        if path.is_symlink():
            return path.resolve()
        if os.name == "nt" and path.exists():
            return path.resolve()
    except OSError:
        return None
    return None


def _create_windows_junction(link: Path, target: Path) -> None:
    """Create a Windows directory junction (no admin required)."""
    # Prefer mklink /J — works without SeCreateSymbolicLinkPrivilege.
    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise KnowledgeMountError(
            "Failed to create Windows junction from "
            f"{link} -> {target}: {completed.stderr or completed.stdout}",
        )


def _create_symlink(link: Path, target: Path) -> None:
    """Create a directory symlink (POSIX) or junction (Windows)."""
    if os.name == "nt":
        _create_windows_junction(link, target)
        return
    os.symlink(target, link, target_is_directory=True)


def detect_dangling_mount(
    workspace_dir: str | Path,
    *,
    mount_name: str = "knowledge",
) -> Path | None:
    """Return the mount path if it is a link whose KB target is gone.

    A dangling mount means the shared knowledge-base directory was removed
    (e.g. by a human deleting it on disk) while this agent still has a
    junction/symlink pointing at it. Returns ``None`` when the mount is
    absent, is a real directory, or points at an existing target.
    """
    mount = Path(workspace_dir).expanduser().resolve() / (mount_name or "knowledge")
    if not (mount.is_symlink() or _is_junction_or_symlink(mount)):
        return None
    target = _resolve_mount_target(mount)
    if target is None:
        return mount
    if not target.exists():
        return mount
    return None


def ensure_knowledge_mount(
    workspace_dir: str | Path,
    kb_id: str,
    *,
    mount_name: str = "knowledge",
    domain: str = "business",
) -> Path:
    """Ensure ``workspace/{mount_name}`` points at the shared KB.

    Creates the KB skeleton if needed. Refuses to start shared mode when an
    existing non-link directory occupies the mount point.

    Raises ``KnowledgeMountError`` when the mount link exists but its KB
    target directory is gone (dangling mount). This happens when a human
    deletes the shared KB on disk while the agent still references it; we
    refuse to silently recreate an empty KB (which would mask the deletion
    and lose the user's intent) and instead surface the situation so the
    user can restore the KB or rebind the agent.
    """
    kb_id = validate_kb_id(kb_id)
    workspace = Path(workspace_dir).expanduser().resolve()
    mount = workspace / (mount_name or "knowledge")

    # Detect a dangling mount BEFORE ensure_kb recreates the KB skeleton.
    # Without this check, ensure_kb() would silently rebuild an empty KB
    # and the agent would resume against an empty knowledge base, hiding
    # the fact that the user deleted the shared KB.
    dangling = detect_dangling_mount(workspace, mount_name=mount_name or "knowledge")
    if dangling is not None:
        raise KnowledgeMountError(
            f"Knowledge mount {mount} points at a missing shared knowledge "
            f"base (kb_id={kb_id}). The knowledge-base directory was removed "
            "from disk. Restore it, or update the agent's "
            "knowledge_base_id to rebind to a different knowledge base.",
        )

    ensure_kb(kb_id, domain=domain)
    target = kb_root(kb_id).resolve()

    if mount.exists() or mount.is_symlink() or _is_junction_or_symlink(mount):
        if _is_junction_or_symlink(mount) or mount.is_symlink():
            current = _resolve_mount_target(mount)
            if current is not None and current.resolve() == target:
                return mount
            # Remount when pointing elsewhere.
            if mount.is_symlink() or _is_junction_or_symlink(mount):
                if mount.is_dir() and not mount.is_symlink():
                    # Windows junction: rmdir removes the link, not the target.
                    mount.rmdir()
                else:
                    mount.unlink()
            else:
                raise KnowledgeMountError(
                    f"Mount path {mount} exists and is not a link; "
                    "refusing to overwrite for knowledge sharing.",
                )
        elif mount.is_dir():
            # Empty dir can be replaced; non-empty refuses shared start.
            if any(mount.iterdir()):
                raise KnowledgeMountError(
                    f"Mount path {mount} is a non-empty directory. "
                    "Knowledge sharing requires a junction/symlink mount; "
                    "refuse copy fallback.",
                )
            mount.rmdir()
        else:
            raise KnowledgeMountError(
                f"Mount path {mount} exists and cannot be replaced.",
            )

    try:
        _create_symlink(mount, target)
    except KnowledgeMountError:
        raise
    except OSError as exc:
        raise KnowledgeMountError(
            f"Failed to mount knowledge base {kb_id} at {mount}: {exc}",
        ) from exc

    logger.info(
        "Mounted knowledge base %s at %s -> %s",
        kb_id,
        mount,
        target,
    )
    return mount


def unmount_knowledge(
    workspace_dir: str | Path,
    *,
    mount_name: str = "knowledge",
) -> bool:
    """Remove the knowledge mount link only (never delete the shared KB)."""
    mount = Path(workspace_dir).expanduser() / (mount_name or "knowledge")
    if not (mount.exists() or mount.is_symlink() or _is_junction_or_symlink(mount)):
        return False
    if mount.is_symlink():
        mount.unlink()
        return True
    if _is_junction_or_symlink(mount) and mount.is_dir():
        mount.rmdir()
        return True
    return False
