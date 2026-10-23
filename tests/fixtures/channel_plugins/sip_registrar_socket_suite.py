"""Real loopback registrar socket lifetime; no external telephone service."""

import asyncio
import importlib.util
from pathlib import Path
import socket

import pytest


async def test_loopback_register_unregister_collision_and_stop_release():
    path = (
        Path(__file__).resolve().parents[3]
        / "plugins/channel/sip/qwenpaw_channel_sip/mini_registrar.py"
    )
    spec = importlib.util.spec_from_file_location("sip_registrar_native", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    registrar = module.MiniRegistrar(port=0)
    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client.bind(("127.0.0.1", 0))
    client.setblocking(False)
    loop = asyncio.get_running_loop()
    await registrar.start()
    address = registrar._transport.get_extra_info("sockname")
    assert address[0] == "127.0.0.1" and address[1] > 0
    try:
        for sequence, expires in ((1, 60), (2, 0)):
            headers = [
                "Via: SIP/2.0/UDP 127.0.0.1;branch=controlled",
                "From: <sip:alice@localhost>;tag=one",
                "To: <sip:alice@localhost>",
                "Call-ID: actual-udp-register",
                f"CSeq: {sequence} REGISTER",
            ]
            request = "\r\n".join(
                [
                    "REGISTER sip:localhost SIP/2.0",
                    *headers,
                    f"Expires: {expires}",
                    "Content-Length: 0",
                    "",
                    "",
                ]
            ).encode()
            await loop.sock_sendto(client, request, address)
            data, sender = await asyncio.wait_for(
                loop.sock_recvfrom(client, 4096), timeout=8
            )
            assert sender == address
            assert (
                data
                == "\r\n".join(
                    ["SIP/2.0 200 OK", *headers, "Content-Length: 0", "", ""]
                ).encode()
            )
            if expires:
                assert registrar._protocol.registry["alice"][0] == (
                    client.getsockname()
                )
            else:
                assert registrar._protocol.registry == {}
        collision = module.MiniRegistrar(port=address[1])
        with pytest.raises(OSError):
            await collision.start()
        assert collision._transport is None
    finally:
        await registrar.stop()
        client.close()
    assert registrar._transport is None
    assert registrar._protocol.closed.done()
    replacement = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        replacement.bind(address)
        assert replacement.getsockname() == address
    finally:
        replacement.close()
