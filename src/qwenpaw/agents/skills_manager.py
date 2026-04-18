# -*- coding: utf-8 -*-
"""Skills management: sync skills from code to working_dir."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import shutil
import tempfile
import threading
import time
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar

import frontmatter
from pydantic import BaseModel, Field

from ..exceptions import SkillsError
from ..security.skill_scanner import scan_skill_directory
from .utils.file_handling import read_text_file_with_encoding_fallback

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
_MAX_ZIP_BYTES = 200 * 1024 * 1024
_REQUIREMENTS_METADATA_NAMESPACES = ("openclaw", "qwenpaw", "clawdbot")
_BUILTIN_SKILL_LANGUAGES = ("en", "zh")
_BUILTIN_SKILL_DIR_RE = re.compile(
    r"^(?P<name>.+)-(?P<language>en|zh)$",
)
_CJK_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")


@dataclass(frozen=True)
class BuiltinSkillVariant:
    name: str
    language: str
    source_name: str
    skill_dir: Path
    skill_md_path: Path
    description: str
    version_text: str
    content_hash: str


@dataclass(frozen=True)
class BuiltinSkillIdentity:
    name: str
    language: str
    source_name: str


class SkillInfo(BaseModel):
    """Workspace or hub skill details returned to callers.

    ``name`` is the stable runtime identifier: the directory / manifest key
    used by APIs, sync state, and channel routing. It is intentionally not
    derived from frontmatter because frontmatter can drift while the on-disk
    workspace identity must remain stable.
    """

    name: str
    description: str = ""
    version_text: str = ""
    content: str
    source: str
    references: dict[str, Any] = Field(default_factory=dict)
    scripts: dict[str, Any] = Field(default_factory=dict)
    emoji: str = ""


class SkillRequirements(BaseModel):
    """System-managed requirements declared by a skill."""

    require_bins: list[str] = Field(default_factory=list)
    require_envs: list[str] = Field(default_factory=list)


_ACTIVE_SKILL_ENV_ENTRIES: dict[str, dict[str, Any]] = {}
_ENV_LOCK = threading.Lock()

# ── Cached singletons (builtin dirs are immutable at runtime) ────────────
_builtin_cache: dict[str, Any] = {}
_BUILTIN_CACHE_LOCK = threading.Lock()


def _builtin_settings_path() -> Path:
    from ..constant import WORKING_DIR

    return Path(WORKING_DIR) / "settings.json"


def _normalize_builtin_skill_language(
    language: str | None,
    *,
    fallback: str = "en",
) -> str:
    normalized = str(language or "").strip().lower()
    if normalized in _BUILTIN_SKILL_LANGUAGES:
        return normalized
    if fallback == "":
        return ""
    return fallback if fallback in _BUILTIN_SKILL_LANGUAGES else "en"


def get_builtin_skill_language_preference() -> str:
    """Return the builtin skill language preference."""
    cached = _builtin_cache.get("language_preference")
    if cached is not None:
        return cached
    with _BUILTIN_CACHE_LOCK:
        cached = _builtin_cache.get("language_preference")
        if cached is not None:
            return cached
        settings_path = _builtin_settings_path()
        try:
            payload = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        explicit = _normalize_builtin_skill_language(
            payload.get("builtin_skill_language"),
            fallback="",
        )
        if explicit:
            result = explicit
        else:
            ui_lang = str(payload.get("language", "") or "").strip().lower()
            result = "zh" if ui_lang.startswith("zh") else "en"
        _builtin_cache["language_preference"] = result
        return result


def set_builtin_skill_language_preference(language: str) -> None:
    """Update the in-memory cached builtin language preference."""
    with _BUILTIN_CACHE_LOCK:
        _builtin_cache[
            "language_preference"
        ] = _normalize_builtin_skill_language(
            language,
        )


def _compute_text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _skill_content_hash_for_path(skill_md_path: Path) -> str:
    try:
        return _compute_text_hash(
            read_text_file_with_encoding_fallback(skill_md_path),
        )
    except OSError:
        return ""


def _read_frontmatter_from_path(skill_md_path: Path) -> Any:
    return frontmatter.loads(
        read_text_file_with_encoding_fallback(skill_md_path),
    )


def _read_frontmatter_safe_from_path(
    skill_md_path: Path,
    skill_name: str = "",
) -> dict[str, Any]:
    if not skill_name:
        skill_name = skill_md_path.parent.name

    try:
        return _read_frontmatter_from_path(skill_md_path)
    except Exception as e:
        logger.warning(
            "Failed to read SKILL frontmatter for '%s' at %s: %s. "
            "Using fallback values.",
            skill_name,
            skill_md_path,
            e,
        )
        return {"name": skill_name, "description": ""}


def _guess_builtin_skill_language(skill_md_path: Path) -> str:
    try:
        content = read_text_file_with_encoding_fallback(skill_md_path)
    except OSError:
        return "en"
    cjk_count = len(_CJK_CHAR_RE.findall(content))
    return "zh" if cjk_count >= 32 else "en"


def _parse_builtin_skill_identity(
    raw_name: str,
    *,
    fallback_language: str | None = None,
) -> BuiltinSkillIdentity | None:
    normalized = str(raw_name or "").strip()
    if not normalized:
        return None

    match = _BUILTIN_SKILL_DIR_RE.fullmatch(normalized)
    if match is not None:
        return BuiltinSkillIdentity(
            name=str(match.group("name") or "").strip(),
            language=str(match.group("language") or "").strip(),
            source_name=normalized,
        )

    if fallback_language is None:
        return None

    return BuiltinSkillIdentity(
        name=normalized,
        language=_normalize_builtin_skill_language(fallback_language),
        source_name=normalized,
    )


def _canonical_builtin_skill_name(
    raw_name: str,
    registry: dict[str, dict[str, BuiltinSkillVariant]] | None = None,
) -> str:
    normalized = str(raw_name or "").strip()
    identity = _parse_builtin_skill_identity(normalized)
    if identity is None:
        return normalized
    if registry is not None and identity.name not in registry:
        return normalized
    return identity.name


def _resolve_builtin_request_identity(
    item: dict[str, Any],
    registry: dict[str, dict[str, BuiltinSkillVariant]],
    *,
    preferred_language: str | None = None,
) -> tuple[str, str]:
    raw_name = str(
        item.get("skill_name", "") or item.get("source_name", "") or "",
    ).strip()
    alias_identity = _parse_builtin_skill_identity(raw_name)
    canonical_name = _canonical_builtin_skill_name(raw_name, registry)
    requested_language = str(item.get("language", "") or "").strip().lower()
    fallback_language = (
        alias_identity.language
        if alias_identity is not None
        else (preferred_language or get_builtin_skill_language_preference())
    )
    language = _normalize_builtin_skill_language(
        requested_language,
        fallback=fallback_language,
    )
    return canonical_name, language


def _iter_packaged_builtin_variants() -> Iterator[BuiltinSkillVariant]:
    builtin_dirs = list(_iter_packaged_builtin_dirs())
    explicit_variant_bases = {
        identity.name
        for skill_dir in builtin_dirs
        for identity in [_parse_builtin_skill_identity(skill_dir.name)]
        if identity is not None
    }

    for skill_dir in builtin_dirs:
        skill_md_path = skill_dir / "SKILL.md"
        if not skill_md_path.exists():
            continue

        identity = _parse_builtin_skill_identity(skill_dir.name)
        if identity is None:
            if skill_dir.name in explicit_variant_bases:
                continue
            identity = _parse_builtin_skill_identity(
                skill_dir.name,
                fallback_language=_guess_builtin_skill_language(skill_md_path),
            )
        if identity is None:
            continue

        post = _read_frontmatter_safe_from_path(
            skill_md_path,
            identity.name,
        )
        yield BuiltinSkillVariant(
            name=identity.name,
            language=identity.language,
            source_name=identity.source_name,
            skill_dir=skill_dir,
            skill_md_path=skill_md_path,
            description=str(post.get("description", "") or ""),
            version_text=_extract_version(post),
            content_hash=_skill_content_hash_for_path(skill_md_path),
        )


def _get_packaged_builtin_registry() -> (
    dict[str, dict[str, BuiltinSkillVariant]]
):
    """Return the packaged builtin registry."""
    cached = _builtin_cache.get("registry")
    if cached is not None:
        return cached
    with _BUILTIN_CACHE_LOCK:
        cached = _builtin_cache.get("registry")
        if cached is not None:
            return cached
        registry: dict[str, dict[str, BuiltinSkillVariant]] = {}
        for variant in _iter_packaged_builtin_variants():
            registry.setdefault(variant.name, {})[variant.language] = variant
        _builtin_cache["registry"] = registry
        return registry


def _select_builtin_variant(
    registry: dict[str, dict[str, BuiltinSkillVariant]],
    skill_name: str,
    language: str | None = None,
    *,
    preferred_language: str | None = None,
) -> BuiltinSkillVariant | None:
    canonical_name = _canonical_builtin_skill_name(skill_name, registry)
    variants = registry.get(canonical_name) or {}
    if not variants:
        return None
    fallback = preferred_language or get_builtin_skill_language_preference()
    resolved = _normalize_builtin_skill_language(language, fallback=fallback)
    return variants.get(resolved) or next(
        iter(sorted(variants.values(), key=lambda item: item.language)),
    )


def _iter_packaged_builtin_dirs() -> Iterator[Path]:
    """Yield packaged builtin skill directories in stable order."""
    builtin_dir = get_builtin_skills_dir()
    if not builtin_dir.exists():
        return
    for skill_dir in sorted(builtin_dir.iterdir()):
        if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
            yield skill_dir


def _get_packaged_builtin_versions() -> dict[str, str]:
    """Return packaged builtin names mapped to their version text."""
    registry = _get_packaged_builtin_registry()
    versions: dict[str, str] = {}
    for skill_name in sorted(registry):
        variant = _select_builtin_variant(registry, skill_name)
        versions[skill_name] = variant.version_text if variant else ""
    return versions


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


def get_workspace_identity(workspace_dir: Path) -> dict[str, str]:
    """Resolve the workspace id together with its display name."""
    workspace_id = workspace_dir.name
    workspace_name = workspace_id
    try:
        from ..config.config import load_agent_config

        workspace_name = load_agent_config(workspace_id).name or workspace_id
    except Exception:
        pass
    return {
        "workspace_id": workspace_id,
        "workspace_name": workspace_name,
    }


def get_pool_skill_manifest_path() -> Path:
    """Return the shared pool skill manifest path."""
    return get_skill_pool_dir() / "skill.json"


def _get_skill_mtime(skill_dir: Path) -> str:
    """Return the latest mtime across the skill directory as ISO string.

    Scans SKILL.md and the directory itself.  Returns an empty string
    on any filesystem error.
    """
    try:
        dir_mtime = skill_dir.stat().st_mtime
        skill_md = skill_dir / "SKILL.md"
        md_mtime = skill_md.stat().st_mtime if skill_md.exists() else 0.0
        mtime = max(dir_mtime, md_mtime)
        return (
            datetime.fromtimestamp(mtime, tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
    except OSError:
        return ""


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
    """Read and parse SKILL.md frontmatter.

    Args:
        skill_dir: Path to skill directory containing SKILL.md

    Returns:
        Parsed frontmatter as dict-like object
    """
    return _read_frontmatter_from_path(skill_dir / "SKILL.md")


def _read_frontmatter_safe(
    skill_dir: Path,
    skill_name: str = "",
) -> dict[str, Any]:
    """Safely read SKILL.md frontmatter with fallback on errors.

    Args:
        skill_dir: Path to skill directory containing SKILL.md
        skill_name: Optional skill name for logging (defaults to dir name)

    Returns:
        Parsed frontmatter dict, or fallback dict with name/description
        on any error (file not found, YAML syntax error, etc.)
    """
    if not skill_name:
        skill_name = skill_dir.name

    try:
        return _read_frontmatter(skill_dir)
    except Exception as e:
        logger.warning(
            f"Failed to read SKILL.md frontmatter for '{skill_name}' "
            f"at {skill_dir}: {e}. Using fallback values.",
        )
        # Return minimal valid frontmatter
        return {"name": skill_name, "description": ""}


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


_IGNORED_SKILL_ARTIFACTS = {
    "__pycache__",
    "__MACOSX",
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
}


def _copy_skill_dir(
    source: Path,
    target: Path,
    *,
    skill_md_source: Path | None = None,
) -> None:
    """Replace *target* with a copy of *source*.

    We intentionally filter only well-known OS/cache artifacts so skill
    content behaves consistently on macOS, Windows, Linux, and Docker.
    User-authored dotfiles are preserved.
    """
    if target.exists():
        shutil.rmtree(target)

    def _ignore(_dir: str, names: list[str]) -> set[str]:
        ignored = {name for name in names if name in _IGNORED_SKILL_ARTIFACTS}
        if skill_md_source is None:
            return ignored
        current_dir = Path(_dir)
        if current_dir.resolve() != source.resolve():
            return ignored
        ignored.add("SKILL.md")
        ignored.update({"SKILL.en.md", "SKILL.zh.md"})
        return ignored

    shutil.copytree(
        source,
        target,
        ignore=_ignore,
    )
    if skill_md_source is not None:
        shutil.copy2(skill_md_source, target / "SKILL.md")


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
        if result is not False:
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


def _is_builtin_skill(skill_name: str, builtin_names: list[str]) -> bool:
    """Check if skill name is in builtin list."""
    return skill_name in builtin_names


def _is_pool_builtin_entry(entry: dict[str, Any] | None) -> bool:
    """Return whether one pool manifest entry represents a builtin slot."""
    return bool(entry) and str(entry.get("source", "") or "") == "builtin"


def _classify_pool_skill_source(
    skill_name: str,
    skill_dir: Path,
    existing: dict[str, Any],
    builtin_names: list[str],
) -> tuple[str, bool]:
    """Classify one pool skill against packaged builtins.

    Preserve the manifest's builtin/customized intent when the entry
    already exists. This lets an outdated builtin remain a builtin slot,
    while same-name customized copies stay customized.
    """
    if existing and _is_pool_builtin_entry(existing):
        return "builtin", False

    if not _is_builtin_skill(skill_name, builtin_names):
        return "customized", False

    if existing:
        return "customized", False

    pool_version = _extract_version(
        _read_frontmatter_safe(skill_dir, skill_name),
    )
    if pool_version:
        return "builtin", False
    return "customized", False


def _is_hidden(name: str) -> bool:
    return name in _IGNORED_SKILL_ARTIFACTS


def _extract_and_validate_zip(data: bytes, tmp_dir: Path) -> None:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        total = sum(info.file_size for info in zf.infolist())
        if total > _MAX_ZIP_BYTES:
            raise SkillsError(
                message="Uncompressed zip exceeds 200MB limit",
            )

        root_path = tmp_dir.resolve()
        for info in zf.infolist():
            target = (tmp_dir / info.filename).resolve()
            if not target.is_relative_to(root_path):
                raise SkillsError(
                    message=f"Unsafe path in zip: {info.filename}",
                )
            if info.external_attr >> 16 & 0o120000 == 0o120000:
                raise SkillsError(
                    message=f"Symlink not allowed in zip: {info.filename}",
                )

        zf.extractall(tmp_dir)


def _safe_child_path(base_dir: Path, relative_name: str) -> Path:
    """Resolve a relative child path and reject traversal / absolute paths."""
    normalized = (relative_name or "").replace("\\", "/").strip()
    if not normalized:
        raise SkillsError(
            message="Skill file path cannot be empty",
        )
    if normalized.startswith("/"):
        raise SkillsError(
            message=f"Absolute path not allowed: {relative_name}",
        )

    path = (base_dir / normalized).resolve()
    base_resolved = base_dir.resolve()
    if not path.is_relative_to(base_resolved):
        raise SkillsError(
            message=f"Unsafe path outside skill directory: {relative_name}",
        )
    return path


def _normalize_skill_dir_name(name: str) -> str:
    """Normalize and validate a skill directory name."""
    normalized = str(name or "").strip()
    if not normalized:
        raise SkillsError(message="Skill name cannot be empty")
    if "\x00" in normalized:
        raise SkillsError(message="Skill name cannot contain NUL bytes")
    if normalized in {".", ".."}:
        raise SkillsError(message=f"Invalid skill name: {normalized}")
    if "/" in normalized or "\\" in normalized:
        raise SkillsError(
            message="Skill name cannot contain path separators",
        )
    return normalized


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
            raise SkillsError(
                message=f"Invalid tree value for {name}: {type(value)}",
            )


def _resolve_skill_name(skill_dir: Path) -> str:
    """Resolve the import-time target name for one concrete skill directory.

    This helper is intentionally import-oriented. Runtime registration inside a
    workspace still keys skills by directory name; we only consult frontmatter
    here so zip imports behave consistently whether a skill is packed at the
    archive root or nested under a folder.
    """
    post = _read_frontmatter_safe(skill_dir)
    name = str(post.get("name") or "").strip()
    if name:
        return name
    return skill_dir.name


def _extract_requirements(post: dict[str, Any]) -> SkillRequirements:
    """Extract requirements from a parsed frontmatter dict."""
    metadata = post.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    requires: Any | None = None
    for namespace in _REQUIREMENTS_METADATA_NAMESPACES:
        provider_metadata = metadata.get(namespace)
        if isinstance(provider_metadata, dict):
            requires = provider_metadata.get("requires")
            if requires is not None:
                break

    if requires is None:
        requires = metadata.get(
            "requires",
            post.get("requires", {}),
        )

    if isinstance(requires, list):
        return SkillRequirements(require_bins=list(requires), require_envs=[])

    if not isinstance(requires, dict):
        return SkillRequirements()

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
    return (
        f"QWENPAW_SKILL_CONFIG_{''.join(normalized).strip('_') or 'DEFAULT'}"
    )


def _build_skill_config_env_overrides(
    skill_name: str,
    config: dict[str, Any],
    require_envs: list[str],
) -> dict[str, str]:
    """Map config keys to env vars based on ``require_envs``.

    Config keys that match a declared ``require_envs`` entry are
    injected as environment variables.  Keys not in ``require_envs``
    are silently skipped (still available via the full JSON var).
    Missing required keys are logged as warnings.
    """
    overrides: dict[str, str] = {}

    normalized_required_envs = [
        str(env_name).strip()
        for env_name in require_envs
        if str(env_name).strip()
    ]

    required_set = set(normalized_required_envs)
    for key, value in config.items():
        if key not in required_set:
            continue
        if value in (None, ""):
            continue
        overrides[key] = _stringify_skill_env_value(value)

    for env_name in normalized_required_envs:
        if env_name not in overrides:
            logger.warning(
                "Skill '%s' requires env '%s' but config does "
                "not provide it",
                skill_name,
                env_name,
            )

    overrides[_skill_config_env_var_name(skill_name)] = json.dumps(
        config,
        ensure_ascii=False,
    )
    return overrides


def _acquire_skill_env_key(key: str, value: str) -> bool:
    with _ENV_LOCK:
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
    with _ENV_LOCK:
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

    Config keys matching ``metadata.requires.env`` entries are injected
    as environment variables.  The full config is always available as
    ``QWENPAW_SKILL_CONFIG_<SKILL_NAME>`` (JSON string).
    """
    manifest = read_skill_manifest(workspace_dir)
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
    protected: bool = False,
) -> dict[str, Any]:
    """Build the manifest-facing metadata for one concrete skill directory.

    The metadata is derived from the actual files on disk every time we
    reconcile. That keeps the manifest descriptive rather than authoritative
    for content details.
    """
    post = _read_frontmatter_safe(skill_dir, skill_name)
    requirements = _extract_requirements(post)
    return {
        "name": skill_name,
        "description": str(post.get("description", "") or ""),
        "version_text": _extract_version(post),
        "commit_text": "",
        "source": source,
        "protected": protected,
        "requirements": requirements.model_dump(),
        "updated_at": _get_skill_mtime(skill_dir),
    }


