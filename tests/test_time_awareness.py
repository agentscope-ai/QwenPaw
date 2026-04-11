# -*- coding: utf-8 -*-
"""Unit tests for time awareness injection functionality.

Tests cover:
- Configuration loading and backward compatibility
- Time formatting with different timezones
- Chinese/English label switching
- Custom format support
- Timezone fallback mechanisms
- Integration with message processing
- Edge cases and error handling
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo
import pytest

from agentscope.message import Msg
from copaw.config.config import Config, TimeAwarenessConfig
from copaw.agents.utils.message_processing import (
    inject_time_awareness,
    get_last_user_message,
    prepend_to_message_content,
)


class TestTimeAwarenessConfig:
    """Test TimeAwarenessConfig configuration model."""

    def test_default_disabled(self):
        """Test that time awareness is disabled by default."""
        config = TimeAwarenessConfig()
        assert config.enabled is False
        assert config.format is None

    def test_custom_format(self):
        """Test custom format configuration."""
        config = TimeAwarenessConfig(enabled=True, format="%Y-%m-%d %H:%M")
        assert config.enabled is True
        assert config.format == "%Y-%m-%d %H:%M"

    def test_config_serialization(self):
        """Test that config can be serialized/deserialized to JSON."""
        config = TimeAwarenessConfig(enabled=True, format="%Y-%m-%d")
        json_str = config.model_dump_json()
        restored = TimeAwarenessConfig.model_validate_json(json_str)
        assert restored.enabled is True
        assert restored.format == "%Y-%m-%d"


class TestConfigIntegration:
    """Test integration of TimeAwarenessConfig into main Config."""

    def test_default_in_main_config(self):
        """Test that main Config has time_awareness field with defaults."""
        config = Config()
        assert hasattr(config, "time_awareness")
        assert config.time_awareness.enabled is False
        assert config.time_awareness.format is None

    def test_backward_compatibility(self):
        """Test that old configs without time_awareness load correctly."""
        # Simulate loading a config without time_awareness field
        config_dict = {
            "channels": {},
            "agents": {"active_agent": "default"},
            "user_timezone": "Asia/Shanghai",
            # No time_awareness field - should use default
        }
        config = Config(**config_dict)
        assert config.time_awareness.enabled is False

    def test_enabled_from_json(self):
        """Test enabling time awareness from JSON config."""
        config_dict = {
            "channels": {},
            "agents": {"active_agent": "default", "language": "zh"},
            "user_timezone": "Asia/Shanghai",
            "time_awareness": {
                "enabled": True,
                "format": None,
            },
        }
        config = Config(**config_dict)
        assert config.time_awareness.enabled is True


class TestInjectTimeAwareness:
    """Test inject_time_awareness() function."""

    @patch("copaw.agents.utils.message_processing.datetime")
    def test_chinese_label(self, mock_datetime):
        """Test Chinese label when language is zh."""
        fixed_time = datetime(
            2026,
            4,
            11,
            14,
            30,
            45,
            tzinfo=ZoneInfo("Asia/Shanghai"),
        )
        mock_datetime.now.return_value = fixed_time
        mock_datetime.side_effect = datetime

        config = MagicMock()
        config.time_awareness = TimeAwarenessConfig(enabled=True)
        config.user_timezone = "Asia/Shanghai"
        config.agents.language = "zh"

        result = inject_time_awareness(config)
        assert result is not None
        assert "[当前时间:" in result
        assert "2026-04-11" in result
        assert "14:30:45" in result
        assert "Asia/Shanghai" in result

    @patch("copaw.agents.utils.message_processing.datetime")
    def test_english_label(self, mock_datetime):
        """Test English label when language is not zh."""
        fixed_time = datetime(
            2026,
            4,
            11,
            2,
            30,
            45,
            tzinfo=ZoneInfo("America/New_York"),
        )
        mock_datetime.now.return_value = fixed_time
        mock_datetime.side_effect = datetime

        config = MagicMock()
        config.time_awareness = TimeAwarenessConfig(enabled=True)
        config.user_timezone = "America/New_York"
        config.agents.language = "en"

        result = inject_time_awareness(config)
        assert result is not None
        assert "[Current time:" in result
        assert "America/New_York" in result

    @patch("copaw.agents.utils.message_processing.datetime")
    def test_custom_format(self, mock_datetime):
        """Test custom strftime format."""
        fixed_time = datetime(2026, 4, 11, 14, 30, 45, tzinfo=ZoneInfo("UTC"))
        mock_datetime.now.return_value = fixed_time
        mock_datetime.strftime = fixed_time.strftime
        mock_datetime.side_effect = datetime

        config = MagicMock()
        config.time_awareness = TimeAwarenessConfig(
            enabled=True,
            format="%Y-%m-%d %H:%M",
        )
        config.user_timezone = "UTC"
        config.agents.language = "en"

        result = inject_time_awareness(config)
        assert result is not None
        assert "2026-04-11 14:30]" in result

    def test_disabled_returns_none(self):
        """Test that disabled mode returns None."""
        config = MagicMock()
        config.time_awareness = TimeAwarenessConfig(enabled=False)

        result = inject_time_awareness(config)
        assert result is None

    def test_none_config_returns_none(self):
        """Test that None config returns None safely."""
        result = inject_time_awareness(None)
        assert result is None

    def test_missing_time_awareness_returns_none(self):
        """Test that config without time_awareness attribute returns None."""
        config = MagicMock(spec=[])  # Empty spec, no attributes
        result = inject_time_awareness(config)
        assert result is None

    @patch("copaw.agents.utils.message_processing.datetime")
    def test_invalid_timezone_fallback(self, mock_datetime):
        """Test fallback to UTC on invalid timezone."""
        fixed_time = datetime(2026, 4, 11, 14, 30, 45, tzinfo=timezone.utc)
        mock_datetime.now.return_value = fixed_time
        mock_datetime.side_effect = datetime

        config = MagicMock()
        config.time_awareness = TimeAwarenessConfig(enabled=True)
        config.user_timezone = "Invalid/Timezone"
        config.agents.language = "en"

        # Should not raise exception, should fallback to UTC
        result = inject_time_awareness(config)
        assert result is not None
        assert "UTC" in result

    @patch("copaw.agents.utils.message_processing.datetime")
    def test_empty_timezone_fallback(self, mock_datetime):
        """Test fallback to UTC on empty timezone string."""
        fixed_time = datetime(2026, 4, 11, 14, 30, 45, tzinfo=timezone.utc)
        mock_datetime.now.return_value = fixed_time
        mock_datetime.side_effect = datetime

        config = MagicMock()
        config.time_awareness = TimeAwarenessConfig(enabled=True)
        config.user_timezone = ""
        config.agents.language = "en"

        result = inject_time_awareness(config)
        assert result is not None
        assert "UTC" in result

    @patch("copaw.agents.utils.message_processing.datetime")
    def test_multiple_timezones(self, mock_datetime):
        """Test correct conversion for multiple timezones."""
        test_cases = [
            ("Europe/London", "Europe/London"),
            ("Asia/Tokyo", "Asia/Tokyo"),
            ("Australia/Sydney", "Australia/Sydney"),
        ]

        for tz_name in test_cases:
            fixed_time = datetime(
                2026,
                4,
                11,
                12,
                0,
                0,
                tzinfo=ZoneInfo(tz_name[0]),
            )
            mock_datetime.now.return_value = fixed_time
            mock_datetime.side_effect = datetime

            config = MagicMock()
            config.time_awareness = TimeAwarenessConfig(enabled=True)
            config.user_timezone = tz_name[0]
            config.agents.language = "en"

            result = inject_time_awareness(config)
            assert result is not None
            assert tz_name[1] in result


class TestGetLastUserMessage:
    """Test get_last_user_message() helper function."""

    def test_find_last_user_message(self):
        """Test finding the last user message from list."""
        msgs = [
            Msg(name="system", role="system", content="System prompt"),
            Msg(name="user1", role="user", content="First message"),
            Msg(name="assistant", role="assistant", content="Response"),
            Msg(name="user2", role="user", content="Second message"),
        ]
        result = get_last_user_message(msgs)
        assert result is not None
        assert result.name == "user2"
        assert result.content == "Second message"

    def test_empty_list_returns_none(self):
        """Test that empty list returns None."""
        result = get_last_user_message([])
        assert result is None

    def test_no_user_message_returns_none(self):
        """Test that list without user messages returns None."""
        msgs = [
            Msg(name="system", role="system", content="System"),
            Msg(name="assistant", role="assistant", content="Response"),
        ]
        result = get_last_user_message(msgs)
        assert result is None

    def test_only_user_messages(self):
        """Test list with only user messages."""
        msgs = [
            Msg(name="user1", role="user", content="First"),
            Msg(name="user2", role="user", content="Second"),
        ]
        result = get_last_user_message(msgs)
        assert result is not None
        assert result.name == "user2"


class TestPrependToMessageContent:
    """Test prepend_to_message_content() with time strings."""

    def test_prepend_string_content(self):
        """Test prepending to string content."""
        msg = Msg(name="user", role="user", content="Hello")
        time_str = "[Current time: 2026-04-11 14:30:45 UTC (Saturday)]"
        prepend_to_message_content(msg, time_str)

        assert msg.content.startswith(time_str)
        assert "Hello" in msg.content
        assert "\n\n" in msg.content

    def test_prepend_list_content_with_text_block(self):
        """Test prepending to list content with text block."""
        msg = Msg(
            name="user",
            role="user",
            content=[{"type": "text", "text": "Hello"}],
        )
        time_str = "[Current time: 2026-04-11 14:30:45 UTC]"
        prepend_to_message_content(msg, time_str)

        assert isinstance(msg.content, list)
        text_block = msg.content[0]
        assert text_block["type"] == "text"
        assert text_block["text"].startswith(time_str)

    def test_prepend_list_content_without_text_block(self):
        """Test prepending to list content without existing text block."""
        msg = Msg(
            name="user",
            role="user",
            content=[{"type": "image", "url": "http://example.com/img.png"}],
        )
        time_str = "[Current time: 2026-04-11 14:30:45 UTC]"
        prepend_to_message_content(msg, time_str)

        assert isinstance(msg.content, list)
        assert len(msg.content) == 2
        assert msg.content[0]["type"] == "text"
        assert msg.content[0]["text"] == time_str


class TestPerformance:
    """Performance and edge case tests."""

    @patch("copaw.agents.utils.message_processing.datetime")
    def test_execution_time(self, mock_datetime):
        """Test that execution completes within 1ms."""
        import time

        fixed_time = datetime(2026, 4, 11, 14, 30, 45, tzinfo=ZoneInfo("UTC"))
        mock_datetime.now.return_value = fixed_time
        mock_datetime.side_effect = datetime

        config = MagicMock()
        config.time_awareness = TimeAwarenessConfig(enabled=True)
        config.user_timezone = "UTC"
        config.agents.language = "en"

        start = time.perf_counter()
        for _ in range(1000):
            inject_time_awareness(config)
        elapsed = (time.perf_counter() - start) * 1000  # Convert to ms

        # Average should be < 1ms per call
        avg_time_ms = elapsed / 1000
        assert (
            avg_time_ms < 1.0
        ), f"Average time {avg_time_ms:.3f}ms exceeds 1ms limit"

    def test_none_msg_safe_handling(self):
        """Test safe handling of None message object."""
        time_str = "[Current time: 2026-04-11 14:30:45 UTC]"
        # Should not raise exception
        prepend_to_message_content(None, time_str)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
