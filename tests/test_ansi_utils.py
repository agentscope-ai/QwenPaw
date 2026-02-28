# -*- coding: utf-8 -*-
"""Tests for ANSI escape sequence utilities."""

import pytest

from copaw.agents.utils.ansi_utils import strip_ansi_sequences


class TestStripAnsiSequences:
    """Test cases for strip_ansi_sequences function."""

    def test_empty_string(self) -> None:
        """Test empty string returns empty."""
        assert strip_ansi_sequences("") == ""

    def test_none_input(self) -> None:
        """Test None input returns None."""
        assert strip_ansi_sequences(None) is None  # type: ignore

    def test_plain_text(self) -> None:
        """Test plain text without ANSI codes is unchanged."""
        text = "Hello World"
        assert strip_ansi_sequences(text) == text

    def test_color_codes(self) -> None:
        """Test removal of color ANSI codes."""
        # Green text
        text = "\x1b[32mHello\x1b[0m World"
        assert strip_ansi_sequences(text) == "Hello World"

        # Red text
        text = "\x1b[31mError\x1b[0m"
        assert strip_ansi_sequences(text) == "Error"

        # Multiple colors
        text = "\x1b[32mSuccess\x1b[0m: \x1b[33mWarning\x1b[0m"
        assert strip_ansi_sequences(text) == "Success: Warning"

    def test_cursor_movement(self) -> None:
        """Test removal of cursor movement codes."""
        # Clear line
        text = "Loading...\x1b[2KDone"
        assert strip_ansi_sequences(text) == "Loading...Done"

        # Cursor up and clear
        text = "\x1b[1A\x1b[KHello"
        assert strip_ansi_sequences(text) == "Hello"

    def test_spinner_animation_output(self) -> None:
        """Test typical spinner/progress output from CLI tools."""
        # Simulated spinner frames
        text = "\x1b[?25l◐ Processing\x1b[1D\x1b[0K◓ Processing\x1b[1D\x1b[0KDone"
        result = strip_ansi_sequences(text)
        assert "\x1b" not in result

    def test_real_world_npx_output(self) -> None:
        """Test with realistic npx/skills output containing many escape codes."""
        text = (
            "\x1b[38;5;250m███████╗██╗  ██╗██╗██╗\x1b[0m\n"
            "\x1b[?25l│\n"
            "◇  Source: test\n"
            "\x1b[?25h"
        )
        result = strip_ansi_sequences(text)
        assert "\x1b" not in result
        assert "███████" in result or "Source" in result

    def test_multiple_escape_types(self) -> None:
        """Test mixed ANSI escape sequence types."""
        text = "\x1b[1m\x1b[31mBold Red\x1b[0m\x1b[2K"
        assert strip_ansi_sequences(text) == "Bold Red"
