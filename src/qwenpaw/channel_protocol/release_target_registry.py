# -*- coding: utf-8 -*-
"""Versioned release target registry for Channel artifact validation."""

from __future__ import annotations


RELEASE_TARGET_REGISTRY_VERSION = 1
RELEASE_TARGET_PLATFORM_TAGS = frozenset(
    {
        "macosx_11_0_arm64",
        "manylinux_2_28_x86_64",
        "win_amd64",
    },
)
