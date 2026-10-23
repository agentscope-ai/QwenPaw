"""Retain original quote/media alignment through actual Driver and HTTP/WS."""

import asyncio
from pathlib import Path

import aiohttp
from aiohttp import web
import pytest

from onebot_native_suite import driver_at, message, until, ws_url


@pytest.mark.parametrize("kind", ["cq-image", "raw-image", "record", "files"])
async def test_quoted_media_markers_and_separate_file_ids(tmp_path, kind):
    bodies = {
        "pic.png": b"\x89PNG\r\n\x1a\nquoted image",
        "voice.amr": b"#!AMR\nquoted voice",
        "quoted.pdf": b"%PDF quoted-file-bytes",
        "current.pdf": b"%PDF current-file-bytes",
    }
    downloaded = []

    async def serve(request):
        name = request.match_info["name"]
        downloaded.append(name)
        return web.Response(body=bodies[name])

    app = web.Application()
    app.router.add_get("/{name}", serve)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    try:
        async with driver_at(tmp_path, require_mention=True) as (
            driver,
            peer,
            _,
        ):
            async with aiohttp.ClientSession() as client:
                async with client.ws_connect(ws_url(driver._platform)) as ws:
                    event = message(901, group=67890)
                    event["message"] = [
                        {"type": "reply", "data": {"id": "321"}},
                        {"type": "at", "data": {"qq": "99999"}},
                    ]
                    if kind == "files":
                        event["message"].append(
                            {
                                "type": "file",
                                "data": {
                                    "file": "current.pdf",
                                    "file_id": "current-file-id",
                                    "name": "current.pdf",
                                },
                            }
                        )
                        data = {
                            "message": [
                                {
                                    "type": "file",
                                    "data": {
                                        "file": "quoted.pdf",
                                        "file_id": "quoted-file-id",
                                        "name": "quoted.pdf",
                                    },
                                }
                            ]
                        }
                    elif kind == "record":
                        event["message"].append(
                            {"type": "text", "data": {"text": "what is it"}}
                        )
                        data = {
                            "message": [
                                {
                                    "type": "record",
                                    "data": {
                                        "file": "voice.amr",
                                        "url": base + "/voice.amr",
                                    },
                                }
                            ]
                        }
                    else:
                        event["message"].append(
                            {"type": "text", "data": {"text": "describe it"}}
                        )
                        cq = f"[CQ:image,file=pic.png,url={base}/pic.png]"
                        data = (
                            {"message": "[图片]", "raw_message": cq}
                            if kind == "raw-image"
                            else {"message": cq}
                        )
                    await ws.send_json(event)
                    action = await asyncio.wait_for(ws.receive_json(), 1)
                    assert action["action"] == "get_msg"
                    assert action["params"] == {"message_id": 321}
                    await ws.send_json(
                        {"retcode": 0, "data": data, "echo": action["echo"]}
                    )
                    if kind == "files":
                        for which in ("quoted", "current"):
                            action = await asyncio.wait_for(
                                ws.receive_json(), 1
                            )
                            assert action["action"] == "get_group_file_url"
                            assert action["params"] == {
                                "group_id": 67890,
                                "file_id": which + "-file-id",
                            }
                            await ws.send_json(
                                {
                                    "retcode": 0,
                                    "echo": action["echo"],
                                    "data": {"url": base + f"/{which}.pdf"},
                                }
                            )
                    await until(lambda: len(peer.batches) == 1)
                    inbound = peer.batches[0]["events"][0]
                    content = inbound["content_parts"]
                    assert len(content) == 5
                    assert content[0] == {
                        "type": "text",
                        "text": "[Quoted message]",
                    }
                    assert content[3] == {
                        "type": "text",
                        "text": "[Current message]",
                    }
                    if kind == "files":
                        assert content[1] == {
                            "type": "text",
                            "text": "[Quoted file message: quoted.pdf]",
                        }
                        assert (
                            content[2]["type"] == content[4]["type"] == "file"
                        )
                        assert content[2]["filename"] == "quoted.pdf"
                        assert content[4]["filename"] == "current.pdf"
                        for part, name in (
                            (content[2], "quoted.pdf"),
                            (content[4], "current.pdf"),
                        ):
                            path = Path(part["file_url"])
                            assert path.is_relative_to(tmp_path)
                            assert path.read_bytes() == bodies[name]
                        assert content[2]["file_url"] != content[4]["file_url"]
                        assert downloaded == ["quoted.pdf", "current.pdf"]
                    else:
                        voice = kind == "record"
                        name = "voice.amr" if voice else "pic.png"
                        assert content[1] == {
                            "type": "text",
                            "text": (
                                "[Quoted voice message]"
                                if voice
                                else "[Quoted image message]"
                            ),
                        }
                        assert content[2]["type"] == (
                            "audio" if voice else "image"
                        )
                        path = Path(
                            content[2]["data" if voice else "image_url"]
                        )
                        assert path.is_relative_to(tmp_path)
                        assert path.read_bytes() == bodies[name]
                        assert content[4] == {
                            "type": "text",
                            "text": "what is it" if voice else "describe it",
                        }
                        assert downloaded == [name]
                    assert inbound["acl_sender_id"] == "12345"
                    assert inbound["metadata"]["group_id"] == "67890"
                    assert (
                        inbound["metadata"]["session_id"]
                        == "onebot:67890:12345"
                    )
    finally:
        await runner.cleanup()
