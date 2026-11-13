# -*- coding: utf-8 -*-
"""Tests for channel Bot identity extraction."""

from types import SimpleNamespace

import pytest

from qwenpaw.app.channels.conflict import get_channel_bot_identity


@pytest.mark.parametrize(
    ("channel_name", "config", "expected"),
    [
        (
            "telegram",
            {"bot_token": " token-1 "},
            (("bot_token", "token-1"),),
        ),
        (
            "mattermost",
            {"url": "https://chat.example.com/", "bot_token": "token-2"},
            (
                ("url", "https://chat.example.com"),
                ("bot_token", "token-2"),
            ),
        ),
        (
            "matrix",
            SimpleNamespace(
                homeserver="https://matrix.example.com/",
                user_id="@bot:example.com",
            ),
            (
                ("homeserver", "https://matrix.example.com"),
                ("user_id", "@bot:example.com"),
            ),
        ),
        (
            "voice",
            {"phone_number_sid": " PN123456789 "},
            (("phone_number_sid", "PN123456789"),),
        ),
    ],
)
def test_get_channel_bot_identity(channel_name, config, expected):
    assert get_channel_bot_identity(channel_name, config) == expected


@pytest.mark.parametrize(
    ("channel_name", "config"),
    [
        ("console", {"bot_id": "ignored"}),
        ("telegram", {"bot_token": ""}),
        ("mattermost", {"url": "", "bot_token": "token"}),
        ("voice", {"phone_number_sid": ""}),
    ],
)
def test_get_channel_bot_identity_skips_unsupported_or_empty_configs(
    channel_name,
    config,
):
    assert get_channel_bot_identity(channel_name, config) is None
