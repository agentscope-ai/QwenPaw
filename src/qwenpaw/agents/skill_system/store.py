# -*- coding: utf-8 -*-
"""Local skill storage, manifest, metadata, and filesystem helpers."""

from __future__ import annotations

import io
import json
import logging
import os
import re
import shutil
import tempfile
import time
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, TypeVar

import frontmatter

from ...exceptions import SkillsError
from ...security.skill_scanner import scan_skill_directory
from ..utils.file_handling import read_text_file_with_encoding_fallback
from .models import SkillInfo, SkillRequirements

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

_RegistryResult = TypeVar("_RegistryResult")
_MAX_ZIP_BYTES = 200 * 1024 * 1024
_REQUIREMENTS_METADATA_NAMESPACES = ("openclaw", "qwenpaw", "clawdbot")


def _read_frontmatter_safe_from_path(
    skill_md_path: Path,
    skill_name: str = "",
) -> dict[str, Any]:
    if not skill_name:
        skill_name = skill_md_path.parent.name

    try:
        return frontmatter.loads(
            read_text_file_with_encoding_fallback(skill_md_path),
        )
    except Exception as e:
        logger.warning(
            "Failed to read SKILL frontmatter for '%s' at %s: %s. "
            "Using fallback values.",
            skill_name,
            skill_md_path,
            e,
        )
        return {"name": skill_name, "description": ""}


def get_skill_pool_dir() -> Path:
    """Return the local shared skill pool directory."""
    from ...constant import WORKING_DIR

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
        from ...config.config import load_agent_config

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
    return frontmatter.loads(
        read_text_file_with_encoding_fallback(skill_dir / "SKILL.md"),
    )


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


def _copy_skill_dir(source: Path, target: Path) -> None:
    """Replace *target* with a copy of *source*.

    We intentionally filter only well-known OS/cache artifacts so skill
    content behaves consistently on macOS, Windows, Linux, and Docker.
    User-authored dotfiles are preserved.
    """
    if target.exists():
        shutil.rmtree(target)

    def _ignore(_dir: str, names: list[str]) -> set[str]:
        return {name for name in names if name in _IGNORED_SKILL_ARTIFACTS}

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


def _normalize_skill_manifest_entry(entry: Any) -> dict[str, Any]:
    """Return a manifest entry as a dict, or an empty dict for legacy junk."""
    return entry if isinstance(entry, dict) else {}


def _is_builtin_skill(skill_name: str, builtin_names: list[str]) -> bool:
    """Check if skill name is in builtin list."""
    return skill_name in builtin_names


def _is_pool_builtin_entry(entry: dict[str, Any] | None) -> bool:
    """Return whether one pool manifest entry represents a builtin slot."""
    normalized = _normalize_skill_manifest_entry(entry)
    return (
        bool(normalized)
        and str(normalized.get("source", "") or "") == "builtin"
    )


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

    try:
        if isinstance(requires, list):
            return SkillRequirements(
                require_bins=list(requires),
                require_envs=[],
            )

        if not isinstance(requires, dict):
            return SkillRequirements()

        return SkillRequirements(
            require_bins=list(requires.get("bins", [])),
            require_envs=list(requires.get("env", [])),
        )
    except Exception as e:
        logger.warning(
            "Failed to parse skill requirements: %s. "
            "Falling back to empty requirements.",
            e,
        )
        return SkillRequirements()


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


@lru_cache(maxsize=256)
def _read_file_text_cached(  # pylint: disable=unused-argument
    path_str: str,
    mtime_ns: int,
) -> str:
    """Return file text cached by *path + mtime*."""
    return Path(path_str).read_text(encoding="utf-8")


def _read_json_mtime_cached(
    path: Path,
    default: dict[str, Any],
) -> dict[str, Any]:
    """``_read_json_unlocked`` variant with mtime cache."""
    if not path.exists():
        return json.loads(json.dumps(default))
    try:
        mtime_ns = os.stat(path).st_mtime_ns
        text = _read_file_text_cached(str(path), mtime_ns)
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Malformed JSON in %s, resetting to default", path)
        return json.loads(json.dumps(default))
    except OSError:
        return json.loads(json.dumps(default))


def read_skill_manifest(
    workspace_dir: Path,
) -> dict[str, Any]:
    """Return the workspace skill manifest, cached by file mtime."""
    path = get_workspace_skill_manifest_path(workspace_dir)
    return _read_json_mtime_cached(path, _default_workspace_manifest())


def read_skill_pool_manifest() -> dict[str, Any]:
    """Return the pool skill manifest, cached by file mtime."""
    path = get_pool_skill_manifest_path()
    return _read_json_mtime_cached(path, _default_pool_manifest())


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
