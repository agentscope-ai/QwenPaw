# -*- coding: utf-8 -*-
"""Zalo Bot channel for QwenPaw (polling only).

Built-in channel. Registered via ``qwenpaw.app.channels.registry``.
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
