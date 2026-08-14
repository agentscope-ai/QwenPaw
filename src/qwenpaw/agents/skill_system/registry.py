# -*- coding: utf-8 -*-
"""Skill registries, builtin sync, runtime resolution, and env overrides."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ...exceptions import SkillsError
from ..utils.file_handling import read_text_file_with_encoding_fallback
from .models import (
    BuiltinSkillIdentity,
    BuiltinSkillVariant,
)
from .store import (
    build_skill_metadata,
    classify_pool_skill_source,
    copy_skill_dir,
    default_pool_manifest,
    default_workspace_manifest,
    extract_version,
    get_pool_skill_manifest_path,
    get_skill_pool_dirs,
    get_skill_pool_dir,
    get_workspace_skill_manifest_path,
    get_workspace_skills_dir,
    is_ignored_skill_entry,
    is_pool_builtin_entry,
    is_primary_pool_skill_dir,
    mutate_json,
    normalize_skill_manifest_entry,
    read_frontmatter_safe_from_path,
    resolve_pool_skill_dir,
    read_json,
    read_skill_manifest,
    read_skill_pool_manifest,
    safe_skill_dir,
    write_json_atomic,
)

logger = logging.getLogger(__name__)


def _read_frontmatter_safe(skill_dir: Path, skill_name: str) -> dict:
    """Read frontmatter from SKILL.md safely.
    
    Extracts name, description, metadata, and triggers from SKILL.md frontmatter.
    
    Args:
        skill_dir: Path to the skill directory
        skill_name: Name of the skill (for error messages)
    
    Returns:
        Dict with 'name', 'description', 'metadata', and 'triggers' keys
    """
    try:
        import frontmatter as fm
        
        skill_md_path = skill_dir / "SKILL.md"
        if not skill_md_path.exists():
            return {"name": skill_name, "description": ""}
        
        content = read_text_file_with_encoding_fallback(skill_md_path)
        post = fm.loads(content)
        
        # Get frontmatter data - frontmatter library stores it in .metadata attribute
        # or we can access it via post[key] for top-level keys like name, description
        fm_dict = {}
        
        # Try to get name from frontmatter (top-level key)
        if hasattr(post, 'name'):
            fm_dict["name"] = post.name
        elif hasattr(post, 'metadata') and isinstance(post.metadata, dict):
            # Fallback: check if name is in metadata dict
            fm_dict["name"] = post.metadata.get("name", skill_name)
        else:
            fm_dict["name"] = skill_name
        
        # Get description from frontmatter (top-level key)
        if hasattr(post, 'description'):
            fm_dict["description"] = str(post.description)
        elif hasattr(post, 'metadata') and isinstance(post.metadata, dict):
            fm_dict["description"] = str(post.metadata.get("description", ""))
        else:
            fm_dict["description"] = ""
        
        # Get metadata dict (nested qwenpaw config etc.)
        if hasattr(post, 'metadata') and isinstance(post.metadata, dict):
            fm_dict["metadata"] = post.metadata
        else:
            fm_dict["metadata"] = {}
        
        # Get triggers from metadata.qwenpaw.triggers or top-level triggers
        triggers = []
        if hasattr(post, 'metadata') and isinstance(post.metadata, dict):
            qwenpaw_config = post.metadata.get("qwenpaw", {})
            if isinstance(qwenpaw_config, dict):
                triggers = qwenpaw_config.get("triggers", [])
        if not triggers and hasattr(post, 'triggers'):
            triggers = post.triggers
        if isinstance(triggers, list):
            fm_dict["triggers"] = triggers
        else:
            fm_dict["triggers"] = []
        
        return fm_dict
    
    except Exception as exc:
        logger.debug(
            "Failed to read frontmatter for skill '%s': %s",
            skill_name,
            exc,
        )
        return {"name": skill_name, "description": "", "metadata": {}, "triggers": []}


BUILTIN_SKILL_LANGUAGES = ("en", "zh")
_BUILTIN_SKILL_DIR_RE = re.compile(
    r"^(?P<name>.+)-(?P<language>en|zh)$",
)

_ACTIVE_SKILL_ENV_ENTRIES: dict[str, dict[str, Any]] = {}
_ENV_LOCK = threading.Lock()

_builtin_cache: dict[str, Any] = {}
_BUILTIN_CACHE_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Builtin skill language preference
# ---------------------------------------------------------------------------


def _normalize_builtin_skill_language(
    language: str | None,
    *,
    fallback: str = "en",
) -> str:
    normalized = str(language or "").strip().lower()
    if normalized in BUILTIN_SKILL_LANGUAGES:
        return normalized
    if fallback == "":
        return ""
    return fallback if fallback in BUILTIN_SKILL_LANGUAGES else "en"


def get_builtin_skill_language_preference() -> str:
    """Return the builtin skill language preference."""
    cached = _builtin_cache.get("language_preference")
    if cached is not None:
        return cached
    with _BUILTIN_CACHE_LOCK:
        cached = _builtin_cache.get("language_preference")
        if cached is not None:
            return cached
        from ...constant import WORKING_DIR

        settings_path = Path(WORKING_DIR) / "settings.json"
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


# ---------------------------------------------------------------------------
# Packaged builtin discovery + variant selection
# ---------------------------------------------------------------------------


def _parse_builtin_skill_identity(
    raw_name: str,
) -> BuiltinSkillIdentity | None:
    normalized = str(raw_name or "").strip()
    if not normalized:
        return None

    match = _BUILTIN_SKILL_DIR_RE.fullmatch(normalized)
    if match is None:
        return None

    return BuiltinSkillIdentity(
        name=str(match.group("name") or "").strip(),
        language=str(match.group("language") or "").strip(),
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


def _iter_packaged_builtin_variants() -> Iterator[BuiltinSkillVariant]:
    for skill_dir in _iter_packaged_builtin_dirs():
        skill_md_path = skill_dir / "SKILL.md"
        if not skill_md_path.exists():
            continue

        identity = _parse_builtin_skill_identity(skill_dir.name)
        if identity is None:
            continue

        post = read_frontmatter_safe_from_path(
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
            version_text=extract_version(post),
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
        if is_ignored_skill_entry(skill_dir.name):
            continue
        if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
            yield skill_dir


def get_packaged_builtin_versions() -> dict[str, str]:
    """Return packaged builtin names mapped to their version text."""
    registry = _get_packaged_builtin_registry()
    versions: dict[str, str] = {}
    for skill_name in sorted(registry):
        variant = _select_builtin_variant(registry, skill_name)
        versions[skill_name] = variant.version_text if variant else ""
    return versions


def get_builtin_skills_dir() -> Path:
    """Return the packaged built-in skill directory."""
    return Path(__file__).resolve().parent.parent / "skills"


def resolve_builtin_skill_dir(
    name: str,
    *,
    preferred_language: str | None = None,
) -> str | None:
    """Return a builtin skill's packaged directory, language-resolved."""
    registry = _get_packaged_builtin_registry()
    variant = _select_builtin_variant(
        registry,
        name,
        preferred_language=preferred_language,
    )
    return str(variant.skill_dir) if variant is not None else None


