# -*- coding: utf-8 -*-
"""Passive metadata for the optional MCP resource; never load its code."""

import json
import logging
from pathlib import Path

from packaging.version import Version

from .architecture import PluginManifest
from .errors import SDKCompatibilityError
from .sdk_version import validate_sdk
from .._version_compat import check_plugin_version_compat

PLUGIN_ID = "qwenpaw-mcp"
BUNDLED_SOURCE = "bundled:" + PLUGIN_ID
logger = logging.getLogger(__name__)


def get_optional_mcp_plugin_dir():
    package = Path(__file__).resolve().parent
    bundled = package / "bundled/optional/mcp"
    return (
        bundled
        if bundled.is_dir()
        else package.parents[2] / "plugins/protocol/mcp"
    )


def read_mcp_manifest(directory):
    manifest = PluginManifest.from_dict(
        json.loads((directory / "plugin.json").read_text(encoding="utf-8")),
    )
    if manifest.id != PLUGIN_ID or manifest.plugin_type.value != "general":
        raise ValueError("Invalid optional MCP identity")
    capabilities = (manifest.sdk or {}).get("capabilities", [])
    if not isinstance(capabilities, list) or "drivers" not in capabilities:
        raise ValueError("Optional MCP must declare the Driver SDK")
    Version(manifest.version)
    return manifest


def mcp_plugin_versions(installed):
    """Read in a worker thread; version failures never change admission."""
    result = {"version": None, "update": None, "update_diagnostics": []}
    if installed is None:
        return result
    stage = "read installed manifest"
    try:
        current = read_mcp_manifest(installed)
        result["version"] = current.version
        stage = "read bundled manifest"
        target = read_mcp_manifest(get_optional_mcp_plugin_dir())
        stage = "check SDK compatibility"
        validate_sdk(target.sdk, PLUGIN_ID)
        stage = "check host compatibility"
        if not check_plugin_version_compat(target)[0]:
            raise ValueError("Incompatible optional MCP resource")
        if Version(target.version) > Version(current.version):
            result["update"] = {
                "installed_version": current.version,
                "version": target.version,
                "source": BUNDLED_SOURCE,
            }
    except (OSError, ValueError, TypeError, SDKCompatibilityError) as exc:
        logger.debug(
            "MCP version check could not %s (%s)",
            stage,
            type(exc).__name__,
        )
        result["update_diagnostics"] = ["version_check_unavailable"]
    return result
