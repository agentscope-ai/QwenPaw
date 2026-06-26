# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Unit tests for ChannelManager channel construction."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from qwenpaw.app.channels import manager as manager_module
from qwenpaw.app.channels.base import BaseChannel
from qwenpaw.app.channels.manager import ChannelManager
from qwenpaw.schemas import ContentType, ImageContent


class _ConfigurableChannel(BaseChannel):
    """Minimal channel used to verify manager-level config wiring."""

    channel = "configurable"

    @classmethod
    def from_config(
        cls,
        process,
        config,
        on_reply_sent=None,
        show_tool_details=True,
        filter_tool_messages=False,
        filter_thinking=False,
    ):
        channel = cls(
            process=process,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
        )
        channel.enabled = getattr(config, "enabled", False)
        return channel

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send(self, to_handle: str, text: str, meta=None) -> None:
        del to_handle, text, meta


@pytest.fixture
def mock_process():
    async def _process(_request: Any):
        yield None

    return _process


def test_from_config_applies_no_text_debounce_toggle(
    monkeypatch,
    mock_process,
):
    """Manager should apply the common no-text debounce toggle."""
    monkeypatch.setattr(
        manager_module,
        "get_available_channels",
        lambda: ["configurable"],
    )
    monkeypatch.setattr(
        manager_module,
        "get_channel_registry",
        lambda: {"configurable": _ConfigurableChannel},
    )
    config = SimpleNamespace(
        show_tool_details=True,
        channels=SimpleNamespace(
            configurable={
                "enabled": True,
                "no_text_debounce_enabled": False,
            },
        ),
    )

    manager = ChannelManager.from_config(mock_process, config)

    assert len(manager.channels) == 1
    channel = manager.channels[0]
    parts = [
        ImageContent(
            type=ContentType.IMAGE,
            image_url="https://example.com/image.png",
        ),
    ]
    should_process, merged = channel._apply_no_text_debounce(
        "session_1",
        parts,
    )

    assert should_process is True
    assert merged == parts
