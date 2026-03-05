# -*- coding: utf-8 -*-
"""Channel registry: built-in + custom channels from working dir."""
from __future__ import annotations

import importlib
import logging
import sys
from typing import TYPE_CHECKING

from ...constant import CUSTOM_CHANNELS_DIR
from .base import BaseChannel
from .console import ConsoleChannel
from .dingtalk import DingTalkChannel
from .discord_ import DiscordChannel
from .feishu import FeishuChannel
from .imessage import IMessageChannel
from .qq import QQChannel
from .telegram import TelegramChannel
from .voice import VoiceChannel

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_BUILTIN: dict[str, type[BaseChannel]] = {
    "imessage": IMessageChannel,
    "discord": DiscordChannel,
    "dingtalk": DingTalkChannel,
    "feishu": FeishuChannel,
    "qq": QQChannel,
    "telegram": TelegramChannel,
    "console": ConsoleChannel,
    "voice": VoiceChannel,
}


def _discover_custom_channels() -> dict[str, type[BaseChannel]]:
    """Load channel classes from CUSTOM_CHANNELS_DIR."""
    out: dict[str, type[BaseChannel]] = {}
    if not CUSTOM_CHANNELS_DIR.is_dir():
        return out

    dir_str = str(CUSTOM_CHANNELS_DIR)
    if dir_str not in sys.path:
        sys.path.insert(0, dir_str)

    for path in sorted(CUSTOM_CHANNELS_DIR.iterdir()):
        if path.suffix == ".py" and path.stem != "__init__":
            name = path.stem
        elif path.is_dir() and (path / "__init__.py").exists():
            name = path.name
        else:
            continue
        try:
            mod = importlib.import_module(name)
        except Exception:
            logger.exception("failed to load custom channel: %s", name)
            continue
        for obj in vars(mod).values():
            if (
                isinstance(obj, type)
                and issubclass(obj, BaseChannel)
                and obj is not BaseChannel
            ):
                key = getattr(obj, "channel", None)
                if key:
                    out[key] = obj
                    logger.debug("custom channel registered: %s", key)
    return out


BUILTIN_CHANNEL_KEYS = frozenset(_BUILTIN.keys())


def get_channel_registry() -> dict[str, type[BaseChannel]]:
    """Built-in channel classes + custom channels from custom_channels/."""
    out = dict(_BUILTIN)
    out.update(_discover_custom_channels())
    return out
