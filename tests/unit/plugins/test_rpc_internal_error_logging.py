# -*- coding: utf-8 -*-
"""Internal handler failures in the RPC peer must be logged."""

from __future__ import annotations

import logging

from qwenpaw.plugins.execution.models import RpcRequest
from qwenpaw.plugins.execution.rpc import RpcPeer, _RequestCancellation


class _FakeTransport:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(
        self,
        payload: str,
        *args: object,
        **kwargs: object,
    ) -> None:
        self.sent.append(payload)


async def test_handler_exception_is_logged_and_error_returned(caplog) -> None:
    transport = _FakeTransport()
    peer = RpcPeer(transport, params_validator=lambda _m, p: p)

    def boom(_params: object, _request: object) -> object:
        raise RuntimeError("plugin handler exploded")

    peer.register_method("demo", boom)
    with caplog.at_level(logging.ERROR):
        await peer._dispatch_request(  # pylint: disable=protected-access
            RpcRequest(id=1, method="demo", params={}),
            _RequestCancellation(),
        )

    assert any("INTERNAL_ERROR" in sent for sent in transport.sent)
    assert any(
        "plugin handler exploded" in (r.exc_text or r.getMessage())
        for r in caplog.records
    )
