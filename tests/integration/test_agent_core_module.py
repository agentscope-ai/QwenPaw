# -*- coding: utf-8 -*-
"""Integration tests for Agent Core internals.

Covers src/qwenpaw/agents/* (command_handler, middlewares, prompt,
utils/file_handling) — several thousand uncovered lines.
"""

from __future__ import annotations

import pytest


# ------------------------------------------------------------------ #
# command_handler
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_fmt_tokens() -> None:
    """_fmt_tokens formats token counts compactly."""
    from qwenpaw.agents.command_handler import _fmt_tokens

    assert _fmt_tokens(500) == "500"
    assert "k" in _fmt_tokens(1500).lower()


@pytest.mark.integration
@pytest.mark.p1
def test_is_conversation_command() -> None:
    """is_conversation_command detects slash commands."""
    from qwenpaw.agents.command_handler import (
        ConversationCommandHandlerMixin,
    )

    class _H(ConversationCommandHandlerMixin):
        pass

    handler = _H()
    assert handler.is_conversation_command("/compact") is True
    assert handler.is_conversation_command("hello") is False
    assert handler.is_conversation_command(None) is False


# ------------------------------------------------------------------ #
# middlewares
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_auto_memory_turn_state() -> None:
    """auto_memory_turn_state returns a dict for an agent state."""
    from qwenpaw.agents.middlewares import auto_memory_turn_state

    class _State:
        pass

    state = _State()
    result = auto_memory_turn_state(state)
    assert isinstance(result, dict)


@pytest.mark.integration
@pytest.mark.p1
def test_reset_auto_memory_turn_state() -> None:
    """reset_auto_memory_turn_state clears the turn state."""
    from qwenpaw.agents.middlewares import (
        auto_memory_turn_state,
        reset_auto_memory_turn_state,
    )

    class _State:
        pass

    state = _State()
    auto_memory_turn_state(state)
    reset_auto_memory_turn_state(state)
    result = auto_memory_turn_state(state)
    assert isinstance(result, dict)


# ------------------------------------------------------------------ #
# prompt
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_build_multimodal_hint() -> None:
    """build_multimodal_hint returns a string."""
    from qwenpaw.agents.prompt import build_multimodal_hint

    assert isinstance(build_multimodal_hint(), str)


@pytest.mark.integration
@pytest.mark.p1
def test_build_driver_policy_recheck_hint() -> None:
    """build_driver_policy_recheck_hint returns a string."""
    from qwenpaw.agents.prompt import (
        build_driver_policy_recheck_hint,
    )

    assert isinstance(build_driver_policy_recheck_hint(), str)


@pytest.mark.integration
@pytest.mark.p1
def test_prompt_config_defaults() -> None:
    """PromptConfig constructs with defaults."""
    from qwenpaw.agents.prompt import PromptConfig

    config = PromptConfig()
    assert config is not None


# ------------------------------------------------------------------ #
# file_handling
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_single_line_log_value() -> None:
    """single_line_log_value collapses newlines."""
    from qwenpaw.agents.utils.file_handling import (
        single_line_log_value,
    )

    assert "\n" not in single_line_log_value("a\nb")


@pytest.mark.integration
@pytest.mark.p1
def test_decode_text_bytes_fallback() -> None:
    """decode_text_bytes_with_encoding_fallback decodes utf-8."""
    from qwenpaw.agents.utils.file_handling import (
        decode_text_bytes_with_encoding_fallback,
    )

    text = decode_text_bytes_with_encoding_fallback(
        "hello".encode("utf-8"),
    )
    assert text == "hello"


@pytest.mark.integration
@pytest.mark.p1
def test_read_text_file_fallback(tmp_path) -> None:
    """read_text_file_with_encoding_fallback reads a utf-8 file."""
    from qwenpaw.agents.utils.file_handling import (
        read_text_file_with_encoding_fallback,
    )

    f = tmp_path / "x.txt"
    f.write_text("content", encoding="utf-8")
    assert read_text_file_with_encoding_fallback(f) == "content"
