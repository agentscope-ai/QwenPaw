# -*- coding: utf-8 -*-
"""Build bounded reading checklists for external Skills and plugins."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .compatibility import AssetType, PluginComponent
from .skill_transfer import read_bounded_tree

ADAPTATION_TEXT_SUFFIXES = {
    "",
    ".bash",
    ".cjs",
    ".js",
    ".json",
    ".jsonc",
    ".jsx",
    ".md",
    ".mjs",
    ".ps1",
    ".py",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
    ".zsh",
}
_IGNORED_PARTS = frozenset(
    {
        ".git",
        "__MACOSX",
        "__pycache__",
        "assets",
        "build",
        "dist",
        "node_modules",
        "tests",
        "vendor",
    },
)
_MANIFEST_DIRS = {".qoder-plugin", ".claude-plugin", ".codex-plugin"}


def _text_files(root: Path) -> list[str]:
    return sorted(
        entry.relative.as_posix()
        for entry in read_bounded_tree(
            root,
            excluded_dirs=_IGNORED_PARTS,
            reject_unsafe=False,
        )
        if not entry.is_dir
        and entry.relative.name != ".DS_Store"
        and not entry.relative.name.startswith("._")
        and entry.relative.suffix.lower() in ADAPTATION_TEXT_SUFFIXES
    )


def _component(component_id: str, kind: str, paths: list[str]):
    return PluginComponent(
        component_id=component_id,
        kind=kind,
        paths=sorted(set(paths)),
    )


def _in_component_dir(path: str, *names: str) -> bool:
    parts = Path(path).parts
    if parts and parts[0] in _MANIFEST_DIRS:
        parts = parts[1:]
    return bool(parts and parts[0] in names)


def discover_components(
    asset_type: AssetType,
    value: Any,
) -> list[PluginComponent]:
    """Build a bounded reading checklist for Mission workers."""
    if asset_type is AssetType.SKILL:
        root = Path(value.directory)
        files = _text_files(root) if root.is_dir() else []
        return [_component("skill:root", "skill", files)] if files else []
    if asset_type is not AssetType.PLUGIN:
        return []
    source = str(value.install_source or "")
    if not source or "://" in source or not Path(source).is_dir():
        return []
    root = Path(source)
    files = _text_files(root)
    used: set[str] = set()
    result: list[PluginComponent] = []

    def add(component_id: str, kind: str, paths: list[str]) -> None:
        selected = [
            path for path in paths if path in files and path not in used
        ]
        if selected:
            used.update(selected)
            result.append(_component(component_id, kind, selected))

    add(
        "manifest",
        "manifest",
        [
            path
            for path in files
            if path
            in {
                "plugin.json",
                ".qoder-plugin/plugin.json",
                ".claude-plugin/plugin.json",
                ".codex-plugin/plugin.json",
                "README.md",
                "UPSTREAM.md",
                "package.json",
                "pyproject.toml",
                "requirements.txt",
            }
        ],
    )
    for path in files:
        if _in_component_dir(path, "skills") and Path(path).name == "SKILL.md":
            skill_root = Path(path).parent
            add(
                f"skill:{path}",
                "skill",
                [
                    candidate
                    for candidate in files
                    if candidate == path
                    or Path(candidate).is_relative_to(skill_root / "scripts")
                ],
            )
        elif _in_component_dir(path, "commands"):
            add(f"command:{path}", "command", [path])
        elif _in_component_dir(path, "agents"):
            add(f"agent:{path}", "agent", [path])
        elif _in_component_dir(path, "rules"):
            add(f"rule:{path}", "rule", [path])
        elif _in_component_dir(path, "mcp", "mcps") or Path(path).name in {
            ".mcp.json",
            "mcp.json",
        }:
            add(f"mcp:{path}", "mcp", [path])
    add(
        "hooks",
        "hook",
        [path for path in files if _in_component_dir(path, "hooks")],
    )
    add(
        "runtime",
        "runtime",
        [
            path
            for path in files
            if path not in used
            and (
                len(Path(path).parts) == 1
                or Path(path).parts[0] in {"src", "backend", "frontend", "lib"}
            )
        ],
    )
    return result


__all__ = ["ADAPTATION_TEXT_SUFFIXES", "discover_components"]
