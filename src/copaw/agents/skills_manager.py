# -*- coding: utf-8 -*-
"""Skills management: sync skills from code to working_dir."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import shutil
import tempfile
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar

import frontmatter
from pydantic import BaseModel, Field
from ..security.skill_scanner import scan_skill_directory

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover
    msvcrt = None

if fcntl is None and msvcrt is None:  # pragma: no cover
    raise ImportError(
        "No file locking module available (need fcntl or msvcrt)",
    )

logger = logging.getLogger(__name__)

ALL_SKILL_ROUTING_CHANNELS = [
    "console",
    "discord",
    "telegram",
    "dingtalk",
    "feishu",
    "imessage",
    "qq",
    "mattermost",
    "wecom",
    "mqtt",
]

_RegistryResult = TypeVar("_RegistryResult")
_MAX_ZIP_BYTES = 1024 * 1024 * 1024


class SkillInfo(BaseModel):
    """Workspace or hub skill details returned to callers."""

    name: str
    description: str = ""
    content: str
    source: str
    path: str
    references: dict[str, Any] = Field(default_factory=dict)
    scripts: dict[str, Any] = Field(default_factory=dict)


class SkillRequirements(BaseModel):
    """System-managed requirements declared by a skill."""

    require_bins: list[str] = Field(default_factory=list)
    require_envs: list[str] = Field(default_factory=list)


_ACTIVE_SKILL_ENV_ENTRIES: dict[str, dict[str, Any]] = {}


def get_builtin_skills_dir() -> Path:
    """Return the packaged built-in skill directory."""
    return Path(__file__).parent / "skills"


def get_skill_pool_dir() -> Path:
    """Return the local shared skill pool directory."""
    from ..constant import WORKING_DIR

    return Path(WORKING_DIR) / "skill_pool"


def get_workspace_skills_dir(workspace_dir: Path) -> Path:
    """Return the workspace skill source directory."""
    preferred = workspace_dir / "skills"
    legacy = workspace_dir / "skill"
    if preferred.exists():
        return preferred
    if legacy.exists():
        try:
            legacy.rename(preferred)
        except OSError:
            return legacy
    return preferred


def get_workspace_skill_manifest_path(workspace_dir: Path) -> Path:
    """Return the workspace skill manifest path."""
    return workspace_dir / "skill.json"


def get_pool_skill_manifest_path() -> Path:
    """Return the shared pool skill manifest path."""
    return get_skill_pool_dir() / "skill.json"


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _directory_tree(directory: Path) -> dict[str, Any]:
    """Recursively describe a directory tree for UI display."""
    tree: dict[str, Any] = {}
    if not directory.exists() or not directory.is_dir():
        return tree

    for item in sorted(directory.iterdir()):
        if item.is_file():
            tree[item.name] = None
        elif item.is_dir():
            tree[item.name] = _directory_tree(item)

    return tree


def _read_frontmatter(skill_dir: Path) -> Any:
    return frontmatter.loads(
        (skill_dir / "SKILL.md").read_text(encoding="utf-8"),
    )


def _extract_version(post: Any) -> str:
    metadata = post.get("metadata") or {}
    for value in (
        post.get("version"),
        metadata.get("version"),
        metadata.get("builtin_skill_version"),
    ):
        if value not in (None, ""):
            return str(value)
    return ""


def _build_signature(skill_dir: Path) -> str:
    """Hash the full skill tree using real file paths and real contents.

    This is the canonical content identity used by migration, pool sync,
    and conflict detection. If any file changes, including ``SKILL.md``,
    the signature changes.

    Example:
        ``skill_pool/docx`` and ``workspaces/a1/skills/docx`` with identical
        files produce the same signature and are treated as synced.
        If the workspace copy edits ``SKILL.md`` or ``scripts/run.py``,
        the signatures diverge and sync status becomes ``conflict``.
    """
    digest = hashlib.sha256()
    for path in sorted(p for p in skill_dir.rglob("*") if p.is_file()):
        digest.update(str(path.relative_to(skill_dir)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _copy_skill_dir(source: Path, target: Path) -> None:
    """Replace *target* with a copy of *source*.

    We intentionally filter only well-known OS/cache artifacts so skill
    content behaves consistently on macOS, Windows, Linux, and Docker.
    User-authored dotfiles are preserved.
    """
    if target.exists():
        shutil.rmtree(target)

    def _ignore(_dir: str, names: list[str]) -> set[str]:
        ignored_names = {
            "__pycache__",
            "__MACOSX",
            ".DS_Store",
            "Thumbs.db",
            "desktop.ini",
        }
        return {name for name in names if name in ignored_names}

    shutil.copytree(
        source,
        target,
        ignore=_ignore,
    )


def _lock_path_for(json_path: Path) -> Path:
    return json_path.with_name(f".{json_path.name}.lock")


@contextmanager
def _file_write_lock(lock_path: Path) -> Iterator[None]:
    """Serialize manifest mutations across processes."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        elif msvcrt is not None:  # pragma: no cover
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            elif msvcrt is not None:  # pragma: no cover
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


