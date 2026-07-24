# -*- coding: utf-8 -*-
"""Static metadata for built-in channels."""

from __future__ import annotations

from dataclasses import dataclass
import sys


@dataclass(frozen=True)
class ChannelSpec:
    key: str
    module: str
    class_name: str
    extra: str | None = None
    platforms: frozenset[str] | None = None

    @property
    def platform_supported(self) -> bool:
        return self.platforms is None or sys.platform in self.platforms


BUILTIN_CHANNEL_SPECS: tuple[ChannelSpec, ...] = (
    ChannelSpec(
        "imessage",
        ".imessage",
        "IMessageChannel",
        platforms=frozenset({"darwin"}),
    ),
    ChannelSpec("discord", ".discord_", "DiscordChannel", "channel-discord"),
    ChannelSpec("dingtalk", ".dingtalk", "DingTalkChannel"),
    ChannelSpec("feishu", ".feishu", "FeishuChannel", "channel-feishu"),
    ChannelSpec("qq", ".qq", "QQChannel", "channel-qq"),
    ChannelSpec("telegram", ".telegram", "TelegramChannel"),
    ChannelSpec(
        "mattermost",
        ".mattermost",
        "MattermostChannel",
        "channel-mattermost",
    ),
    ChannelSpec("mqtt", ".mqtt", "MQTTChannel", "channel-mqtt"),
    ChannelSpec("console", ".console", "ConsoleChannel"),
    ChannelSpec("matrix", ".matrix", "MatrixChannel", "channel-matrix"),
    ChannelSpec("slack", ".slack", "SlackChannel", "channel-slack"),
    ChannelSpec("voice", ".voice", "VoiceChannel", "channel-voice"),
    ChannelSpec("sip", ".sip", "SIPChannel", "channel-sip"),
    ChannelSpec("wecom", ".wecom", "WecomChannel", "channel-wecom"),
    ChannelSpec("xiaoyi", ".xiaoyi", "XiaoYiChannel"),
    ChannelSpec("yuanbao", ".yuanbao", "YuanbaoChannel", "channel-yuanbao"),
    ChannelSpec("wechat", ".wechat", "WeChatChannel", "channel-wechat"),
    ChannelSpec("onebot", ".onebot", "OneBotChannel"),
)

BUILTIN_CHANNEL_CATALOG = {spec.key: spec for spec in BUILTIN_CHANNEL_SPECS}
