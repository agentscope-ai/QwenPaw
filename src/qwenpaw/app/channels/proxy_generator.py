from __future__ import annotations

import logging
from pathlib import Path

from qwenpaw.constant import CUSTOM_CHANNELS_DIR

logger = logging.getLogger(__name__)

CHANNEL_CLASS_MAP: dict[str, tuple[str, str]] = {
    "imessage": ("qwenpaw.app.channels.imessage", "IMessageChannel"),
    "discord": ("qwenpaw.app.channels.discord_", "DiscordChannel"),
    "dingtalk": ("qwenpaw.app.channels.dingtalk", "DingTalkChannel"),
    "feishu": ("qwenpaw.app.channels.feishu", "FeishuChannel"),
    "qq": ("qwenpaw.app.channels.qq", "QQChannel"),
    "telegram": ("qwenpaw.app.channels.telegram", "TelegramChannel"),
    "mattermost": ("qwenpaw.app.channels.mattermost", "MattermostChannel"),
    "mqtt": ("qwenpaw.app.channels.mqtt", "MQTTChannel"),
    "matrix": ("qwenpaw.app.channels.matrix", "MatrixChannel"),
    "voice": ("qwenpaw.app.channels.voice", "VoiceChannel"),
    "sip": ("qwenpaw.app.channels.sip", "SIPChannel"),
    "wecom": ("qwenpaw.app.channels.wecom", "WecomChannel"),
    "xiaoyi": ("qwenpaw.app.channels.xiaoyi", "XiaoYiChannel"),
    "weixin": ("qwenpaw.app.channels.weixin", "WeixinChannel"),
    "onebot": ("qwenpaw.app.channels.onebot", "OneBotChannel"),
}

_TEMPLATE = """\
from {module} import {cls}


class ProxyChannel({cls}):
    channel = {key!r}
"""


def generate_proxy(source_key: str, new_key: str) -> Path:
    if source_key not in CHANNEL_CLASS_MAP:
        raise ValueError(
            f"Cannot duplicate channel '{source_key}': "
            f"not in CHANNEL_CLASS_MAP",
        )
    module, cls = CHANNEL_CLASS_MAP[source_key]
    CUSTOM_CHANNELS_DIR.mkdir(parents=True, exist_ok=True)
    path = CUSTOM_CHANNELS_DIR / f"{new_key}.py"
    path.write_text(_TEMPLATE.format(module=module, cls=cls, key=new_key), encoding="utf-8")
    logger.info("Generated proxy channel file: %s", path)
    return path


def list_proxy_keys() -> list[str]:
    if not CUSTOM_CHANNELS_DIR.exists():
        return []
    return sorted(
        p.stem for p in CUSTOM_CHANNELS_DIR.glob("*.py") if p.stem != "__init__"
    )


def delete_proxy(key: str) -> bool:
    path = CUSTOM_CHANNELS_DIR / f"{key}.py"
    if path.exists():
        path.unlink()
        logger.info("Deleted proxy channel file: %s", path)
        return True
    return False
