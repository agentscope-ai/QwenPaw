# -*- coding: utf-8 -*-
"""
Console Channel Unit Tests - Simple Channel Template

This serves as the reference implementation for testing simple channels.
For complex channels with external dependencies (HTTP, WebSocket), see
 test_dingtalk.py for advanced patterns.

Key patterns demonstrated:
1. Basic initialization testing
2. Output capture (for console-based channels)
3. Lifecycle testing (start/stop)
4. Simple mocking (no external dependencies)
"""
# pylint: disable=redefined-outer-name,reimported

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from copaw.app.channels.console.channel import ConsoleChannel


class TestConsoleChannelUnit:
    """
    Unit tests for ConsoleChannel.

    These complement the contract tests by verifying internal behavior,
    such as enabled/disabled state and output formatting.
    """

    @pytest.fixture
    def mock_process(self):
        """Create mock process handler."""

        async def mock_handler(*_args, **_kwargs):
            event = MagicMock()
            event.object = "message"
            event.status = "completed"
            yield event

        return AsyncMock(side_effect=mock_handler)

    @pytest.fixture
    def channel(self, mock_process):
        """Create ConsoleChannel instance."""
        return ConsoleChannel(
            process=mock_process,
            enabled=True,
            bot_prefix="[BOT] ",
            show_tool_details=False,
            filter_tool_messages=False,
            filter_thinking=False,
        )

    def test_init_stores_enabled_flag(self, mock_process):
        """Constructor should store the enabled flag."""
        from copaw.app.channels.console.channel import ConsoleChannel

        ch = ConsoleChannel(
            process=mock_process,
            enabled=False,
            bot_prefix="[TEST] ",
        )

        assert ch.enabled is False
        assert ch.bot_prefix == "[TEST] "

    @pytest.mark.asyncio
    async def test_send_prints_to_stdout(self, channel, capsys):
        """send() should print message to stdout when enabled."""
        await channel.send("user123", "Hello World", meta={})

        captured = capsys.readouterr()
        assert "Hello World" in captured.out
        assert "[BOT]" in captured.out or "user123" in captured.out

    @pytest.mark.asyncio
    async def test_send_disabled_does_nothing(self, mock_process, capsys):
        """send() should do nothing when disabled."""
        from copaw.app.channels.console.channel import ConsoleChannel

        ch = ConsoleChannel(
            process=mock_process,
            enabled=False,
            bot_prefix="[BOT] ",
        )

        await ch.send("user123", "Hello World", meta={})

        captured = capsys.readouterr()
        assert captured.out == ""

    @pytest.mark.asyncio
    async def test_send_includes_prefix(self, mock_process, capsys):
        """send() should include bot_prefix before message."""
        from copaw.app.channels.console.channel import ConsoleChannel

        ch = ConsoleChannel(
            process=mock_process,
            enabled=True,
            bot_prefix=">> ",
        )

        await ch.send("user123", "Test message", meta={})

        captured = capsys.readouterr()
        # Prefix should appear before or with message
        assert ">> " in captured.out
        assert "Test message" in captured.out

    @pytest.mark.asyncio
    async def test_start_when_enabled(self, channel):
        """start() should complete without error when enabled."""
        # Should not raise
        await channel.start()

    @pytest.mark.asyncio
    async def test_start_when_disabled(self, mock_process):
        """start() should handle disabled channel gracefully."""
        from copaw.app.channels.console.channel import ConsoleChannel

        ch = ConsoleChannel(
            process=mock_process,
            enabled=False,
            bot_prefix="",
        )

        # Should not raise
        await ch.start()

    @pytest.mark.asyncio
    async def test_stop_when_enabled(self, channel):
        """stop() should complete without error when enabled."""
        await channel.start()
        await channel.stop()
        # Should not raise

    @pytest.mark.asyncio
    async def test_stop_when_disabled(self, mock_process):
        """stop() should handle disabled channel gracefully."""
        from copaw.app.channels.console.channel import ConsoleChannel

        ch = ConsoleChannel(
            process=mock_process,
            enabled=False,
            bot_prefix="",
        )

        # Should not raise
        await ch.stop()

    @pytest.mark.asyncio
    async def test_send_content_parts_combines_text(
        self,
        mock_process,
        capsys,
    ):
        """send_content_parts() should combine multiple text parts."""
        from copaw.app.channels.base import TextContent, ContentType

        ch = ConsoleChannel(
            process=mock_process,
            enabled=True,
            bot_prefix="",
        )

        parts = [
            TextContent(type=ContentType.TEXT, text="Line 1"),
            TextContent(type=ContentType.TEXT, text="Line 2"),
        ]

        await ch.send_content_parts("user123", parts, meta={})

        captured = capsys.readouterr()
        assert "Line 1" in captured.out
        assert "Line 2" in captured.out


class TestConsoleChannelFromEnv:
    """Tests for from_env factory method."""

    @pytest.fixture
    def mock_process(self):
        return AsyncMock()

    def test_from_env_reads_enabled(self, mock_process, monkeypatch):
        """from_env should read CONSOLE_CHANNEL_ENABLED from environment."""
        from copaw.app.channels.console.channel import ConsoleChannel

        monkeypatch.setenv("CONSOLE_CHANNEL_ENABLED", "0")

        channel = ConsoleChannel.from_env(mock_process)

        assert channel.enabled is False

    def test_from_env_reads_bot_prefix(self, mock_process, monkeypatch):
        """from_env should read CONSOLE_BOT_PREFIX from environment."""
        from copaw.app.channels.console.channel import ConsoleChannel

        monkeypatch.setenv("CONSOLE_BOT_PREFIX", "[TEST] ")

        channel = ConsoleChannel.from_env(mock_process)

        assert channel.bot_prefix == "[TEST] "

    def test_from_env_defaults(self, mock_process, monkeypatch):
        """from_env should use sensible defaults."""
        from copaw.app.channels.console.channel import ConsoleChannel

        # Clear environment
        monkeypatch.delenv("CONSOLE_CHANNEL_ENABLED", raising=False)
        monkeypatch.delenv("CONSOLE_BOT_PREFIX", raising=False)

        channel = ConsoleChannel.from_env(mock_process)

        assert channel.enabled is True  # Default enabled
        assert channel.bot_prefix == "[BOT] "  # Default prefix


class TestConsoleChannelFromConfig:
    """Tests for from_config factory method."""

    @pytest.fixture
    def mock_process(self):
        return AsyncMock()

    def test_from_config_uses_config_values(self, mock_process):
        """from_config should use values from config object."""
        from copaw.app.channels.console.channel import ConsoleChannel
        from copaw.config.config import ConsoleConfig

        config = ConsoleConfig(
            enabled=False,
            bot_prefix="[CFG] ",
        )

        channel = ConsoleChannel.from_config(
            process=mock_process,
            config=config,
        )

        assert channel.enabled is False
        assert channel.bot_prefix == "[CFG] "
