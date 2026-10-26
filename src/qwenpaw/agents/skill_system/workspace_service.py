# -*- coding: utf-8 -*-
"""Workspace-scoped skill lifecycle service."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from ...exceptions import SkillsError
from ...utils.io_utils import write_text_atomic
from ..utils.file_handling import read_text_file_with_encoding_fallback
from .models import SkillInfo
from .registry import (
    get_packaged_builtin_versions,
    reconcile_workspace_manifest,
    resolve_effective_skills,
)
from .store import (
    build_import_conflict,
    build_skill_metadata,
    commit_pawport_skill,
    copy_skill_dir,
    discard_prepared_pawport_skill,
    default_workspace_manifest,
    extract_zip_skills,
    get_workspace_skill_manifest_path,
    get_workspace_skills_dir,
    import_skill_dir,
    iter_skill_dirs,
    mutate_json,
    normalize_skill_dir_name,
    read_skill_from_dir,
    read_skill_manifest,
    rel_path_of,
    renamed_skill_rel_path,
    resolve_skill_dir,
    resolve_skill_dir_checked,
    safe_nested_skill_dir,
    safe_skill_dir,
    scan_skill_dir_or_raise,
    staged_skill_dir,
    suggest_conflict_name,
    validate_skill_content,
    write_skill_to_dir,
)


def _register_workspace_skill_entry(
    payload: dict[str, Any],
    skill_name: str,
    skill_dir: Path,
    *,
    enable: bool = False,
    installed_from: str = "",
    config: dict[str, Any] | None = None,
    source: str | None = None,
    rel_path: str = "",
) -> None:
    """Upsert a workspace skill entry — single source of truth for shape."""
    payload.setdefault("skills", {})
    entry = payload["skills"].get(skill_name) or {}
    # Explicit *source* wins (e.g. /make-skill stamps "agent"); otherwise
    # fall back to existing entry / builtin lookup / "customized" default.
    if source is not None:
        resolved_source = source
    elif "source" in entry:
        resolved_source = entry["source"]
    elif skill_name in get_packaged_builtin_versions():
        resolved_source = "builtin"
    else:
        resolved_source = "customized"
    metadata = build_skill_metadata(
        skill_name,
        skill_dir,
        source=resolved_source,
        protected=False,
    )
    payload["skills"][skill_name] = {
        "enabled": bool(entry.get("enabled", enable)),
        "channels": entry.get("channels") or ["all"],
        "preload": entry.get("preload") is True,
        "source": metadata["source"],
        "rel_path": rel_path,
        "installed_from": (
            installed_from or str(entry.get("installed_from", "") or "")
        ),
        "config": (
            dict(config)
            if config is not None
            else dict(entry.get("config") or {})
        ),
        "metadata": metadata,
        "requirements": metadata["requirements"],
        "updated_at": metadata["updated_at"],
    }


def _resolve_install_source(source_dir: Path) -> Path:
    source_value = os.path.abspath(
        os.path.expanduser(os.fspath(source_dir)),
    )
    if os.path.islink(source_value) or not os.path.isdir(source_value):
        raise SkillsError(message="Skill source must be a directory")
    source_root = Path(source_value).resolve()
    skill_md = (source_root / "SKILL.md").resolve()
    if not skill_md.is_relative_to(source_root) or not skill_md.is_file():
        raise SkillsError(message="Skill source must contain SKILL.md")
    resolved_source = source_root
    try:
        for path in resolved_source.rglob("*"):
            if path.is_symlink():
                raise SkillsError(
                    message=f"Symlink not allowed in skill: {path}",
                )
            if not path.is_file() and not path.is_dir():
                raise SkillsError(
                    message=f"Unsupported file type in skill: {path}",
                )
    except OSError as exc:
        raise SkillsError(message="Could not inspect Skill source") from exc
    return resolved_source


def _resolve_install_root(workspace_dir: Path, source_root: Path) -> Path:
    skill_root = get_workspace_skills_dir(workspace_dir)
    if skill_root.is_symlink():
        raise SkillsError(message="Workspace Skill root cannot be a symlink")
    skill_root.mkdir(parents=True, exist_ok=True)
    resolved_skill_root = skill_root.resolve(strict=True)
    if resolved_skill_root.parent != workspace_dir.resolve(strict=True):
        raise SkillsError(message="Workspace Skill root is outside workspace")
    if resolved_skill_root.is_relative_to(source_root):
        raise SkillsError(
            message="Skill source cannot contain the install destination",
        )
    return resolved_skill_root


def _install_conflict_result(
    skill_root: Path,
    skill_name: str,
) -> dict[str, Any]:
    existing = {path.name for path in iter_skill_dirs(skill_root)}
    return {
        "success": False,
        "reason": "conflict",
        "name": skill_name,
        "suggested_name": suggest_conflict_name(skill_name, existing),
    }


class SkillService:
    """Workspace-scoped skill lifecycle service.

    This service owns editable skills inside one workspace, including create,
    zip import, enable/disable, channel routing, config persistence, and file
    access. It treats ``<workspace>/skills`` as the source of truth for skill
    content and ``<workspace>/skill.json`` as the source of truth for runtime
    state such as ``enabled`` and ``channels``.

    Example:
        a user creates ``demo_skill`` in workspace ``a1`` -> files are written
        under ``workspaces/a1/skills/demo_skill`` and metadata/state are
        reconciled into ``workspaces/a1/skill.json``.

        a user enables ``docx`` for the ``discord`` channel only -> the skill
        files stay the same, but the workspace manifest updates ``enabled`` and
        ``channels`` so runtime resolution changes on the next read.
    """

    def __init__(self, workspace_dir: Path):
        self.workspace_dir = Path(workspace_dir).expanduser()
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

    def _read_manifest(self) -> dict[str, Any]:
        return read_skill_manifest(self.workspace_dir)

    def _resolve_skill_dir(self, skill_name: str) -> Path | None:
        """Resolve a workspace skill name to its (possibly nested) dir.

        The manifest ``rel_path`` is authoritative. The checked variant
        rejects symlinked categories that resolve outside the skills root, so
        every mutation path (save / delete / enable) shares one boundary
        policy instead of silently writing outside the workspace.
        """
        manifest = self._read_manifest()
        entry = manifest.get("skills", {}).get(skill_name) or {}
        return resolve_skill_dir_checked(
            get_workspace_skills_dir(self.workspace_dir),
            skill_name,
            str(entry.get("rel_path") or ""),
        )

    def list_all_skills(self) -> list[SkillInfo]:
        manifest = self._read_manifest()
        skill_root = get_workspace_skills_dir(self.workspace_dir)
        skills: list[SkillInfo] = []
        for skill_name, entry in sorted(manifest.get("skills", {}).items()):
            skill_dir = resolve_skill_dir(
                skill_root,
                skill_name,
                str(entry.get("rel_path") or ""),
            )
            if skill_dir is None:
                continue
            source = entry.get("source", "customized")
            skill = read_skill_from_dir(skill_dir, source)
            if skill is not None:
                skills.append(skill)
        return skills

    def list_available_skills(self) -> list[SkillInfo]:
        manifest = self._read_manifest()
        skill_root = get_workspace_skills_dir(self.workspace_dir)
        skills: list[SkillInfo] = []
        for skill_name in resolve_effective_skills(
            self.workspace_dir,
            "console",
        ):
            entry = manifest.get("skills", {}).get(skill_name, {})
            skill_dir = resolve_skill_dir(
                skill_root,
                skill_name,
                str(entry.get("rel_path") or ""),
            )
            if skill_dir is None:
                continue
            skill = read_skill_from_dir(
                skill_dir,
                "builtin"
                if entry.get("source", "customized") == "builtin"
                else "customized",
            )
            if skill is not None:
                skills.append(skill)
        return skills

    def create_skill(
        self,
        name: str,
        content: str,
        references: dict[str, Any] | None = None,
        scripts: dict[str, Any] | None = None,
        extra_files: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
        enable: bool = False,
        installed_from: str = "",
        source: str | None = None,
    ) -> str | None:
        validate_skill_content(content)
        skill_name = normalize_skill_dir_name(name)
        skill_root = get_workspace_skills_dir(self.workspace_dir)
        skill_root.mkdir(parents=True, exist_ok=True)
        if resolve_skill_dir(skill_root, skill_name) is not None:
            return None
        with staged_skill_dir(skill_name) as staged_dir:
            write_skill_to_dir(
                staged_dir,
                content,
                references,
                scripts,
                extra_files,
            )
            result = self.install_skill_directory(
                staged_dir,
                target_name=skill_name,
                enable=enable,
                installed_from=installed_from,
                config=config,
                source=source,
            )
        return str(result["name"]) if result["success"] else None

    def install_skill_directory(
        self,
        source_dir: Path,
        *,
        target_name: str | None = None,
        rel_path: str = "",
        enable: bool = False,
        source: str | None = None,
        installed_from: str = "",
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Install one complete local Skill directory without overwriting.

        ``source_dir`` must be selected by a trusted caller, must not be a
        symlink, and must contain ``SKILL.md``. Raw client-provided paths must
        not be forwarded to this filesystem API.
        """
        source_root = _resolve_install_source(source_dir)
        resolved_skill_root = _resolve_install_root(
            self.workspace_dir,
            source_root,
        )
        staged_dir: Path | None = None
        try:
            stage = Path(
                tempfile.mkdtemp(
                    prefix="~skill-install-",
                    dir=resolved_skill_root,
                ),
            )
            staged_dir = stage
            copy_skill_dir(source_root, stage)
            skill_md = stage / "SKILL.md"
            if skill_md.is_symlink() or not skill_md.is_file():
                raise SkillsError(message="Skill source must contain SKILL.md")
            content = read_text_file_with_encoding_fallback(skill_md)
            declared_name, _ = validate_skill_content(content)
            skill_name = normalize_skill_dir_name(target_name or declared_name)
            scan_skill_dir_or_raise(stage, skill_name)

            target_dir = safe_nested_skill_dir(
                resolved_skill_root,
                rel_path or skill_name,
            )
            if target_dir.exists() or target_dir.is_symlink():
                return _install_conflict_result(
                    resolved_skill_root,
                    skill_name,
                )
            manifest_path = get_workspace_skill_manifest_path(
                self.workspace_dir,
            )
            installed = False
            conflict = False
            installed_enabled = bool(enable)

            target_dir.parent.mkdir(parents=True, exist_ok=True)

            def _install(payload: dict[str, Any]) -> bool:
                nonlocal conflict, installed, installed_enabled
                if target_dir.exists() or target_dir.is_symlink():
                    conflict = True
                    return False
                payload.setdefault("skills", {})
                stage.rename(target_dir)
                installed = True
                _register_workspace_skill_entry(
                    payload,
                    skill_name,
                    target_dir,
                    enable=enable,
                    source=source,
                    installed_from=installed_from,
                    config=config,
                    rel_path=rel_path_of(resolved_skill_root, target_dir),
                )
                installed_enabled = bool(
                    payload["skills"][skill_name]["enabled"],
                )
                return True

            try:
                mutate_json(
                    manifest_path,
                    default_workspace_manifest(),
                    _install,
                )
            except Exception as exc:
                if installed:
                    try:
                        shutil.rmtree(target_dir)
                    except OSError as cleanup_exc:
                        raise SkillsError(
                            message=(
                                "Workspace skill files were created, but "
                                "manifest update failed and rollback cleanup "
                                "also failed."
                            ),
                            details={
                                "skill_name": skill_name,
                                "workspace_dir": str(self.workspace_dir),
                                "manifest_path": str(manifest_path),
                                "cleanup_error": str(cleanup_exc),
                            },
                        ) from exc
                raise SkillsError(
                    message=(
                        "Workspace skill files were created, but manifest "
                        "update failed. File changes were rolled back."
                    ),
                    details={
                        "skill_name": skill_name,
                        "workspace_dir": str(self.workspace_dir),
                        "manifest_path": str(manifest_path),
                    },
                ) from exc

            if conflict:
                return _install_conflict_result(
                    resolved_skill_root,
                    skill_name,
                )
            return {
                "success": True,
                "name": skill_name,
                "enabled": installed_enabled,
                "path": str(target_dir),
            }
        except UnicodeError as exc:
            raise SkillsError(
                message="Could not read source SKILL.md",
            ) from exc
        except OSError as exc:
            raise SkillsError(
                message="Could not install Skill directory",
            ) from exc
        finally:
            if staged_dir is not None and staged_dir.exists():
                shutil.rmtree(staged_dir, ignore_errors=True)

    def save_skill(
        self,
        *,
        skill_name: str,
        content: str,
        target_name: str | None = None,
        config: dict[str, Any] | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Edit-in-place or rename-save a workspace skill."""
        validate_skill_content(content)
        try:
            skill_name = normalize_skill_dir_name(skill_name)
        except SkillsError:
            return {"success": False, "reason": "not_found"}
        final_name = normalize_skill_dir_name(target_name or skill_name)
        manifest = self._read_manifest()
        old_entry = manifest.get("skills", {}).get(skill_name)
        if old_entry is None:
            return {"success": False, "reason": "not_found"}

        if final_name == skill_name:
            return self._save_skill_in_place(
                skill_name=skill_name,
                content=content,
                config=config,
                old_entry=old_entry,
            )

        skill_root = get_workspace_skills_dir(self.workspace_dir)
        old_dir = resolve_skill_dir_checked(
            skill_root,
            skill_name,
            str(old_entry.get("rel_path") or ""),
        ) or safe_skill_dir(skill_root, skill_name)
        target_rel = renamed_skill_rel_path(
            rel_path_of(skill_root, old_dir),
            final_name,
        )
        target_dir = safe_nested_skill_dir(skill_root, target_rel)
        # Check the exact destination the rename will write, and treat an
        # existing skill identity (same leaf name anywhere) as a conflict:
        # silently replacing an enabled skill is data loss.
        identity_exists = final_name in manifest.get("skills", {})
        if not overwrite and (target_dir.exists() or identity_exists):
            existing = (
                {p.name for p in iter_skill_dirs(skill_root)}
                if skill_root.exists()
                else set()
            )
            return {
                "success": False,
                "reason": "conflict",
                "suggested_name": suggest_conflict_name(
                    final_name,
                    existing,
                ),
            }
        return self._save_skill_as_rename(
            skill_name=skill_name,
            final_name=final_name,
            content=content,
            config=config,
            old_entry=old_entry,
            old_dir=old_dir,
            target_dir=target_dir,
            target_rel=target_rel,
        )

    def _save_skill_in_place(
        self,
        *,
        skill_name: str,
        content: str,
        config: dict[str, Any] | None,
        old_entry: dict[str, Any],
    ) -> dict[str, Any]:
        new_config = (
            config if config is not None else old_entry.get("config") or {}
        )
        skill_root = get_workspace_skills_dir(self.workspace_dir)
        skill_root.mkdir(parents=True, exist_ok=True)
        skill_dir = resolve_skill_dir_checked(
            skill_root,
            skill_name,
            str(old_entry.get("rel_path") or ""),
        ) or safe_skill_dir(
            skill_root,
            skill_name,
        )
        rel_path = rel_path_of(skill_root, skill_dir)

        old_md = (
            (skill_dir / "SKILL.md").read_text(encoding="utf-8")
            if (skill_dir / "SKILL.md").exists()
            else ""
        )
        content_changed = content != old_md
        if not content_changed and new_config == (
            old_entry.get("config") or {}
        ):
            return {
                "success": True,
                "mode": "noop",
                "name": skill_name,
            }

        if content_changed:
            with staged_skill_dir(skill_name) as staged_dir:
                if skill_dir.exists():
                    copy_skill_dir(skill_dir, staged_dir)
                (staged_dir / "SKILL.md").write_text(
                    content,
                    encoding="utf-8",
                )
                scan_skill_dir_or_raise(staged_dir, skill_name)
            write_text_atomic(
                skill_dir / "SKILL.md",
                content,
                encoding="utf-8",
                new_file_mode=0o644,
            )
        source = (
            "customized"
            if content_changed
            else old_entry.get("source", "customized")
        )
        metadata = build_skill_metadata(
            skill_name,
            skill_dir,
            source=source,
            protected=False,
        )

        def _edit(payload: dict[str, Any]) -> None:
            payload.setdefault("skills", {})
            current_entry = (
                payload["skills"].get(skill_name) or old_entry or {}
            )
            next_entry = {
                "enabled": bool(current_entry.get("enabled", False)),
                "channels": current_entry.get("channels") or ["all"],
                "preload": current_entry.get("preload") is True,
                "source": metadata["source"],
                "rel_path": rel_path,
                "installed_from": str(
                    current_entry.get("installed_from", "") or "",
                ),
                "config": new_config,
                "metadata": metadata,
                "requirements": metadata["requirements"],
                "updated_at": metadata["updated_at"],
            }
            existing_tags = current_entry.get("tags")
            if existing_tags is not None:
                next_entry["tags"] = existing_tags
            payload["skills"][skill_name] = next_entry

        mutate_json(
            get_workspace_skill_manifest_path(self.workspace_dir),
            default_workspace_manifest(),
            _edit,
        )
        return {
            "success": True,
            "mode": "edit",
            "name": skill_name,
        }

    def _save_skill_as_rename(
        self,
        *,
        skill_name: str,
        final_name: str,
        content: str,
        config: dict[str, Any] | None,
        old_entry: dict[str, Any],
        old_dir: Path,
        target_dir: Path,
        target_rel: str,
    ) -> dict[str, Any]:
        with staged_skill_dir(final_name) as staged_dir:
            copy_skill_dir(old_dir, staged_dir)
            (staged_dir / "SKILL.md").write_text(
                content,
                encoding="utf-8",
            )
            scan_skill_dir_or_raise(staged_dir, final_name)
            copy_skill_dir(staged_dir, target_dir)

        old_config = (
            config if config is not None else old_entry.get("config") or {}
        )
        old_channels = old_entry.get("channels") or ["all"]
        metadata = build_skill_metadata(
            final_name,
            target_dir,
            source="customized",
            protected=False,
        )

        def _rename_entry(payload: dict[str, Any]) -> None:
            payload.setdefault("skills", {})
            current_entry = (
                payload["skills"].get(skill_name) or old_entry or {}
            )
            next_entry = {
                "enabled": bool(current_entry.get("enabled", False)),
                "channels": current_entry.get("channels") or old_channels,
                "preload": current_entry.get("preload") is True,
                "source": metadata["source"],
                "rel_path": target_rel,
                "installed_from": str(
                    current_entry.get("installed_from", "") or "",
                ),
                "config": old_config,
                "metadata": metadata,
                "requirements": metadata["requirements"],
                "updated_at": metadata["updated_at"],
            }
            existing_tags = current_entry.get("tags")
            if existing_tags is not None:
                next_entry["tags"] = existing_tags
            payload["skills"][final_name] = next_entry
            payload["skills"].pop(skill_name, None)

        mutate_json(
            get_workspace_skill_manifest_path(self.workspace_dir),
            default_workspace_manifest(),
            _rename_entry,
        )
        if old_dir.exists():
            shutil.rmtree(old_dir)

        return {
            "success": True,
            "mode": "rename",
            "name": final_name,
        }

    # Import planning intentionally handles validation, conflicts, and commit
    # as one transaction-like flow.
    # pylint: disable-next=too-many-branches
    def import_from_zip(
        self,
        data: bytes,
        enable: bool = False,
        target_name: str | None = None,
        rename_map: dict[str, str] | None = None,
        pawport_owner: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        skill_root = get_workspace_skills_dir(self.workspace_dir)
        skill_root.mkdir(parents=True, exist_ok=True)
        tmp_dir, found = extract_zip_skills(data)
        renames = rename_map or {}
        try:
            normalized_target = str(target_name or "").strip()
            if normalized_target:
                normalized_target = normalize_skill_dir_name(
                    normalized_target,
                )
                if len(found) != 1:
                    raise SkillsError(
                        message=(
                            "target_name is only supported for "
                            "single-skill zip imports"
                        ),
                    )
                found = [
                    (
                        found[0][0],
                        normalized_target,
                        renamed_skill_rel_path(
                            found[0][2],
                            normalized_target,
                        ),
                    ),
                ]
            # rename_map keys may be either a skill name (legacy clients) or
            # the archive rel_path (source-specific, so a/foo and b/foo can
            # be renamed independently). The destination leaf always follows
            # the renamed name; the category prefix is preserved.
            renamed_found: list[tuple[Path, str, str]] = []
            for skill_dir, skill_name, rel_path in found:
                rename = renames.get(rel_path) if rel_path else None
                if rename is None:
                    rename = renames.get(skill_name, skill_name)
                new_name = normalize_skill_dir_name(rename)
                renamed_found.append(
                    (
                        skill_dir,
                        new_name,
                        renamed_skill_rel_path(rel_path, new_name),
                    ),
                )
            found = renamed_found
            manifest = self._read_manifest()
            existing_entries = manifest.get("skills", {})
            existing_on_disk = (
                {p.name for p in iter_skill_dirs(skill_root)}
                if skill_root.exists()
                else set()
            )
            conflicts: list[dict[str, Any]] = []
            planned: list[tuple[Path, str, str]] = []
            seen_names: set[str] = set()
            for skill_dir, skill_name, dest_rel in found:
                validate_skill_content(
                    (skill_dir / "SKILL.md").read_text(encoding="utf-8"),
                )
                scan_skill_dir_or_raise(skill_dir, skill_name)
                if skill_name in seen_names:
                    conflicts.append(
                        build_import_conflict(
                            skill_name,
                            existing_on_disk,
                        ),
                    )
                    continue
                seen_names.add(skill_name)
                entry = existing_entries.get(skill_name) or {}
                current_dir = resolve_skill_dir(
                    skill_root,
                    skill_name,
                    str(entry.get("rel_path") or ""),
                )
                current_rel = (
                    rel_path_of(skill_root, current_dir)
                    if current_dir is not None
                    else ""
                )
                target_dir = safe_nested_skill_dir(skill_root, dest_rel)
                exists = target_dir.exists()
                if exists and pawport_owner is not None:
                    exists = not discard_prepared_pawport_skill(
                        target_dir,
                        pawport_owner,
                    )
                # Skill identity is the leaf name, not the path: importing
                # ``a/foo`` while ``foo`` exists elsewhere would silently
                # replace (and re-enable) the existing identity. Only a
                # same-location replacement may reuse the identity.
                identity_occupied = (
                    skill_name in existing_entries
                    or skill_name in existing_on_disk
                )
                if identity_occupied and current_rel != dest_rel:
                    conflicts.append(
                        build_import_conflict(
                            skill_name,
                            existing_on_disk,
                            selected=dest_rel,
                            shadowed=current_rel,
                        ),
                    )
                    continue
                if exists:
                    conflicts.append(
                        build_import_conflict(
                            skill_name,
                            existing_on_disk,
                        ),
                    )
                    continue
                planned.append((skill_dir, skill_name, dest_rel))
            if conflicts:
                return {
                    "imported": [],
                    "count": 0,
                    "enabled": False,
                    "conflicts": conflicts,
                }
            imported: list[str] = []
            imported_dests: list[tuple[str, str]] = []
            for skill_dir, skill_name, dest_rel in planned:
                if import_skill_dir(
                    skill_dir,
                    skill_root,
                    skill_name,
                    pawport_owner,
                    dest_rel,
                ):
                    imported.append(skill_name)
                    imported_dests.append((skill_name, dest_rel))

            if imported:
                reconcile_workspace_manifest(self.workspace_dir)

                def _mark_imported_entries(payload: dict[str, Any]) -> None:
                    skills = payload.setdefault("skills", {})
                    for name in imported:
                        entry = skills.get(name)
                        if entry is not None:
                            entry["installed_from"] = "zip"

                mutate_json(
                    get_workspace_skill_manifest_path(self.workspace_dir),
                    default_workspace_manifest(),
                    _mark_imported_entries,
                )

                if enable:
                    for skill_name in imported:
                        self.enable_skill(skill_name)
                if pawport_owner is not None:
                    for _skill_name, dest_rel in imported_dests:
                        commit_pawport_skill(
                            skill_root / dest_rel,
                            pawport_owner,
                        )

            return {
                "imported": imported,
                "count": len(imported),
                "enabled": enable and bool(imported),
                "conflicts": conflicts,
            }
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def enable_skill(
        self,
        name: str,
        target_workspaces: list[str] | None = None,
    ) -> dict[str, Any]:
        # Enabling a skill only flips manifest state after a fresh scan of the
        # current on-disk skill directory.
        #
        # Example:
        # if ``skills/docx`` was edited after creation and now violates scan
        # policy, enable returns a scan failure instead of trusting old state.
        try:
            skill_name = normalize_skill_dir_name(name)
        except SkillsError:
            return {
                "success": False,
                "updated_workspaces": [],
                "failed": [self.workspace_dir.name],
                "reason": "not_found",
            }
        if (
            target_workspaces
            and self.workspace_dir.name not in target_workspaces
        ):
            return {
                "success": False,
                "updated_workspaces": [],
                "failed": target_workspaces,
                "reason": "workspace_mismatch",
            }

        manifest_path = get_workspace_skill_manifest_path(self.workspace_dir)
        skill_dir = self._resolve_skill_dir(skill_name)
        if skill_dir is None or not skill_dir.exists():
            return {
                "success": False,
                "updated_workspaces": [],
                "failed": [self.workspace_dir.name],
                "reason": "not_found",
            }
        scan_skill_dir_or_raise(skill_dir, skill_name)

        def _update(payload: dict[str, Any]) -> bool:
            entry = payload.get("skills", {}).get(skill_name)
            if entry is None:
                return False
            entry["enabled"] = True
            entry.setdefault("channels", ["all"])
            return True

        updated = mutate_json(
            manifest_path,
            default_workspace_manifest(),
            _update,
        )
        if not updated:
            return {
                "success": False,
                "updated_workspaces": [],
                "failed": [self.workspace_dir.name],
                "reason": "not_found",
            }

        return {
            "success": True,
            "updated_workspaces": [self.workspace_dir.name],
            "failed": [],
            "reason": None,
        }

    def disable_skill(self, name: str) -> dict[str, Any]:
        try:
            skill_name = normalize_skill_dir_name(name)
        except SkillsError:
            return {"success": False, "updated_workspaces": []}
        manifest_path = get_workspace_skill_manifest_path(self.workspace_dir)

        def _update(payload: dict[str, Any]) -> bool:
            entry = payload.get("skills", {}).get(skill_name)
            if entry is None:
                return False
            entry["enabled"] = False
            return True

        updated = mutate_json(
            manifest_path,
            default_workspace_manifest(),
            _update,
        )
        if not updated:
            return {"success": False, "updated_workspaces": []}

        return {
            "success": True,
            "updated_workspaces": [self.workspace_dir.name],
        }

    def set_skill_channels(
        self,
        name: str,
        channels: list[str] | None,
    ) -> bool:
        """Update one workspace skill's channel scope."""
        try:
            skill_name = normalize_skill_dir_name(name)
        except SkillsError:
            return False
        manifest_path = get_workspace_skill_manifest_path(self.workspace_dir)
        normalized = channels or ["all"]

        def _update(payload: dict[str, Any]) -> bool:
            entry = payload.get("skills", {}).get(skill_name)
            if entry is None:
                return False
            entry["channels"] = normalized
            return True

        updated = mutate_json(
            manifest_path,
            default_workspace_manifest(),
            _update,
        )
        return updated

    def set_skill_preload(self, name: str, preload: bool) -> bool:
        """Update one workspace skill's preload policy."""
        try:
            skill_name = normalize_skill_dir_name(name)
        except SkillsError:
            return False
        manifest_path = get_workspace_skill_manifest_path(self.workspace_dir)

        def _update(payload: dict[str, Any]) -> bool:
            entry = payload.get("skills", {}).get(skill_name)
            if entry is None:
                return False
            entry["preload"] = preload
            return True

        return mutate_json(
            manifest_path,
            default_workspace_manifest(),
            _update,
        )

    def set_skill_tags(
        self,
        name: str,
        tags: list[str] | None,
    ) -> bool:
        """Update one workspace skill's user tags."""
        try:
            skill_name = normalize_skill_dir_name(name)
        except SkillsError:
            return False
        manifest_path = get_workspace_skill_manifest_path(
            self.workspace_dir,
        )
        normalized = tags or []

        def _update(payload: dict[str, Any]) -> bool:
            entry = payload.get("skills", {}).get(skill_name)
            if entry is None:
                return False
            entry["tags"] = normalized
            return True

        return mutate_json(
            manifest_path,
            default_workspace_manifest(),
            _update,
        )

    def delete_skill(self, name: str) -> bool:
        try:
            skill_name = normalize_skill_dir_name(name)
        except SkillsError:
            return False
        manifest = self._read_manifest()
        entry = manifest.get("skills", {}).get(skill_name)
        if entry is None or entry.get("enabled", False):
            return False

        skill_dir = self._resolve_skill_dir(skill_name)
        if skill_dir is not None and skill_dir.exists():
            shutil.rmtree(skill_dir)

        def _update(payload: dict[str, Any]) -> None:
            payload.get("skills", {}).pop(skill_name, None)

        try:
            mutate_json(
                get_workspace_skill_manifest_path(self.workspace_dir),
                default_workspace_manifest(),
                _update,
            )
        except Exception as exc:
            raise SkillsError(
                message=(
                    "Workspace skill files were deleted, but manifest "
                    "update failed."
                ),
                details={
                    "skill_name": skill_name,
                    "workspace_dir": str(self.workspace_dir),
                    "manifest_path": str(
                        get_workspace_skill_manifest_path(self.workspace_dir),
                    ),
                },
            ) from exc
        return True

    # pylint: disable-next=too-many-return-statements
    def load_skill_file(
        self,
        skill_name: str,
        file_path: str,
    ) -> str | None:
        normalized = file_path.replace("\\", "/")
        if (
            ".." in normalized
            or normalized.startswith("/")
            or not (
                normalized.startswith("references/")
                or normalized.startswith("scripts/")
            )
        ):
            return None
        try:
            skill_name = normalize_skill_dir_name(skill_name)
            base_dir = self._resolve_skill_dir(skill_name)
        except SkillsError:
            return None
        if base_dir is None:
            return None
        if skill_name not in self._read_manifest().get("skills", {}):
            return None
        if not base_dir.exists():
            return None
        full_path = (base_dir / normalized).resolve()
        if not full_path.is_relative_to(base_dir) or not full_path.is_file():
            return None
        return read_text_file_with_encoding_fallback(full_path)