_TIMESTAMP_SUFFIX_RE = re.compile(r"(-\d{14})+$")


def suggest_conflict_name(
    skill_name: str,
    existing_names: set[str] | None = None,
) -> str:
    """Return a timestamp-suffixed rename suggestion for collisions.

    Strips any previously-appended timestamp suffixes from *skill_name*
    before generating a new one, so names never accumulate multiple
    ``-YYYYMMDDHHMMSS`` tails.  When *existing_names* is provided the
    function iterates (up to 100 attempts) until it finds a candidate
    that is not already taken.
    """
    base = _TIMESTAMP_SUFFIX_RE.sub("", skill_name) or skill_name
    taken = existing_names or set()
    for _ in range(100):
        suffix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        candidate = f"{base}-{suffix}"
        if candidate not in taken:
            return candidate
        time.sleep(0.01)
    return f"{base}-{suffix}"


class SkillConflictError(RuntimeError):
    """Raised when an import or save operation hits a renameable conflict."""

    def __init__(self, detail: dict[str, Any]):
        super().__init__(str(detail.get("message") or "Skill conflict"))
        self.detail = detail


def _build_import_conflict(
    skill_name: str,
    existing_names: set[str] | None = None,
) -> dict[str, Any]:
    return {
        "reason": "conflict",
        "skill_name": skill_name,
        "suggested_name": suggest_conflict_name(
            skill_name,
            existing_names,
        ),
    }


