"""Original WeCom media matrix plus actual SDK downloads and native routes."""

from pathlib import Path

import pytest
import pytest_asyncio
from aiohttp import web

pytest.register_assert_rewrite("wecom_native_support")
from wecom_native_support import (  # noqa: E402
    ingress,
    send,
    text_frame,
    eventually,
)

pytest_plugins = ["wecom_native_support"]


async def proactive(native):
    driver, peer, identity, server = native
    result = await peer.methods["channel.response.open"](
        {
            **identity,
            "to_handle": "wecom:user_123",
            "meta": {"wecom_chatid": "chat_456"},
        },
        None,
    )
    return result["response_handle"]


@pytest.mark.parametrize("source_type", ["data", "path", "file_url"])
async def test_file_display_name_reaches_upload_init(
    wecom_native, tmp_path, source_type
):
    driver, peer, identity, server = wecom_native
    local_file = tmp_path / "local.pdf"
    local_file.write_bytes(b"pdf-data")
    sources = {
        "data": "data:application/pdf;base64,cGRmLWRhdGE=",
        "path": str(local_file),
        "file_url": local_file.as_uri(),
    }
    handle = await proactive(wecom_native)
    result = await send(
        wecom_native,
        handle,
        content_parts=[
            {
                "type": "file",
                "file_url": sources[source_type],
                "filename": "report.pdf",
            }
        ],
    )
    assert result["state"] == "acknowledged"
    init = server.rows("aibot_upload_media_init")[0]["body"]
    expected = "report.pdf" if source_type == "data" else "local.pdf"
    assert init["filename"] == expected
    assert init["total_size"] == 8
    assert len(server.rows("aibot_upload_media_init")) == 1
    assert len(server.rows("aibot_send_msg")) == 1
    assert local_file.read_bytes() == b"pdf-data"
    if source_type == "data":
        assert not list(driver._platform._media_dir.iterdir())
    else:
        assert not driver._platform._media_dir.exists()


@pytest_asyncio.fixture
async def media_http():
    requests = []
    app = web.Application()

    async def respond(request):
        requests.append(request.path)
        if request.path == "/missing":
            return web.Response(status=404)
        return web.Response(
            body=b"native-media-bytes",
            headers={
                "Content-Disposition": 'attachment; filename="source.bin"',
            },
        )

    app.router.add_get("/{name}", respond)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        yield "http://127.0.0.1:" + str(port), requests
    finally:
        await runner.cleanup()


async def test_native_media_download_mixed_voice_diagnostics_and_dedup(
    wecom_native, media_http
):
    driver, peer, identity, server = wecom_native
    base, requests = media_http
    for kind in ("image", "file", "video"):
        frame = text_frame("download-" + kind)
        frame["body"]["msgtype"] = kind
        frame["body"][kind] = {"url": base + "/" + kind}
        before = len(peer.batches)
        event = await ingress(wecom_native, frame)
        assert len(peer.batches) == before + 1
        assert requests.count("/" + kind) == 1
        part = event["content_parts"][0]
        assert part["type"] == kind
        path = Path(part[kind + "_url"])
        assert path.is_file() and path.read_bytes() == b"native-media-bytes"
        assert path.is_relative_to(driver._platform._media_dir)
    frame = text_frame("mixed")
    frame["body"].update(
        msgtype="mixed",
        mixed={
            "msg_item": [
                {"msgtype": "text", "text": {"content": "  mixed text  "}},
                {"msgtype": "image", "image": {"url": base + "/mixed"}},
            ]
        },
    )
    before = len(peer.batches)
    event = await ingress(wecom_native, frame)
    assert len(peer.batches) == before + 1
    assert len(event["content_parts"]) >= 2
    assert event["content_parts"][0] == {"type": "text", "text": "mixed text"}
    assert event["content_parts"][1]["type"] == "image"
    assert requests.count("/mixed") == 1
    await eventually(
        lambda: "wecom:mixed" in driver._platform._processed_message_ids
    )
    # Actual duplicate decoder/Driver path for the accepted native frame.
    before = len(peer.batches)
    assert await driver._platform._on_message(frame) is True
    assert len(peer.batches) == before
    assert requests.count("/mixed") == 1
    for kind, data, expected in [
        ("voice", {"content": "recognized voice"}, "recognized voice"),
        ("unknown_type", {}, "unknown_type"),
        ("image", {}, "no url"),
        ("voice", {}, "no text"),
        ("image", {"url": base + "/missing"}, "download failed"),
    ]:
        frame = text_frame("diagnostic-" + expected)
        frame["body"].update(msgtype=kind)
        frame["body"][kind] = data
        before = len(peer.batches)
        event = await ingress(wecom_native, frame)
        assert len(peer.batches) == before + 1
        assert expected in event["content_parts"][0]["text"]
    assert requests.count("/missing") == 1


async def test_native_welcome_empty_welcome_prefix_proactive_and_empty_text(
    wecom_native,
):
    driver, peer, identity, server = wecom_native
    platform = driver._platform
    enter = {
        "cmd": "aibot_event_callback",
        "headers": {"req_id": "welcome"},
        "body": {
            "msgtype": "event",
            "event": {"eventtype": "enter_chat"},
            "from": {"userid": "sender-A"},
        },
    }
    platform.config["welcome_text"] = "Welcome!"
    server.push(enter)
    await eventually(
        lambda: len(server.rows("aibot_respond_welcome_msg")) == 1
    )
    assert server.rows("aibot_respond_welcome_msg")[0] == {
        "cmd": "aibot_respond_welcome_msg",
        "headers": {"req_id": "welcome"},
        "body": {"msgtype": "text", "text": {"content": "Welcome!"}},
    }
    platform.config["welcome_text"] = ""
    enter["headers"]["req_id"] = "no-welcome"
    server.push(enter)
    event = await ingress(wecom_native, text_frame("after-empty-welcome"))
    assert len(server.rows("aibot_respond_welcome_msg")) == 1
    assert peer.batches[-1]["events"][0] == event
    before = list(server.rows("aibot_respond_msg"))
    empty = await send(
        wecom_native,
        event["response_handle"],
        delivery="empty",
        content_parts=[{"type": "text", "text": ""}],
    )
    assert empty["state"] == "acknowledged"
    assert server.rows("aibot_respond_msg") == before
    platform.config["bot_prefix"] = "[Bot]"
    result = await send(
        wecom_native,
        event["response_handle"],
        delivery="prefix",
        content_parts=[{"type": "text", "text": "Hello"}],
    )
    assert result["state"] == "acknowledged"
    assert (
        server.rows("aibot_respond_msg")[-1]["body"]["stream"]["content"]
        == "[Bot]  Hello"
    )
    handle = await proactive(wecom_native)
    assert (
        await send(
            wecom_native,
            handle,
            delivery="proactive",
            content_parts=[{"type": "text", "text": "Hello"}],
        )
    )["state"] == "acknowledged"
    assert server.rows("aibot_send_msg")[-1]["body"] == {
        "chatid": "chat_456",
        "msgtype": "markdown",
        "markdown": {"content": "[Bot]  Hello"},
    }
    assert (
        await send(
            wecom_native,
            handle,
            delivery="direct",
            content_source="direct",
            content_parts=[{"type": "text", "text": "Hello World"}],
        )
    )["state"] == "acknowledged"
    assert server.rows("aibot_send_msg")[-1]["body"] == {
        "chatid": "chat_456",
        "msgtype": "markdown",
        "markdown": {"content": "[Bot]Hello World"},
    }
    assert len(server.rows("aibot_send_msg")) == 2
