# -*- coding: utf-8 -*-
"""BaseChannel query-extraction unit tests.

The shared query extraction feeds command classification and queue
priority, so it must return the user's own text — even when a channel
prepends quoted (replied-to) message context — while the full quoted
message still reaches the model (#8342).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from qwenpaw.app.channels.base import BaseChannel, ProcessHandler
from qwenpaw.app.channels.console.channel import ConsoleChannel


@pytest.fixture
def mock_process() -> ProcessHandler:
    """Mock agent processing flow, returns simple text response."""

    async def process(_request: Any):
        from qwenpaw.schemas import (
            ContentType,
            Event,
            Message,
            MessageType,
            Role,
            RunStatus,
            TextContent,
        )

        yield Event(
            object="message",
            status=RunStatus.Completed,
            type="message.completed",
            id="test-1",
            created_at=1234567890,
            message=Message(
                type=MessageType.MESSAGE,
                role=Role.ASSISTANT,
                content=[
                    TextContent(type=ContentType.TEXT, text="Test response"),
                ],
            ),
        )

    return process


@pytest.fixture
def base_channel(mock_process) -> BaseChannel:
    """
    Use ConsoleChannel as a testable instance of BaseChannel.
    ConsoleChannel is the simplest implementation,
    suitable for testing base class logic.
    """
    return ConsoleChannel(
        process=mock_process,
        enabled=True,
        bot_prefix="[TEST] ",
    )


class TestExtractQueryQuoteContext:
    """
    Quoted-reply context must not defeat command detection (#8342).
    """

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
