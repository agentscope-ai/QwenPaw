# -*- coding: utf-8 -*-
"""Dispatch compatibility for channels with their own ``send_event``.

``ChannelManager`` hands a per-turn delivery mapping to channels so a
one-line notice is sent once per user turn. That mapping is optional:
a channel may override ``send_event`` with the original four arguments, and
passing the extra keyword to such a channel turns every ordinary dispatch
into a ``TypeError``.
"""

import pytest

from qwenpaw.app.channels.manager import ChannelManager, _accepts_dispatched


class _LegacyChannel:
    """Channel written against the original ``send_event`` signature."""

    def __init__(self) -> None:
        self.seen: dict | None = None

    async def send_event(self, *, user_id, session_id, event, meta=None):
        self.seen = {
            "user_id": user_id,
            "session_id": session_id,
            "event": event,
            "meta": meta,
        }


class _ModernChannel:
    """Channel that declares the per-turn delivery mapping."""

    def __init__(self) -> None:
        self.seen: dict | None = None

    async def send_event(
        self,
        *,
        user_id,
        session_id,
        event,
        meta=None,
        dispatched=None,
    ):
        self.seen = dispatched


def _manager_for(channel):
    manager = object.__new__(ChannelManager)

    async def get_channel(name):
        return channel

    manager.get_channel = get_channel
    return manager


@pytest.mark.asyncio
async def test_a_legacy_channel_never_receives_the_turn_mapping() -> None:
    """The four-argument override keeps working, notice or no notice."""
    channel = _LegacyChannel()
    manager = _manager_for(channel)
    event = object()
    turn: dict = {}

    await manager.send_event(
        channel="qq",
        user_id="u",
        session_id="s",
        event=event,
        meta={},
        dispatched=turn,
    )

    assert channel.seen is not None
    assert channel.seen["event"] is event
    assert channel.seen["meta"] == {"session_id": "s", "user_id": "u"}
    # Nothing consumed the turn state: that channel has no deduplication.
    assert turn == {}


@pytest.mark.asyncio
async def test_a_channel_that_declares_the_mapping_receives_it() -> None:
    """A channel that opts in still gets the one-notice-per-turn state."""
    channel = _ModernChannel()
    manager = _manager_for(channel)
    turn: dict = {}

    await manager.send_event(
        channel="qq",
        user_id="u",
        session_id="s",
        event=object(),
        meta={},
        dispatched=turn,
    )

    assert channel.seen is turn


class _ForwardingChannel:
    """Channel that forwards ``**kwargs`` to ``BaseChannel.send_event``.

    Forwarding is the usual way to tweak one behaviour without restating the
    signature, so it accepts the per-turn mapping even though it never names
    it. Treating that as "no support" silently dropped the deduplication.
    """

    def __init__(self) -> None:
        self.seen: dict | None = None

    async def send_event(self, **kwargs):
        self.seen = kwargs


@pytest.mark.asyncio
async def test_a_forwarding_channel_still_gets_the_turn_mapping() -> None:
    """``**kwargs`` overrides keep one notice per turn."""
    channel = _ForwardingChannel()
    manager = _manager_for(channel)
    turn: dict = {}

    await manager.send_event(
        channel="qq",
        user_id="u",
        session_id="s",
        event=object(),
        meta={},
        dispatched=turn,
    )

    assert channel.seen is not None
    assert channel.seen["dispatched"] is turn


class _ArgsKwargsChannel:
    """Channel that pipes positional and keyword arguments through."""

    def __init__(self) -> None:
        self.seen: dict | None = None

    async def send_event(self, *args, **kwargs):
        self.seen = kwargs


class _NoSendEvent:
    """A channel shape that cannot receive events at all."""


@pytest.mark.asyncio
async def test_an_args_kwargs_override_also_gets_the_turn_mapping() -> None:
    channel = _ArgsKwargsChannel()
    manager = _manager_for(channel)
    turn: dict = {}

    await manager.send_event(
        channel="qq",
        user_id="u",
        session_id="s",
        event=object(),
        meta={},
        dispatched=turn,
    )

    assert channel.seen is not None
    assert channel.seen["dispatched"] is turn


def test_a_channel_without_send_event_is_rejected() -> None:
    """Probing must answer ``False`` instead of raising for an odd shape."""
    assert _accepts_dispatched(_NoSendEvent()) is False
