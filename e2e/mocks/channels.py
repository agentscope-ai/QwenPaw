# -*- coding: utf-8 -*-
"""Mock API responses for channels endpoints."""
from __future__ import annotations

import json
from playwright.sync_api import Page

_MOCK_CHANNELS = {
    "console": {
        "enabled": True,
        "bot_prefix": "",
        "filter_tool_messages": False,
        "filter_thinking": False,
    },
    "dingtalk": {
        "enabled": False,
        "bot_prefix": "",
        "filter_tool_messages": False,
        "filter_thinking": False,
    },
    "feishu": {
        "enabled": False,
        "bot_prefix": "",
        "filter_tool_messages": False,
        "filter_thinking": False,
    },
    "telegram": {
        "enabled": False,
        "bot_prefix": "",
        "filter_tool_messages": False,
        "filter_thinking": False,
    },
}

_MOCK_CHANNEL_TYPES = [
    "console",
    "dingtalk",
    "feishu",
    "telegram",
    "discord",
    "qq",
    "wecom",
    "mqtt",
]


def register(page: Page):
    """Register channels API route mocks."""

    def _handle_types(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_MOCK_CHANNEL_TYPES),
        )

    def _handle_list(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_MOCK_CHANNELS),
        )

    def _handle_get_channel(route):
        channel_name = route.request.url.split("/channels/")[-1].split("?")[0]
        # Skip qrcode routes
        if "/" in channel_name:
            route.fallback()
            return
        config = _MOCK_CHANNELS.get(channel_name, {"enabled": False})
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(config),
        )

    def _handle_update_channel(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_MOCK_CHANNELS),
        )

    page.route("**/api/config/channels/types**", _handle_types)
    page.route(
        "**/api/config/channels/*/qrcode**",
        lambda route: route.fallback(),
    )
    page.route("**/api/config/channels/*", _handle_get_channel)
    page.route("**/api/config/channels", _handle_list)
