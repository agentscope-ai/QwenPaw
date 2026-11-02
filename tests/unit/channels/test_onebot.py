# -*- coding: utf-8 -*-
"""OneBot authenticated reverse WebSocket and real native deliveries."""
import asyncio
from contextlib import asynccontextmanager
import socket
from pathlib import Path
import aiohttp
import pytest
from qwenpaw.channel_protocol.models import SendParams
from tests.channel_support.driver import bind, module

pytestmark = pytest.mark.asyncio


async def until(check):
    async def poll():
        while not check():
            await asyncio.sleep(0.005)

    await asyncio.wait_for(poll(), 1)


def message(number, *, user=12345, group=None, text="hello"):
    value = {
        "post_type": "message",
        "message_type": "group" if group else "private",
        "message_id": number,
        "user_id": user,
        "self_id": 99999,
        "message": [{"type": "text", "data": {"text": text}}],
        "sender": {"nickname": "TestUser", "card": ""},
    }
    if group:
        value["group_id"] = group
    return value


def ws_url(platform, path="/ws"):
    host = platform.endpoint.host
    host = "[" + host + "]" if ":" in host else host
    return f"http://{host}:{platform.listen_port}{path}"


@asynccontextmanager
async def driver_at(tmp_path, **config):
    driver = module("onebot").OneBotDriver()
    peer, identity = bind("onebot", driver, tmp_path)
    try:
        await driver.start(
            {
                "enabled": True,
                "ws_host": "127.0.0.1",
                "ws_port": 0,
                "workspace_dir": str(tmp_path),
                **config,
            },
        )
        yield driver, peer, identity.to_mapping()
    finally:
        await driver.stop()


async def test_authenticated_websocket_accepts_valid_token(tmp_path):
    async with driver_at(tmp_path, access_token="secret") as (
        driver,
        peer,
        identity,
    ):
        async with aiohttp.ClientSession() as client:
            with pytest.raises(aiohttp.WSServerHandshakeError) as rejected:
                await client.ws_connect(ws_url(driver._platform))
            assert rejected.value.status == 401
            async with client.ws_connect(
                ws_url(driver._platform),
                headers={"Authorization": "Bearer secret"},
            ) as ws:
                await ws.send_json(message(1))
                await until(lambda: peer.batches)
                assert peer.batches[0]["events"][0]["sender_id"] == "12345"


@pytest.mark.parametrize(
    ("group", "share", "session"),
    [
        (None, False, "onebot:12345"),
        (67890, False, "onebot:67890:12345"),
        (67890, True, "onebot:g:67890"),
    ],
)
async def test_real_driver_acl_session_stable_event_and_route(
    tmp_path,
    group,
    share,
    session,
):
    async with driver_at(tmp_path, share_session_in_group=share) as (
        driver,
        peer,
        identity,
    ):
        async with aiohttp.ClientSession() as client:
            async with client.ws_connect(ws_url(driver._platform)) as ws:
                event = message(101, group=group)
                await ws.send_json(event)
                await until(lambda: len(peer.batches) == 1)
                inbound = peer.batches[0]["events"][0]
                assert inbound["event_id"] == "onebot:message:101"
                assert (
                    inbound["sender_id"] == inbound["acl_sender_id"] == "12345"
                )
                assert inbound["metadata"]["session_id"] == session
                assert inbound["metadata"]["debounce_key"] == session
                assert inbound["content_parts"] == [
                    {"type": "text", "text": "hello"},
                ]
                await ws.send_json(event)
                await ws.send_json(message(102, group=group))
                await until(lambda: len(peer.batches) == 2)
                assert [
                    row["events"][0]["event_id"] for row in peer.batches
                ] == ["onebot:message:101", "onebot:message:102"]
                assert driver._route_attrs(inbound["response_handle"]) == {
                    "to_handle": "group:67890" if group else "12345",
                }


@pytest.mark.parametrize(
    "target,action,id_key",
    [
        ("12345", "send_private_msg", "user_id"),
        ("group:67890", "send_group_msg", "group_id"),
    ],
)
async def test_text_and_file_use_native_recipient(
    tmp_path,
    target,
    action,
    id_key,
):
    async with driver_at(tmp_path) as (driver, peer, identity):
        async with aiohttp.ClientSession() as client:
            async with client.ws_connect(ws_url(driver._platform)) as ws:
                opened = await peer.methods["channel.response.open"](
                    {**identity, "to_handle": target, "meta": {}},
                    None,
                )
                params = SendParams.from_mapping(
                    {
                        **identity,
                        "to_handle": opened["response_handle"],
                        "delivery_id": "reply",
                        "operation": "message.create",
                        "content_parts": [{"type": "text", "text": "answer"}],
                    },
                )
                sending = asyncio.create_task(
                    peer.methods["channel.send"](params, None),
                )
                frame = await asyncio.wait_for(ws.receive_json(), 1)
                assert frame["action"] == action
                assert frame["params"][id_key] == int(target.split(":")[-1])
                assert frame["params"]["message"] == [
                    {"type": "text", "data": {"text": "answer"}},
                ]
                await ws.send_json(
                    {
                        "echo": frame["echo"],
                        "retcode": 0,
                        "data": {"message_id": 900},
                    },
                )
                assert (await sending)["state"] == "acknowledged"
                document = tmp_path / "report.txt"
                document.write_text("file payload")
                media = SendParams.from_mapping(
                    {
                        **identity,
                        "to_handle": opened["response_handle"],
                        "delivery_id": "file",
                        "operation": "message.create",
                        "content_source": "media",
                        "content_parts": [
                            {
                                "type": "file",
                                "file_url": str(document),
                                "filename": "report.txt",
                            },
                        ],
                    },
                )
                sending = asyncio.create_task(
                    peer.methods["channel.send"](media, None),
                )
                frame = await asyncio.wait_for(ws.receive_json(), 1)
                assert frame["action"] == (
                    "upload_group_file"
                    if target.startswith("group:")
                    else "upload_private_file"
                )
                assert frame["params"][id_key] == int(target.split(":")[-1])
                assert (
                    Path(frame["params"]["file"]).read_text() == "file payload"
                )
                assert frame["params"]["name"] == "report.txt"
                await ws.send_json(
                    {"echo": frame["echo"], "retcode": 0, "data": {}},
                )
                assert (await sending)["state"] == "acknowledged"


async def test_stop_releases_listener_port_and_owned_tasks(tmp_path):
    async with driver_at(tmp_path) as (driver, peer, identity):
        platform = driver._platform
        port = platform.listen_port
        await driver.stop()
        assert platform.listen_port is None and driver._platform is None
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", port))
        assert peer.calls[-1][0] == "ingress.endpoint.unregister"
