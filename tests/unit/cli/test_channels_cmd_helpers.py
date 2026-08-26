# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-import
"""Unit tests for cli/channels_cmd.py helper functions.

Coverage-driven backfill (batch 4, coverage-first per the 2026-08-24
instruction: upstream PRs are only considered after backend_unit coverage
rises by at least 5 percentage points). Target: the channels CLI helpers
(masking, config field iteration, configurator discovery), which
previously had almost no coverage.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import qwenpaw.cli.channels_cmd as cc


# ---------------------------------------------------------------------------
# _mask
# ---------------------------------------------------------------------------


class TestMask:
    def test_empty(self):
        assert cc._mask("") == "(empty)"

    def test_short_value_fully_masked(self):
        assert cc._mask("abc") == "****"
        assert cc._mask("abcd") == "****"

    def test_long_value_keeps_first_four(self):
        assert cc._mask("abcdefgh") == "abcd****"


# ---------------------------------------------------------------------------
# _channel_enabled
# ---------------------------------------------------------------------------


class TestChannelEnabled:
    def test_none_is_disabled(self):
        assert cc._channel_enabled(None) is False

    def test_attribute_enabled(self):
        assert cc._channel_enabled(SimpleNamespace(enabled=True)) is True
        assert cc._channel_enabled(SimpleNamespace(enabled=False)) is False

    def test_dict_enabled(self):
        assert cc._channel_enabled({"enabled": True}) is True
        assert cc._channel_enabled({"enabled": False}) is False
        assert cc._channel_enabled({}) is False

    def test_unknown_object_disabled(self):
        assert cc._channel_enabled(object()) is False


# ---------------------------------------------------------------------------
# _channel_config_fields
# ---------------------------------------------------------------------------


class TestChannelConfigFields:
    def test_pydantic_model_style(self):
        class _Model:
            model_fields = {"enabled": None, "token": None}

            def __init__(self):
                self.enabled = True
                self.token = "t"

        fields = dict(cc._channel_config_fields(_Model()))
        assert fields == {"token": "t"}

    def test_dict_style(self):
        fields = dict(
            cc._channel_config_fields({"enabled": True, "a": 1}),
        )
        assert fields == {"a": 1}

    def test_object_style(self):
        obj = SimpleNamespace(enabled=True, x=5)
        fields = dict(cc._channel_config_fields(obj))
        assert fields == {"x": 5}


# ---------------------------------------------------------------------------
# _get_channel_config
# ---------------------------------------------------------------------------


class TestGetChannelConfig:
    def test_attr_hit(self):
        channels = SimpleNamespace(discord="cfg")
        config = SimpleNamespace(channels=channels)
        assert cc._get_channel_config(config, "discord") == "cfg"

    def test_extra_fallback(self):
        channels = SimpleNamespace(__pydantic_extra__={"weird": "cfg"})
        config = SimpleNamespace(channels=channels)
        assert cc._get_channel_config(config, "weird") == "cfg"

    def test_missing_returns_none(self):
        channels = SimpleNamespace(__pydantic_extra__={})
        config = SimpleNamespace(channels=channels)
        assert cc._get_channel_config(config, "ghost") is None


# ---------------------------------------------------------------------------
# _get_channel_names / get_channel_configurators
# ---------------------------------------------------------------------------


class TestGetChannelNames:
    def test_filters_by_available(self, monkeypatch):
        monkeypatch.setattr(
            cc,
            "get_available_channels",
            lambda: ("console", "discord"),
        )
        monkeypatch.setattr(
            cc,
            "get_channel_registry",
            lambda: {"console": object(), "discord": object()},
        )
        names = cc._get_channel_names()
        assert "console" in names
        assert "discord" in names

    def test_plugin_channel_display_name(self, monkeypatch):
        class _Plugin:
            display_name = "My Plugin Channel"

        monkeypatch.setattr(cc, "get_available_channels", lambda: ("mychan",))
        monkeypatch.setattr(
            cc,
            "get_channel_registry",
            lambda: {"mychan": _Plugin},
        )
        names = cc._get_channel_names()
        assert names["mychan"] == "My Plugin Channel"

    def test_plugin_channel_fallback_title(self, monkeypatch):
        monkeypatch.setattr(
            cc,
            "get_available_channels",
            lambda: ("my_channel",),
        )
        monkeypatch.setattr(
            cc,
            "get_channel_registry",
            lambda: {"my_channel": object},
        )
        names = cc._get_channel_names()
        assert names["my_channel"] == "My Channel"


class TestGetChannelConfigurators:
    def test_builtin_filtered_by_available(self, monkeypatch):
        monkeypatch.setattr(
            cc,
            "get_available_channels",
            lambda: ("console", "discord"),
        )
        monkeypatch.setattr(cc, "get_channel_registry", lambda: {})
        configurators = cc.get_channel_configurators()
        assert "console" in configurators
        assert "discord" in configurators
        assert "telegram" not in configurators

    def test_plugin_configurator_used(self, monkeypatch):
        called = {}

        def plugin_configurator(current):
            called["yes"] = True
            return current

        class _Plugin:
            display_name = "Plug"

            @staticmethod
            def get_configurator():
                return plugin_configurator

        monkeypatch.setattr(cc, "get_available_channels", lambda: ("plug",))
        monkeypatch.setattr(
            cc,
            "get_channel_registry",
            lambda: {"plug": _Plugin},
        )
        configurators = cc.get_channel_configurators()
        assert "plug" in configurators
        display, run = configurators["plug"]
        assert display == "Plug"
        result = run({"enabled": True})
        assert called["yes"] is True
        assert result == {"enabled": True}

    def test_plugin_without_configurator_uses_default(
        self,
        monkeypatch,
    ):
        monkeypatch.setattr(
            cc,
            "get_available_channels",
            lambda: ("bare",),
        )
        monkeypatch.setattr(
            cc,
            "get_channel_registry",
            lambda: {"bare": object},
        )
        configurators = cc.get_channel_configurators()
        assert "bare" in configurators
        display, _ = configurators["bare"]
        assert display == "Bare"

    def test_unknown_channel_skipped(self, monkeypatch):
        monkeypatch.setattr(cc, "get_available_channels", lambda: ("ghost",))
        monkeypatch.setattr(cc, "get_channel_registry", lambda: {})
        configurators = cc.get_channel_configurators()
        assert "ghost" not in configurators


class TestDefaultPluginConfiguratorBehavior:
    """Default configurator exercised through wrapped plugin path."""

    def test_sets_enabled_and_prefix(self, monkeypatch):
        class _Plugin:
            pass

        monkeypatch.setattr(cc, "get_available_channels", lambda: ("bare",))
        monkeypatch.setattr(
            cc,
            "get_channel_registry",
            lambda: {"bare": _Plugin},
        )
        monkeypatch.setattr(cc, "prompt_confirm", lambda *a, **kw: True)
        monkeypatch.setattr(
            cc.click,
            "prompt",
            lambda *a, **kw: kw.get("default", ""),
        )
        configurators = cc.get_channel_configurators()
        _, run = configurators["bare"]
        result = run({"enabled": False, "bot_prefix": "[BOT]"})
        assert result["enabled"] is True
        assert result["bot_prefix"] == "[BOT]"
