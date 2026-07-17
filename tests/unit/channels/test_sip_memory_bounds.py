# -*- coding: utf-8 -*-
"""Regression tests for bounded SIP channel state."""
# pylint: disable=missing-function-docstring,protected-access
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from qwenpaw.app.channels.sip.livekit_backend import (
    _put_latest_audio as lk_put,
)
from qwenpaw.app.channels.sip.mini_registrar import _SIPProxy
from qwenpaw.app.channels.sip.pyvoip_backend import (
    _put_latest_audio as voip_put,
)


def test_audio_queue_discards_oldest_frame() -> None:
    queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=2)
    queue.put_nowait(b"old")
    queue.put_nowait(b"recent")

    lk_put(queue, b"latest")

    assert list(queue._queue) == [b"recent", b"latest"]


def test_audio_queue_keeps_end_marker_when_full() -> None:
    queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=1)
    queue.put_nowait(b"stale")

    voip_put(queue, None)

    assert queue.get_nowait() is None


def test_registrar_honors_unregister_and_keeps_response_route() -> None:
    proxy = _SIPProxy()
    transport = MagicMock()
    proxy.connection_made(transport)
    address = ("127.0.0.1", 5062)
    register = "REGISTER sip:test SIP/2.0\r\nTo: <sip:alice@test>\r\n\r\n"
    proxy._register(register, address)
    assert proxy.registry["alice"][0] == address

    unregister = (
        "REGISTER sip:test SIP/2.0\r\nTo: <sip:alice@test>\r\n"
        "Expires: 0\r\n\r\n"
    )
    proxy._register(unregister, address)
    assert "alice" not in proxy.registry

    proxy.transactions["call-1"] = (address, float("inf"))
    response = "SIP/2.0 200 OK\r\nCall-ID: call-1\r\n\r\n"
    proxy._forward_response(response, ("127.0.0.1", 5063))
    proxy._forward_response(response, ("127.0.0.1", 5063))

    assert "call-1" in proxy.transactions
    assert transport.sendto.call_count == 4


def test_stale_unregister_does_not_remove_new_registration() -> None:
    proxy = _SIPProxy()
    proxy.connection_made(MagicMock())
    old_address = ("127.0.0.1", 5062)
    new_address = ("127.0.0.1", 5063)
    register = "REGISTER sip:test SIP/2.0\r\nTo: <sip:alice@test>\r\n\r\n"
    unregister = (
        "REGISTER sip:test SIP/2.0\r\nTo: <sip:alice@test>\r\n"
        "Expires: 0\r\n\r\n"
    )

    proxy._register(register, old_address)
    proxy._register(register, new_address)
    proxy._register(unregister, old_address)

    assert proxy.registry["alice"][0] == new_address


def test_registrar_honors_contact_expires_unregister() -> None:
    proxy = _SIPProxy()
    proxy.connection_made(MagicMock())
    address = ("127.0.0.1", 5062)
    register = "REGISTER sip:test SIP/2.0\r\nTo: <sip:alice@test>\r\n\r\n"
    unregister = (
        "REGISTER sip:test SIP/2.0\r\nTo: <sip:alice@test>\r\n"
        "Contact: <sip:alice@127.0.0.1>;expires=0\r\n\r\n"
    )

    proxy._register(register, address)
    proxy._register(unregister, address)

    assert "alice" not in proxy.registry
