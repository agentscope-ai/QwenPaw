# -*- coding: utf-8 -*-
"""Version preflight, deliberately independent of plugin imports."""

import re

from packaging.version import InvalidVersion, Version

from .errors import SDKCompatibilityError

SDK_VERSION = "1.0.0"
SDK_CAPABILITIES = frozenset(
    {
        "tools",
        "logging",
        "models",
        "resources",
        "storage",
        "messages",
        "config",
        "commands",
        "hooks",
        "prompts",
        "modes",
        "skills",
        "markets",
        "providers",
        "memory",
        "events",
        "apps",
        "channels",
    },
)


def validate_sdk(declaration, plugin_id=None):
    """Reject explicit incompatible declarations before loading plugin code."""
    if declaration is None:
        return
    if plugin_id is not None and not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_-]*",
        plugin_id,
    ):
        raise SDKCompatibilityError(
            "SDK plugin IDs must contain only letters, digits, underscores "
            "and hyphens",
        )
    if not isinstance(declaration, dict):
        raise SDKCompatibilityError(
            "sdk must contain version and capabilities",
        )
    try:
        requested = Version(declaration["version"])
    except (KeyError, TypeError, InvalidVersion) as exc:
        raise SDKCompatibilityError(
            "sdk.version must be a version string",
        ) from exc
    supported = Version(SDK_VERSION)
    if requested.major != supported.major or requested > supported:
        raise SDKCompatibilityError(f"Unsupported SDK version: {requested}")
    capabilities = declaration.get("capabilities", [])
    if not isinstance(capabilities, list) or not all(
        isinstance(x, str) for x in capabilities
    ):
        raise SDKCompatibilityError("sdk.capabilities must be a list of names")
    missing = set(capabilities) - SDK_CAPABILITIES
    if missing:
        raise SDKCompatibilityError(
            f"Unsupported SDK capabilities: {sorted(missing)}",
        )
    secrets = declaration.get("secrets", [])
    if not isinstance(secrets, list) or not all(
        isinstance(name, str) and name for name in secrets
    ):
        raise SDKCompatibilityError(
            "sdk.secrets must be a list of setting names",
        )
