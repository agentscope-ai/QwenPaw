# -*- coding: utf-8 -*-
"""A late cancel must not tear down a completed ordinary response frame."""

import asyncio

import pytest

from qwenpaw.plugins.execution.errors import RpcError
from qwenpaw.plugins.execution.framing import FramedTransport
from qwenpaw.plugins.execution.rpc import RpcPeer


class HeldDrain:
    """Real socket writer with a gate after the first visible write."""

    def __init__(self, writer):
        self.writer = writer
        self.entered, self.release = asyncio.Event(), asyncio.Event()

    def __getattr__(self, name):
        return getattr(self.writer, name)

    async def drain(self):
        await self.writer.drain()
        if not self.entered.is_set():
            self.entered.set()
            await self.release.wait()


@pytest.mark.asyncio
@pytest.mark.parametrize("reply_error", [False, True])
async def test_late_cancel_during_reply_drain_preserves_connection(
    reply_error,
):
    accepted = asyncio.get_running_loop().create_future()
    seen = asyncio.Event()

    class ObservedPeer(RpcPeer):
        def _cancel_incoming(self, params):
            super()._cancel_incoming(params)
            seen.set()

    listener = await asyncio.start_server(
        lambda reader, writer: accepted.set_result((reader, writer)),
        "127.0.0.1",
        0,
    )
    client = server = held = None
    calls = []
    try:
        reader, writer = await asyncio.open_connection(
            "127.0.0.1",
            listener.sockets[0].getsockname()[1],
        )
        remote_reader, remote_writer = await accepted
        held = HeldDrain(remote_writer)
        server = ObservedPeer(FramedTransport(remote_reader, held))
        client = RpcPeer(FramedTransport(reader, writer))

        async def respond(params, request):
            calls.append(request.id)
            if reply_error and request.id == "first":
                raise RpcError(-32000, "expected rejection")
            return {"id": request.id}

        server.register_method("example.echo", respond)
        await server.start()
        await client.start()
        if reply_error:
            with pytest.raises(RpcError, match="expected rejection"):
                await client.call(
                    "example.echo",
                    {},
                    request_id="first",
                    timeout=2,
                )
        else:
            assert await client.call(
                "example.echo",
                {},
                request_id="first",
                timeout=2,
            ) == {"id": "first"}
        await asyncio.wait_for(held.entered.wait(), 2)
        await client.notify(
            "request.cancel",
            {"request_id": "first", "reason": "caller_cancelled"},
        )
        await asyncio.wait_for(seen.wait(), 2)
        held.release.set()
        assert await client.call(
            "example.echo",
            {},
            request_id="second",
            timeout=2,
        ) == {"id": "second"}
        assert calls == ["first", "second"]
        assert not client.is_closed and not server.is_closed
    finally:
        if held:
            held.release.set()
        await asyncio.gather(
            *(peer.aclose() for peer in (client, server) if peer),
        )
        listener.close()
        await listener.wait_closed()
