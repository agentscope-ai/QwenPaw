# -*- coding: utf-8 -*-
"""Tests for WeCom channel config models."""

from copaw.config.config import ChannelConfig, WeComConfig, WeComAppConfig


def test_wecom_config_defaults() -> None:
    cfg = WeComConfig()
    assert cfg.enabled is False
    assert cfg.webhook_path == "/wecom"
    assert cfg.reply_timeout_sec == 4.5


def test_wecom_app_config_defaults() -> None:
    cfg = WeComAppConfig()
    assert cfg.enabled is False
    assert cfg.webhook_path == "/wecom-app"
    assert cfg.api_base_url == "https://qyapi.weixin.qq.com"


def test_channel_config_includes_wecom() -> None:
    ch = ChannelConfig()
    assert isinstance(ch.wecom, WeComConfig)
    assert isinstance(ch.wecom_app, WeComAppConfig)


def test_wecom_legacy_fields_are_normalized() -> None:
    cfg = WeComConfig.model_validate(
        {
            "enabled": True,
            "token": "t",
            "encodingAESKey": "k",
            "receiveId": "rid",
            "webhookPath": "/x",
            "replyTimeoutSec": 6.0,
        },
    )
    assert cfg.encoding_aes_key == "k"
    assert cfg.receive_id == "rid"
    assert cfg.webhook_path == "/x"
    assert cfg.reply_timeout_sec == 6.0
