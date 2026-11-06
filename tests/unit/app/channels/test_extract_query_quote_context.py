# -*- coding: utf-8 -*-
"""Quoted-reply context must not defeat command detection (#8342).

Channels prepend the quoted (replied-to) message as a ``[quoted ...]``
block before the user's own text. The shared query extraction feeds
command classification and queue priority, so it must return the user's
own text while the full quoted message still reaches the model.
"""

# pylint: disable=redefined-outer-name,protected-access,unused-argument
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from qwenpaw.app.channels.base import BaseChannel, ProcessHandler
from qwenpaw.app.channels.console.channel import ConsoleChannel


@pytest.fixture
def mock_process() -> ProcessHandler:
    """Mock agent processing flow; the query extraction never calls it."""

    async def process(_request: Any):
        yield None

    return process


@pytest.fixture
def base_channel(mock_process) -> BaseChannel:
    """ConsoleChannel is the simplest testable BaseChannel instance."""
    return ConsoleChannel(
        process=mock_process,
        enabled=True,
        bot_prefix="[TEST] ",
    )


class TestExtractQueryQuoteContext:
    """``_extract_query_from_payload`` sees the user's own text."""

    QUOTED_STOP = "[quoted message: Alice: quarterly report]\n/stop"

    @pytest.fixture(autouse=True)
    def _with_command_registry(self, base_channel):
        from qwenpaw.app.channels.command_registry import CommandRegistry

        base_channel._command_registry = CommandRegistry()

    def test_dict_payload_quoted_reply_resolves_command(self, base_channel):
        payload = {
            "content_parts": [
                {"type": "text", "text": self.QUOTED_STOP},
            ],
        }

        query = base_channel._extract_query_from_payload(payload)

        assert query == "/stop"
        assert base_channel._command_registry.is_control_command(query)
        assert base_channel._command_registry.get_priority_level(query) == 0

    def test_object_payload_quoted_reply_resolves_command(
        self,
        base_channel,
    ):
        from qwenpaw.schemas import ContentType, Message, Role, TextContent

        request = SimpleNamespace(
            input=[
                Message(
                    role=Role.USER,
                    content=[
                        TextContent(
                            type=ContentType.TEXT,
                            text=self.QUOTED_STOP,
                        ),
                    ],
                ),
            ],
        )

        query = base_channel._extract_query_from_payload(request)

        assert query == "/stop"
        assert base_channel._command_registry.is_control_command(query)

    def test_quoted_reply_without_new_text_is_not_control(
        self,
        base_channel,
    ):
        payload = {
            "content_parts": [
                {"type": "text", "text": "[quoted message: /stop]"},
            ],
        }

        query = base_channel._extract_query_from_payload(payload)

        assert query == ""
        assert not base_channel._command_registry.is_control_command(query)

    def test_command_only_inside_quote_is_not_control(self, base_channel):
        payload = {
            "content_parts": [
                {
                    "type": "text",
                    "text": "[quoted message: /stop]\nare you there?",
                },
            ],
        }

        query = base_channel._extract_query_from_payload(payload)

        assert query == "are you there?"
        assert not base_channel._command_registry.is_control_command(query)

    def test_normal_quoted_chat_keeps_plain_classification(
        self,
        base_channel,
    ):
        payload = {
            "content_parts": [
                {
                    "type": "text",
                    "text": "[quoted message: Alice: hi]\nhello there",
                },
            ],
        }

        query = base_channel._extract_query_from_payload(payload)

        assert query == "hello there"
        assert not base_channel._command_registry.is_control_command(query)
        assert base_channel._command_registry.get_priority_level(query) == 20

    def test_plain_command_without_quote_unchanged(self, base_channel):
        payload = {
            "content_parts": [{"type": "text", "text": "/stop"}],
        }

        query = base_channel._extract_query_from_payload(payload)

        assert query == "/stop"
        assert base_channel._command_registry.is_control_command(query)
