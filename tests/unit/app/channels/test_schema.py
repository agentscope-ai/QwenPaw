# -*- coding: utf-8 -*-
"""Unit tests for qwenpaw.app.channels.schema."""

from __future__ import annotations

# pylint: disable=protected-access,redefined-outer-name,unused-argument,use-implicit-booleaness-not-comparison,unused-import  # noqa: E501

import pytest

from qwenpaw.app.channels.schema import (
    BUILTIN_CHANNEL_TYPES,
    DEFAULT_CHANNEL,
    ChannelAddress,
    ChannelMessageConverter,
    ChannelType,
)


class TestChannelAddress:
    def test_kind_and_id_required(self):
        addr = ChannelAddress(kind="dm", id="u1")
        assert addr.kind == "dm"
        assert addr.id == "u1"
        assert addr.extra is None

    def test_extra_defaults_none(self):
        addr = ChannelAddress(kind="channel", id="c1")
        assert addr.extra is None

    def test_to_handle_default_format(self):
        addr = ChannelAddress(kind="discord", id="123")
        assert addr.to_handle() == "discord:123"

    def test_to_handle_uses_extra_override(self):
        addr = ChannelAddress(
            kind="dm",
            id="456",
            extra={"to_handle": "discord:ch:999"},
        )
        assert addr.to_handle() == "discord:ch:999"

    def test_to_handle_extra_without_to_handle_key(self):
        addr = ChannelAddress(kind="dm", id="u1", extra={"foo": "bar"})
        assert addr.to_handle() == "dm:u1"

    def test_to_handle_extra_to_handle_non_string(self):
        addr = ChannelAddress(kind="dm", id="u1", extra={"to_handle": 42})
        assert addr.to_handle() == "42"

    def test_to_handle_empty_id(self):
        addr = ChannelAddress(kind="console", id="")
        assert addr.to_handle() == "console:"

    def test_extra_is_mutable_dict(self):
        addr = ChannelAddress(kind="dm", id="x")
        addr.extra = {"k": "v"}
        assert addr.extra == {"k": "v"}


class TestChannelSchemaConstants:
    def test_default_channel_is_console(self):
        assert DEFAULT_CHANNEL == "console"

    def test_default_channel_is_builtin(self):
        assert DEFAULT_CHANNEL in BUILTIN_CHANNEL_TYPES

    def test_channel_type_is_str(self):
        assert ChannelType is str

    def test_builtin_types_contains_expected(self):
        for name in (
            "imessage",
            "discord",
            "dingtalk",
            "feishu",
            "qq",
            "telegram",
            "mqtt",
            "console",
            "voice",
            "sip",
            "slack",
            "xiaoyi",
            "yuanbao",
        ):
            assert name in BUILTIN_CHANNEL_TYPES

    def test_builtin_types_is_tuple(self):
        assert isinstance(BUILTIN_CHANNEL_TYPES, tuple)

    def test_builtin_types_unique(self):
        assert len(BUILTIN_CHANNEL_TYPES) == len(set(BUILTIN_CHANNEL_TYPES))


class TestChannelMessageConverterProtocol:
    def test_protocol_is_runtime_checkable(self):
        assert isinstance(ChannelMessageConverter, type)

    def test_protocol_methods_exist(self):
        assert hasattr(
            ChannelMessageConverter,
            "build_agent_request_from_native",
        )
        assert hasattr(ChannelMessageConverter, "send_response")

    def test_object_satisfying_protocol(self):
        class Impl:
            def build_agent_request_from_native(self, native_payload):
                return native_payload

            async def send_response(self, to_handle, response, meta=None):
                return None

        impl = Impl()
        assert isinstance(impl, ChannelMessageConverter)

    def test_object_missing_send_response_does_not_satisfy(self):
        class Bad:
            def build_agent_request_from_native(self, native_payload):
                return None

        impl = Bad()
        assert not isinstance(impl, ChannelMessageConverter)
