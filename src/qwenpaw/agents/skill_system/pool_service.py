# -*- coding: utf-8 -*-
"""Shared skill-pool lifecycle service."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

from ...exceptions import SkillsError
from ..utils.file_handling import read_text_file_with_encoding_fallback
from .models import SkillInfo
from .registry import (
    ensure_skill_pool_initialized,
)
from .store import (
    build_import_conflict,
    build_skill_metadata,
    copy_skill_dir,
    default_pool_manifest,
    default_workspace_manifest,
    extract_zip_skills,
    get_pool_skill_manifest_path,
    get_skill_pool_dir,
    get_workspace_identity,
    get_workspace_skill_manifest_path,
    get_workspace_skills_dir,
    import_skill_dir,
    mutate_json,
    normalize_skill_dir_name,
    read_json,
    read_skill_from_dir,
    read_skill_manifest,
    read_skill_pool_manifest,
    safe_skill_dir,
    scan_skill_dir_or_raise,
    staged_skill_dir,
    suggest_conflict_name,
    validate_skill_content,
    write_skill_to_dir,
)


class SkillPoolService:
    """Shared skill-pool lifecycle service.

    This service manages reusable skills in the local shared pool
    ``WORKING_DIR/skill_pool``. It supports creating pool-native skills,
    importing zips, syncing packaged builtins, uploading skills from a
    workspace into the pool, and downloading pool skills back into one or more
    workspaces.

    The pool is intentionally separate from any single workspace: it is the
    place for shared reuse, conflict detection, and builtin version management.

    Example:
        uploading ``demo_skill`` from workspace ``a1`` stores a shared copy in
        ``skill_pool/demo_skill`` and records the workspace-to-pool linkage in
        the workspace manifest.

        downloading pool skill ``shared_docx`` into workspace ``b1`` creates
        ``workspaces/b1/skills/shared_docx`` and marks its sync state against
        the pool entry.
    """

    def __init__(self):
        ensure_skill_pool_initialized()

    def list_all_skills(self) -> list[SkillInfo]:
        manifest = read_skill_pool_manifest()
        pool_dir = get_skill_pool_dir()
        skills: list[SkillInfo] = []
        for skill_name, entry in sorted(manifest.get("skills", {}).items()):
            skill = read_skill_from_dir(
                pool_dir / skill_name,
                entry.get("source", "customized"),
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
    ) -> str | None:
        validate_skill_content(content)
        skill_name = normalize_skill_dir_name(name)
        pool_dir = get_skill_pool_dir()
        skill_dir = safe_skill_dir(pool_dir, skill_name)
        manifest = read_skill_pool_manifest()
        existing = manifest.get("skills", {}).get(skill_name)
        if existing is not None or skill_dir.exists():
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
            payload["skills"][skill_name] = build_skill_metadata(
                skill_name,
                skill_dir,
                source="customized",
                protected=False,
            )
            if config is not None:
                payload["skills"][skill_name]["config"] = dict(config)

        try:
            mutate_json(
                get_pool_skill_manifest_path(),
                default_pool_manifest(),
                _update,
            )
        except Exception as exc:
            try:
                if skill_dir.exists():
                    shutil.rmtree(skill_dir, ignore_errors=True)
            except Exception as cleanup_exc:
                raise SkillsError(
                    message=(
                        "Skill pool files were created, but manifest update "
                        "failed and rollback cleanup also failed."
                    ),
                    details={
                        "skill_name": skill_name,
                        "manifest_path": str(get_pool_skill_manifest_path()),
                        "cleanup_error": str(cleanup_exc),
                    },
                ) from exc
            raise SkillsError(
                message=(
                    "Skill pool manifest update failed after file creation. "
                    "File changes were rolled back."
                ),
                details={
                    "skill_name": skill_name,
                    "manifest_path": str(get_pool_skill_manifest_path()),
                },
            ) from exc
        return skill_name

    def import_from_zip(
        self,
        data: bytes,
        target_name: str | None = None,
        rename_map: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        pool_dir = get_skill_pool_dir()
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
            manifest = read_skill_pool_manifest()
            existing_pool_names = (
                set(
                    manifest.get("skills", {}).keys(),
                )
                | {p.name for p in pool_dir.iterdir() if p.is_dir()}
                if pool_dir.exists()
                else set(
                    manifest.get("skills", {}).keys(),
                )
            )
            for skill_dir, skill_name in found:
                scan_skill_dir_or_raise(skill_dir, skill_name)
            conflicts: list[dict[str, Any]] = []
            planned: list[tuple[Path, str]] = []
            seen_names: set[str] = set()
            for skill_dir, skill_name in found:
                if skill_name in seen_names:
                    conflicts.append(
                        build_import_conflict(
                            skill_name,
                            existing_pool_names,
                        ),
                    )
                    continue
                seen_names.add(skill_name)
                existing = manifest.get("skills", {}).get(
                    skill_name,
                )
                occupied = (
                    existing is not None or (pool_dir / skill_name).exists()
                )
                if occupied:
                    conflicts.append(
                        build_import_conflict(
                            skill_name,
                            existing_pool_names,
                        ),
                    )
                    continue
                planned.append((skill_dir, skill_name))
            if conflicts:
                return {
                    "imported": [],
                    "count": 0,
                    "conflicts": conflicts,
                }
            imported: list[str] = []
            for skill_dir, skill_name in planned:
                if import_skill_dir(
                    skill_dir,
                    pool_dir,
                    skill_name,
                ):
                    imported.append(skill_name)

            if imported:

                def _update(payload: dict[str, Any]) -> None:
                    payload.setdefault("skills", {})
                    for name in imported:
                        payload["skills"][name] = build_skill_metadata(
                            name,
                            pool_dir / name,
                            source="customized",
                            protected=False,
                        )

                mutate_json(
                    get_pool_skill_manifest_path(),
                    default_pool_manifest(),
                    _update,
                )
            return {
                "imported": imported,
                "count": len(imported),
                "conflicts": conflicts,
            }
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def delete_skill(self, name: str) -> bool:
        try:
            skill_name = normalize_skill_dir_name(name)
        except SkillsError:
            return False
        manifest = read_skill_pool_manifest()
        entry = manifest.get("skills", {}).get(skill_name)
        if entry is None:
            return False

        skill_dir = safe_skill_dir(get_skill_pool_dir(), skill_name)
        if skill_dir.exists():
            shutil.rmtree(skill_dir)

        def _update(payload: dict[str, Any]) -> None:
            payload.get("skills", {}).pop(skill_name, None)

        try:
            mutate_json(
                get_pool_skill_manifest_path(),
                default_pool_manifest(),
                _update,
            )
        except Exception as exc:
            raise SkillsError(
                message=(
                    "Skill pool files were deleted, but manifest update "
                    "failed."
                ),
                details={
                    "skill_name": skill_name,
                    "manifest_path": str(get_pool_skill_manifest_path()),
                },
            ) from exc
        return True

    def set_pool_skill_tags(
        self,
        name: str,
        tags: list[str] | None,
    ) -> bool:
        """Update one pool skill's user tags."""
        try:
            skill_name = normalize_skill_dir_name(name)
        except SkillsError:
            return False
        normalized = tags or []

        def _update(payload: dict[str, Any]) -> bool:
            entry = payload.get("skills", {}).get(skill_name)
            if entry is None:
                return False
            entry["tags"] = normalized
            return True

        return mutate_json(
            get_pool_skill_manifest_path(),
            default_pool_manifest(),
            _update,
        )

    def get_edit_target_name(
        self,
        skill_name: str,
        *,
        target_name: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        try:
            skill_name = normalize_skill_dir_name(skill_name)
            normalized_target = normalize_skill_dir_name(
                target_name or skill_name,
            )
        except SkillsError:
            return {"success": False, "reason": "not_found"}
        manifest = read_skill_pool_manifest()
        entry = manifest.get("skills", {}).get(skill_name)
        if entry is None:
            return {"success": False, "reason": "not_found"}

        pool_names = set(manifest.get("skills", {}).keys())
        if normalized_target == skill_name:
            return {
                "success": True,
                "mode": "edit",
                "name": skill_name,
            }

        existing = manifest.get("skills", {}).get(normalized_target)
        if existing is not None and not overwrite:
            return {
                "success": False,
                "reason": "conflict",
                "mode": "rename",
                "suggested_name": suggest_conflict_name(
                    normalized_target,
                    pool_names,
                ),
            }
        return {
            "success": True,
            "mode": "rename",
            "name": normalized_target,
        }

    def save_pool_skill(
        self,
        *,
        skill_name: str,
        content: str,
        target_name: str | None = None,
        config: dict[str, Any] | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        validate_skill_content(content)
        try:
            skill_name = normalize_skill_dir_name(skill_name)
        except SkillsError:
            return {"success": False, "reason": "not_found"}
        manifest = read_skill_pool_manifest()
        entry = manifest.get("skills", {}).get(skill_name)
        if entry is None:
            return {"success": False, "reason": "not_found"}

        edit_target = self.get_edit_target_name(
            skill_name,
            target_name=target_name,
            overwrite=overwrite,
        )
        if not edit_target.get("success"):
            return edit_target

        final_name = str(edit_target["name"])
        if str(edit_target["mode"]) == "rename" and final_name != skill_name:
            return self._save_pool_skill_as_rename(
                skill_name=skill_name,
                final_name=final_name,
                content=content,
                config=config,
                entry=entry,
            )
        return self._save_pool_skill_in_place(
            skill_name=skill_name,
            content=content,
            config=config,
            entry=entry,
        )

    def _save_pool_skill_in_place(
        self,
        *,
        skill_name: str,
        content: str,
        config: dict[str, Any] | None,
        entry: dict[str, Any],
    ) -> dict[str, Any]:
        skill_dir = safe_skill_dir(get_skill_pool_dir(), skill_name)
        new_config = (
            config if config is not None else entry.get("config") or {}
        )
        old_md = (
            (skill_dir / "SKILL.md").read_text(encoding="utf-8")
            if (skill_dir / "SKILL.md").exists()
            else ""
        )
        content_changed = content != old_md
        if not content_changed and new_config == (entry.get("config") or {}):
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
            else entry.get("source", "customized")
        )

        def _update(payload: dict[str, Any]) -> None:
            payload.setdefault("skills", {})
            current_entry = payload["skills"].get(skill_name) or entry or {}
            next_entry = build_skill_metadata(
                skill_name,
                skill_dir,
                source=source,
                protected=False,
            )
            next_entry["config"] = new_config
            if source == "builtin":
                builtin_language = (
                    str(
                        current_entry.get("builtin_language", "") or "",
                    )
                    .strip()
                    .lower()
                )
                if builtin_language:
                    next_entry["builtin_language"] = builtin_language
                builtin_source_name = str(
                    current_entry.get("builtin_source_name", "") or "",
                ).strip()
                if builtin_source_name:
                    next_entry["builtin_source_name"] = builtin_source_name
            existing_tags = current_entry.get("tags")
            if existing_tags is not None:
                next_entry["tags"] = existing_tags
            payload["skills"][skill_name] = next_entry

        mutate_json(
            get_pool_skill_manifest_path(),
            default_pool_manifest(),
            _update,
        )
        return {
            "success": True,
            "mode": "edit",
            "name": skill_name,
        }

    def _save_pool_skill_as_rename(
        self,
        *,
        skill_name: str,
        final_name: str,
        content: str,
        config: dict[str, Any] | None,
        entry: dict[str, Any],
    ) -> dict[str, Any]:
        pool_dir = get_skill_pool_dir()
        skill_dir = safe_skill_dir(pool_dir, final_name)
        old_skill_dir = safe_skill_dir(pool_dir, skill_name)

        with staged_skill_dir(final_name) as staged_dir:
            if old_skill_dir.exists():
                copy_skill_dir(old_skill_dir, staged_dir)
            (staged_dir / "SKILL.md").write_text(
                content,
                encoding="utf-8",
            )
            scan_skill_dir_or_raise(staged_dir, final_name)
            copy_skill_dir(staged_dir, skill_dir)
        if old_skill_dir.exists():
            shutil.rmtree(old_skill_dir)

        new_config = (
            config if config is not None else entry.get("config") or {}
        )

        def _update(payload: dict[str, Any]) -> None:
            payload.setdefault("skills", {})
            current_entry = payload["skills"].get(skill_name) or entry or {}
            next_entry = build_skill_metadata(
                final_name,
                skill_dir,
                source="customized",
                protected=False,
            )
            next_entry["config"] = new_config
            existing_tags = current_entry.get("tags")
            if existing_tags is not None:
                next_entry["tags"] = existing_tags
            payload["skills"][final_name] = next_entry
            payload["skills"].pop(skill_name, None)

        mutate_json(
            get_pool_skill_manifest_path(),
            default_pool_manifest(),
            _update,
        )
        return {
            "success": True,
            "mode": "rename",
            "name": final_name,
        }

    def upload_from_workspace(
        self,
        workspace_dir: Path,
        skill_name: str,
        *,
        overwrite: bool = False,
        preview_only: bool = False,
    ) -> dict[str, Any]:
        try:
            skill_name = normalize_skill_dir_name(skill_name)
            source_dir = safe_skill_dir(
                get_workspace_skills_dir(workspace_dir),
                skill_name,
            )
        except SkillsError:
            return {"success": False, "reason": "not_found"}
        if not source_dir.exists():
            return {"success": False, "reason": "not_found"}

        final_name = normalize_skill_dir_name(skill_name)
        target_dir = safe_skill_dir(get_skill_pool_dir(), final_name)
        manifest = read_skill_pool_manifest()
        existing = manifest.get("skills", {}).get(final_name)
        if existing:
            if not overwrite:
                return {
                    "success": False,
                    "reason": "conflict",
                    "suggested_name": suggest_conflict_name(
                        final_name,
                    ),
                }
        if preview_only:
            return {"success": True, "name": final_name}

        with staged_skill_dir(final_name) as staged_dir:
            copy_skill_dir(source_dir, staged_dir)
            scan_skill_dir_or_raise(staged_dir, final_name)
            copy_skill_dir(staged_dir, target_dir)

        ws_manifest = read_json(
            get_workspace_skill_manifest_path(workspace_dir),
            default_workspace_manifest(),
        )
        workspace_entry = ws_manifest.get("skills", {}).get(skill_name, {})
        ws_config = workspace_entry.get("config") or {}
        ws_tags = workspace_entry.get("tags")

        def _update(payload: dict[str, Any]) -> None:
            payload.setdefault("skills", {})
            pool_entry = build_skill_metadata(
                final_name,
                target_dir,
                source="customized",
                protected=False,
            )
            if ws_config:
                pool_entry["config"] = ws_config
            if ws_tags is not None:
                pool_entry["tags"] = ws_tags
            payload["skills"][final_name] = pool_entry

        mutate_json(
            get_pool_skill_manifest_path(),
            default_pool_manifest(),
            _update,
        )

        return {"success": True, "name": final_name}

    @staticmethod
    def _check_download_conflict(
        entry: dict[str, Any],
        existing: dict[str, Any] | None,
        final_name: str,
        workspace_identity: dict[str, str],
        workspace_dir: Path,
    ) -> dict[str, Any] | None:
        """Return a conflict dict if download should be blocked."""
        if not existing:
            return None
        ws_id = workspace_identity["workspace_id"]
        ws_name = workspace_identity["workspace_name"]
        if (
            entry.get("source") == "builtin"
            and existing.get("source") == "builtin"
        ):
            pool_ver = entry.get("version_text", "")
            ws_ver = (existing.get("metadata") or {}).get(
                "version_text",
                "",
            )
            if pool_ver and ws_ver and pool_ver == ws_ver:
                pool_lang = str(
                    entry.get("builtin_language", "") or "",
                )
                ws_lang = str(
                    existing.get("builtin_language", "") or "",
                )
                if pool_lang and ws_lang and pool_lang != ws_lang:
                    return {
                        "success": False,
                        "reason": "language_switch",
                        "workspace_id": ws_id,
                        "workspace_name": ws_name,
                        "skill_name": final_name,
                        "source_language": pool_lang,
                        "current_language": ws_lang,
                    }
                if pool_lang and not ws_lang:
                    pool_md = (
                        safe_skill_dir(get_skill_pool_dir(), final_name)
                        / "SKILL.md"
                    )
                    ws_md = (
                        safe_skill_dir(
                            get_workspace_skills_dir(workspace_dir),
                            final_name,
                        )
                        / "SKILL.md"
                    )
                    try:
                        pool_hash = hashlib.sha256(
                            read_text_file_with_encoding_fallback(
                                pool_md,
                            ).encode("utf-8"),
                        ).hexdigest()
                        ws_hash = hashlib.sha256(
                            read_text_file_with_encoding_fallback(
                                ws_md,
                            ).encode("utf-8"),
                        ).hexdigest()
                    except OSError:
                        pool_hash = ws_hash = ""
                    if pool_hash and ws_hash and pool_hash != ws_hash:
                        return {
                            "success": False,
                            "reason": "language_switch",
                            "workspace_id": ws_id,
                            "workspace_name": ws_name,
                            "skill_name": final_name,
                            "source_language": pool_lang,
                            "current_language": ws_lang,
                        }
                return {
                    "success": True,
                    "mode": "unchanged",
                    "name": final_name,
                    "workspace_id": ws_id,
                    "workspace_name": ws_name,
                    "backfill_language": pool_lang or "",
                }
            return {
                "success": False,
                "reason": "builtin_upgrade",
                "workspace_id": ws_id,
                "workspace_name": ws_name,
                "skill_name": final_name,
                "source_version_text": pool_ver,
                "current_version_text": ws_ver,
            }
        return {
            "success": False,
            "reason": "conflict",
            "workspace_id": ws_id,
            "workspace_name": ws_name,
            "suggested_name": suggest_conflict_name(final_name),
        }

    @staticmethod
    def _backfill_workspace_language(
        workspace_dir: Path,
        skill_name: str,
        language: str,
    ) -> None:
        """Write ``builtin_language`` into an existing workspace entry."""

        def _patch(payload: dict[str, Any]) -> None:
            ws_entry = payload.get("skills", {}).get(skill_name)
            if ws_entry is not None:
                ws_entry["builtin_language"] = language

        mutate_json(
            get_workspace_skill_manifest_path(workspace_dir),
            default_workspace_manifest(),
            _patch,
        )

    def download_to_workspace(
        self,
        skill_name: str,
        workspace_dir: Path,
        *,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        try:
            skill_name = normalize_skill_dir_name(skill_name)
        except SkillsError:
            return {"success": False, "reason": "not_found"}
        manifest = read_skill_pool_manifest()
        entry = manifest.get("skills", {}).get(skill_name)
        if entry is None:
            return {"success": False, "reason": "not_found"}

        source_dir = safe_skill_dir(get_skill_pool_dir(), skill_name)
        final_name = normalize_skill_dir_name(skill_name)
        target_dir = safe_skill_dir(
            get_workspace_skills_dir(workspace_dir),
            final_name,
        )
        workspace_manifest = read_skill_manifest(workspace_dir)
        existing = workspace_manifest.get("skills", {}).get(final_name)
        workspace_identity = get_workspace_identity(workspace_dir)
        if not overwrite:
            conflict = self._check_download_conflict(
                entry,
                existing,
                final_name,
                workspace_identity,
                workspace_dir,
            )
            if conflict is not None:
                if conflict.get("backfill_language"):
                    self._backfill_workspace_language(
                        workspace_dir,
                        final_name,
                        conflict["backfill_language"],
                    )
                return conflict

        target_dir.parent.mkdir(parents=True, exist_ok=True)
        with staged_skill_dir(final_name) as staged_dir:
            copy_skill_dir(source_dir, staged_dir)
            scan_skill_dir_or_raise(staged_dir, final_name)
            copy_skill_dir(staged_dir, target_dir)

        pool_config = entry.get("config") or {}
        pool_tags = entry.get("tags")

        def _update(payload: dict[str, Any]) -> None:
            payload.setdefault("skills", {})
            metadata = build_skill_metadata(
                final_name,
                target_dir,
                source="builtin"
                if entry.get("source") == "builtin"
                else "customized",
                protected=False,
            )
            ws_entry: dict[str, Any] = {
                "enabled": True,
                "channels": ["all"],
                "source": metadata["source"],
                "config": pool_config,
                "metadata": metadata,
                "requirements": metadata["requirements"],
                "updated_at": metadata["updated_at"],
            }
            pool_lang = str(
                entry.get("builtin_language", "") or "",
            )
            if entry.get("source") == "builtin" and pool_lang:
                ws_entry["builtin_language"] = pool_lang
            if pool_tags is not None:
                ws_entry["tags"] = pool_tags
            payload["skills"][final_name] = ws_entry

        mutate_json(
            get_workspace_skill_manifest_path(workspace_dir),
            default_workspace_manifest(),
            _update,
        )
        return {
            "success": True,
            "name": final_name,
            "workspace_id": workspace_identity["workspace_id"],
            "workspace_name": workspace_identity["workspace_name"],
        }

    def preflight_download_to_workspace(
        self,
        skill_name: str,
        workspace_dir: Path,
        *,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        manifest = read_skill_pool_manifest()
        entry = manifest.get("skills", {}).get(skill_name)
        if entry is None:
            return {"success": False, "reason": "not_found"}

        final_name = normalize_skill_dir_name(skill_name)
        workspace_manifest = read_skill_manifest(workspace_dir)
        existing = workspace_manifest.get("skills", {}).get(final_name)
        workspace_identity = get_workspace_identity(workspace_dir)
        if not overwrite:
            conflict = self._check_download_conflict(
                entry,
                existing,
                final_name,
                workspace_identity,
                workspace_dir,
            )
            if conflict is not None:
                return conflict
        return {
            "success": True,
            "workspace_id": workspace_identity["workspace_id"],
            "workspace_name": workspace_identity["workspace_name"],
            "name": final_name,
        }
