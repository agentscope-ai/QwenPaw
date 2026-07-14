# -*- coding: utf-8 -*-
"""Zalo Bot channel for QwenPaw 2.0 (polling only).

Registered as a plugin via ``api.register_channel()``. See
``zalo_plugin.py`` for the plugin entry point.
"""

from .channel import (
    ZaloChannel,
    get_channel,
    install,
)

__all__ = [
    "ZaloChannel",
    "install",
    "get_channel",
]
