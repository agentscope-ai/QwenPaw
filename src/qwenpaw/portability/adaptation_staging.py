# -*- coding: utf-8 -*-
"""Safe local snapshots and component inventories for adaptation."""

from __future__ import annotations

import re
import secrets
import shutil
from pathlib import Path
from typing import Any

from .compatibility import AssetType
from .codex_plugin_adapter import ADAPTER as CODEX_PLUGIN_ADAPTER
from .compatibility_testing import discover_components
from .models import ProviderInventory
from .skill_transfer import copy_bounded_tree

_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _target(root: Path, name: str, fallback: str) -> Path:
    slug = _SLUG_RE.sub("-", name).strip(".-")[:48] or fallback
    target, suffix = root / slug, 1
    while target.exists():
        suffix += 1
        target = root / f"{slug}-{suffix}"
    return target


def stage_local_assets(inventory: ProviderInventory, root: Path) -> list[str]:
    """Copy local Skill and plugin inputs into the private staging tree."""
    warnings: list[str] = []
    skills_root, plugins_root = root / "skills", root / "plugins"
    skills_root.mkdir(parents=True, mode=0o700, exist_ok=True)
    plugins_root.mkdir(parents=True, mode=0o700, exist_ok=True)
    for index, skill in enumerate(inventory.skills, start=1):
        source = Path(skill.directory)
        target = _target(skills_root, skill.name, f"skill-{index}")
        skill.directory = target
        try:
            copy_bounded_tree(source, target, required_file="SKILL.md")
        except Exception as exc:  # pylint: disable=broad-except
            shutil.rmtree(target, ignore_errors=True)
            skill.directory = skills_root / f".failed-{secrets.token_hex(12)}"
            warnings.append(
                f"Skill {skill.name!r} 无法进入安全暂存区："
                f"{type(exc).__name__}: {exc}",
            )

    for index, plugin in enumerate(inventory.plugins, start=1):
        source_text = str(
            plugin.install_source or plugin.metadata.get("install_path") or "",
        )
        if not source_text or source_text.startswith(("http://", "https://")):
            continue
        source = Path(source_text).expanduser()
        target = _target(plugins_root, plugin.name, f"plugin-{index}")
        plugin.install_source = str(target)
        try:
            required = "plugin.json"
            for candidate in (
                ".qoder-plugin/plugin.json",
                ".codex-plugin/plugin.json",
                ".claude-plugin/plugin.json",
            ):
                if (source / candidate).is_file():
                    required = candidate
                    break
            copy_bounded_tree(source, target, required_file=required)
            if plugin.metadata.get("adapter") in {
                "qoder_skill_only_v1",
                CODEX_PLUGIN_ADAPTER,
            }:
                plugin.metadata["canonical_plugin_source"] = str(
                    target.resolve(),
                )
        except Exception as exc:  # pylint: disable=broad-except
            shutil.rmtree(target, ignore_errors=True)
            plugin.install_source = str(
                plugins_root / f".failed-{secrets.token_hex(12)}",
            )
            warnings.append(
                f"Plugin {plugin.name!r} 无法进入安全暂存区："
                f"{type(exc).__name__}: {exc}",
            )
    return warnings


def component_map(inventory: ProviderInventory) -> dict[str, list[Any]]:
    result: dict[str, list[Any]] = {}
    for asset_type, values in (
        (AssetType.SKILL, inventory.skills),
        (AssetType.PLUGIN, inventory.plugins),
    ):
        for value in values:
            key = f"{asset_type.value}:{value.source_id}"
            result[key] = discover_components(asset_type, value)
    return result


__all__ = ["component_map", "stage_local_assets"]
