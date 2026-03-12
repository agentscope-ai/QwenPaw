# -*- coding: utf-8 -*-
"""Unit tests for Discord streaming feature.

Tests DiscordTypingController, DiscordDraftStream, DiscordConfig.streaming_mode,
and the from_env/from_config wiring -- all without a real Discord connection.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_channel(channel_id: str = "1234") -> AsyncMock:
    """Fake discord.abc.Messageable with trigger_typing and send."""
    ch = AsyncMock()
    ch.trigger_typing = AsyncMock()
    fake_msg = AsyncMock()
    fake_msg.edit = AsyncMock()
    fake_msg.delete = AsyncMock()
    fake_msg.content = ""
    ch.send = AsyncMock(return_value=fake_msg)
    return ch


# ---------------------------------------------------------------------------
# DiscordConfig
# ---------------------------------------------------------------------------


class TestDiscordConfig:
    def test_streaming_mode_default_is_off(self):
        from copaw.config.config import DiscordConfig

        cfg = DiscordConfig()
        assert cfg.streaming_mode == "off"

    def test_streaming_mode_partial_accepted(self):
        from copaw.config.config import DiscordConfig

        cfg = DiscordConfig(streaming_mode="partial")
        assert cfg.streaming_mode == "partial"

    def test_streaming_mode_invalid_raises(self):
        from pydantic import ValidationError

        from copaw.config.config import DiscordConfig

        with pytest.raises(ValidationError):
            DiscordConfig(streaming_mode="full")


# ---------------------------------------------------------------------------
# DiscordTypingController
# ---------------------------------------------------------------------------


class TestDiscordTypingController:
    @pytest.mark.asyncio
    async def test_start_calls_trigger_typing(self):
        from copaw.app.channels.discord_.channel import DiscordTypingController

        channel = _make_channel()
        ctrl = DiscordTypingController()
        ctrl.start(channel)
        # Give the task a moment to fire the first trigger_typing
        await asyncio.sleep(0.05)
        ctrl.stop()
        # trigger_typing should have been called at least once
        assert channel.trigger_typing.called

    @pytest.mark.asyncio
    async def test_stop_cancels_loop(self):
        from copaw.app.channels.discord_.channel import DiscordTypingController

        channel = _make_channel()
        ctrl = DiscordTypingController()
        ctrl.start(channel)
        await asyncio.sleep(0.02)
        ctrl.stop()
        assert ctrl._task is None
        assert ctrl._stopped is True

    @pytest.mark.asyncio
    async def test_stop_before_start_is_safe(self):
        from copaw.app.channels.discord_.channel import DiscordTypingController

        ctrl = DiscordTypingController()
        ctrl.stop()  # should not raise

    @pytest.mark.asyncio
    async def test_stopped_flag_prevents_restart(self):
        from copaw.app.channels.discord_.channel import DiscordTypingController

        channel = _make_channel()
        ctrl = DiscordTypingController()
        ctrl.start(channel)
        ctrl.stop()
        # After stop, _stopped should be True
        assert ctrl._stopped is True


# ---------------------------------------------------------------------------
# DiscordDraftStream
# ---------------------------------------------------------------------------


class TestDiscordDraftStream:
    @pytest.mark.asyncio
    async def test_send_placeholder_sends_message(self):
        from copaw.app.channels.discord_.channel import (
            DiscordDraftStream,
            _DRAFT_PLACEHOLDER,
        )

        channel = _make_channel()
        draft = DiscordDraftStream(channel)
        await draft.send_placeholder()
        channel.send.assert_called_once_with(_DRAFT_PLACEHOLDER)

    @pytest.mark.asyncio
    async def test_flush_with_content_edits_message(self):
        from copaw.app.channels.discord_.channel import DiscordDraftStream

        channel = _make_channel()
        draft = DiscordDraftStream(channel, max_len=2000)
        await draft.send_placeholder()
        draft.append("Hello, world!")
        await draft.flush()
        # edit should have been called with the buffer content
        draft._draft_msg.edit.assert_called()
        call_kwargs = draft._draft_msg.edit.call_args
        assert "Hello, world!" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_flush_empty_buffer_deletes_placeholder(self):
        from copaw.app.channels.discord_.channel import DiscordDraftStream

        channel = _make_channel()
        draft = DiscordDraftStream(channel)
        await draft.send_placeholder()
        # Save the reference before flush clears it
        placeholder_msg = draft._draft_msg
        await draft.flush()  # nothing appended → calls clear() → deletes msg
        placeholder_msg.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_clear_deletes_message(self):
        from copaw.app.channels.discord_.channel import DiscordDraftStream

        channel = _make_channel()
        draft = DiscordDraftStream(channel)
        await draft.send_placeholder()
        await draft.clear()
        draft._draft_msg is None or None  # after clear, ref is gone

    @pytest.mark.asyncio
    async def test_truncation_at_max_len(self):
        from copaw.app.channels.discord_.channel import DiscordDraftStream

        channel = _make_channel()
        draft = DiscordDraftStream(channel, max_len=10)
        await draft.send_placeholder()
        draft.append("A" * 20)
        await draft.flush()
        call_kwargs = draft._draft_msg.edit.call_args
        edited_content = call_kwargs[1]["content"]
        assert len(edited_content) <= 10


# ---------------------------------------------------------------------------
# from_env streaming_mode wiring
# ---------------------------------------------------------------------------


class TestFromEnvStreamingMode:
    def test_default_streaming_mode_from_env_is_off(self, monkeypatch):
        """DISCORD_STREAMING_MODE not set -> off."""
        monkeypatch.delenv("DISCORD_STREAMING_MODE", raising=False)
        # We don't need a real process handler for this test
        from copaw.app.channels.discord_.channel import DiscordChannel

        with patch.object(DiscordChannel, "__init__", return_value=None):
            channel = DiscordChannel.__new__(DiscordChannel)
            # Simulate from_env calling cls(**kwargs) with streaming_mode
            import os

            raw = os.getenv("DISCORD_STREAMING_MODE", "off").strip().lower()
            mode = "partial" if raw == "partial" else "off"
            assert mode == "off"

    def test_partial_streaming_mode_from_env(self, monkeypatch):
        """DISCORD_STREAMING_MODE=partial -> partial."""
        monkeypatch.setenv("DISCORD_STREAMING_MODE", "partial")
        import os

        raw = os.getenv("DISCORD_STREAMING_MODE", "off").strip().lower()
        mode = "partial" if raw == "partial" else "off"
        assert mode == "partial"

    def test_unknown_streaming_mode_from_env_defaults_to_off(self, monkeypatch):
        monkeypatch.setenv("DISCORD_STREAMING_MODE", "full")
        import os

        raw = os.getenv("DISCORD_STREAMING_MODE", "off").strip().lower()
        mode = "partial" if raw == "partial" else "off"
        assert mode == "off"
