# -*- coding: utf-8 -*-
"""Read installed plugin sources without constructing execution services.

Discovery honors persisted uninstall intent. Recovery can also inspect leftover
sources. Consumers apply enabled settings and host-version policy. One invalid
source produces a diagnostic while its peers remain discoverable.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from .architecture import PluginManifest
from .sdk_version import validate_sdk
from .settings import read_plugin_intent

logger = logging.getLogger(__name__)
PAWPORT_MARKER = ".qwenpaw-pawport.json"


@dataclass(frozen=True)
class DiscoveryIssue:
    """One source whose manifest could not be read or accepted."""

    source_path: Path
    message: str


@dataclass(frozen=True)
class DiscoveryResult:
    """A fresh directory scan, preserving source order and diagnostics."""

    plugins: tuple[tuple[PluginManifest, Path], ...]
    issues: tuple[DiscoveryIssue, ...]


def is_disabled_plugin_dir(path: Path) -> bool:
    """Exclude hidden, renamed-disabled and uncommitted PawPort sources."""
    if path.name.startswith(".") or path.name.endswith(".disabled"):
        return True
    try:
        marker = json.loads((path / PAWPORT_MARKER).read_text())
    except (OSError, ValueError, TypeError):
        return False
    return isinstance(marker, dict) and marker.get("state") == "prepared"


def read_manifest(manifest_path: Path) -> PluginManifest:
    """Parse a manifest and reject unsupported SDKs before executing code.

    File, JSON, manifest-validation and SDK-compatibility errors propagate to
    the caller. Host-version eligibility remains a separate admission check.
    """
    with manifest_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, dict):
        validate_sdk(data.get("sdk"), data.get("id"))
    return PluginManifest.from_dict(data)


def discover_plugins(
    plugin_dirs: Iterable[Path],
    load_manifest: Callable[[Path], PluginManifest] = read_manifest,
    include_uninstalled: bool = False,
) -> DiscoveryResult:
    """Scan direct children using the host's installed-source conventions.

    The optional reader preserves Loader's manifest override point. Scans do
    not cache results: installing, removing or renaming a source is visible
    to the next consumer. No entry module or requirements file is executed.
    """
    plugins = []
    issues = []
    plugin_dirs = tuple(plugin_dirs)
    for directory in plugin_dirs:
        directory = Path(directory)
        try:
            if not directory.exists():
                logger.debug("Plugin directory not found: %s", directory)
                continue
            sources = tuple(directory.iterdir())
        except OSError as exc:
            issues.append(DiscoveryIssue(directory, str(exc)))
            logger.error("Cannot scan plugin directory %s: %s", directory, exc)
            continue
        logger.info("Scanning plugin directory: %s", directory)
        for source in sources:
            try:
                if not source.is_dir():
                    continue
                if is_disabled_plugin_dir(source):
                    logger.info(
                        "Skipping disabled/hidden plugin directory: %s",
                        source.name,
                    )
                    continue
                manifest_path = source / "plugin.json"
                if not manifest_path.exists():
                    continue
                manifest = load_manifest(manifest_path)
                if not include_uninstalled and read_plugin_intent(
                    manifest.id,
                    plugins_dir=plugin_dirs[0],
                ):
                    continue
            except Exception as exc:  # noqa: BLE001
                issues.append(DiscoveryIssue(source, str(exc)))
                logger.error(
                    "Cannot discover plugin source %s: %s",
                    source,
                    exc,
                    exc_info=True,
                )
                continue
            plugins.append((manifest, source))
            logger.info("Discovered plugin: %s", manifest.id)
    return DiscoveryResult(tuple(plugins), tuple(issues))
