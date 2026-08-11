# -*- coding: utf-8 -*-
"""Reading the persisted per-chat project-dirs override on every turn.

The override lives on the chat, so the hook must re-read it every turn:
this is what keeps session-level directories in effect after the turn
that set them.
"""
# pylint: disable=protected-access
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.hooks.request_setup.contextvars_hook import _session_project_dirs


class _ChatManager:
    """Mirrors the real signature, including the required `channel` arg."""

    def __init__(self, chat=None) -> None:
        self._chat = chat
        self.lookup_calls: list[tuple] = []

    async def get_chat_id_by_session(
        self,
        session_id: str,
        channel: str,
        user_id: str | None = None,
    ) -> str | None:
        self.lookup_calls.append((session_id, channel, user_id))
        return self._chat.id if self._chat else None

    async def get_chat(self, chat_id: str):
        if self._chat and self._chat.id == chat_id:
            return self._chat
        return None


def _ctx(chat_manager, *, session_id="console:u1", channel="console"):
    return SimpleNamespace(
        session_id=session_id,
        workspace=SimpleNamespace(chat_manager=chat_manager),
        request=SimpleNamespace(channel=channel, user_id="u1"),
    )


def _chat(entries: list[dict] | None):
    meta = {}
    if entries is not None:
        meta["runtime_context"] = {"project_dirs": entries}
    return SimpleNamespace(id="chat-1", meta=meta)


_CHOSEN = [{"path": "/repos/chosen", "label": None}]


@pytest.mark.asyncio
async def test_reads_the_persisted_override():
    """The whole point: this must work on turn 2, 3, 4 … not just turn 1."""
    manager = _ChatManager(_chat(_CHOSEN))

    result = await _session_project_dirs(_ctx(manager))

    assert result == [
        {"path": str(Path("/repos/chosen")), "label": None},
    ]


@pytest.mark.asyncio
async def test_passes_channel_to_the_lookup():
    """`channel` is a required positional arg; omitting it finds nothing."""
    manager = _ChatManager(_chat(_CHOSEN))

    await _session_project_dirs(_ctx(manager, channel="console"))

    assert manager.lookup_calls == [("console:u1", "console", "u1")]


@pytest.mark.asyncio
async def test_returns_none_when_chat_has_no_override():
    manager = _ChatManager(_chat(None))
    assert await _session_project_dirs(_ctx(manager)) is None


@pytest.mark.asyncio
async def test_returns_none_when_no_chat_matches():
    manager = _ChatManager(None)
    assert await _session_project_dirs(_ctx(manager)) is None


@pytest.mark.asyncio
async def test_returns_none_without_a_session_id():
    manager = _ChatManager(_chat(_CHOSEN))
    assert await _session_project_dirs(_ctx(manager, session_id="")) is None


@pytest.mark.asyncio
async def test_returns_none_without_a_chat_manager():
    ctx = SimpleNamespace(
        session_id="console:u1",
        workspace=SimpleNamespace(chat_manager=None),
        request=SimpleNamespace(channel="console", user_id="u1"),
    )
    assert await _session_project_dirs(ctx) is None


@pytest.mark.asyncio
async def test_legacy_single_value_is_wrapped():
    """Singular-era chats stored one path under project_dir."""
    chat = SimpleNamespace(
        id="chat-1",
        meta={"runtime_context": {"project_dir": "/repos/legacy"}},
    )
    manager = _ChatManager(chat)

    result = await _session_project_dirs(_ctx(manager))

    assert result == [
        {"path": str(Path("/repos/legacy")), "label": None},
    ]


@pytest.mark.asyncio
async def test_lookup_failure_is_logged_loudly(caplog):
    """A broken lookup silently degrades behaviour, so it must be visible."""

    class _Broken(_ChatManager):
        async def get_chat_id_by_session(self, *args, **kwargs):
            raise RuntimeError("repo unavailable")

    with caplog.at_level("WARNING"):
        result = await _session_project_dirs(_ctx(_Broken()))

    assert result is None
    assert any(
        record.levelname == "WARNING" for record in caplog.records
    ), "a failed session-override lookup must warn, not whisper at debug"


@pytest.mark.asyncio
async def test_missing_channel_falls_back_to_default_channel():
    """Cron/heartbeat turns may not carry a channel on the request."""
    manager = _ChatManager(_chat(_CHOSEN))
    ctx = SimpleNamespace(
        session_id="console:u1",
        workspace=SimpleNamespace(chat_manager=manager),
        request=SimpleNamespace(channel=None, user_id=None),
    )

    result = await _session_project_dirs(ctx)

    assert result == [
        {"path": str(Path("/repos/chosen")), "label": None},
    ]
    assert manager.lookup_calls[0][1], "a channel must still be supplied"