def _pool_skill_content_hash(skill_name: str, entry: dict[str, Any]) -> str:
    content_hash = str(entry.get("content_hash", "") or "")
    if content_hash:
        return content_hash
    return _skill_content_hash_for_path(
        get_skill_pool_dir() / skill_name / "SKILL.md",
    )


def _resolve_pool_builtin_language(
    skill_name: str,
    entry: dict[str, Any],
    registry: dict[str, dict[str, BuiltinSkillVariant]],
    *,
    preferred_language: str | None = None,
) -> str:
    canonical_name = _canonical_builtin_skill_name(skill_name, registry)
    variants = registry.get(canonical_name) or {}
    if not variants:
        return ""

    configured = str(entry.get("builtin_language", "") or "").strip().lower()
    if configured in variants:
        return configured

    source_identity = _parse_builtin_skill_identity(
        str(entry.get("builtin_source_name", "") or "").strip(),
    )
    if (
        source_identity is not None
        and source_identity.name == canonical_name
        and source_identity.language in variants
    ):
        return source_identity.language

    current_hash = _pool_skill_content_hash(canonical_name, entry)
    if current_hash:
        matching = [
            language
            for language, variant in variants.items()
            if variant.content_hash == current_hash
        ]
        if len(matching) == 1:
            return matching[0]

    preferred = preferred_language or get_builtin_skill_language_preference()
    if preferred in variants:
        return preferred
    return sorted(variants.keys())[0]


def _build_builtin_language_spec(
    skill_name: str,
    language: str,
    variant: BuiltinSkillVariant,
    variants: dict[str, BuiltinSkillVariant],
    current: dict[str, Any],
    *,
    current_language: str = "",
) -> dict[str, Any]:
    if not current:
        status = "missing"
    else:
        current_source = str(current.get("source", "") or "")
        current_version_text = str(current.get("version_text", "") or "")
        current_variant = variants.get(current_language)
        if current_source != "builtin":
            status = "conflict"
        elif (
            current_variant is not None
            and current_version_text == current_variant.version_text
        ):
            status = "current"
        elif (
            current_version_text
            and current_variant is not None
            and current_variant.version_text
            and current_version_text != current_variant.version_text
        ):
            status = "outdated"
        else:
            status = "conflict"
    return {
        "language": language,
        "description": variant.description,
        "version_text": variant.version_text,
        "source_name": variant.source_name,
        "status": status,
    }


