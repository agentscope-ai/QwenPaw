# -*- coding: utf-8 -*-
"""Tests for WeCom channel configurator registration."""

from copaw.cli.channels_cmd import (
    CHANNEL_NAMES,
    configure_wecom,
    get_channel_configurators,
)
from copaw.config.config import WeComConfig


def test_wecom_configurator_registered():
    configurators = get_channel_configurators()
    assert "wecom" in configurators


def test_wecom_channel_name_registered():
    assert CHANNEL_NAMES["wecom"] == "WeCom"


def test_configure_wecom_updates_show_streaming_reply(monkeypatch):
    responses = iter(
        [
            True,
            True,
        ]
    )

    monkeypatch.setattr(
        "copaw.cli.channels_cmd.prompt_confirm",
        lambda _text, default=False: next(responses),
    )
    monkeypatch.setattr(
        "copaw.cli.channels_cmd.click.prompt",
        lambda _text, default="", **_kwargs: default,
    )
    monkeypatch.setattr(
        "copaw.cli.channels_cmd.prompt_path",
        lambda _text, default="", **_kwargs: default,
    )

    config = WeComConfig(
        enabled=True,
        bot_prefix="@bot",
        bot_id="bot-1",
        bot_secret="secret-1",
        show_streaming_reply=False,
    )

    updated = configure_wecom(config)

    assert updated.show_streaming_reply is True
