# -*- coding: utf-8 -*-
"""Workspace-scoped skill lifecycle service."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ...exceptions import SkillsError
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
    copy_skill_dir,
    default_workspace_manifest,
    extract_zip_skills,
    get_workspace_skill_manifest_path,
    get_workspace_skills_dir,
    import_skill_dir,
    mutate_json,
    normalize_skill_dir_name,
    read_skill_from_dir,
    read_skill_manifest,
    safe_skill_dir,
    scan_skill_dir_or_raise,
    staged_skill_dir,
    suggest_conflict_name,
    validate_skill_content,
    write_skill_to_dir,
)


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

    def list_all_skills(self) -> list[SkillInfo]:
        manifest = self._read_manifest()
        skill_root = get_workspace_skills_dir(self.workspace_dir)
        skills: list[SkillInfo] = []
        for skill_name, entry in sorted(manifest.get("skills", {}).items()):
            skill_dir = skill_root / skill_name
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
            skill = read_skill_from_dir(
                skill_root / skill_name,
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
    ) -> str | None:
        validate_skill_content(content)
        skill_name = normalize_skill_dir_name(name)
        skill_root = get_workspace_skills_dir(self.workspace_dir)
        skill_root.mkdir(parents=True, exist_ok=True)
        skill_dir = safe_skill_dir(skill_root, skill_name)
        if skill_dir.exists():
            return None

        with staged_skill_dir(skill_name) as staged_dir:
            write_skill_to_dir(
                staged_dir,
                content,
                references,
                scripts,
                extra_files,
            )
            scan_skill_dir_or_raise(staged_dir, skill_name)
            copy_skill_dir(staged_dir, skill_dir)

        def _update(payload: dict[str, Any]) -> None:
            payload.setdefault("skills", {})
            entry = payload["skills"].get(skill_name) or {}
            if "source" in entry:
                source = entry["source"]
            elif skill_name in get_packaged_builtin_versions():
                source = "builtin"
            else:
                source = "customized"
            metadata = build_skill_metadata(
                skill_name,
                skill_dir,
                source=source,
                protected=False,
            )
            payload["skills"][skill_name] = {
                "enabled": bool(entry.get("enabled", enable)),
                "channels": entry.get("channels") or ["all"],
                "source": metadata["source"],
                "config": (
                    dict(config)
                    if config is not None
                    else dict(entry.get("config") or {})
                ),
                "metadata": metadata,
                "requirements": metadata["requirements"],
                "updated_at": metadata["updated_at"],
            }

        try:
            mutate_json(
                get_workspace_skill_manifest_path(self.workspace_dir),
                default_workspace_manifest(),
                _update,
            )
        except Exception as exc:
            try:
                if skill_dir.exists():
                    shutil.rmtree(skill_dir, ignore_errors=True)
            except Exception as cleanup_exc:
                raise SkillsError(
                    message=(
                        "Workspace skill files were created, but manifest "
                        "update failed and rollback cleanup also failed."
                    ),
                    details={
                        "skill_name": skill_name,
                        "workspace_dir": str(self.workspace_dir),
                        "manifest_path": str(
                            get_workspace_skill_manifest_path(
                                self.workspace_dir,
                            ),
                        ),
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
                    "manifest_path": str(
                        get_workspace_skill_manifest_path(self.workspace_dir),
                    ),
                },
            ) from exc
        return skill_name

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
        try:
            skill_name = normalize_skill_dir_name(skill_name)
            final_name = normalize_skill_dir_name(target_name or skill_name)
        except SkillsError:
            return {"success": False, "reason": "not_found"}
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
        target_dir = safe_skill_dir(skill_root, final_name)
        if target_dir.exists() and not overwrite:
            existing = (
                {p.name for p in skill_root.iterdir() if p.is_dir()}
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
        skill_dir = safe_skill_dir(skill_root, skill_name)

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
            (skill_dir / "SKILL.md").write_text(
                content,
                encoding="utf-8",
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
                "source": metadata["source"],
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
    ) -> dict[str, Any]:
        skill_root = get_workspace_skills_dir(self.workspace_dir)
        target_dir = safe_skill_dir(skill_root, final_name)
        old_dir = safe_skill_dir(skill_root, skill_name)

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
                "source": metadata["source"],
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

    def import_from_zip(
        self,
        data: bytes,
        enable: bool = False,
        target_name: str | None = None,
        rename_map: dict[str, str] | None = None,
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
                found = [(found[0][0], normalized_target)]
            found = [
                (d, normalize_skill_dir_name(renames.get(n, n)))
                for d, n in found
            ]
            existing_on_disk = (
                {p.name for p in skill_root.iterdir() if p.is_dir()}
                if skill_root.exists()
                else set()
            )
            conflicts: list[dict[str, Any]] = []
            planned: list[tuple[Path, str]] = []
            seen_names: set[str] = set()
            for skill_dir, skill_name in found:
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
                exists = (skill_root / skill_name).exists()
                if exists:
                    conflicts.append(
                        build_import_conflict(
                            skill_name,
                            existing_on_disk,
                        ),
                    )
                    continue
                planned.append((skill_dir, skill_name))
            if conflicts:
                return {
                    "imported": [],
                    "count": 0,
                    "enabled": False,
                    "conflicts": conflicts,
                }
            imported: list[str] = []
            for skill_dir, skill_name in planned:
                if import_skill_dir(
                    skill_dir,
                    skill_root,
                    skill_name,
                ):
                    imported.append(skill_name)

            if imported:
                reconcile_workspace_manifest(self.workspace_dir)
                if enable:
                    for skill_name in imported:
                        self.enable_skill(skill_name)

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
        skill_dir = safe_skill_dir(
            get_workspace_skills_dir(self.workspace_dir),
            skill_name,
        )
        if not skill_dir.exists():
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

        skill_dir = safe_skill_dir(
            get_workspace_skills_dir(self.workspace_dir),
            skill_name,
        )
        if skill_dir.exists():
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
            base_dir = safe_skill_dir(
                get_workspace_skills_dir(self.workspace_dir),
                skill_name,
            )
        except SkillsError:
            return None
        if skill_name not in self._read_manifest().get("skills", {}):
            return None
        if not base_dir.exists():
            return None
        full_path = (base_dir / normalized).resolve()
        if not full_path.is_relative_to(base_dir) or not full_path.is_file():
            return None
        return read_text_file_with_encoding_fallback(full_path)
