# -*- coding: utf-8 -*-
"""Constrained translation for user-authored Qoder Skill-only plugins."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .compatibility_safety import bounded_plain_text
from .models import SourcePlugin
from .skill_transfer import (
    read_bounded_tree,
    read_regular_file,
    write_tree_entry,
)

_MAX_MANIFEST_BYTES = 1024 * 1024
_PLUGIN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_QODER_NATIVE_PLUGIN_FEATURES = {
    "agents",
    "canvas",
    "commands",
    "hooks",
    "mcp",
    "mcpServers",
    "tools",
}
_QODER_BINDING_MARKERS = (
    b".qoder",
    b"qoder_",
    b"qoder-",
    b"sharedclientcache",
)


def _has_skill_directory(root: Path) -> bool:
    if not root.is_dir() or root.is_symlink():
        return False
    if (root / "SKILL.md").is_file():
        return True
    try:
        children = root.iterdir()
    except OSError:
        return False
    for child in children:
        if not child.is_dir() or child.is_symlink():
            continue
        if (child / "SKILL.md").is_file():
            return True
    return False


def _contains_qoder_bindings(skills_root: Path) -> bool:
    for entry in read_bounded_tree(skills_root):
        if entry.is_dir or len(entry.data or b"") > 2 * 1024 * 1024:
            continue
        if any(
            marker in (entry.data or b"").lower()
            for marker in _QODER_BINDING_MARKERS
        ):
            return True
    return False


# pylint: disable-next=too-many-return-statements,too-many-branches
def discover_qoder_custom_skill_adapter(
    qoder_home: Path,
    install_path: Path | None,
    manifest: Any,
    record: dict[str, Any],
    plugin_id: str = "",
) -> dict[str, Any] | None:
    """Describe a bounded Qoder Skill-only plugin translation."""
    if install_path is None or not isinstance(manifest, dict):
        return None
    try:
        source = install_path.resolve(strict=True)
    except OSError:
        return None
    if install_path.is_symlink() or not source.is_dir():
        return None
    source_kind = str(record.get("source") or "")
    plugin_name = marketplace = ""
    if "@" in plugin_id:
        plugin_name, marketplace = plugin_id.rsplit("@", 1)
    custom_root = qoder_home / "plugins" / "custom"
    if source_kind == "custom" or (
        source_kind == "" and marketplace in {"", "local-custom"}
    ):
        try:
            if not source.is_relative_to(custom_root.resolve(strict=True)):
                return None
        except OSError:
            return None
        source_kind = "custom"
    elif source_kind in {"", "marketplace"} and marketplace:
        source_kind = "marketplace"
        cache = qoder_home / "plugins" / "cache" / marketplace / plugin_name
        version = str(record.get("version") or "")
        candidates = [cache]
        if version:
            candidates.insert(0, cache / version)
        try:
            if source not in {
                candidate.resolve(strict=True) for candidate in candidates
            }:
                return None
        except OSError:
            return None
        if str(manifest.get("name") or "") != plugin_name:
            return None
        manifest_version = str(manifest.get("version") or "")
        if version and manifest_version and version != manifest_version:
            return None
    else:
        return None
    skills_value = manifest.get("skills")
    if not isinstance(skills_value, str) or not skills_value.strip():
        return None
    try:
        skills_root = (source / skills_value).resolve(strict=True)
    except OSError:
        return None
    if (
        not skills_root.is_dir()
        or not skills_root.is_relative_to(source)
        or not _has_skill_directory(skills_root)
    ):
        return None
    if any(manifest.get(key) for key in _QODER_NATIVE_PLUGIN_FEATURES):
        return None
    try:
        _validate_source_tree(source)
        harness_bound = _contains_qoder_bindings(skills_root)
    except (OSError, ValueError):
        return None
    return {
        "adapter": "qoder_skill_only_v1",
        "canonical_plugin_source": str(source),
        "qoder_source_kind": source_kind,
        "skills_relative_path": str(skills_root.relative_to(source)),
        "harness_bound": harness_bound,
        # Compatibility is not activation authorization.  The generated
        # QwenPaw wrapper keeps even binding-free source Skills disabled until
        # the user explicitly reviews them.
        "skills_enabled_by_default": False,
    }


def _validated_source(plugin: SourcePlugin) -> Path:
    source = Path(plugin.install_source).expanduser()
    canonical_raw = str(plugin.metadata.get("canonical_plugin_source") or "")
    if source.is_symlink():
        raise ValueError("Qoder custom plugin source is symbolic")
    source = source.resolve(strict=True)
    if not source.is_dir():
        raise ValueError("Qoder plugin source is unavailable")
    if canonical_raw:
        valid = source == Path(canonical_raw).expanduser().resolve(strict=True)
    else:
        custom_root = str(plugin.metadata.get("canonical_custom_root") or "")
        if not custom_root:
            raise ValueError("Qoder plugin provenance is missing")
        valid = source.is_relative_to(
            Path(custom_root).expanduser().resolve(strict=True),
        )
    if not valid:
        raise ValueError("Qoder plugin source changed after discovery")
    return source


def _read_qoder_manifest(source: Path) -> dict[str, Any]:
    path = source / ".qoder-plugin" / "plugin.json"
    try:
        encoded = read_regular_file(path, max_bytes=_MAX_MANIFEST_BYTES)
    except ValueError as exc:
        if "byte safety limit" in str(exc):
            raise ValueError(
                "Qoder custom plugin manifest exceeds 1 MiB",
            ) from exc
        raise ValueError(
            "Qoder custom plugin manifest is unavailable",
        ) from exc
    except OSError as exc:
        raise ValueError(
            "Qoder custom plugin manifest is unavailable",
        ) from exc
    manifest = json.loads(encoded.decode("utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("Qoder custom plugin manifest is invalid")
    if any(manifest.get(key) for key in _QODER_NATIVE_PLUGIN_FEATURES):
        raise ValueError(
            "Qoder-native tools/hooks/MCP/commands cannot be auto-adapted",
        )
    return manifest


def _validated_skills_root(
    source: Path,
    manifest: dict[str, Any],
) -> Path:
    raw = manifest.get("skills")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("Qoder custom plugin has no Skill-only source")
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Qoder custom plugin Skills path is unsafe")
    root = (source / relative).resolve(strict=True)
    if not root.is_dir() or not root.is_relative_to(source):
        raise ValueError("Qoder custom plugin Skills path escaped its source")
    if not _has_skill_directory(root):
        raise ValueError("Qoder custom plugin contains no usable Skills")
    return root


def _validate_source_tree(source: Path) -> None:
    for _entry in read_bounded_tree(source):
        pass


def _copy_skill_tree(source: Path, target: Path) -> None:
    """Copy only verified regular files into the generated wrapper."""
    target.mkdir(mode=0o700)
    for entry in read_bounded_tree(source):
        write_tree_entry(target, entry)


def _copy_optional_readme(source: Path, target: Path) -> None:
    """Copy one optional README through the same no-follow boundary."""
    try:
        data = read_regular_file(source)
    except FileNotFoundError:
        return
    target.write_bytes(data)
    target.chmod(0o600)


def _plugin_backend() -> str:
    return (
        "# -*- coding: utf-8 -*-\n"
        '"""Generated adapter for a Qoder Skill-only plugin."""\n\n'
        "from pathlib import Path\n\n"
        "_ROOT = Path(__file__).parent\n\n\n"
        "class ImportedQoderSkillPlugin:\n"
        "    def register(self, api) -> None:\n"
        "        api.register_skill_provider(\n"
        '            skills_dir=_ROOT / "skills",\n'
        "            enabled_by_default=False,\n"
        '            channels=["all"],\n'
        "        )\n\n\n"
        "plugin = ImportedQoderSkillPlugin()\n"
    )


def _author(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("name") or value.get("email") or ""
    return bounded_plain_text(value or "Imported from Qoder", 200)


def _qwenpaw_manifest(
    plugin: SourcePlugin,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    plugin_id = bounded_plain_text(
        manifest.get("name") or plugin.name,
        128,
    )
    if not _PLUGIN_ID_RE.fullmatch(plugin_id):
        raise ValueError("Qoder custom plugin name is unsafe")
    descriptions = {}
    description_zh = manifest.get("descriptionZh")
    if isinstance(description_zh, str) and description_zh.strip():
        descriptions["zh-CN"] = bounded_plain_text(description_zh, 4096)
    return {
        "id": plugin_id,
        "name": bounded_plain_text(
            manifest.get("displayName") or plugin_id,
            200,
        ),
        "version": bounded_plain_text(
            manifest.get("version") or plugin.version or "0.0.0",
            100,
        ),
        "type": "general",
        "description": bounded_plain_text(
            manifest.get("description"),
            4096,
        ),
        "description_i18n": descriptions,
        "author": _author(manifest.get("author")),
        "entry": {"backend": "plugin.py"},
        "dependencies": [],
        "meta": {
            "migration": {
                "source": "qoder",
                "source_id": plugin.source_id,
                "adapter": "qoder_skill_only_v1",
                "harness_bound": bool(plugin.metadata.get("harness_bound")),
                "requires_review": True,
            },
        },
    }


def stage_qoder_skill_plugin(plugin: SourcePlugin) -> Path:
    """Build a review-safe QwenPaw wrapper for a Qoder Skill-only plugin."""
    source = _validated_source(plugin)
    manifest = _read_qoder_manifest(source)
    skills_root = _validated_skills_root(source, manifest)
    _validate_source_tree(source)
    temp_root = Path(tempfile.mkdtemp(prefix="qwenpaw-qoder-plugin-"))
    target = temp_root / "plugin"
    try:
        target.mkdir()
        _copy_skill_tree(skills_root, target / "skills")
        _copy_optional_readme(
            source / "README.md",
            target / "README.qoder.md",
        )
        (target / "plugin.py").write_text(
            _plugin_backend(),
            encoding="utf-8",
        )
        (target / "plugin.json").write_text(
            json.dumps(
                _qwenpaw_manifest(plugin, manifest),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return target
    except BaseException:
        shutil.rmtree(temp_root, ignore_errors=True)
        raise


__all__ = [
    "discover_qoder_custom_skill_adapter",
    "stage_qoder_skill_plugin",
]