def _top_level_builtin_candidate_status(
    language_specs: dict[str, dict[str, Any]],
    selected_language: str,
) -> str:
    return str(
        language_specs.get(selected_language, {}).get("status", "")
        or "missing",
    )


def _build_builtin_import_candidate(
    skill_name: str,
    *,
    pool_skills: dict[str, Any],
    registry: dict[str, dict[str, BuiltinSkillVariant]],
    preferred_language: str | None = None,
) -> dict[str, Any]:
    """Build one builtin import candidate enriched with pool state."""
    pref = preferred_language or get_builtin_skill_language_preference()
    canonical_name = _canonical_builtin_skill_name(skill_name, registry)
    variants = registry.get(canonical_name) or {}
    current = pool_skills.get(canonical_name) or {}
    current_version_text = str(current.get("version_text", "") or "")
    current_source = str(current.get("source", "") or "")
    current_language = ""
    if current and current_source == "builtin":
        current_language = _resolve_pool_builtin_language(
            canonical_name,
            current,
            registry,
            preferred_language=pref,
        )
    preferred_variant = _select_builtin_variant(
        registry,
        canonical_name,
        pref,
        preferred_language=pref,
    )
    preferred_lang = preferred_variant.language if preferred_variant else ""
    language_specs = {
        language: _build_builtin_language_spec(
            canonical_name,
            language,
            variant,
            variants,
            current,
            current_language=current_language,
        )
        for language, variant in sorted(variants.items())
    }
    return {
        "name": canonical_name,
        "description": preferred_variant.description
        if preferred_variant
        else "",
        "version_text": preferred_variant.version_text
        if preferred_variant
        else "",
        "current_version_text": current_version_text,
        "current_source": current_source,
        "current_language": current_language,
        "available_languages": sorted(variants.keys()),
        "languages": language_specs,
        "status": _top_level_builtin_candidate_status(
            language_specs,
            preferred_lang,
        ),
    }


def list_builtin_import_candidates() -> list[dict[str, Any]]:
    """List builtin skills available from packaged source."""
    registry = _get_packaged_builtin_registry()
    if not registry:
        return []

    pref = get_builtin_skill_language_preference()
    manifest = read_skill_pool_manifest()
    pool_skills = manifest.get("skills", {})
    candidates: list[dict[str, Any]] = []

    for skill_name in sorted(registry):
        candidates.append(
            _build_builtin_import_candidate(
                skill_name,
                pool_skills=pool_skills,
                registry=registry,
                preferred_language=pref,
            ),
        )
    return candidates


def _default_builtin_import_requests(
    registry: dict[str, dict[str, BuiltinSkillVariant]],
    candidates: dict[str, dict[str, Any]],
    *,
    preferred_language: str | None = None,
) -> list[dict[str, str]]:
    pref = preferred_language or get_builtin_skill_language_preference()
    requests: list[dict[str, str]] = []
    for skill_name in sorted(candidates):
        variant = _select_builtin_variant(
            registry,
            skill_name,
            pref,
            preferred_language=pref,
        )
        if variant is None:
            continue
        requests.append(
            {
                "skill_name": skill_name,
                "language": variant.language,
            },
        )
    return requests


def _normalize_builtin_import_requests(
    selected_imports: list[dict[str, Any]],
    registry: dict[str, dict[str, BuiltinSkillVariant]],
    candidates: dict[str, dict[str, Any]],
    *,
    preferred_language: str | None = None,
) -> tuple[list[tuple[str, str]], list[str], list[str]]:
    normalized_imports: list[tuple[str, str]] = []
    unknown: list[str] = []
    unsupported: list[str] = []

    for item in selected_imports:
        skill_name, language = _resolve_builtin_request_identity(
            item,
            registry,
            preferred_language=preferred_language,
        )
        if skill_name not in candidates:
            raw_name = str(item.get("skill_name", "") or "").strip()
            unknown.append(raw_name or skill_name or "<empty>")
            continue
        if language not in (registry.get(skill_name) or {}):
            unsupported.append(f"{skill_name}:{language}")
            continue
        normalized_imports.append((skill_name, language))

    return normalized_imports, unknown, unsupported


def _build_builtin_import_conflicts(
    normalized_imports: list[tuple[str, str]],
    candidates: dict[str, dict[str, Any]],
) -> list[dict[str, str]]:
    conflicts: list[dict[str, str]] = []
    for skill_name, language in normalized_imports:
        candidate = candidates[skill_name]
        current_source = str(candidate.get("current_source", "") or "")
        current_language = str(candidate.get("current_language", "") or "")
        language_spec = candidate.get("languages", {}).get(language, {}) or {}
        status = str(language_spec.get("status", "") or "")
        if not current_source:
            continue
        if (
            current_source == "builtin"
            and current_language
            and current_language != language
        ):
            conflicts.append(
                {
                    "skill_name": skill_name,
                    "language": language,
                    "status": "language_switch",
                    "source_name": str(
                        language_spec.get("source_name", "") or "",
                    ),
                    "source_version_text": str(
                        language_spec.get("version_text", "") or "",
                    ),
                    "current_version_text": str(
                        candidate.get("current_version_text", "") or "",
                    ),
                    "current_source": current_source,
                    "current_language": current_language,
                },
            )
            continue
        if status not in {"conflict", "outdated"}:
            continue
        conflicts.append(
            {
                "skill_name": skill_name,
                "language": language,
                "status": status,
                "source_name": str(
                    language_spec.get("source_name", "") or "",
                ),
                "source_version_text": str(
                    language_spec.get("version_text", "") or "",
                ),
                "current_version_text": str(
                    candidate.get("current_version_text", "") or "",
                ),
                "current_source": current_source,
                "current_language": current_language,
            },
        )
    return conflicts


def _pool_builtin_matches_variant(
    skill_name: str,
    existing: dict[str, Any],
    language: str,
    variant: BuiltinSkillVariant,
    registry: dict[str, dict[str, BuiltinSkillVariant]],
    *,
    preferred_language: str | None = None,
) -> bool:
    """Check if a pool entry already matches a specific builtin variant."""
    current_source = str(existing.get("source", "") or "")
    current_language = _resolve_pool_builtin_language(
        skill_name,
        existing,
        registry,
        preferred_language=preferred_language,
    )
    current_version_text = str(existing.get("version_text", "") or "")
    return (
        current_source == "builtin"
        and current_language == language
        and current_version_text == variant.version_text
    )