def _read_json_unlocked(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return json.loads(json.dumps(default))
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Malformed JSON in %s, resetting to default", path)
        return json.loads(json.dumps(default))


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    with _file_write_lock(_lock_path_for(path)):
        return _read_json_unlocked(path, default)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temp_path: Path | None = None
    payload = dict(payload)
    payload["version"] = max(
        int(payload.get("version", 0)) + 1,
        int(datetime.now(timezone.utc).timestamp() * 1000),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=path.parent,
            prefix=f".{path.stem}_",
            suffix=path.suffix,
            delete=False,
            encoding="utf-8",
        ) as handle:
            handle.write(json.dumps(payload, indent=2, ensure_ascii=False))
            temp_path = Path(handle.name)
        temp_path.replace(path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink(missing_ok=True)


def _mutate_json(
    path: Path,
    default: dict[str, Any],
    mutator: Callable[[dict[str, Any]], _RegistryResult],
) -> _RegistryResult:
    with _file_write_lock(_lock_path_for(path)):
        payload = _read_json_unlocked(path, default)
        result = mutator(payload)
        _write_json_atomic(path, payload)
        return result


def _default_workspace_manifest() -> dict[str, Any]:
    return {
        "schema_version": "workspace-skill-manifest.v1",
        "version": 0,
        "skills": {},
    }


def _default_pool_manifest() -> dict[str, Any]:
    return {
        "schema_version": "skill-pool-manifest.v1",
        "version": 0,
        "skills": {},
        "builtin_skill_names": [],
    }


def _get_builtin_skill_names() -> list[str]:
    """Get list of builtin skill names from src/copaw/agents/skills/."""
    builtin_dir = get_builtin_skills_dir()
    if not builtin_dir.exists():
        return []
    return sorted(
        [
            p.name
            for p in builtin_dir.iterdir()
            if p.is_dir() and (p / "SKILL.md").exists()
        ],
    )


def _is_builtin_skill(skill_name: str, builtin_names: list[str]) -> bool:
    """Check if skill name is in builtin list."""
    return skill_name in builtin_names


def _is_hidden(name: str) -> bool:
    return name in {
        "__pycache__",
        "__MACOSX",
        ".DS_Store",
        "Thumbs.db",
        "desktop.ini",
    }


def _extract_and_validate_zip(data: bytes, tmp_dir: Path) -> None:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        total = sum(info.file_size for info in zf.infolist())
        if total > _MAX_ZIP_BYTES:
            raise ValueError("Uncompressed zip exceeds 200MB limit")

        root_path = tmp_dir.resolve()
        for info in zf.infolist():
            target = (tmp_dir / info.filename).resolve()
            if not target.is_relative_to(root_path):
                raise ValueError(f"Unsafe path in zip: {info.filename}")
            if info.external_attr >> 16 & 0o120000 == 0o120000:
                raise ValueError(
                    f"Symlink not allowed in zip: {info.filename}",
                )

        zf.extractall(tmp_dir)


def _safe_child_path(base_dir: Path, relative_name: str) -> Path:
    """Resolve a relative child path and reject traversal / absolute paths."""
    normalized = (relative_name or "").replace("\\", "/").strip()
    if not normalized:
        raise ValueError("Skill file path cannot be empty")
    if normalized.startswith("/"):
        raise ValueError(f"Absolute path not allowed: {relative_name}")

    path = (base_dir / normalized).resolve()
    base_resolved = base_dir.resolve()
    if not path.is_relative_to(base_resolved):
        raise ValueError(
            f"Unsafe path outside skill directory: {relative_name}",
        )
    return path


def _create_files_from_tree(base_dir: Path, tree: dict[str, Any]) -> None:
    for name, value in (tree or {}).items():
        path = _safe_child_path(base_dir, name)
        if isinstance(value, dict):
            path.mkdir(parents=True, exist_ok=True)
            _create_files_from_tree(path, value)
        elif value is None or isinstance(value, str):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value or "", encoding="utf-8")
        else:
            raise ValueError(f"Invalid tree value for {name}: {type(value)}")


def _resolve_skill_name(skill_dir: Path) -> str:
    try:
        post = _read_frontmatter(skill_dir)
        name = str(post.get("name") or "").strip()
        if name:
            return name
    except Exception:
        pass
    return skill_dir.name


def _find_skill_dirs(root: Path) -> list[tuple[Path, str]]:
    if (root / "SKILL.md").exists():
        return [(root, _resolve_skill_name(root))]
    return [
        (path, _resolve_skill_name(path))
        for path in sorted(root.iterdir())
        if not _is_hidden(path.name)
        and path.is_dir()
        and (path / "SKILL.md").exists()
    ]


def read_skill_requirements(skill_dir: Path) -> SkillRequirements:
    """Parse skill requirements from frontmatter metadata."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return SkillRequirements()

    post = frontmatter.loads(skill_md.read_text(encoding="utf-8"))
    metadata = post.get("metadata") or {}
    if "openclaw" in metadata:
        requires = metadata["openclaw"].get("requires", {})
    elif "copaw" in metadata:
        requires = metadata["copaw"].get("requires", {})
    else:
        requires = metadata.get("requires", {})

    return SkillRequirements(
        require_bins=list(requires.get("bins", [])),
        require_envs=list(requires.get("env", [])),
    )


def _stringify_skill_env_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _skill_config_env_var_name(skill_name: str) -> str:
    normalized = [
        char if char.isalnum() else "_"
        for char in str(skill_name or "").upper()
    ]
    return f"COPAW_SKILL_CONFIG_{''.join(normalized).strip('_') or 'DEFAULT'}"


def _build_skill_config_env_overrides(
    skill_name: str,
    config: dict[str, Any],
    require_envs: list[str],
) -> dict[str, str]:
    overrides: dict[str, str] = {}

    env_config = config.get("env")
    if isinstance(env_config, dict):
        for raw_key, raw_value in env_config.items():
            env_key = str(raw_key or "").strip()
            if not env_key or raw_value in (None, ""):
                continue
            overrides[env_key] = _stringify_skill_env_value(raw_value)

    api_key = config.get("api_key")
    if api_key in (None, ""):
        api_key = config.get("apiKey")

    normalized_required_envs = [
        str(env_name).strip()
        for env_name in require_envs
        if str(env_name).strip()
    ]
    if api_key not in (None, "") and len(normalized_required_envs) == 1:
        overrides.setdefault(
            normalized_required_envs[0],
            _stringify_skill_env_value(api_key),
        )

    overrides[_skill_config_env_var_name(skill_name)] = json.dumps(
        config,
        ensure_ascii=False,
    )
    return overrides


def _acquire_skill_env_key(key: str, value: str) -> bool:
    active = _ACTIVE_SKILL_ENV_ENTRIES.get(key)
    if active is not None:
        if active["value"] != value:
            return False
        active["count"] += 1
        if os.environ.get(key) is None:
            os.environ[key] = value
        return True

    if os.environ.get(key) is not None:
        return False

    _ACTIVE_SKILL_ENV_ENTRIES[key] = {
        "baseline": None,
        "value": value,
        "count": 1,
    }
    os.environ[key] = value
    return True


def _release_skill_env_key(key: str) -> None:
    active = _ACTIVE_SKILL_ENV_ENTRIES.get(key)
    if active is None:
        return

    active["count"] -= 1
    if active["count"] > 0:
        if os.environ.get(key) is None:
            os.environ[key] = active["value"]
        return

    _ACTIVE_SKILL_ENV_ENTRIES.pop(key, None)
    os.environ.pop(key, None)


@contextmanager
def apply_skill_config_env_overrides(
    workspace_dir: Path,
    channel_name: str,
) -> Iterator[None]:
    """Inject effective skill config into env for one agent turn.

    Mirrors the provider-style runtime injection pattern without requiring
    skill registration changes. Skill scripts can read:

    - explicit env values from ``config.env``
    - a single required env auto-filled from ``config.api_key``/``apiKey``
    - the full JSON config from ``COPAW_SKILL_CONFIG_<SKILL_NAME>``
    """
    manifest = reconcile_workspace_manifest(workspace_dir)
    entries = manifest.get("skills", {})
    active_keys: list[str] = []

    try:
        for skill_name in resolve_effective_skills(
            workspace_dir,
            channel_name,
        ):
            entry = entries.get(skill_name) or {}
            config = entry.get("config") or {}
            if not isinstance(config, dict) or not config:
                continue

            requirements = entry.get("requirements") or {}
            require_envs = requirements.get("require_envs") or []
            overrides = _build_skill_config_env_overrides(
                skill_name,
                config,
                list(require_envs),
            )
            for env_key, env_value in overrides.items():
                if not _acquire_skill_env_key(env_key, env_value):
                    logger.warning(
                        "Skipped env override '%s' for skill '%s'",
                        env_key,
                        skill_name,
                    )
                    continue
                active_keys.append(env_key)
        yield
    finally:
        for env_key in reversed(active_keys):
            _release_skill_env_key(env_key)


def _build_skill_metadata(
    skill_name: str,
    skill_dir: Path,
    *,
    source: str,
    origin: dict[str, Any] | None = None,
    protected: bool = False,
) -> dict[str, Any]:
    """Build the manifest-facing metadata for one concrete skill directory.

    The metadata is derived from the actual files on disk every time we
    reconcile. That keeps the manifest descriptive rather than authoritative
    for content details.

    Example:
        if ``skills/docx/SKILL.md`` changes description text, the next
        reconcile updates ``description`` and ``signature`` here without the
        caller manually editing ``skill.json``.
    """
    post = _read_frontmatter(skill_dir)
    requirements = read_skill_requirements(skill_dir)
    now = _timestamp()
    return {
        "name": skill_name,
        "description": str(post.get("description", "") or ""),
        "version_text": _extract_version(post),
        "commit_text": "",
        "signature": _build_signature(skill_dir),
        "source": source,
        "protected": protected,
        "origin": origin or {},
        "requirements": requirements.model_dump(),
        "updated_at": now,
    }


def suggest_conflict_name(skill_name: str) -> str:
    """Return a timestamp-suffixed rename suggestion for collisions."""
    suffix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{skill_name}-{suffix}"


# pylint: disable=too-many-statements
def _sync_builtin_skills_into_pool(
    force: bool = False,
    approve_conflicts: bool = False,
    overwrite_existing: bool = True,
    preview_only: bool = False,
) -> dict[str, list[Any]]:
    """Mirror packaged builtins into the local skill pool.

    Behavior summary:
    - Missing builtin in pool -> copy it in.
    - Unmodified builtin in pool -> leave it alone.
    - Locally modified builtin in pool -> report conflict unless conflicts are
      explicitly approved.
    - Non-builtin skill already using the builtin name -> either conflict or
      rename that local skill before restoring the builtin.

    Example:
        if packaged ``pdf`` is version 2.0 but local ``skill_pool/pdf`` was
        manually edited, ``fetch_latest_builtin_skills()`` reports a conflict
        instead of silently overwriting the local copy.
    """
    pool_dir = get_skill_pool_dir()
    pool_dir.mkdir(parents=True, exist_ok=True)

    synced: list[str] = []
    updates: list[str] = []
    additions: list[str] = []
    conflicts: list[dict[str, str]] = []
    renamed: list[dict[str, str]] = []

    builtin_dir = get_builtin_skills_dir()
    if not builtin_dir.exists():
        return {"synced": synced, "conflicts": conflicts}

    manifest_path = get_pool_skill_manifest_path()
    manifest_default = _default_pool_manifest()

    # pylint: disable=too-many-branches
    def _process(payload: dict[str, Any]) -> dict[str, list[Any]]:
        skills = payload.setdefault("skills", {})
        payload["builtin_skill_names"] = _get_builtin_skill_names()
        for skill_dir in sorted(builtin_dir.iterdir()):
            if not skill_dir.is_dir() or not (skill_dir / "SKILL.md").exists():
                continue

            skill_name = skill_dir.name
            target = pool_dir / skill_name
            existing = skills.get(skill_name)
            existing_source = (existing or {}).get("source")
            existing_signature = str((existing or {}).get("signature") or "")
            builtin_signature = _build_signature(skill_dir)
            target_signature = (
                _build_signature(target) if target.exists() else ""
            )

            # Gate 1: non-builtin skill already occupies this name.
            # Three branches:
            #   same-signature  -> pass-through (content identical)
            #   approve_conflicts -> rename the occupant, then restore
            #   else            -> report conflict to caller
            if existing is not None and existing_source not in {
                "builtin",
                None,
            }:
                if existing_signature == builtin_signature:
                    pass
                elif approve_conflicts:
                    suggested_name = suggest_conflict_name(
                        skill_name,
                    )
                    renamed_target = pool_dir / suggested_name
                    while renamed_target.exists():
                        suggested_name = suggest_conflict_name(
                            suggested_name,
                        )
                        renamed_target = pool_dir / suggested_name
                    if target.exists():
                        target.rename(renamed_target)
                    skills[suggested_name] = _build_skill_metadata(
                        suggested_name,
                        renamed_target,
                        source=str(existing_source or "customized"),
                        origin=existing.get("origin") or {},
                        protected=bool(
                            existing.get("protected", False),
                        ),
                    )
                    skills.pop(skill_name, None)
                    renamed.append(
                        {"from": skill_name, "to": suggested_name},
                    )
                else:
                    conflicts.append(
                        {
                            "skill_name": skill_name,
                            "suggested_name": suggest_conflict_name(
                                skill_name,
                            ),
                        },
                    )
                    continue

            # Gate 2: the pool slot is source="builtin" (or new), but
            # the on-disk copy has been locally modified. We report a
            # "local_modified" conflict when we can't safely overwrite
            # without user approval—this prevents silent data loss when
            # a user edits a builtin skill on disk and then upgrades.
            would_overwrite = False
            has_modified_target = (
                target.exists() and builtin_signature != target_signature
            )
            has_local_builtin_conflict = (
                has_modified_target
                and bool(existing_signature)
                and existing_signature != target_signature
                and (force or overwrite_existing)
                and not approve_conflicts
            )

            if (
                target.exists()
                and builtin_signature != target_signature
                and (force or overwrite_existing)
            ):
                would_overwrite = True

            if has_local_builtin_conflict:
                conflicts.append(
                    {
                        "skill_name": skill_name,
                        "reason": "local_modified",
                        "suggested_name": suggest_conflict_name(
                            skill_name,
                        ),
                    },
                )
                continue

            if preview_only:
                if not target.exists():
                    additions.append(skill_name)
                elif would_overwrite:
                    updates.append(skill_name)
                continue

            if force or not target.exists():
                _copy_skill_dir(skill_dir, target)
                synced.append(skill_name)
                if not target_signature:
                    additions.append(skill_name)
                else:
                    updates.append(skill_name)
            elif overwrite_existing:
                if builtin_signature != target_signature:
                    _copy_skill_dir(skill_dir, target)
                    synced.append(skill_name)
                    updates.append(skill_name)

            skills[skill_name] = _build_skill_metadata(
                skill_name,
                target,
                source="builtin",
                origin={"type": "builtin"},
                protected=True,
            )

        return {
            "synced": synced,
            "updates": updates,
            "additions": additions,
            "conflicts": conflicts,
            "renamed": renamed,
        }

    if preview_only:
        payload = _read_json(manifest_path, manifest_default)
        return _process(payload)

    return _mutate_json(
        manifest_path,
        manifest_default,
        _process,
    )


def ensure_skill_pool_initialized() -> bool:
    """Ensure the local skill pool exists and built-ins are synced into it."""
    pool_dir = get_skill_pool_dir()
    created = False
    if not pool_dir.exists():
        pool_dir.mkdir(parents=True, exist_ok=True)
        created = True

    manifest_path = get_pool_skill_manifest_path()
    if not manifest_path.exists():
        _write_json_atomic(manifest_path, _default_pool_manifest())
        created = True

    _sync_builtin_skills_into_pool(force=False, overwrite_existing=False)
    return created


def reconcile_pool_manifest() -> dict[str, Any]:
    """Reconcile shared pool metadata with the filesystem.

    The pool manifest is not treated as the source of truth for content.
    Instead, the pool directory on disk is scanned and metadata is rebuilt
    from the discovered skills. Manifest-only bookkeeping such as ``config``
    and ``origin`` is preserved when possible.

    Example:
        if a user manually drops ``skill_pool/demo/SKILL.md`` onto disk,
        the next reconcile adds ``demo`` to ``skill_pool/skill.json``.
    """
    pool_dir = get_skill_pool_dir()
    pool_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = get_pool_skill_manifest_path()
    if not manifest_path.exists():
        _write_json_atomic(manifest_path, _default_pool_manifest())

    builtin_names = _get_builtin_skill_names()
    builtin_dir = get_builtin_skills_dir()

    def _update(payload: dict[str, Any]) -> dict[str, Any]:
        payload.setdefault("skills", {})
        payload["builtin_skill_names"] = builtin_names
        skills = payload["skills"]

        discovered = {
            path.name: path
            for path in pool_dir.iterdir()
            if path.is_dir() and (path / "SKILL.md").exists()
        }

        for skill_name, skill_dir in sorted(discovered.items()):
            existing = skills.get(skill_name, {})
            is_builtin_name = _is_builtin_skill(skill_name, builtin_names)

            if is_builtin_name:
                src_skill_dir = builtin_dir / skill_name
                if src_skill_dir.exists():
                    pool_signature = _build_signature(skill_dir)
                    src_signature = _build_signature(src_skill_dir)
                    source = (
                        "builtin"
                        if pool_signature == src_signature
                        else "customized"
                    )
                else:
                    source = "customized"
            else:
                source = "customized"

            protected = source == "builtin"
            origin = existing.get("origin") or {}
            if source == "builtin":
                origin = {"type": "builtin"}
            has_config = "config" in existing
            config = existing.get("config") if has_config else None
            skills[skill_name] = _build_skill_metadata(
                skill_name,
                skill_dir,
                source=source,
                origin=origin,
                protected=protected,
            )
            if has_config:
                skills[skill_name]["config"] = config

        missing = [
            skill_name
            for skill_name in list(skills)
            if skill_name not in discovered
        ]
        for skill_name in missing:
            if skill_name in builtin_names:
                src_skill_dir = builtin_dir / skill_name
                if src_skill_dir.exists():
                    _copy_skill_dir(src_skill_dir, pool_dir / skill_name)
                    skills[skill_name] = _build_skill_metadata(
                        skill_name,
                        pool_dir / skill_name,
                        source="builtin",
                        origin={"type": "builtin"},
                        protected=True,
                    )
                    continue
            skills.pop(skill_name, None)

        return payload

    return _mutate_json(
        manifest_path,
        _default_pool_manifest(),
        _update,
    )


def _compute_sync_to_pool(
    skill_name: str,
    workspace_skill_dir: Path,
    pool_manifest: dict[str, Any],
    entry: dict[str, Any],
) -> dict[str, Any]:
    """Compute one workspace skill's relationship to the shared pool.

    Status values:
    - ``not_sync``: no corresponding pool entry exists
    - ``synced``: workspace and pool signatures match exactly
    - ``conflict``: both exist but real contents differ

    Example:
        workspace ``docx`` downloaded from pool and left untouched ->
        ``synced``.
        If the workspace user edits ``SKILL.md`` afterwards ->
        ``conflict``.
    """
    origin = entry.get("origin") or {}
    pool_name = origin.get("pool_name") or skill_name
    pool_entry = pool_manifest.get("skills", {}).get(pool_name)

    if pool_entry is None:
        return {"status": "not_sync", "pool_name": pool_name}

    workspace_signature = _build_signature(workspace_skill_dir)
    pool_signature = pool_entry.get("signature", "")
    if workspace_signature == pool_signature:
        return {"status": "synced", "pool_name": pool_name}
    return {"status": "conflict", "pool_name": pool_name}


def reconcile_workspace_manifest(workspace_dir: Path) -> dict[str, Any]:
    """Reconcile one workspace manifest with the filesystem.

    This is the bridge between editable files under ``<workspace>/skills`` and
    runtime-facing state in ``skill.json``.

    Behavior summary:
    - Discover every on-disk skill directory with ``SKILL.md``.
    - Preserve user state such as ``enabled``, ``channels``, and ``config``.
    - Refresh metadata and sync status from the real files.
    - Remove manifest entries whose directories no longer exist.

    Example:
        if a user deletes ``workspaces/a1/skills/demo_skill`` by hand, the
        next reconcile removes ``demo_skill`` from
        ``workspaces/a1/skill.json``.
    """
    workspace_dir.mkdir(parents=True, exist_ok=True)
    workspace_skills_dir = get_workspace_skills_dir(workspace_dir)
    workspace_skills_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = get_workspace_skill_manifest_path(workspace_dir)
    pool_manifest = _read_json(
        get_pool_skill_manifest_path(),
        _default_pool_manifest(),
    )
    builtin_names = pool_manifest.get("builtin_skill_names", [])

    if not manifest_path.exists():
        _write_json_atomic(manifest_path, _default_workspace_manifest())

    def _update(payload: dict[str, Any]) -> dict[str, Any]:
        payload.setdefault("skills", {})
        skills = payload["skills"]

        discovered = {
            path.name: path
            for path in workspace_skills_dir.iterdir()
            if path.is_dir() and (path / "SKILL.md").exists()
        }

        for skill_name, skill_dir in sorted(discovered.items()):
            existing = skills.get(skill_name) or {}
            enabled = bool(existing.get("enabled", False))
            channels = existing.get("channels") or ["all"]

            # Source logic:
            # - If name NOT in builtin_names -> customized
            # - If name IN builtin_names AND signature matches pool builtin
            #   -> builtin
            # - If name IN builtin_names BUT signature differs -> customized
            workspace_signature = _build_signature(skill_dir)
            is_builtin_name = _is_builtin_skill(skill_name, builtin_names)

            if is_builtin_name:
                pool_entry = pool_manifest.get("skills", {}).get(skill_name)
                pool_signature = (
                    pool_entry.get("signature", "") if pool_entry else ""
                )
                source = (
                    "builtin"
                    if workspace_signature == pool_signature
                    else "customized"
                )
            else:
                source = "customized"

            origin = existing.get("origin") or {}
            metadata = _build_skill_metadata(
                skill_name,
                skill_dir,
                source=source,
                origin=origin,
                protected=False,
            )
            next_entry = {
                "enabled": enabled,
                "channels": channels,
                "source": source,
                "origin": origin,
                "metadata": metadata,
                "requirements": metadata["requirements"],
                "sync_to_pool": _compute_sync_to_pool(
                    skill_name,
                    skill_dir,
                    pool_manifest,
                    {"origin": origin},
                ),
                "updated_at": _timestamp(),
            }
            if "config" in existing:
                next_entry["config"] = existing.get("config")
            skills[skill_name] = next_entry
            skills[skill_name].pop("sync_to_hub", None)

        for skill_name in list(skills):
            if skill_name not in discovered:
                skills.pop(skill_name, None)

        return payload

    return _mutate_json(
        manifest_path,
        _default_workspace_manifest(),
        _update,
    )


def list_workspaces() -> list[dict[str, str]]:
    """List configured workspaces."""
    workspaces: list[dict[str, str]] = []
    try:
        from ..config.utils import load_config

        config = load_config()
        for agent_id, profile in sorted(config.agents.profiles.items()):
            workspaces.append(
                {
                    "agent_id": agent_id,
                    "workspace_dir": str(
                        Path(profile.workspace_dir).expanduser(),
                    ),
                },
            )
    except Exception as exc:
        logger.warning("Failed to load configured workspaces: %s", exc)

    seen = {item["workspace_dir"] for item in workspaces}
    from ..constant import WORKING_DIR

    root = Path(WORKING_DIR) / "workspaces"
    if root.exists():
        for workspace_dir in sorted(root.iterdir()):
            if not workspace_dir.is_dir():
                continue
            text = str(workspace_dir)
            if text in seen:
                continue
            workspaces.append(
                {"agent_id": workspace_dir.name, "workspace_dir": text},
            )

    return workspaces


def read_skill_manifest(workspace_dir: Path) -> dict[str, Any]:
    """Public helper returning a reconciled workspace manifest."""
    return reconcile_workspace_manifest(workspace_dir)


def read_skill_pool_manifest() -> dict[str, Any]:
    """Public helper returning a reconciled pool manifest."""
    return reconcile_pool_manifest()


def resolve_effective_skills(
    workspace_dir: Path,
    channel_name: str,
    *,
    _registry: dict | None = None,
) -> list[str]:
    """Resolve enabled workspace skills for one channel."""
    manifest = reconcile_workspace_manifest(workspace_dir)
    resolved = []
    for skill_name, entry in sorted(manifest.get("skills", {}).items()):
        if not entry.get("enabled", False):
            continue
        channels = entry.get("channels") or ["all"]
        if "all" in channels or channel_name in channels:
            skill_dir = get_workspace_skills_dir(workspace_dir) / skill_name
            if skill_dir.exists():
                resolved.append(skill_name)
    return resolved


def ensure_skills_initialized(workspace_dir: Path) -> None:
    """Ensure workspace manifests exist before runtime use."""
    reconcile_workspace_manifest(workspace_dir)


def fetch_latest_builtin_skills(
    approve_conflicts: bool = False,
    preview_only: bool = False,
) -> dict[str, list[Any]]:
    """Force a built-in sync for the skill pool page."""
    result = _sync_builtin_skills_into_pool(
        force=True,
        approve_conflicts=approve_conflicts,
        preview_only=preview_only,
    )
    if not preview_only:
        reconcile_pool_manifest()
    return result


def _read_skill_from_dir(skill_dir: Path, source: str) -> SkillInfo | None:
    if not skill_dir.is_dir():
        return None

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return None

    try:
        content = skill_md.read_text(encoding="utf-8")
        description = ""
        try:
            post = frontmatter.loads(content)
            description = str(post.get("description", "") or "")
        except Exception:
            pass

        references = {}
        scripts = {}
        references_dir = skill_dir / "references"
        scripts_dir = skill_dir / "scripts"
        if references_dir.exists():
            references = _directory_tree(references_dir)
        if scripts_dir.exists():
            scripts = _directory_tree(scripts_dir)

        return SkillInfo(
            name=skill_dir.name,
            description=description,
            content=content,
            source=source,
            path=str(skill_dir),
            references=references,
            scripts=scripts,
        )
    except Exception as exc:
        logger.error("Failed to read skill %s: %s", skill_dir, exc)
        return None


def _validate_skill_content(content: str) -> tuple[str, str]:
    post = frontmatter.loads(content)
    skill_name = str(post.get("name") or "").strip()
    skill_description = str(post.get("description") or "").strip()
    if not skill_name or not skill_description:
        raise ValueError(
            "SKILL.md must include non-empty frontmatter name and description",
        )
    return skill_name, skill_description


def _import_skill_dir(
    src_dir: Path,
    target_root: Path,
    skill_name: str,
    overwrite: bool,
) -> bool:
    try:
        post = _read_frontmatter(src_dir)
        if not post.get("name") or not post.get("description"):
            return False
    except Exception:
        return False

    target_dir = target_root / skill_name
    if target_dir.exists() and not overwrite:
        return False
    _copy_skill_dir(src_dir, target_dir)
    return True


def _write_skill_to_dir(
    skill_dir: Path,
    content: str,
    references: dict[str, Any] | None = None,
    scripts: dict[str, Any] | None = None,
    extra_files: dict[str, Any] | None = None,
) -> None:
    """Write a skill's files into a directory (shared by create flows)."""
    if skill_dir.exists():
        shutil.rmtree(skill_dir)
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    _create_files_from_tree(skill_dir, extra_files or {})
    if references:
        ref_dir = skill_dir / "references"
        ref_dir.mkdir(parents=True, exist_ok=True)
        _create_files_from_tree(ref_dir, references)
    if scripts:
        script_dir = skill_dir / "scripts"
        script_dir.mkdir(parents=True, exist_ok=True)
        _create_files_from_tree(script_dir, scripts)


def _extract_zip_skills(data: bytes) -> tuple[Path, list[tuple[Path, str]]]:
    """Extract and validate a skill zip.

    Returns ``(tmp_dir, found_skills)``.
    """
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise ValueError("Uploaded file is not a valid zip archive")
    tmp_dir = Path(tempfile.mkdtemp(prefix="copaw_skill_upload_"))
    _extract_and_validate_zip(data, tmp_dir)
    real_entries = [
        path for path in tmp_dir.iterdir() if not _is_hidden(path.name)
    ]
    extract_root = (
        real_entries[0]
        if len(real_entries) == 1 and real_entries[0].is_dir()
        else tmp_dir
    )
    # Zip imports use extracted directory names as internal identifiers.
    # Frontmatter name remains available to the LLM through SKILL.md.
    if (extract_root / "SKILL.md").exists():
        found = [(extract_root, extract_root.name)]
    else:
        found = [
            (path, path.name)
            for path in sorted(extract_root.iterdir())
            if not _is_hidden(path.name)
            and path.is_dir()
            and (path / "SKILL.md").exists()
        ]
    if not found:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise ValueError("No valid skills found in uploaded zip")
    return tmp_dir, found


def _scan_skill_dir_or_raise(skill_dir: Path, skill_name: str) -> None:
    scan_skill_directory(skill_dir, skill_name=skill_name)


@contextmanager
def _staged_skill_dir(skill_name: str) -> Iterator[Path]:
    """Create a temporary skill directory used for staged writes."""
    temp_root = Path(
        tempfile.mkdtemp(prefix=f"copaw_skill_stage_{skill_name}_"),
    )
    stage_dir = temp_root / skill_name
    try:
        yield stage_dir
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


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

    def _manifest(self) -> dict[str, Any]:
        return reconcile_workspace_manifest(self.workspace_dir)

    def list_all_skills(self) -> list[SkillInfo]:
        manifest = self._manifest()
        skill_root = get_workspace_skills_dir(self.workspace_dir)
        skills: list[SkillInfo] = []
        for skill_name, entry in sorted(manifest.get("skills", {}).items()):
            skill_dir = skill_root / skill_name
            source = entry.get("source", "workspace")
            skill = _read_skill_from_dir(skill_dir, source)
            if skill is not None:
                skills.append(skill)
        return skills

    def list_available_skills(self) -> list[SkillInfo]:
        manifest = self._manifest()
        skill_root = get_workspace_skills_dir(self.workspace_dir)
        skills: list[SkillInfo] = []
        for skill_name in resolve_effective_skills(
            self.workspace_dir,
            "console",
        ):
            entry = manifest.get("skills", {}).get(skill_name, {})
            skill = _read_skill_from_dir(
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
        overwrite: bool = True,
        references: dict[str, Any] | None = None,
        scripts: dict[str, Any] | None = None,
        extra_files: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
    ) -> str | None:
        _validate_skill_content(content)
        skill_name = str(name or "")
        skill_root = get_workspace_skills_dir(self.workspace_dir)
        skill_root.mkdir(parents=True, exist_ok=True)
        skill_dir = skill_root / skill_name
        if skill_dir.exists() and not overwrite:
            return None

        with _staged_skill_dir(skill_name) as staged_dir:
            _write_skill_to_dir(
                staged_dir,
                content,
                references,
                scripts,
                extra_files,
            )
            _scan_skill_dir_or_raise(staged_dir, skill_name)
            _copy_skill_dir(staged_dir, skill_dir)

        def _update(payload: dict[str, Any]) -> None:
            payload.setdefault("skills", {})
            entry = payload["skills"].get(skill_name) or {}
            metadata = _build_skill_metadata(
                skill_name,
                skill_dir,
                source=(
                    "builtin"
                    if entry.get("source", "customized") == "builtin"
                    else "customized"
                ),
                origin=entry.get("origin") or {},
                protected=False,
            )
            payload["skills"][skill_name] = {
                "enabled": bool(entry.get("enabled", False)),
                "channels": entry.get("channels") or ["all"],
                "source": metadata["source"],
                "origin": entry.get("origin") or {},
                "config": dict(config or entry.get("config") or {}),
                "metadata": metadata,
                "requirements": metadata["requirements"],
                "sync_to_pool": entry.get("sync_to_pool") or {},
                "updated_at": _timestamp(),
            }

        _mutate_json(
            get_workspace_skill_manifest_path(self.workspace_dir),
            _default_workspace_manifest(),
            _update,
        )
        reconcile_workspace_manifest(self.workspace_dir)
        return skill_name

    def import_from_zip(
        self,
        data: bytes,
        overwrite: bool = True,
        enable: bool = False,
    ) -> dict[str, Any]:
        skill_root = get_workspace_skills_dir(self.workspace_dir)
        skill_root.mkdir(parents=True, exist_ok=True)
        tmp_dir, found = _extract_zip_skills(data)
        try:
            for skill_dir, skill_name in found:
                _scan_skill_dir_or_raise(skill_dir, skill_name)
            imported: list[str] = []
            for skill_dir, skill_name in found:
                if _import_skill_dir(
                    skill_dir,
                    skill_root,
                    skill_name,
                    overwrite,
                ):
                    imported.append(skill_name)

            manifest = reconcile_workspace_manifest(self.workspace_dir)
            if enable:
                for skill_name in imported:
                    entry = manifest.get("skills", {}).get(skill_name)
                    if entry is not None:
                        self.enable_skill(skill_name)

            return {
                "imported": imported,
                "count": len(imported),
                "enabled": enable and bool(imported),
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
        skill_name = str(name or "")
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
        skill_dir = get_workspace_skills_dir(self.workspace_dir) / skill_name
        if not skill_dir.exists():
            return {
                "success": False,
                "updated_workspaces": [],
                "failed": [self.workspace_dir.name],
                "reason": "not_found",
            }
        _scan_skill_dir_or_raise(skill_dir, skill_name)

        def _update(payload: dict[str, Any]) -> bool:
            entry = payload.get("skills", {}).get(skill_name)
            if entry is None:
                return False
            entry["enabled"] = True
            entry.setdefault("channels", ["all"])
            entry["updated_at"] = _timestamp()
            return True

        updated = _mutate_json(
            manifest_path,
            _default_workspace_manifest(),
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
        skill_name = str(name or "")
        manifest_path = get_workspace_skill_manifest_path(self.workspace_dir)

        def _update(payload: dict[str, Any]) -> bool:
            entry = payload.get("skills", {}).get(skill_name)
            if entry is None:
                return False
            entry["enabled"] = False
            entry["updated_at"] = _timestamp()
            return True

        updated = _mutate_json(
            manifest_path,
            _default_workspace_manifest(),
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
        skill_name = str(name or "")
        manifest_path = get_workspace_skill_manifest_path(self.workspace_dir)
        normalized = channels or ["all"]

        def _update(payload: dict[str, Any]) -> bool:
            entry = payload.get("skills", {}).get(skill_name)
            if entry is None:
                return False
            entry["channels"] = normalized
            entry["updated_at"] = _timestamp()
            return True

        updated = _mutate_json(
            manifest_path,
            _default_workspace_manifest(),
            _update,
        )
        return updated

    def delete_skill(self, name: str) -> bool:
        skill_name = str(name or "")
        manifest = self._manifest()
        entry = manifest.get("skills", {}).get(skill_name)
        if entry is None or entry.get("enabled", False):
            return False

        skill_dir = get_workspace_skills_dir(self.workspace_dir) / skill_name
        if skill_dir.exists():
            shutil.rmtree(skill_dir)

        def _update(payload: dict[str, Any]) -> None:
            payload.get("skills", {}).pop(skill_name, None)

        _mutate_json(
            get_workspace_skill_manifest_path(self.workspace_dir),
            _default_workspace_manifest(),
            _update,
        )
        return True

    def load_skill_file(
        self,
        skill_name: str,
        file_path: str,
        source: str,
    ) -> str | None:
        del source
        normalized = file_path.replace("\\", "/")
        if ".." in normalized or normalized.startswith("/"):
            return None
        if not (
            normalized.startswith("references/")
            or normalized.startswith("scripts/")
        ):
            return None

        manifest = self._manifest()
        if skill_name not in manifest.get("skills", {}):
            return None

        workspace_base_dir = (
            get_workspace_skills_dir(self.workspace_dir) / skill_name
        )
        if not workspace_base_dir.exists():
            return None

        base_dir = workspace_base_dir

        full_path = base_dir / normalized
        if not full_path.exists() or not full_path.is_file():
            return None
        return full_path.read_text(encoding="utf-8")


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
        manifest = reconcile_pool_manifest()
        pool_dir = get_skill_pool_dir()
        skills: list[SkillInfo] = []
        for skill_name, entry in sorted(manifest.get("skills", {}).items()):
            skill = _read_skill_from_dir(
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
        overwrite: bool = True,
        references: dict[str, Any] | None = None,
        scripts: dict[str, Any] | None = None,
        extra_files: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
    ) -> str | None:
        _validate_skill_content(content)
        skill_name = str(name or "")
        pool_dir = get_skill_pool_dir()
        skill_dir = pool_dir / skill_name
        manifest = reconcile_pool_manifest()
        existing = manifest.get("skills", {}).get(skill_name)
        if existing and existing.get("protected"):
            return None
        if skill_dir.exists() and not overwrite:
            return None

        with _staged_skill_dir(skill_name) as staged_dir:
            _write_skill_to_dir(
                staged_dir,
                content,
                references,
                scripts,
                extra_files,
            )
            _scan_skill_dir_or_raise(staged_dir, skill_name)
            _copy_skill_dir(staged_dir, skill_dir)

        def _update(payload: dict[str, Any]) -> None:
            payload.setdefault("skills", {})
            payload["skills"][skill_name] = _build_skill_metadata(
                skill_name,
                skill_dir,
                source="customized",
                origin={"type": "pool_create"},
                protected=False,
            )
            if config:
                payload["skills"][skill_name]["config"] = dict(config)

        _mutate_json(
            get_pool_skill_manifest_path(),
            _default_pool_manifest(),
            _update,
        )
        return skill_name

    def import_from_zip(
        self,
        data: bytes,
        overwrite: bool = True,
    ) -> dict[str, Any]:
        pool_dir = get_skill_pool_dir()
        tmp_dir, found = _extract_zip_skills(data)
        try:
            manifest = reconcile_pool_manifest()
            for skill_dir, skill_name in found:
                _scan_skill_dir_or_raise(skill_dir, skill_name)
            imported: list[str] = []
            for skill_dir, skill_name in found:
                existing = manifest.get("skills", {}).get(skill_name)
                if existing and existing.get("protected"):
                    continue
                if _import_skill_dir(
                    skill_dir,
                    pool_dir,
                    skill_name,
                    overwrite,
                ):
                    imported.append(skill_name)

            def _update(payload: dict[str, Any]) -> None:
                payload.setdefault("skills", {})
                for skill_name in imported:
                    payload["skills"][skill_name] = _build_skill_metadata(
                        skill_name,
                        pool_dir / skill_name,
                        source="customized",
                        origin={"type": "pool_import"},
                        protected=False,
                    )

            _mutate_json(
                get_pool_skill_manifest_path(),
                _default_pool_manifest(),
                _update,
            )
            return {"imported": imported, "count": len(imported)}
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def delete_skill(self, name: str) -> bool:
        skill_name = str(name or "")
        manifest = reconcile_pool_manifest()
        entry = manifest.get("skills", {}).get(skill_name)
        if entry is None or entry.get("protected"):
            return False

        skill_dir = get_skill_pool_dir() / skill_name
        if skill_dir.exists():
            shutil.rmtree(skill_dir)

        def _update(payload: dict[str, Any]) -> None:
            payload.get("skills", {}).pop(skill_name, None)

        _mutate_json(
            get_pool_skill_manifest_path(),
            _default_pool_manifest(),
            _update,
        )
        return True

    def get_edit_target_name(
        self,
        skill_name: str,
        *,
        target_name: str | None = None,
    ) -> dict[str, Any]:
        manifest = reconcile_pool_manifest()
        entry = manifest.get("skills", {}).get(skill_name)
        if entry is None:
            return {"success": False, "reason": "not_found"}

        if not entry.get("protected"):
            normalized_target = str(target_name or skill_name)
            if normalized_target == skill_name:
                return {
                    "success": True,
                    "mode": "edit",
                    "name": skill_name,
                }
            existing = manifest.get("skills", {}).get(normalized_target)
            if existing is not None:
                return {
                    "success": False,
                    "reason": "conflict",
                    "mode": "rename",
                    "suggested_name": suggest_conflict_name(
                        normalized_target,
                    ),
                }
            return {
                "success": True,
                "mode": "rename",
                "name": normalized_target,
            }

        suggested_name = str(
            target_name or suggest_conflict_name(skill_name),
        )
        existing = manifest.get("skills", {}).get(suggested_name)
        if existing is not None:
            return {
                "success": False,
                "reason": "conflict",
                "mode": "fork",
                "suggested_name": suggest_conflict_name(
                    suggested_name,
                ),
            }
        return {
            "success": True,
            "mode": "fork",
            "name": suggested_name,
        }

    def save_pool_skill(
        self,
        *,
        skill_name: str,
        content: str,
        references: dict[str, Any] | None = None,
        scripts: dict[str, Any] | None = None,
        extra_files: dict[str, Any] | None = None,
        target_name: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        _validate_skill_content(content)
        manifest = reconcile_pool_manifest()
        entry = manifest.get("skills", {}).get(skill_name)
        if entry is None:
            return {"success": False, "reason": "not_found"}

        edit_target = self.get_edit_target_name(
            skill_name,
            target_name=target_name,
        )
        if not edit_target.get("success"):
            return edit_target

        final_name = str(edit_target["name"])
        skill_dir = get_skill_pool_dir() / final_name
        old_skill_dir = get_skill_pool_dir() / skill_name
        with _staged_skill_dir(final_name) as staged_dir:
            _write_skill_to_dir(
                staged_dir,
                content,
                references,
                scripts,
                extra_files,
            )
            _scan_skill_dir_or_raise(staged_dir, final_name)
            _copy_skill_dir(staged_dir, skill_dir)

        if (
            str(edit_target["mode"]) == "rename"
            and final_name != skill_name
            and old_skill_dir.exists()
        ):
            shutil.rmtree(old_skill_dir)

        def _update(payload: dict[str, Any]) -> None:
            payload.setdefault("skills", {})
            next_entry = _build_skill_metadata(
                final_name,
                skill_dir,
                source="customized",
                origin={
                    "type": "pool_edit"
                    if not entry.get("protected")
                    else "pool_builtin_fork",
                    "source_skill_name": skill_name,
                },
                protected=False,
            )
            existing_config = (
                config
                if config is not None
                else entry.get("config")
                if final_name == skill_name
                else payload["skills"].get(final_name, {}).get("config")
            ) or {}
            if existing_config:
                next_entry["config"] = existing_config
            payload["skills"][final_name] = next_entry
            if (
                str(edit_target["mode"]) == "rename"
                and final_name != skill_name
            ):
                payload["skills"].pop(skill_name, None)

        _mutate_json(
            get_pool_skill_manifest_path(),
            _default_pool_manifest(),
            _update,
        )
        return {
            "success": True,
            "mode": str(edit_target["mode"]),
            "name": final_name,
        }

    def upload_from_workspace(
        self,
        workspace_dir: Path,
        skill_name: str,
        *,
        target_name: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        source_dir = get_workspace_skills_dir(workspace_dir) / skill_name
        if not source_dir.exists():
            return {"success": False, "reason": "not_found"}

        final_name = str(target_name or skill_name)
        target_dir = get_skill_pool_dir() / final_name
        manifest = reconcile_pool_manifest()
        existing = manifest.get("skills", {}).get(final_name)
        if existing:
            if existing.get("protected"):
                return {
                    "success": False,
                    "reason": "conflict",
                    "suggested_name": suggest_conflict_name(
                        final_name,
                    ),
                }
            if not overwrite:
                return {
                    "success": False,
                    "reason": "conflict",
                    "suggested_name": suggest_conflict_name(
                        final_name,
                    ),
                }

        with _staged_skill_dir(final_name) as staged_dir:
            _copy_skill_dir(source_dir, staged_dir)
            _scan_skill_dir_or_raise(staged_dir, final_name)
            _copy_skill_dir(staged_dir, target_dir)

        ws_manifest = _read_json(
            get_workspace_skill_manifest_path(workspace_dir),
            _default_workspace_manifest(),
        )
        ws_config = (
            ws_manifest.get("skills", {}).get(skill_name, {}).get("config")
        ) or {}

        def _update(payload: dict[str, Any]) -> None:
            payload.setdefault("skills", {})
            entry = _build_skill_metadata(
                final_name,
                target_dir,
                source="customized",
                origin={
                    "type": "workspace_upload",
                    "workspace_id": workspace_dir.name,
                    "workspace_skill_name": skill_name,
                },
                protected=False,
            )
            if ws_config:
                entry["config"] = ws_config
            payload["skills"][final_name] = entry

        _mutate_json(
            get_pool_skill_manifest_path(),
            _default_pool_manifest(),
            _update,
        )

        def _mark_synced(payload: dict[str, Any]) -> None:
            entry = payload.get("skills", {}).get(skill_name)
            if entry is None:
                return
            entry["origin"] = {
                **(entry.get("origin") or {}),
                "pool_name": final_name,
            }
            entry["sync_to_pool"] = {
                "status": "synced",
                "pool_name": final_name,
            }
            entry.pop("sync_to_hub", None)
            entry["updated_at"] = _timestamp()

        _mutate_json(
            get_workspace_skill_manifest_path(workspace_dir),
            _default_workspace_manifest(),
            _mark_synced,
        )

        return {"success": True, "name": final_name}

    def download_to_workspace(
        self,
        skill_name: str,
        workspace_dir: Path,
        *,
        target_name: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        manifest = reconcile_pool_manifest()
        entry = manifest.get("skills", {}).get(skill_name)
        if entry is None:
            return {"success": False, "reason": "not_found"}

        source_dir = get_skill_pool_dir() / skill_name
        final_name = str(target_name or skill_name)
        target_dir = get_workspace_skills_dir(workspace_dir) / final_name
        workspace_manifest = reconcile_workspace_manifest(workspace_dir)
        existing = workspace_manifest.get("skills", {}).get(final_name)
        if existing and not overwrite:
            return {
                "success": False,
                "reason": "conflict",
                "workspace_id": workspace_dir.name,
                "suggested_name": suggest_conflict_name(
                    final_name,
                ),
            }

        target_dir.parent.mkdir(parents=True, exist_ok=True)
        with _staged_skill_dir(final_name) as staged_dir:
            _copy_skill_dir(source_dir, staged_dir)
            _scan_skill_dir_or_raise(staged_dir, final_name)
            _copy_skill_dir(staged_dir, target_dir)

        pool_config = entry.get("config") or {}

        def _update(payload: dict[str, Any]) -> None:
            payload.setdefault("skills", {})
            metadata = _build_skill_metadata(
                final_name,
                target_dir,
                source="builtin"
                if entry.get("source") == "builtin"
                else "customized",
                origin={
                    "type": "pool_download",
                    "pool_name": skill_name,
                    "pool_source": entry.get("source"),
                },
                protected=False,
            )
            payload["skills"][final_name] = {
                "enabled": False,
                "channels": ["all"],
                "source": metadata["source"],
                "origin": metadata["origin"],
                "config": pool_config,
                "metadata": metadata,
                "requirements": metadata["requirements"],
                "sync_to_pool": {
                    "status": "synced",
                    "pool_name": skill_name,
                },
                "updated_at": _timestamp(),
            }

        _mutate_json(
            get_workspace_skill_manifest_path(workspace_dir),
            _default_workspace_manifest(),
            _update,
        )
        return {"success": True, "name": final_name}

    def preflight_download_to_workspace(
        self,
        skill_name: str,
        workspace_dir: Path,
        *,
        target_name: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        manifest = reconcile_pool_manifest()
        entry = manifest.get("skills", {}).get(skill_name)
        if entry is None:
            return {"success": False, "reason": "not_found"}

        final_name = str(target_name or skill_name)
        workspace_manifest = reconcile_workspace_manifest(workspace_dir)
        existing = workspace_manifest.get("skills", {}).get(final_name)
        if existing and not overwrite:
            return {
                "success": False,
                "reason": "conflict",
                "workspace_id": workspace_dir.name,
                "suggested_name": suggest_conflict_name(
                    final_name,
                ),
            }
        return {
            "success": True,
            "workspace_id": workspace_dir.name,
            "name": final_name,
        }
