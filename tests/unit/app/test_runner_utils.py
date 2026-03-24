# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from copaw.app.message_filters import filter_runtime_messages


def _build_message(message_type: str, text: str) -> SimpleNamespace:
    return SimpleNamespace(
        type=message_type,
        content=[SimpleNamespace(text=text)],
    )


def test_console_config_hides_thinking_by_default() -> None:
    config_source = Path("src/copaw/config/config.py").read_text(
        encoding="utf-8",
    )

    assert "class ConsoleConfig(BaseChannelConfig):" in config_source
    assert "filter_thinking: bool = True" in config_source


def test_filter_runtime_messages_removes_reasoning_messages() -> None:
    messages = [
        _build_message("message", "final answer"),
        _build_message("reasoning", "hidden reasoning"),
    ]

    filtered = filter_runtime_messages(messages, filter_thinking=True)

    assert [message.type for message in filtered] == ["message"]
    assert filtered[0].content[0].text == "final answer"


def test_filter_runtime_messages_keeps_reasoning_when_disabled() -> None:
    messages = [
        _build_message("message", "final answer"),
        _build_message("reasoning", "visible reasoning"),
    ]

    filtered = filter_runtime_messages(messages, filter_thinking=False)

    assert [message.type for message in filtered] == ["message", "reasoning"]
