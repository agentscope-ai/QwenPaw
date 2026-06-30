# -*- coding: utf-8 -*-
"""Plugin–QwenPaw version compatibility check.

Semantics: left-closed, right-open interval  ``>=min, <max``.
When ``max`` is not specified, it is derived from ``min`` as
``{major}.{minor+1}.0`` (all patch versions of the same minor).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Tuple

from packaging.version import Version

if TYPE_CHECKING:
    from .plugins.architecture import PluginManifest

logger = logging.getLogger(__name__)


def _derive_exclusive_max(min_str: str) -> Version:
    """Derive exclusive upper bound from a min version string.

    '1.1.6' -> Version('1.2.0')
    """
    parts = min_str.split(".")
    major = int(parts[0])
    minor = int(parts[1]) if len(parts) > 1 else 0
    return Version(f"{major}.{minor + 1}.0")


def check_plugin_version_compat(
    manifest: "PluginManifest",
) -> Tuple[bool, str]:
    """Check whether a plugin is compatible with the running QwenPaw.

    Returns:
        (compatible, warning_message) — message is empty on success.
    """
    from .__version__ import __version__ as current_version_str

    current = Version(current_version_str)

    # Pre-release versions (e.g. 2.0.0b2) should be treated as their base
    # release for compatibility purposes — developers on a pre-release build
    # must be able to load plugins targeting the upcoming release.
    if current.pre is not None:
        current = Version(f"{current.major}.{current.minor}.{current.micro}")

    qv = manifest.qwenpaw_version
    if qv is not None:
        min_v = Version(qv.min)
        max_v = Version(qv.max) if qv.max else _derive_exclusive_max(qv.min)
    else:
        min_v = Version(manifest.min_version)
        max_v = (
            Version(manifest.max_version)
            if manifest.max_version
            else _derive_exclusive_max(manifest.min_version)
        )

    if current < min_v or current >= max_v:
        msg = f"requires QwenPaw >={min_v}, <{max_v}, current is {current}"
        return False, msg
    return True, ""