# ---------------------------------------------------------------------------
# Skill config -> environment variable overrides
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Builtin import candidate building
# ---------------------------------------------------------------------------


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

    # Migration fallback: match pool SKILL.md content against packaged
    # variants by SHA-256 hash, then guess from CJK character density.
    try:
        pool_md = get_skill_pool_dir() / canonical_name / "SKILL.md"
        pool_content = read_text_file_with_encoding_fallback(pool_md)
    except OSError:
        pool_content = ""
    if pool_content:
        pool_hash = hashlib.sha256(
            pool_content.encode("utf-8"),
        ).hexdigest()
        matching = [
            lang
            for lang, v in variants.items()
            if hashlib.sha256(
                read_text_file_with_encoding_fallback(
                    v.skill_md_path,
                ).encode("utf-8"),
            ).hexdigest()
            == pool_hash
        ]
        if len(matching) == 1:
            return matching[0]
        # Guess from actual content: significant CJK presence → zh.
        cjk_count = len(re.findall(r"[\u4e00-\u9fff]", pool_content))
        guessed = "zh" if cjk_count >= 32 else "en"
        if guessed in variants:
            return guessed

    # Final fallback: user preference or first available language.
    fallback = preferred_language or get_builtin_skill_language_preference()
    return fallback if fallback in variants else sorted(variants.keys())[0]


