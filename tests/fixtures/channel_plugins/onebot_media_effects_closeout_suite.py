"""Old outgoing media effects through real private Driver and reverse WS."""

import asyncio

import aiohttp
import pytest

from onebot_native_suite import driver_at, ws_url
from qwenpaw.channel_protocol.models import SendParams


@pytest.mark.parametrize(
    ("target", "part", "action", "parameters"),
    [
        (
            "12345",
            {"type": "image", "image_url": "https://img.example.com/pic.png"},
            "send_private_msg",
            {
                "user_id": 12345,
                "message": [
                    {
                        "type": "image",
                        "data": {"file": "https://img.example.com/pic.png"},
                    }
                ],
            },
        ),
        (
            "12345",
            {"type": "audio", "data": "https://a.com/v.mp3"},
            "send_private_msg",
            {
                "user_id": 12345,
                "message": [
                    {"type": "record", "data": {"file": "https://a.com/v.mp3"}}
                ],
            },
        ),
        (
            "12345",
            {"type": "video", "video_url": "https://v.com/v.mp4"},
            "send_private_msg",
            {
                "user_id": 12345,
                "message": [
                    {"type": "video", "data": {"file": "https://v.com/v.mp4"}}
                ],
            },
        ),
        (
            "group:67890",
            {
                "type": "file",
                "file_url": "https://f.com/report.xlsx",
                "filename": "report.xlsx",
            },
            "upload_group_file",
            {
                "group_id": 67890,
                "file": "https://f.com/report.xlsx",
                "name": "report.xlsx",
            },
        ),
        (
            "12345",
            {"type": "file", "file_url": "LOCAL", "filename": "report.txt"},
            "upload_private_file",
            {
                "user_id": 12345,
                "file": "base64://ZmFrZQ==",
                "name": "report.txt",
            },
        ),
        (
            "group:67890",
            {"type": "image", "image_url": "https://img.example.com/pic.png"},
            "send_group_msg",
            {
                "group_id": 67890,
                "message": [
                    {
                        "type": "image",
                        "data": {"file": "https://img.example.com/pic.png"},
                    }
                ],
            },
        ),
    ],
    ids=[
        "image",
        "audio",
        "video",
        "group-file",
        "local-base64",
        "group-image",
    ],
)
async def test_original_media_exact_native_effect(
    tmp_path,
    target,
    part,
    action,
    parameters,
):
    part = dict(part)
    if part.get("file_url") == "LOCAL":
        local = tmp_path / "report.txt"
        local.write_bytes(b"fake")
        part["file_url"] = local.as_uri()
    async with driver_at(tmp_path, media_base64=True) as (
        driver,
        peer,
        identity,
    ):
        async with aiohttp.ClientSession() as client:
            async with client.ws_connect(ws_url(driver._platform)) as ws:
                route = await peer.methods["channel.response.open"](
                    {**identity, "to_handle": target, "meta": {}},
                    None,
                )
                params = SendParams.from_mapping(
                    {
                        **identity,
                        "to_handle": route["response_handle"],
                        "delivery_id": "old-media",
                        "operation": "message.create",
                        "content_parts": [part],
                    }
                )
                send = asyncio.create_task(
                    peer.methods["channel.send"](params, None)
                )
                try:
                    frame = await asyncio.wait_for(ws.receive_json(), 1)
                    assert frame["action"] == action
                    assert frame["params"] == parameters
                    await ws.send_json(
                        {"retcode": 0, "data": {}, "echo": frame["echo"]}
                    )
                    assert (await asyncio.wait_for(send, 1))[
                        "state"
                    ] == "acknowledged"
                    with pytest.raises(asyncio.TimeoutError):
                        await asyncio.wait_for(ws.receive_json(), 0.05)
                finally:
                    if not send.done():
                        send.cancel()
                    await asyncio.gather(send, return_exceptions=True)


async def test_empty_native_parts_have_zero_effect_and_closed_dto_rejects_file(
    tmp_path,
):
    async with driver_at(tmp_path) as (driver, peer, identity):
        async with aiohttp.ClientSession() as client:
            async with client.ws_connect(ws_url(driver._platform)) as ws:
                # Native empty behavior retained; the public DTO is stricter.
                result = await driver._platform.send_message(
                    "12345",
                    [
                        {"type": "text", "text": ""},
                        {"type": "file", "file_url": ""},
                    ],
                )
                assert result == {"api_calls": "0", "native_message_ids": "[]"}
                with pytest.raises(ValueError):
                    SendParams.from_mapping(
                        {
                            **identity,
                            "to_handle": "12345",
                            "delivery_id": "empty",
                            "operation": "message.create",
                            "content_parts": [
                                {"type": "file", "file_url": ""}
                            ],
                        }
                    )
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(ws.receive_json(), 0.05)
