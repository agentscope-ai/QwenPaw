# -*- coding: utf-8 -*-
# ChannelManager is provided by __getattr__ (lazy-loaded).
# pylint: disable=undefined-all-variable
__all__ = ["ChannelManager"]


def __getattr__(name: str):
    """Lazy-load ChannelManager to avoid pulling feishu/lark_oapi on CLI."""
    if name == "ChannelManager":
        from .manager import ChannelManager

        return ChannelManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