def import_builtin_skills(
    imports: list[dict[str, Any]] | None = None,
    *,
    overwrite_conflicts: bool = False,
) -> dict[str, list[Any]]:
    """Import selected builtins from packaged source into the local pool."""
    pool_dir = get_skill_pool_dir()
    pool_dir.mkdir(parents=True, exist_ok=True)

    registry = _get_packaged_builtin_registry()
    pref = get_builtin_skill_language_preference()
    manifest = read_skill_pool_manifest()
    pool_skills = manifest.get("skills", {})
    candidates = {
        skill_name: _build_builtin_import_candidate(
            skill_name,
            pool_skills=pool_skills,
            registry=registry,
            preferred_language=pref,
        )
        for skill_name in sorted(registry)
    }
    selected_imports = imports or _default_builtin_import_requests(
        registry,
        candidates,
        preferred_language=pref,
    )
    (
        normalized_imports,
        unknown,
        unsupported,
    ) = _normalize_builtin_import_requests(
        selected_imports,
        registry,
        candidates,
        preferred_language=pref,
    )

    if unknown:
        raise SkillsError(
            message=f"Unknown builtin skill(s): {', '.join(sorted(unknown))}",
        )
    if unsupported:
        raise SkillsError(
            message=(
                "Unsupported builtin language selection(s): "
                f"{', '.join(sorted(unsupported))}"
            ),
        )

    conflicts = _build_builtin_import_conflicts(
        normalized_imports,
        candidates,
    )
    if conflicts and not overwrite_conflicts:
        return {
            "imported": [],
            "updated": [],
            "unchanged": [],
            "conflicts": conflicts,
        }

    imported: list[str] = []
    updated: list[str] = []
    unchanged: list[str] = []
    manifest_path = get_pool_skill_manifest_path()
    manifest_default = _default_pool_manifest()

    def _process(payload: dict[str, Any]) -> dict[str, list[Any]]:
        skills = payload.setdefault("skills", {})
        payload["builtin_skill_names"] = sorted(registry.keys())
        for skill_name, language in normalized_imports:
            variant = registry[skill_name][language]
            target = pool_dir / skill_name
            existing = skills.get(skill_name) or {}

            if not target.exists():
                _copy_skill_dir(
                    variant.skill_dir,
                    target,
                    skill_md_source=variant.skill_md_path,
                )
                imported.append(skill_name)
            elif _pool_builtin_matches_variant(
                skill_name,
                existing,
                language,
                variant,
                registry,
                preferred_language=pref,
            ):
                unchanged.append(skill_name)
            else:
                _copy_skill_dir(
                    variant.skill_dir,
                    target,
                    skill_md_source=variant.skill_md_path,
                )
                updated.append(skill_name)

            entry = _build_skill_metadata(
                skill_name,
                target,
                source="builtin",
                protected=False,
            )
            entry["builtin_language"] = language
            entry["builtin_source_name"] = variant.source_name
            if "config" in existing:
                entry["config"] = existing.get("config")
            if "tags" in existing:
                entry["tags"] = existing.get("tags")
            skills[skill_name] = entry

        return {
            "imported": imported,
            "updated": updated,
            "unchanged": unchanged,
            "conflicts": conflicts,
        }

    return _mutate_json(
        manifest_path,
        manifest_default,
        _process,
    )


