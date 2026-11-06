# -*- coding: utf-8 -*-
"""Delivered official channels, safe for host discovery and release builds.

Add a record only together with its descriptor, source and builtin retirement.
Channel routing identity, plugin ownership and source folder are independent.
"""

from __future__ import annotations

OFFICIAL_CHANNELS: tuple[dict[str, str], ...] = (
    {
        "channel_key": "telegram",
        "plugin_id": "telegram",
        "source_dir": "telegram",
        "icon": "",
        "doc_url": "https://qwenpaw.agentscope.io/docs/channels",
    },
    {
        "channel_key": "slack",
        "plugin_id": "slack",
        "source_dir": "slack",
        "icon": "",
        "doc_url": "https://qwenpaw.agentscope.io/docs/channels",
    },
    {
        "channel_key": "discord",
        "plugin_id": "discord",
        "source_dir": "discord",
        "icon": "",
        "doc_url": "https://qwenpaw.agentscope.io/docs/channels",
    },
    {
        "channel_key": "mqtt",
        "plugin_id": "mqtt",
        "source_dir": "mqtt",
        "icon": "",
        "doc_url": "https://qwenpaw.agentscope.io/docs/channels",
    },
    {
        "channel_key": "mattermost",
        "plugin_id": "mattermost",
        "source_dir": "mattermost",
        "icon": "",
        "doc_url": "https://qwenpaw.agentscope.io/docs/channels",
    },
    {
        "channel_key": "dingtalk",
        "plugin_id": "dingtalk",
        "source_dir": "dingtalk",
        "icon": "",
        "doc_url": "https://qwenpaw.agentscope.io/docs/channels",
    },
    {
        "channel_key": "feishu",
        "plugin_id": "feishu",
        "source_dir": "feishu",
        "icon": "",
        "doc_url": "https://qwenpaw.agentscope.io/docs/channels",
    },
    {
        "channel_key": "qq",
        "plugin_id": "qq",
        "source_dir": "qq",
        "icon": "",
        "doc_url": "https://qwenpaw.agentscope.io/docs/channels",
    },
    {
        "channel_key": "wecom",
        "plugin_id": "wecom",
        "source_dir": "wecom",
        "icon": "",
        "doc_url": "https://qwenpaw.agentscope.io/docs/channels",
    },
    {
        "channel_key": "yuanbao",
        "plugin_id": "yuanbao",
        "source_dir": "yuanbao",
        "icon": "",
        "doc_url": "https://qwenpaw.agentscope.io/docs/channels",
    },
    {
        "channel_key": "xiaoyi",
        "plugin_id": "xiaoyi",
        "source_dir": "xiaoyi",
        "icon": "",
        "doc_url": "https://qwenpaw.agentscope.io/docs/channels",
    },
    {
        "channel_key": "wechat",
        "plugin_id": "wechat",
        "source_dir": "wechat",
        "icon": "",
        "doc_url": "https://qwenpaw.agentscope.io/docs/channels",
    },
    {
        "channel_key": "matrix",
        "plugin_id": "matrix",
        "source_dir": "matrix",
        "icon": "",
        "doc_url": "https://qwenpaw.agentscope.io/docs/channels",
    },
    {
        "channel_key": "imessage",
        "plugin_id": "imessage",
        "source_dir": "imessage",
        "icon": "",
        "doc_url": "https://qwenpaw.agentscope.io/docs/channels",
    },
    {
        "channel_key": "onebot",
        "plugin_id": "onebot",
        "source_dir": "onebot",
        "icon": "",
        "doc_url": "https://qwenpaw.agentscope.io/docs/channels",
    },
    {
        "channel_key": "azure_bot",
        "plugin_id": "azure-bot",
        "source_dir": "azure_bot",
        "icon": "",
        "doc_url": "https://qwenpaw.agentscope.io/docs/channels",
    },
    {
        "channel_key": "voice",
        "plugin_id": "voice",
        "source_dir": "voice",
        "icon": "",
        "doc_url": "https://qwenpaw.agentscope.io/docs/channels",
    },
    {
        "channel_key": "sip",
        "plugin_id": "sip",
        "source_dir": "sip",
        "icon": "",
        "doc_url": "https://qwenpaw.agentscope.io/docs/channels",
    },
)


def official_channel_owners() -> dict[str, str]:
    """Map channel routing keys to the plugin that may claim them."""
    return {row["channel_key"]: row["plugin_id"] for row in OFFICIAL_CHANNELS}


def official_channel_for_plugin(plugin_id: str) -> dict[str, str] | None:
    """Resolve a delivered plugin independently of its routing/source name."""
    return next(
        (row for row in OFFICIAL_CHANNELS if row["plugin_id"] == plugin_id),
        None,
    )
