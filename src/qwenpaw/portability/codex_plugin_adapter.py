# -*- coding: utf-8 -*-
"""Translate a staged Codex content bundle into a QwenPaw plugin."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .compatibility_safety import bounded_plain_text
from .models import SourcePlugin
from .skill_transfer import read_bounded_tree, write_tree_entry

ADAPTER = "codex_content_bundle_v1"
_PLUGIN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SOURCE_MANIFESTS = (
    Path(".codex-plugin/plugin.json"),
    Path(".claude-plugin/plugin.json"),
)
_ROOT_CONFLICTS = {
    Path("plugin.json"),
    Path("plugin.py"),
    Path("requirements.txt"),
}


def _manifest(source: Path) -> tuple[dict[str, Any], Path]:
    relative = next(
        (item for item in _SOURCE_MANIFESTS if (source / item).is_file()),
        _SOURCE_MANIFESTS[0],
    )
    path = source / relative
    if (
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_size > 1024 * 1024
    ):
        raise ValueError("Codex plugin manifest is unavailable or too large")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Codex plugin manifest is invalid")
    return value, relative


def _skill_paths(source: Path, manifest: dict[str, Any]) -> list[Path]:
    declared = manifest.get("skills")
    values = [declared] if isinstance(declared, str) else declared
    if not isinstance(values, list):
        values = ["skills"] if (source / "skills").is_dir() else []
    paths: list[Path] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        relative = Path(value)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Codex plugin Skills path is unsafe")
        path = (source / relative).resolve(strict=True)
        if not path.is_dir() or not path.is_relative_to(source):
            raise ValueError("Codex plugin Skills path escaped its source")
        if path not in paths:
            paths.append(path)
    return paths


def _backend(skill_paths: list[Path], root: Path) -> str:
    calls = []
    for path in skill_paths:
        relative = path.relative_to(root).as_posix()
        calls.append(
            "        api.register_skill_provider(\n"
            f"            skills_dir=_ROOT / {relative!r},\n"
            "            enabled_by_default=False,\n"
            '            channels=["all"],\n'
            "        )",
        )
    body = "\n".join(calls) or "        return None"
    return (
        "# -*- coding: utf-8 -*-\n"
        '"""Generated adapter for a Codex content plugin."""\n\n'
        "from pathlib import Path\n\n"
        "_ROOT = Path(__file__).parent\n\n\n"
        "class ImportedCodexContentPlugin:\n"
        "    def register(self, api) -> None:\n"
        f"{body}\n\n\n"
        "plugin = ImportedCodexContentPlugin()\n"
    )


def _qwenpaw_manifest(
    plugin: SourcePlugin,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    plugin_id = bounded_plain_text(manifest.get("name") or plugin.name, 128)
    if not _PLUGIN_ID_RE.fullmatch(plugin_id):
        raise ValueError("Codex plugin name is unsafe")
    interface = manifest.get("interface")
    display_name = (
        interface.get("displayName") if isinstance(interface, dict) else ""
    )
    author = manifest.get("author")
    if isinstance(author, dict):
        author = author.get("name") or author.get("email")
    return {
        "id": plugin_id,
        "name": bounded_plain_text(
            display_name or plugin.name or plugin_id,
            200,
        ),
        "version": bounded_plain_text(
            manifest.get("version") or plugin.version or "0.0.0",
            100,
        ),
        "type": "general",
        "description": bounded_plain_text(manifest.get("description"), 4096),
        "author": bounded_plain_text(author or "Imported from Codex", 200),
        "entry": {"backend": "plugin.py"},
        "dependencies": [],
        "meta": {
            "migration": {
                "source": "codex",
                "source_id": plugin.source_id,
                "adapter": ADAPTER,
                "requires_review": True,
            },
        },
    }


def stage_codex_content_plugin(plugin: SourcePlugin) -> Path:
    """Build a native wrapper from an isolated Codex plugin snapshot."""
    source = Path(plugin.install_source).expanduser()
    if source.is_symlink():
        raise ValueError("Codex plugin source is symbolic")
    source = source.resolve(strict=True)
    manifest, source_manifest = _manifest(source)
    skills = _skill_paths(source, manifest)
    if not skills and not manifest.get("mcpServers"):
        raise ValueError("Codex plugin has no portable Skills or MCP servers")

    temp_root = Path(tempfile.mkdtemp(prefix="qwenpaw-codex-plugin-"))
    target = temp_root / "plugin"
    try:
        target.mkdir(mode=0o700)
        for entry in read_bounded_tree(
            source,
            required_file=str(source_manifest),
        ):
            if entry.relative in _ROOT_CONFLICTS:
                continue
            write_tree_entry(target, entry)
        (target / "plugin.py").write_text(
            _backend(skills, source),
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


__all__ = ["ADAPTER", "stage_codex_content_plugin"]
