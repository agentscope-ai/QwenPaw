# -*- coding: utf-8 -*-
"""Thin bridge from qwenpaw core into extension/skill_sign."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_EXTENSION_DIR = _REPO_ROOT / "extension"
if str(_EXTENSION_DIR) not in sys.path:
    sys.path.insert(0, str(_EXTENSION_DIR))

from skill_sign.host_bridge import (  # noqa: E402
    SIGNATURE_SCHEME,
    get_router,
    verify_skill_package,
    verify_skill_package_signature,
)


def get_skill_sign_router():
    """Return the FastAPI router owned by extension/skill_sign."""

    return get_router()


__all__ = [
    "SIGNATURE_SCHEME",
    "get_skill_sign_router",
    "get_router",
    "verify_skill_package",
    "verify_skill_package_signature",
]