def _build_builtin_language_spec(
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
    current = normalize_skill_manifest_entry(
        pool_skills.get(canonical_name),
    )
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
        "status": str(
            language_specs.get(preferred_lang, {}).get("status", "")
            or "missing",
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


def _normalize_builtin_import_requests(
    selected_imports: list[dict[str, Any]],
    registry: dict[str, dict[str, BuiltinSkillVariant]],
    candidates: dict[str, dict[str, Any]],
    *,
    preferred_language: str = "en",
) -> tuple[list[tuple[str, str]], list[str], list[str]]:
    """Validate and normalize import requests to (name, language) tuples."""
    normalized: list[tuple[str, str]] = []
    unknown: list[str] = []
    unsupported: list[str] = []
    for item in selected_imports:
        raw_name = str(
            item.get("skill_name", "") or item.get("source_name", "") or "",
        ).strip()
        alias_identity = _parse_builtin_skill_identity(raw_name)
        sk_name = _canonical_builtin_skill_name(raw_name, registry)
        requested_lang = str(item.get("language", "") or "").strip().lower()
        fallback_lang = (
            alias_identity.language
            if alias_identity is not None
            else preferred_language
        )
        lang = _normalize_builtin_skill_language(
            requested_lang,
            fallback=fallback_lang,
        )
        if sk_name not in candidates:
            unknown.append(raw_name or sk_name or "<empty>")
        elif lang not in (registry.get(sk_name) or {}):
            unsupported.append(f"{sk_name}:{lang}")
        else:
            normalized.append((sk_name, lang))
    return normalized, unknown, unsupported


def _collect_builtin_import_conflicts(
    normalized_imports: list[tuple[str, str]],
    candidates: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return conflict descriptors for imports that need user confirmation."""
    conflicts: list[dict[str, Any]] = []
    for skill_name, language in normalized_imports:
        candidate = candidates[skill_name]
        cur_src = str(candidate.get("current_source", "") or "")
        cur_lang = str(candidate.get("current_language", "") or "")
        lang_spec = candidate.get("languages", {}).get(language, {}) or {}
        status = str(lang_spec.get("status", "") or "")
        if not cur_src:
            continue
        if cur_src == "builtin" and cur_lang and cur_lang != language:
            status = "language_switch"
        elif status not in {"conflict", "outdated"}:
            continue
        conflicts.append(
            {
                "skill_name": skill_name,
                "language": language,
                "status": status,
                "source_name": str(
                    lang_spec.get("source_name", "") or "",
                ),
                "source_version_text": str(
                    lang_spec.get("version_text", "") or "",
                ),
                "current_version_text": str(
                    candidate.get("current_version_text", "") or "",
                ),
                "current_source": cur_src,
                "current_language": cur_lang,
            },
        )
    return conflicts


# ---------------------------------------------------------------------------
# Builtin import execution + pool initialization
# ---------------------------------------------------------------------------


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
    # Build default import requests when none provided.
    if imports is None:
        selected_imports: list[dict[str, Any]] = []
        for skill_name in sorted(candidates):
            variant = _select_builtin_variant(
                registry,
                skill_name,
                pref,
                preferred_language=pref,
            )
            if variant is not None:
                selected_imports.append(
                    {"skill_name": skill_name, "language": variant.language},
                )
    else:
        selected_imports = imports

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

    conflicts = _collect_builtin_import_conflicts(
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
    manifest_default = default_pool_manifest()

    def _process(payload: dict[str, Any]) -> dict[str, list[Any]]:
        skills = payload.setdefault("skills", {})
        payload["builtin_skill_names"] = sorted(registry.keys())
        for skill_name, language in normalized_imports:
            variant = registry[skill_name][language]
            target = safe_skill_dir(pool_dir, skill_name)
            existing = skills.get(skill_name) or {}

            if not target.exists():
                copy_skill_dir(variant.skill_dir, target)
                imported.append(skill_name)
            elif (
                existing.get("source") == "builtin"
                and _resolve_pool_builtin_language(
                    skill_name,
                    existing,
                    registry,
                    preferred_language=pref,
                )
                == language
                and str(
                    existing.get("version_text", "") or "",
                )
                == variant.version_text
            ):
                unchanged.append(skill_name)
            else:
                copy_skill_dir(variant.skill_dir, target)
                updated.append(skill_name)

            entry = build_skill_metadata(
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
            for au_key in (
                "auto_update",
                "auto_update_targets",
                "auto_update_synced_hash",
            ):
                if au_key in existing:
                    entry[au_key] = existing.get(au_key)
            skills[skill_name] = entry

        return {
            "imported": imported,
            "updated": updated,
            "unchanged": unchanged,
            "conflicts": conflicts,
        }

    return mutate_json(
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
            if not is_pool_builtin_entry(entry):
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
        mutate_json(
            get_pool_skill_manifest_path(),
            default_pool_manifest(),
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
        write_json_atomic(manifest_path, default_pool_manifest())
        created = True

    if created:
        import_builtin_skills()
    else:
        migrate_pool_builtin_language_fields()
    return created


# ---------------------------------------------------------------------------
# Manifest reconciliation (pool + workspace)
# ---------------------------------------------------------------------------


def _discover_pool_skill_dirs() -> dict[str, Path]:
    """Scan pool roots in priority order, mapping skill name to its dir.

    The primary pool is scanned first, then configured read-only roots in
    order. The first occurrence of a name wins (the pool wins over extras);
    shadowed duplicates are skipped with a warning.
    """
    discovered: dict[str, Path] = {}
    for root in get_skill_pool_dirs():
        if not root.is_dir():
            continue
        for path in sorted(root.iterdir()):
            if is_ignored_skill_entry(path.name):
                continue
            if not (path.is_dir() and (path / "SKILL.md").exists()):
                continue
            if path.name in discovered:
                logger.warning(
                    "Skill '%s' in '%s' is shadowed by '%s'; skipping",
                    path.name,
                    root,
                    discovered[path.name].parent,
                )
                continue
            discovered[path.name] = path
    return discovered


def _build_reconciled_pool_entry(
    skill_name: str,
    skill_dir: Path,
    existing: dict[str, Any],
    *,
    registry: dict[str, dict[str, BuiltinSkillVariant]],
    builtin_names: list[str],
    preferred_language: str,
) -> dict[str, Any]:
    """Build one pool manifest entry from a discovered skill directory."""
    is_external = not is_primary_pool_skill_dir(skill_dir)
    if is_external:
        # External roots live outside the pool and never hold packaged
        # builtins; always classify as customized.
        source, protected = "customized", False
    else:
        source, protected = classify_pool_skill_source(
            skill_name,
            skill_dir,
            existing,
            builtin_names,
        )
    new_entry = build_skill_metadata(
        skill_name,
        skill_dir,
        source=source,
        protected=protected,
    )
    new_entry["external"] = is_external
    if not is_external and (
        source == "builtin" or is_pool_builtin_entry(existing)
    ):
        language = _resolve_pool_builtin_language(
            skill_name,
            existing or new_entry,
            registry,
            preferred_language=preferred_language,
        )
        if language:
            new_entry["builtin_language"] = language
            if language in (registry.get(skill_name) or {}):
                new_entry["builtin_source_name"] = registry[skill_name][
                    language
                ].source_name
    if "config" in existing:
        new_entry["config"] = existing.get("config")
    existing_tags = existing.get("tags")
    if existing_tags is not None:
        new_entry["tags"] = existing_tags
    existing_installed_from = existing.get("installed_from")
    if existing_installed_from:
        new_entry["installed_from"] = existing_installed_from
    # Phase 2B/2C: Preserve dynamic field (lazy loading config)
    existing_dynamic = existing.get("dynamic")
    if existing_dynamic:
        new_entry["dynamic"] = existing_dynamic
    for au_key in (
        "auto_update",
        "auto_update_targets",
        "auto_update_synced_hash",
    ):
        if au_key in existing:
            new_entry[au_key] = existing.get(au_key)
    return new_entry


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
        write_json_atomic(manifest_path, default_pool_manifest())

    registry = _get_packaged_builtin_registry()
    pref = get_builtin_skill_language_preference()
    builtin_names = sorted(registry.keys())

    def _update(payload: dict[str, Any]) -> dict[str, Any]:
        payload.setdefault("skills", {})
        payload.setdefault("builtin_skill_names", [])
        skills = payload["skills"]

        discovered = _discover_pool_skill_dirs()
        for skill_name, skill_dir in sorted(discovered.items()):
            raw_existing = skills.get(skill_name)
            existing = normalize_skill_manifest_entry(raw_existing)
            if raw_existing not in (None, existing):
                logger.warning(
                    (
                        "Malformed pool manifest entry for '%s'; "
                        "rebuilding from disk"
                    ),
                    skill_name,
                )
            try:
                skills[skill_name] = _build_reconciled_pool_entry(
                    skill_name,
                    skill_dir,
                    existing,
                    registry=registry,
                    builtin_names=builtin_names,
                    preferred_language=pref,
                )
            except Exception:
                logger.warning(
                    "Skipping pool skill '%s' during reconcile",
                    skill_name,
                    exc_info=True,
                )

        for skill_name in list(skills):
            if skill_name not in discovered:
                skills.pop(skill_name, None)

        return payload

    return mutate_json(
        manifest_path,
        default_pool_manifest(),
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
    builtin_versions = get_packaged_builtin_versions()

    if not manifest_path.exists():
        write_json_atomic(manifest_path, default_workspace_manifest())

    def _update(payload: dict[str, Any]) -> dict[str, Any]:
        payload.setdefault("skills", {})
        skills = payload["skills"]

        discovered = {
            path.name: path
            for path in workspace_skills_dir.iterdir()
            if not is_ignored_skill_entry(path.name)
            and path.is_dir()
            and (path / "SKILL.md").exists()
        }

        for skill_name, skill_dir in sorted(discovered.items()):
            raw_existing = skills.get(skill_name)
            existing = normalize_skill_manifest_entry(raw_existing)
            if raw_existing not in (None, existing):
                logger.warning(
                    (
                        "Malformed workspace manifest entry for '%s'; "
                        "rebuilding from disk"
                    ),
                    skill_name,
                )
            try:
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

                metadata = build_skill_metadata(
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
                existing_installed_from = existing.get("installed_from")
                if existing_installed_from:
                    next_entry["installed_from"] = existing_installed_from
                # Phase 2B/2C: Preserve dynamic field (lazy loading config)
                existing_dynamic = existing.get("dynamic")
                if existing_dynamic:
                    next_entry["dynamic"] = existing_dynamic
                skills[skill_name] = next_entry
                skills[skill_name].pop("sync_to_hub", None)
                skills[skill_name].pop("sync_to_pool", None)
            except Exception:
                logger.warning(
                    "Skipping workspace skill '%s' during reconcile",
                    skill_name,
                    exc_info=True,
                )

        for skill_name in list(skills):
            if skill_name not in discovered:
                skills.pop(skill_name, None)

        return payload

    return mutate_json(
        manifest_path,
        default_workspace_manifest(),
        _update,
    )


# ---------------------------------------------------------------------------
# Workspace listing + runtime skill resolution
# ---------------------------------------------------------------------------


def list_workspaces() -> list[dict[str, str]]:
    """List configured workspaces with agent names."""
    workspaces: list[dict[str, str]] = []
    try:
        from ...config.utils import load_config
        from ...config.config import load_agent_config

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


def resolve_core_and_lazy_skills(
    workspace_dir: Path,
    channel_name: str,
) -> tuple[list[str], dict[str, Any]]:
    """Resolve workspace skills into core (eager) and lazy categories.
    
    Returns:
        tuple[core_skills, lazy_skills_meta]:
            - core_skills: list of skill names (always loaded)
            - lazy_skills_meta: dict mapping skill_name -> {mode, triggers, description}
    
    New in Phase 1: Dynamic Skill Loading
    Skills with "dynamic.mode" == "lazy" are separated from core skills.
    Only their name + description are injected at startup; full SKILL.md
    is loaded on-demand when a trigger keyword matches user input.
    """
    manifest = read_skill_manifest(workspace_dir)
    core_skills = []
    lazy_skills_meta = {}
    
    for skill_name, entry in sorted(manifest.get("skills", {}).items()):
        if not entry.get("enabled", False):
            continue
        channels = entry.get("channels") or ["all"]
        if "all" not in channels and channel_name not in channels:
            continue
        
        skill_dir = get_workspace_skills_dir(workspace_dir) / skill_name
        if not skill_dir.exists():
            continue
        
        # Check if this is a lazy skill
        dynamic_config = entry.get("dynamic") or {}
        mode = dynamic_config.get("mode", "eager")
        
        if mode == "lazy":
            # Lazy skill: store metadata only (name + description + triggers)
            description = ""
            try:
                post = _read_frontmatter_safe(skill_dir, skill_name)
                description = str(post.get("description", "") or "")
            except Exception:
                pass
            
            lazy_skills_meta[skill_name] = {
                "mode": "lazy",
                "triggers": dynamic_config.get("triggers", []),
                "description": description,
                "skill_dir": skill_dir,
            }
        else:
            # Core skill (eager): always load
            core_skills.append(skill_name)
    
    return core_skills, lazy_skills_meta


def detect_lazy_skill_trigger(
    user_input: str,
    lazy_skills_meta: dict[str, Any],
    use_semantic: bool = False,
) -> str | None:
    """Detect if user input matches any lazy skill's trigger keywords or semantic meaning.
    
    Args:
        user_input: The user's message/input text
        lazy_skills_meta: Dict from resolve_core_and_lazy_skills()
        use_semantic: If True, use IntentClassifier for semantic matching (Phase 2A)
                     If False, use simple keyword matching (Phase 1)
    
    Returns:
        Skill name if a trigger matches, None otherwise.
    
    Phase 1: Simple keyword matching
    Phase 2A: Enhanced with semantic similarity using llama-server embedding model
    """
    if not user_input or not lazy_skills_meta:
        return None
    
    # Phase 1: Keyword matching (fast path)
    for skill_name, meta in lazy_skills_meta.items():
        triggers = meta.get("triggers", [])
        for trigger in triggers:
            if trigger in user_input:
                logger.debug(
                    "Lazy skill trigger matched (keyword): '%s' in '%s' -> skill '%s'",
                    trigger,
                    user_input[:50],
                    skill_name,
                )
                return skill_name
    
    # Phase 2A: Semantic matching (if enabled)
    if use_semantic:
        try:
            from .intent_classifier import get_intent_classifier
            
            classifier = get_intent_classifier()
            
            # Register all lazy skills with their triggers
            for skill_name, meta in lazy_skills_meta.items():
                triggers = meta.get("triggers", [])
                if triggers:  # Only register if has triggers
                    # Get or create existing registration
                    existing = getattr(classifier, '_skill_triggers', {})
                    if skill_name not in existing:
                        classifier.register_skill(skill_name, triggers)
            
            # Classify user input
            matched_skill, score = classifier.classify(user_input)
            
            if matched_skill:
                logger.info(
                    "Lazy skill trigger matched (semantic): score=%.2f -> skill '%s'",
                    score,
                    matched_skill,
                )
                return matched_skill
        
        except Exception as exc:
            logger.debug(
                "Semantic matching failed, falling back to keyword match: %s",
                exc,
            )
    
    return None


def load_skill_content(
    workspace_dir: Path,
    skill_name: str,
) -> str:
    """Load full SKILL.md content for a lazy skill on-demand.
    
    Args:
        workspace_dir: Workspace directory path
        skill_name: Name of the skill to load
    
    Returns:
        Full SKILL.md content as string
    
    Raises:
        SkillsError: If skill directory or SKILL.md not found
    
    New in Phase 1: Dynamic Skill Loading
    This function is called when a lazy skill's trigger is detected,
    or when the user explicitly requests to load a skill via /load command.
    """
    skill_dir = get_workspace_skills_dir(workspace_dir) / skill_name
    if not skill_dir.exists():
        # Fallback: check pool directories (including external skill_paths)
        pool_dir = resolve_pool_skill_dir(skill_name)
        if pool_dir is not None:
            skill_dir = pool_dir
        else:
            raise SkillsError(
                message=f"Skill directory not found: '{skill_name}' at {skill_dir}"
            )
    
    skill_md_path = skill_dir / "SKILL.md"
    if not skill_md_path.exists():
        raise SkillsError(
            message=f"SKILL.md not found for skill '{skill_name}'"
        )
    
    try:
        content = read_text_file_with_encoding_fallback(skill_md_path)
        logger.info(
            "Loaded lazy skill content: '%s' (%d bytes)",
            skill_name,
            len(content),
        )
        return content
    except Exception as exc:
        logger.error(
            "Failed to load skill content for '%s': %s",
            skill_name,
            exc,
        )
        raise SkillsError(
            message=f"Failed to read SKILL.md for skill '{skill_name}': {exc}"
        )


def ensure_skills_initialized(workspace_dir: Path) -> None:
    """Ensure workspace manifests exist before runtime use."""
    reconcile_workspace_manifest(workspace_dir)


# ---------------------------------------------------------------------------
# Builtin sync status + update notices
# ---------------------------------------------------------------------------


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
        manifest = read_json(
            get_pool_skill_manifest_path(),
            default_pool_manifest(),
        )
        pool_skills = manifest.get("skills", {})
    result: dict[str, dict[str, Any]] = {}
    for name, variants in registry.items():
        pool_entry = pool_skills.get(name)
        if pool_entry is None or not is_pool_builtin_entry(pool_entry):
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
        if not is_pool_builtin_entry(pool_entry):
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
    manifest = read_json(
        get_pool_skill_manifest_path(),
        default_pool_manifest(),
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
    if existing is None or not is_pool_builtin_entry(existing):
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
        copy_skill_dir(variant.skill_dir, target)
        payload.setdefault("skills", {})
        entry = build_skill_metadata(
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
        for au_key in (
            "auto_update",
            "auto_update_targets",
            "auto_update_synced_hash",
        ):
            if au_key in current:
                entry[au_key] = current.get(au_key)
        payload["skills"][canonical_name] = entry
        return entry

    return mutate_json(
        get_pool_skill_manifest_path(),
        default_pool_manifest(),
        _update,
    )
