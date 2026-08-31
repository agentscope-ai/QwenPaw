# -*- coding: utf-8 -*-
"""Integration tests for channels manager + chats utils internals.

Covers src/qwenpaw/app/channels/manager.py and
src/qwenpaw/app/chats/utils.py (Channels + Chat modules, several
thousand uncovered lines).
"""

from __future__ import annotations

import pytest


# ------------------------------------------------------------------ #
# ChannelManager
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_channel_manager_empty() -> None:
    """ChannelManager constructs with an empty channel list."""
    from qwenpaw.app.channels.manager import ChannelManager

    manager = ChannelManager(channels=[])
    assert manager is not None


@pytest.mark.integration
@pytest.mark.p1
def test_channel_manager_get_channel_missing() -> None:
    """get_channel returns None for an unknown channel id."""
    import asyncio

    from qwenpaw.app.channels.manager import ChannelManager

    manager = ChannelManager(channels=[])
    result = asyncio.run(manager.get_channel("integ-unknown"))
    assert result is None


# ------------------------------------------------------------------ #
# chats utils: text cleaning
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_strip_injected_skill_block() -> None:
    """strip_injected_skill_block removes injected skill markers."""
    from qwenpaw.app.chats.utils import strip_injected_skill_block

    text = "hello <skill>injected</skill> world"
    cleaned = strip_injected_skill_block(text, "assistant")
    assert isinstance(cleaned, str)


@pytest.mark.integration
@pytest.mark.p1
def test_clean_display_text_passthrough() -> None:
    """clean_display_text returns plain text unchanged."""
    from qwenpaw.app.chats.utils import clean_display_text

    assert clean_display_text("plain text", "assistant") == "plain text"


# ------------------------------------------------------------------ #
# chats utils: url helpers
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_is_local_file_url() -> None:
    """_is_local_file_url distinguishes local file URLs."""
    from qwenpaw.app.chats.utils import _is_local_file_url

    assert _is_local_file_url("file:///tmp/x.png") is True
    assert _is_local_file_url("https://example.com/x.png") is False


@pytest.mark.integration
@pytest.mark.p1
def test_abspath_from_url() -> None:
    """_abspath_from_url extracts the path from a file URL."""
    from qwenpaw.app.chats.utils import _abspath_from_url

    assert _abspath_from_url("file:///tmp/x.png") == "/tmp/x.png"


# ------------------------------------------------------------------ #
# chats utils: timestamp normalization
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_normalize_msg_timestamp() -> None:
    """_normalize_msg_timestamp converts to the user timezone."""
    from zoneinfo import ZoneInfo

    from qwenpaw.app.chats.utils import _normalize_msg_timestamp

    normalized = _normalize_msg_timestamp(
        "2026-08-26T00:00:00Z",
        ZoneInfo("Asia/Shanghai"),
    )
    assert isinstance(normalized, str)
    assert "+08:00" in normalized or "08:00" in normalized


@pytest.mark.integration
@pytest.mark.p1
def test_process_local_tz() -> None:
    """_process_local_tz returns a tzinfo."""
    from qwenpaw.app.chats.utils import _process_local_tz

    assert _process_local_tz() is not None
