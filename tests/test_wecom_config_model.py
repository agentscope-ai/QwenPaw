# -*- coding: utf-8 -*-
"""Tests for WeCom built-in channel config."""

from copaw.config.config import ChannelConfig, WeComConfig


class TestWeComConfig:
    def test_defaults(self):
        config = WeComConfig()
        assert config.enabled is False
        assert config.show_streaming_reply is True
        assert config.bot_id == ""
        assert config.bot_secret == ""
        assert config.ws_url == "wss://openws.work.weixin.qq.com"
        assert config.ping_interval_seconds == 30
        assert config.reconnect_min_seconds == 1
        assert config.reconnect_max_seconds == 30

    def test_show_streaming_reply_can_be_disabled(self):
        config = WeComConfig(show_streaming_reply=False)
        assert config.show_streaming_reply is False

    def test_channel_config_includes_wecom(self):
        ch = ChannelConfig()
        assert hasattr(ch, "wecom")
        assert isinstance(ch.wecom, WeComConfig)
        assert ch.wecom.enabled is False

    def test_channel_config_from_dict(self):
        data = {
            "wecom": {
                "enabled": True,
                "bot_id": "bot-1",
                "bot_secret": "secret-1",
                "ws_url": "wss://example.test/ws",
                "processed_ids_path": "processed.json",
                "route_store_path": "routes.json",
            }
        }
        ch = ChannelConfig(**data)
        assert ch.wecom.enabled is True
        assert ch.wecom.bot_id == "bot-1"
        assert ch.wecom.bot_secret == "secret-1"
        assert ch.wecom.ws_url == "wss://example.test/ws"