def migrate_pool_builtin_language_fields() -> bool:
    """Ensure builtin language metadata is set for all builtin pool entries."""
    registry = _get_packaged_builtin_registry()
    if not registry:
        return False

    preferred_language = get_builtin_skill_language_preference()

    def _update(payload: dict[str, Any]) -> bool:
        skills = payload.setdefault("skills", {})
        changed = False
        for skill_name, entry in skills.items():
            if not _is_pool_builtin_entry(entry):
                continue
            variants = registry.get(skill_name) or {}
            if not variants:
                continue
            language = _resolve_pool_builtin_language(
                skill_name,
                entry,
                registry,
                preferred_language=preferred_language,
            )
            if not language:
                language = (
                    preferred_language
                    if preferred_language in variants
                    else sorted(variants.keys())[0]
                )
            source_name = variants[language].source_name
            if entry.get("builtin_language") != language:
                entry["builtin_language"] = language
                changed = True
            if entry.get("builtin_source_name") != source_name:
                entry["builtin_source_name"] = source_name
                changed = True
        return changed

    return bool(
        _mutate_json(
            get_pool_skill_manifest_path(),
            _default_pool_manifest(),
            _update,
        ),
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

    if created:
        import_builtin_skills()
    else:
        migrate_pool_builtin_language_fields()
    return created


def reconcile_pool_manifest() -> dict[str, Any]:
    """Reconcile shared pool metadata with the filesystem.

    The pool manifest is not treated as the source of truth for content.
    Instead, the pool directory on disk is scanned and metadata is rebuilt
    from the discovered skills. Manifest-only bookkeeping such as ``config``
    is preserved when possible.

    Example:
        if a user manually drops ``skill_pool/demo/SKILL.md`` onto disk,
        the next reconcile adds ``demo`` to ``skill_pool/skill.json``.
    """
    pool_dir = get_skill_pool_dir()
    pool_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = get_pool_skill_manifest_path()
    if not manifest_path.exists():
        _write_json_atomic(manifest_path, _default_pool_manifest())

    registry = _get_packaged_builtin_registry()
    pref = get_builtin_skill_language_preference()
    builtin_names = sorted(registry.keys())

    def _update(payload: dict[str, Any]) -> dict[str, Any]:
        payload.setdefault("skills", {})
        payload.setdefault("builtin_skill_names", [])
        skills = payload["skills"]

        discovered = {
            path.name: path
            for path in pool_dir.iterdir()
            if path.is_dir() and (path / "SKILL.md").exists()
        }

        for skill_name, skill_dir in sorted(discovered.items()):
            existing = skills.get(skill_name, {})
            source, protected = _classify_pool_skill_source(
                skill_name,
                skill_dir,
                existing,
                builtin_names,
            )
            has_config = "config" in existing
            config = existing.get("config") if has_config else None
            existing_tags = existing.get("tags")
            skills[skill_name] = _build_skill_metadata(
                skill_name,
                skill_dir,
                source=source,
                protected=protected,
            )
            if source == "builtin" or _is_pool_builtin_entry(existing):
                language = _resolve_pool_builtin_language(
                    skill_name,
                    existing or skills[skill_name],
                    registry,
                    preferred_language=pref,
                )
                if language:
                    skills[skill_name]["builtin_language"] = language
                    if language in (registry.get(skill_name) or {}):
                        skills[skill_name]["builtin_source_name"] = registry[
                            skill_name
                        ][language].source_name
            if has_config:
                skills[skill_name]["config"] = config
            if existing_tags is not None:
                skills[skill_name]["tags"] = existing_tags

        for skill_name in list(skills):
            if skill_name not in discovered:
                skills.pop(skill_name, None)

        return payload

    return _mutate_json(
        manifest_path,
        _default_pool_manifest(),
        _update,
    )


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
    builtin_versions = _get_packaged_builtin_versions()

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

            # Inherit source from manifest when the entry already exists.
            # For new skills, default to "builtin" if name matches a
            # packaged builtin, otherwise "customized".
            if existing:
                source = existing.get("source", "customized")
            else:
                source = (
                    "builtin"
                    if skill_name in builtin_versions
                    else "customized"
                )

            metadata = _build_skill_metadata(
                skill_name,
                skill_dir,
                source=source,
                protected=False,
            )
            next_entry = {
                "enabled": enabled,
                "channels": channels,
                "source": source,
                "metadata": metadata,
                "requirements": metadata["requirements"],
                "updated_at": metadata["updated_at"],
            }
            if "config" in existing:
                next_entry["config"] = existing.get("config")
            existing_tags = existing.get("tags")
            if existing_tags is not None:
                next_entry["tags"] = existing_tags
            skills[skill_name] = next_entry
            skills[skill_name].pop("sync_to_hub", None)
            skills[skill_name].pop("sync_to_pool", None)

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
    """List configured workspaces with agent names."""
    workspaces: list[dict[str, str]] = []
    try:
        from ..config.utils import load_config
        from ..config.config import load_agent_config

        config = load_config()
        # Only return agents that are still in the configuration
        # This ensures deleted agents are not included
        for agent_id, profile in sorted(config.agents.profiles.items()):
            agent_name = agent_id
            try:
                agent_name = load_agent_config(agent_id).name or agent_id
            except Exception:
                pass
            workspaces.append(
                {
                    "agent_id": agent_id,
                    "agent_name": agent_name,
                    "workspace_dir": str(
                        Path(profile.workspace_dir).expanduser(),
                    ),
                },
            )
    except Exception as exc:
        logger.warning("Failed to load configured workspaces: %s", exc)

    # Note: We intentionally do NOT scan the workspaces/ directory
    # for unlisted workspaces, as those may belong to deleted agents
    # and should not appear in the broadcast list

    return workspaces


def read_skill_manifest(
    workspace_dir: Path,
) -> dict[str, Any]:
    """Return the cached workspace skill manifest."""
    path = get_workspace_skill_manifest_path(workspace_dir)
    return _read_json_unlocked(path, _default_workspace_manifest())


def read_skill_pool_manifest() -> dict[str, Any]:
    """Return the cached pool skill manifest."""
    path = get_pool_skill_manifest_path()
    return _read_json_unlocked(path, _default_pool_manifest())


def resolve_effective_skills(
    workspace_dir: Path,
    channel_name: str,
) -> list[str]:
    """Resolve enabled workspace skills for one channel."""
    manifest = read_skill_manifest(workspace_dir)
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


def get_pool_builtin_sync_status(
    *,
    pool_skills: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Compare pool skills against packaged builtins.

    Returns a dict keyed by skill name with sync status for each
    builtin pool skill.

    Status values:
    - ``synced``: pool builtin version matches the packaged builtin version
    - ``outdated``: builtin version differs, or the packaged builtin
    was removed
    """
    registry = _get_packaged_builtin_registry()
    if not registry:
        return {}

    pref = get_builtin_skill_language_preference()
    if pool_skills is None:
        manifest = _read_json(
            get_pool_skill_manifest_path(),
            _default_pool_manifest(),
        )
        pool_skills = manifest.get("skills", {})
    result: dict[str, dict[str, Any]] = {}
    for name, variants in registry.items():
        pool_entry = pool_skills.get(name)
        if pool_entry is None or not _is_pool_builtin_entry(pool_entry):
            continue
        language = _resolve_pool_builtin_language(
            name,
            pool_entry,
            registry,
            preferred_language=pref,
        )
        variant = variants.get(language)
        if variant is None:
            result[name] = {
                "sync_status": "outdated",
                "latest_version_text": "",
                "available_languages": sorted(variants.keys()),
            }
            continue
        current_version_text = str(
            pool_entry.get("version_text", "") or "",
        )
        if current_version_text != variant.version_text:
            result[name] = {
                "sync_status": "outdated",
                "latest_version_text": variant.version_text,
                "available_languages": sorted(variants.keys()),
            }
        else:
            result[name] = {
                "sync_status": "synced",
                "latest_version_text": "",
                "available_languages": sorted(variants.keys()),
            }
    for name, pool_entry in pool_skills.items():
        if not _is_pool_builtin_entry(pool_entry):
            continue
        if name in registry:
            continue
        result[name] = {
            "sync_status": "outdated",
            "latest_version_text": "",
            "available_languages": [],
        }
    return result


def _build_builtin_notice_fingerprint(payload: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    digest.update(
        json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8"),
    )
    return digest.hexdigest()


def get_pool_builtin_update_notice() -> dict[str, Any]:
    """Return added/missing/updated/removed builtin changes relative to pool.

    The comparison baseline comes from ``builtin_skill_names`` in the pool
    manifest, which is intentionally updated only when builtin imports happen.
    That lets the UI keep surfacing newly added/removed builtins across plain
    refreshes until the user explicitly reviews them.
    """
    registry = _get_packaged_builtin_registry()
    pref = get_builtin_skill_language_preference()
    manifest = _read_json(
        get_pool_skill_manifest_path(),
        _default_pool_manifest(),
    )
    pool_skills = manifest.get("skills", {})

    previous_builtin_names = {
        str(name).strip()
        for name in manifest.get("builtin_skill_names", [])
        if str(name).strip()
    }
    current_builtin_names = set(registry.keys())

    added: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    updated: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []

    for name in sorted(current_builtin_names):
        current = pool_skills.get(name) or {}
        candidate = _build_builtin_import_candidate(
            name,
            pool_skills=pool_skills,
            registry=registry,
            preferred_language=pref,
        )
        if name not in previous_builtin_names:
            added.append(candidate)
            continue

        candidate_status = str(candidate.get("status", "") or "")
        if candidate_status == "missing":
            missing.append(candidate)
            continue

        if candidate_status != "current":
            updated.append(candidate)

    for name in sorted(previous_builtin_names - current_builtin_names):
        current = pool_skills.get(name) or {}
        if not current:
            continue
        removed.append(
            {
                "name": name,
                "description": str(current.get("description", "") or ""),
                "current_version_text": str(
                    current.get("version_text", "") or "",
                ),
                "current_source": str(current.get("source", "") or ""),
            },
        )

    actionable_skill_names = sorted(
        {
            item["name"]
            for item in [*added, *missing, *updated]
            if str(item.get("status", "") or "") != "current"
        },
    )
    total_changes = len(added) + len(missing) + len(updated) + len(removed)
    fingerprint = ""
    if total_changes:
        fingerprint = _build_builtin_notice_fingerprint(
            {
                "added": [
                    {
                        "name": item["name"],
                        "version_text": item.get("version_text", ""),
                        "current_language": item.get("current_language", ""),
                        "status": item.get("status", ""),
                    }
                    for item in added
                ],
                "missing": [
                    {
                        "name": item["name"],
                        "status": item.get("status", ""),
                        "version_text": item.get("version_text", ""),
                        "current_language": item.get("current_language", ""),
                        "current_version_text": item.get(
                            "current_version_text",
                            "",
                        ),
                    }
                    for item in missing
                ],
                "updated": [
                    {
                        "name": item["name"],
                        "status": item.get("status", ""),
                        "version_text": item.get("version_text", ""),
                        "current_language": item.get("current_language", ""),
                        "current_version_text": item.get(
                            "current_version_text",
                            "",
                        ),
                    }
                    for item in updated
                ],
                "removed": [
                    {
                        "name": item["name"],
                        "current_version_text": item.get(
                            "current_version_text",
                            "",
                        ),
                        "current_source": item.get("current_source", ""),
                    }
                    for item in removed
                ],
            },
        )

    return {
        "fingerprint": fingerprint,
        "has_updates": total_changes > 0,
        "total_changes": total_changes,
        "actionable_skill_names": actionable_skill_names,
        "added": added,
        "missing": missing,
        "updated": updated,
        "removed": removed,
    }


def update_single_builtin(
    skill_name: str,
    *,
    language: str | None = None,
) -> dict[str, Any]:
    """Update one builtin skill in the pool to the latest packaged version."""
    registry = _get_packaged_builtin_registry()
    canonical_name = _canonical_builtin_skill_name(skill_name, registry)
    if canonical_name not in registry:
        raise SkillsError(
            message=f"'{skill_name}' is not a builtin skill",
        )

    manifest = read_skill_pool_manifest()
    existing = manifest.get("skills", {}).get(canonical_name)
    if existing is None or not _is_pool_builtin_entry(existing):
        raise SkillsError(
            message=f"'{canonical_name}' is not a builtin pool skill",
        )

    pref = get_builtin_skill_language_preference()
    selected_language = _normalize_builtin_skill_language(
        language
        or _resolve_pool_builtin_language(
            canonical_name,
            existing,
            registry,
            preferred_language=pref,
        )
        or existing.get("builtin_language"),
        fallback=pref,
    )
    variant = registry.get(canonical_name, {}).get(selected_language)
    if variant is None:
        raise SkillsError(
            message=(
                f"Packaged builtin '{canonical_name}' does not support "
                f"language '{selected_language}'"
            ),
        )

    pool_dir = get_skill_pool_dir()
    target = pool_dir / canonical_name

    def _update(payload: dict[str, Any]) -> dict[str, Any]:
        _copy_skill_dir(
            variant.skill_dir,
            target,
            skill_md_source=variant.skill_md_path,
        )
        payload.setdefault("skills", {})
        entry = _build_skill_metadata(
            canonical_name,
            target,
            source="builtin",
            protected=False,
        )
        entry["builtin_language"] = selected_language
        entry["builtin_source_name"] = variant.source_name
        current = payload.get("skills", {}).get(canonical_name, {})
        if "config" in current:
            entry["config"] = current["config"]
        if "tags" in current:
            entry["tags"] = current["tags"]
        payload["skills"][canonical_name] = entry
        return entry

    return _mutate_json(
        get_pool_skill_manifest_path(),
        _default_pool_manifest(),
        _update,
    )


def _builtin_versions_match(
    *,
    pool_version_text: str,
    workspace_version_text: str,
) -> bool:
    return bool(
        pool_version_text
        and workspace_version_text
        and pool_version_text == workspace_version_text,
    )


def _extract_emoji_from_metadata(metadata: Any) -> str:
    """Extract emoji from metadata.qwenpaw.emoji."""
    if not isinstance(metadata, dict):
        return ""
    qwenpaw = metadata.get("qwenpaw")
    if isinstance(qwenpaw, dict):
        return str(qwenpaw.get("emoji", "") or "")
    return ""


def _read_skill_from_dir(skill_dir: Path, source: str) -> SkillInfo | None:
    if not skill_dir.is_dir():
        return None

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return None

    try:
        content = read_text_file_with_encoding_fallback(skill_md)
        description = ""
        emoji = ""
        post: Any = {}
        try:
            post = frontmatter.loads(content)
            description = str(post.get("description", "") or "")

            # Extract emoji from metadata.qwenpaw.emoji
            emoji = _extract_emoji_from_metadata(post.get("metadata", {}))
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
            version_text=_extract_version(post),
            content=content,
            source=source,
            references=references,
            scripts=scripts,
            emoji=emoji,
        )
    except Exception as exc:
        logger.error("Failed to read skill %s: %s", skill_dir, exc)
        return None


def _validate_skill_content(content: str) -> tuple[str, str]:
    post = frontmatter.loads(content)
    skill_name = str(post.get("name") or "").strip()
    skill_description = str(post.get("description") or "").strip()
    if not skill_name or not skill_description:
        raise SkillsError(
            message=(
                "SKILL.md must include non-empty frontmatter "
                "name and description"
            ),
        )
    return skill_name, skill_description


def _import_skill_dir(
    src_dir: Path,
    target_root: Path,
    skill_name: str,
) -> bool:
    """Import a skill directory to target location.

    Args:
        src_dir: Source skill directory
        target_root: Target root directory
        skill_name: Name of the skill
    Returns:
        bool: True if import succeeded, False otherwise
    """
    post = _read_frontmatter_safe(src_dir, skill_name)
    if not post.get("name") or not post.get("description"):
        return False

    target_dir = target_root / skill_name
    if target_dir.exists():
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

    Naming rule:
    - single-skill zips use the skill frontmatter ``name`` when present
    - multi-skill zips apply the same rule per top-level skill directory

    This keeps import results consistent across different zip layouts.
    """
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise SkillsError(
            message="Uploaded file is not a valid zip archive",
        )
    tmp_dir = Path(tempfile.mkdtemp(prefix="qwenpaw_skill_upload_"))
    _extract_and_validate_zip(data, tmp_dir)
    real_entries = [
        path for path in tmp_dir.iterdir() if not _is_hidden(path.name)
    ]
    extract_root = (
        real_entries[0]
        if len(real_entries) == 1 and real_entries[0].is_dir()
        else tmp_dir
    )
    if (extract_root / "SKILL.md").exists():
        found = [(extract_root, _resolve_skill_name(extract_root))]
    else:
        found = [
            (path, _resolve_skill_name(path))
            for path in sorted(extract_root.iterdir())
            if not _is_hidden(path.name)
            and path.is_dir()
            and (path / "SKILL.md").exists()
        ]
    if not found:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise SkillsError(
            message="No valid skills found in uploaded zip",
        )
    return tmp_dir, found


def _scan_skill_dir_or_raise(skill_dir: Path, skill_name: str) -> None:
    scan_skill_directory(skill_dir, skill_name=skill_name)


@contextmanager
def _staged_skill_dir(skill_name: str) -> Iterator[Path]:
    """Create a temporary skill directory used for staged writes."""
    temp_root = Path(
        tempfile.mkdtemp(prefix=f"qwenpaw_skill_stage_{skill_name}_"),
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

    def _read_manifest(self) -> dict[str, Any]:
        return read_skill_manifest(self.workspace_dir)

    def list_all_skills(self) -> list[SkillInfo]:
        manifest = self._read_manifest()
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
        manifest = self._read_manifest()
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
        references: dict[str, Any] | None = None,
        scripts: dict[str, Any] | None = None,
        extra_files: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
        enable: bool = False,
    ) -> str | None:
        _validate_skill_content(content)
        skill_name = _normalize_skill_dir_name(name)
        skill_root = get_workspace_skills_dir(self.workspace_dir)
        skill_root.mkdir(parents=True, exist_ok=True)
        skill_dir = skill_root / skill_name
        if skill_dir.exists():
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
            if "source" in entry:
                source = entry["source"]
            elif skill_name in _get_packaged_builtin_versions():
                source = "builtin"
            else:
                source = "customized"
            metadata = _build_skill_metadata(
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

        _mutate_json(
            get_workspace_skill_manifest_path(self.workspace_dir),
            _default_workspace_manifest(),
            _update,
        )
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
        final_name = _normalize_skill_dir_name(target_name or skill_name)
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
        target_dir = skill_root / final_name
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
        skill_dir = skill_root / skill_name

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
            with _staged_skill_dir(skill_name) as staged_dir:
                if skill_dir.exists():
                    _copy_skill_dir(skill_dir, staged_dir)
                (staged_dir / "SKILL.md").write_text(
                    content,
                    encoding="utf-8",
                )
                _scan_skill_dir_or_raise(staged_dir, skill_name)
            (skill_dir / "SKILL.md").write_text(
                content,
                encoding="utf-8",
            )
        source = (
            "customized"
            if content_changed
            else old_entry.get("source", "customized")
        )
        metadata = _build_skill_metadata(
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

        _mutate_json(
            get_workspace_skill_manifest_path(self.workspace_dir),
            _default_workspace_manifest(),
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
        target_dir = skill_root / final_name
        old_dir = skill_root / skill_name

        with _staged_skill_dir(final_name) as staged_dir:
            _copy_skill_dir(old_dir, staged_dir)
            (staged_dir / "SKILL.md").write_text(
                content,
                encoding="utf-8",
            )
            _scan_skill_dir_or_raise(staged_dir, final_name)
            _copy_skill_dir(staged_dir, target_dir)

        old_config = (
            config if config is not None else old_entry.get("config") or {}
        )
        old_channels = old_entry.get("channels") or ["all"]
        metadata = _build_skill_metadata(
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

        _mutate_json(
            get_workspace_skill_manifest_path(self.workspace_dir),
            _default_workspace_manifest(),
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
        tmp_dir, found = _extract_zip_skills(data)
        renames = rename_map or {}
        try:
            normalized_target = str(target_name or "").strip()
            if normalized_target:
                normalized_target = _normalize_skill_dir_name(
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
                (d, _normalize_skill_dir_name(renames.get(n, n)))
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
                _scan_skill_dir_or_raise(skill_dir, skill_name)
                if skill_name in seen_names:
                    conflicts.append(
                        _build_import_conflict(
                            skill_name,
                            existing_on_disk,
                        ),
                    )
                    continue
                seen_names.add(skill_name)
                exists = (skill_root / skill_name).exists()
                if exists:
                    conflicts.append(
                        _build_import_conflict(
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
                if _import_skill_dir(
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
            return True

        updated = _mutate_json(
            manifest_path,
            _default_workspace_manifest(),
            _update,
        )
        return updated

    def set_skill_tags(
        self,
        name: str,
        tags: list[str] | None,
    ) -> bool:
        """Update one workspace skill's user tags."""
        skill_name = str(name or "")
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

        return _mutate_json(
            manifest_path,
            _default_workspace_manifest(),
            _update,
        )

    def delete_skill(self, name: str) -> bool:
        skill_name = str(name or "")
        manifest = self._read_manifest()
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
    ) -> str | None:
        normalized = file_path.replace("\\", "/")
        if ".." in normalized or normalized.startswith("/"):
            return None
        if not (
            normalized.startswith("references/")
            or normalized.startswith("scripts/")
        ):
            return None

        manifest = self._read_manifest()
        if skill_name not in manifest.get("skills", {}):
            return None

        base_dir = get_workspace_skills_dir(self.workspace_dir) / skill_name
        if not base_dir.exists():
            return None

        full_path = base_dir / normalized
        if not full_path.exists() or not full_path.is_file():
            return None
        return read_text_file_with_encoding_fallback(full_path)


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
        references: dict[str, Any] | None = None,
        scripts: dict[str, Any] | None = None,
        extra_files: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
    ) -> str | None:
        _validate_skill_content(content)
        skill_name = _normalize_skill_dir_name(name)
        pool_dir = get_skill_pool_dir()
        skill_dir = pool_dir / skill_name
        manifest = read_skill_pool_manifest()
        existing = manifest.get("skills", {}).get(skill_name)
        if existing is not None or skill_dir.exists():
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
                protected=False,
            )
            if config is not None:
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
        target_name: str | None = None,
        rename_map: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        pool_dir = get_skill_pool_dir()
        tmp_dir, found = _extract_zip_skills(data)
        renames = rename_map or {}
        try:
            normalized_target = str(target_name or "").strip()
            if normalized_target:
                normalized_target = _normalize_skill_dir_name(
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
                (d, _normalize_skill_dir_name(renames.get(n, n)))
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
                _scan_skill_dir_or_raise(skill_dir, skill_name)
            conflicts: list[dict[str, Any]] = []
            planned: list[tuple[Path, str]] = []
            seen_names: set[str] = set()
            for skill_dir, skill_name in found:
                if skill_name in seen_names:
                    conflicts.append(
                        _build_import_conflict(
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
                        _build_import_conflict(
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
                if _import_skill_dir(
                    skill_dir,
                    pool_dir,
                    skill_name,
                ):
                    imported.append(skill_name)

            if imported:

                def _update(payload: dict[str, Any]) -> None:
                    payload.setdefault("skills", {})
                    for name in imported:
                        payload["skills"][name] = _build_skill_metadata(
                            name,
                            pool_dir / name,
                            source="customized",
                            protected=False,
                        )

                _mutate_json(
                    get_pool_skill_manifest_path(),
                    _default_pool_manifest(),
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
        skill_name = str(name or "")
        manifest = read_skill_pool_manifest()
        entry = manifest.get("skills", {}).get(skill_name)
        if entry is None:
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

    def set_pool_skill_tags(
        self,
        name: str,
        tags: list[str] | None,
    ) -> bool:
        """Update one pool skill's user tags."""
        skill_name = str(name or "")
        normalized = tags or []

        def _update(payload: dict[str, Any]) -> bool:
            entry = payload.get("skills", {}).get(skill_name)
            if entry is None:
                return False
            entry["tags"] = normalized
            return True

        return _mutate_json(
            get_pool_skill_manifest_path(),
            _default_pool_manifest(),
            _update,
        )

    def get_edit_target_name(
        self,
        skill_name: str,
        *,
        target_name: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        manifest = read_skill_pool_manifest()
        entry = manifest.get("skills", {}).get(skill_name)
        if entry is None:
            return {"success": False, "reason": "not_found"}

        pool_names = set(manifest.get("skills", {}).keys())
        normalized_target = _normalize_skill_dir_name(
            target_name or skill_name,
        )
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
        _validate_skill_content(content)
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
        skill_dir = get_skill_pool_dir() / skill_name
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
            with _staged_skill_dir(skill_name) as staged_dir:
                if skill_dir.exists():
                    _copy_skill_dir(skill_dir, staged_dir)
                (staged_dir / "SKILL.md").write_text(
                    content,
                    encoding="utf-8",
                )
                _scan_skill_dir_or_raise(staged_dir, skill_name)
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
            next_entry = _build_skill_metadata(
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

        _mutate_json(
            get_pool_skill_manifest_path(),
            _default_pool_manifest(),
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
        skill_dir = get_skill_pool_dir() / final_name
        old_skill_dir = get_skill_pool_dir() / skill_name

        with _staged_skill_dir(final_name) as staged_dir:
            if old_skill_dir.exists():
                _copy_skill_dir(old_skill_dir, staged_dir)
            (staged_dir / "SKILL.md").write_text(
                content,
                encoding="utf-8",
            )
            _scan_skill_dir_or_raise(staged_dir, final_name)
            _copy_skill_dir(staged_dir, skill_dir)
        if old_skill_dir.exists():
            shutil.rmtree(old_skill_dir)

        new_config = (
            config if config is not None else entry.get("config") or {}
        )

        def _update(payload: dict[str, Any]) -> None:
            payload.setdefault("skills", {})
            current_entry = payload["skills"].get(skill_name) or entry or {}
            next_entry = _build_skill_metadata(
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

        _mutate_json(
            get_pool_skill_manifest_path(),
            _default_pool_manifest(),
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
        source_dir = get_workspace_skills_dir(workspace_dir) / skill_name
        if not source_dir.exists():
            return {"success": False, "reason": "not_found"}

        final_name = _normalize_skill_dir_name(skill_name)
        target_dir = get_skill_pool_dir() / final_name
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

        with _staged_skill_dir(final_name) as staged_dir:
            _copy_skill_dir(source_dir, staged_dir)
            _scan_skill_dir_or_raise(staged_dir, final_name)
            _copy_skill_dir(staged_dir, target_dir)

        ws_manifest = _read_json(
            get_workspace_skill_manifest_path(workspace_dir),
            _default_workspace_manifest(),
        )
        workspace_entry = ws_manifest.get("skills", {}).get(skill_name, {})
        ws_config = workspace_entry.get("config") or {}
        ws_tags = workspace_entry.get("tags")

        def _update(payload: dict[str, Any]) -> None:
            payload.setdefault("skills", {})
            pool_entry = _build_skill_metadata(
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

        _mutate_json(
            get_pool_skill_manifest_path(),
            _default_pool_manifest(),
            _update,
        )

        return {"success": True, "name": final_name}

    @staticmethod
    def _check_download_conflict(
        entry: dict[str, Any],
        existing: dict[str, Any] | None,
        final_name: str,
        workspace_dir: Path,
        workspace_identity: dict[str, str],
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
            if _builtin_versions_match(
                pool_version_text=str(pool_ver or ""),
                workspace_version_text=str(ws_ver or ""),
            ):
                return {
                    "success": True,
                    "mode": "unchanged",
                    "name": final_name,
                    "workspace_id": ws_id,
                    "workspace_name": ws_name,
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

    def download_to_workspace(
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

        source_dir = get_skill_pool_dir() / skill_name
        final_name = _normalize_skill_dir_name(skill_name)
        target_dir = get_workspace_skills_dir(workspace_dir) / final_name
        workspace_manifest = read_skill_manifest(workspace_dir)
        existing = workspace_manifest.get("skills", {}).get(final_name)
        workspace_identity = get_workspace_identity(workspace_dir)
        if not overwrite:
            conflict = self._check_download_conflict(
                entry,
                existing,
                final_name,
                workspace_dir,
                workspace_identity,
            )
            if conflict is not None:
                return conflict

        target_dir.parent.mkdir(parents=True, exist_ok=True)
        with _staged_skill_dir(final_name) as staged_dir:
            _copy_skill_dir(source_dir, staged_dir)
            _scan_skill_dir_or_raise(staged_dir, final_name)
            _copy_skill_dir(staged_dir, target_dir)

        pool_config = entry.get("config") or {}
        pool_tags = entry.get("tags")

        def _update(payload: dict[str, Any]) -> None:
            payload.setdefault("skills", {})
            metadata = _build_skill_metadata(
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
            if pool_tags is not None:
                ws_entry["tags"] = pool_tags
            payload["skills"][final_name] = ws_entry

        _mutate_json(
            get_workspace_skill_manifest_path(workspace_dir),
            _default_workspace_manifest(),
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

        final_name = _normalize_skill_dir_name(skill_name)
        workspace_manifest = read_skill_manifest(workspace_dir)
        existing = workspace_manifest.get("skills", {}).get(final_name)
        workspace_identity = get_workspace_identity(workspace_dir)
        if not overwrite:
            conflict = self._check_download_conflict(
                entry,
                existing,
                final_name,
                workspace_dir,
                workspace_identity,
            )
            if conflict is not None:
                return conflict
        return {
            "success": True,
            "workspace_id": workspace_identity["workspace_id"],
            "workspace_name": workspace_identity["workspace_name"],
            "name": final_name,
        }
