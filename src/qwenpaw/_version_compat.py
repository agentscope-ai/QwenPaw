# -*- coding: utf-8 -*-
"""Plugin–QwenPaw version compatibility check.

Semantics: left-closed, right-open interval  ``>=min, <max``.
When ``max`` is not specified, no upper bound is enforced — the plugin
is considered compatible with any QwenPaw version that satisfies ``>=min``.
This follows the universal convention (pip, npm, cargo) where an
unspecified upper bound means no upper bound.
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

    .. deprecated::
        This function is retained for backward compatibility but no longer
        called by :func:`check_plugin_version_compat`.  An unspecified ``max``
        now means *no upper bound* instead of a derived exclusive bound.
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
        max_v = Version(qv.max) if qv.max else None
    else:
        min_v = Version(manifest.min_version)
        max_v = Version(manifest.max_version) if manifest.max_version else None

    if current < min_v or (max_v is not None and current >= max_v):
        upper = f", <{max_v}" if max_v is not None else ""
        msg = f"requires QwenPaw >={min_v}{upper}, current is {current}"
        return False, msg
    return True, ""
