# -*- coding: utf-8 -*-
"""Explicit offline preparation for saved, formerly built-in backends."""

from __future__ import annotations

import json
from contextlib import ExitStack
from pathlib import Path
import tempfile
import zipfile

from ..constant import CONFIG_FILE, PLUGINS_DIR, WORKING_DIR
from ..utils.io_utils import run_sync_io
from .dependency_gate import DependencyGate, combined_requirements
from .loader import PluginLoader

_LEGACY_PLUGINS = {
    "codex": "qwenpaw-harness-codex",
    "qoder": "qwenpaw-harness-qoder",
}


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _bundle_sources(plugin_dir: Path, needed: set[str], staging: Path):
    """Read only the supplied prepared-package tree; never import entries."""
    sources = {}

    def remember(source, manifest, bundle):
        plugin_id = manifest.get("id")
        if plugin_id not in needed:
            return
        if plugin_id in sources:
            raise ValueError(f"Multiple prepared packages for {plugin_id}")
        sources[plugin_id] = (source, bundle)

    for manifest_path in sorted(plugin_dir.rglob("plugin.json")):
        remember(
            manifest_path.parent,
            _read_json(manifest_path),
            manifest_path.parent,
        )
    for bundle in sorted(plugin_dir.rglob("*.zip")):
        with zipfile.ZipFile(bundle) as archive:
            manifests = [
                name
                for name in archive.namelist()
                if Path(name).name == "plugin.json"
                and len(Path(name).parts) <= 2
            ]
            if len(manifests) != 1:
                continue
            manifest = json.loads(archive.read(manifests[0]))
            if manifest.get("id") not in needed:
                continue
            destination = staging / str(len(sources))
            destination.mkdir()
            for name in archive.namelist():
                if (
                    not (destination / name)
                    .resolve()
                    .is_relative_to(
                        destination.resolve(),
                    )
                ):
                    raise ValueError(f"Unsafe prepared ZIP member: {name}")
            archive.extractall(destination)
            remember(
                (destination / manifests[0]).parent,
                manifest,
                bundle,
            )
    return sources


def _prepare(plugin_dir: Path, staging: Path, loader: PluginLoader):
    config = _read_json(WORKING_DIR / CONFIG_FILE)
    used: dict[str, list[str]] = {}
    for agent_id, profile in (
        config.get("agents", {})
        .get(
            "profiles",
            {},
        )
        .items()
    ):
        workspace = Path(profile["workspace_dir"]).expanduser()
        agent = _read_json(workspace / "agent.json")
        if plugin_id := _LEGACY_PLUGINS.get(agent.get("backend", "")):
            used.setdefault(plugin_id, []).append(agent_id)
    if not used:
        return {"plugins": []}, {}
    sources = _bundle_sources(plugin_dir, set(used), staging)
    rows = []
    for plugin_id, agents in sorted(used.items()):
        settings = config.get("plugins", {}).get(plugin_id, {})
        row = {
            "plugin_id": plugin_id,
            "agents": sorted(agents),
            "enabled": bool(settings.get("enabled", True)),
            "bundle": None,
            "version": None,
            "installed_version": None,
            "missing_dependencies": [],
            "action": "provide-package",
            "result": "not-applied",
        }
        installed = PLUGINS_DIR / plugin_id / "plugin.json"
        dependency_source = None
        if installed.is_file():
            _, manifest = loader.read_source_manifest(installed.parent)
            if manifest.id != plugin_id:
                raise ValueError(f"Installed plugin ID mismatch: {installed}")
            row["installed_version"] = manifest.version
            row["action"] = "keep-installed"
            dependency_source = installed.parent
        if plugin_id in sources:
            source, bundle = sources[plugin_id]
            _, manifest = loader.read_source_manifest(source)
            row["bundle"] = str(bundle)
            row["version"] = manifest.version
            if dependency_source is None:
                dependency_source = source
                row["action"] = "install"
        if dependency_source is not None:
            with combined_requirements(dependency_source) as requirements:
                decision = DependencyGate().evaluate(
                    requirements,
                    allow_install=False,
                    plugin_id=plugin_id,
                )
            row["missing_dependencies"] = decision.missing
            if decision.unsupported:
                raise ValueError(decision.reason)
            if decision.missing:
                row["action"] = "prepare-dependencies"
        rows.append(row)
    return {"plugins": rows}, sources


async def migrate_legacy_harnesses(
    plugin_dir: Path,
    *,
    apply: bool = False,
) -> dict:
    """Prepare using initialized working-dir constants; never activate code."""
    loader = PluginLoader([PLUGINS_DIR])
    cleanup = ExitStack()
    try:
        staging = Path(
            await run_sync_io(
                lambda: cleanup.enter_context(
                    tempfile.TemporaryDirectory(
                        prefix="qwenpaw-harness-migrate-",
                    ),
                ),
            ),
        )
        report, sources = await run_sync_io(
            _prepare,
            Path(plugin_dir),
            staging,
            loader,
        )
        if apply:
            for row in report["plugins"]:
                if row["action"] == "keep-installed":
                    row["result"] = "skipped"
                elif row["action"] == "install":
                    await loader.install_plugin_files(
                        sources[row["plugin_id"]][0],
                        allow_install=False,
                    )
                    row["result"] = "installed"
                else:
                    row["result"] = "not-prepared"
        return report
    finally:
        await run_sync_io(cleanup.close)
