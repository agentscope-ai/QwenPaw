# -*- coding: utf-8 -*-
"""Unit tests for extraSystemPrompt support in the console chat pipeline.

Validates the full data-flow:
  API request → _extract_session_and_payload → native_payload.meta
  → ConsoleChannel.build_agent_request_from_native → request.channel_meta
  → Runner.query_handler → build_env_context → system prompt
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from qwenpaw.app.routers.console import _extract_session_and_payload
from qwenpaw.app.runner.utils import build_env_context


class TestExtractSessionAndPayloadExtraSystemPrompt:
    """_extract_session_and_payload should extract extraSystemPrompt."""

    def test_dict_with_extra_system_prompt(self):
        data = {
            "input": [],
            "session_id": "sess-1",
            "user_id": "u1",
            "channel": "console",
            "extraSystemPrompt": "user_key=sk-abc",
        }
        payload = _extract_session_and_payload(data)
        assert payload["meta"]["extra_system_prompt"] == "user_key=sk-abc"

    def test_dict_without_extra_system_prompt(self):
        data = {
            "input": [],
            "session_id": "sess-1",
            "user_id": "u1",
            "channel": "console",
        }
        payload = _extract_session_and_payload(data)
        assert "extra_system_prompt" not in payload["meta"]

    def test_dict_with_empty_extra_system_prompt(self):
        data = {
            "input": [],
            "session_id": "sess-1",
            "user_id": "u1",
            "channel": "console",
            "extraSystemPrompt": "",
        }
        payload = _extract_session_and_payload(data)
        assert "extra_system_prompt" not in payload["meta"]

    def test_dict_with_non_string_extra_system_prompt(self):
        data = {
            "input": [],
            "session_id": "sess-1",
            "user_id": "u1",
            "channel": "console",
            "extraSystemPrompt": 12345,
        }
        payload = _extract_session_and_payload(data)
        assert "extra_system_prompt" not in payload["meta"]

    def test_agent_request_with_extra_system_prompt(self):
        from agentscope_runtime.engine.schemas.agent_schemas import (
            AgentRequest,
            Message,
            MessageType,
            Role,
            TextContent,
            ContentType,
        )

        req = AgentRequest(
            session_id="sess-2",
            user_id="u2",
            channel="console",
            input=[
                Message(
                    type=MessageType.MESSAGE,
                    role=Role.USER,
                    content=[
                        TextContent(type=ContentType.TEXT, text="hi"),
                    ],
                ),
            ],
        )
        req.extraSystemPrompt = "business_id=xyz"
        payload = _extract_session_and_payload(req)
        assert payload["meta"]["extra_system_prompt"] == "business_id=xyz"

    def test_agent_request_without_extra_system_prompt(self):
        from agentscope_runtime.engine.schemas.agent_schemas import (
            AgentRequest,
            Message,
            MessageType,
            Role,
            TextContent,
            ContentType,
        )

        req = AgentRequest(
            session_id="sess-3",
            user_id="u3",
            channel="console",
            input=[
                Message(
                    type=MessageType.MESSAGE,
                    role=Role.USER,
                    content=[
                        TextContent(type=ContentType.TEXT, text="hi"),
                    ],
                ),
            ],
        )
        payload = _extract_session_and_payload(req)
        assert "extra_system_prompt" not in payload["meta"]


class TestBuildEnvContextExtraSystemPrompt:
    """build_env_context should inject extra_system_prompt."""

    def test_with_extra_system_prompt(self):
        ctx = build_env_context(
            session_id="s1",
            user_id="u1",
            extra_system_prompt="api_key=sk-test123",
        )
        assert "Extra Context:" in ctx
        assert "api_key=sk-test123" in ctx

    def test_without_extra_system_prompt(self):
        ctx = build_env_context(
            session_id="s1",
            user_id="u1",
        )
        assert "Extra Context:" not in ctx

    def test_multiline_extra_system_prompt(self):
        prompt = "line one\nline two\nline three"
        ctx = build_env_context(
            session_id="s1",
            user_id="u1",
            extra_system_prompt=prompt,
        )
        assert "line one" in ctx
        assert "line two" in ctx
        assert "line three" in ctx

    def test_empty_extra_system_prompt_not_injected(self):
        ctx = build_env_context(
            session_id="s1",
            user_id="u1",
            extra_system_prompt="",
        )
        assert "Extra Context:" not in ctx

    def test_none_extra_system_prompt_not_injected(self):
        ctx = build_env_context(
            session_id="s1",
            user_id="u1",
            extra_system_prompt=None,
        )
        assert "Extra Context:" not in ctx

    def test_extra_context_after_important(self):
        ctx = build_env_context(
            session_id="s1",
            user_id="u1",
            extra_system_prompt="my context",
        )
        important_idx = ctx.index("- Important:")
        extra_idx = ctx.index("- Extra Context:")
        assert extra_idx > important_idx


class TestConsoleChannelExtraSystemPrompt:
    """ConsoleChannel.build_agent_request_from_native should propagate
    extra_system_prompt from meta to request.channel_meta."""

    @pytest.fixture
    def channel(self):
        from unittest.mock import AsyncMock

        from qwenpaw.app.channels.console.channel import ConsoleChannel

        return ConsoleChannel(
            process=AsyncMock(),
            enabled=True,
            bot_prefix="",
        )

    def test_meta_extra_system_prompt_propagated(self, channel):
        from agentscope_runtime.engine.schemas.agent_schemas import (
            TextContent,
            ContentType,
        )

        payload = {
            "channel_id": "console",
            "sender_id": "u1",
            "content_parts": [
                TextContent(type=ContentType.TEXT, text="hi"),
            ],
            "meta": {
                "session_id": "sess-x",
                "user_id": "u1",
                "extra_system_prompt": "my_secret=abc",
            },
        }
        request = channel.build_agent_request_from_native(payload)
        assert request.channel_meta.get("extra_system_prompt") == "my_secret=abc"

    def test_meta_without_extra_system_prompt(self, channel):
        from agentscope_runtime.engine.schemas.agent_schemas import (
            TextContent,
            ContentType,
        )

        payload = {
            "channel_id": "console",
            "sender_id": "u1",
            "content_parts": [
                TextContent(type=ContentType.TEXT, text="hi"),
            ],
            "meta": {
                "session_id": "sess-y",
                "user_id": "u1",
            },
        }
        request = channel.build_agent_request_from_native(payload)
        assert "extra_system_prompt" not in request.channel_meta
