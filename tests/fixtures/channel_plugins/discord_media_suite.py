"""Discord media bytes, workspace authorization and effect cleanup."""

import asyncio
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading

import psutil
import pytest

from discord_suite import forbid_host_sdk
from discord_support import (
    callback_done,
    discord,
    discord_sdk,
    eventually,
    fault_runtime,
    push,
    route,
    rows,
    runtime,
    send,
    set_mode,
)


def closed_files(sdk):
    path = sdk.work / "ledger.jsonl"
    return (
        [json.loads(line) for line in path.read_text().splitlines()]
        if path.exists()
        else []
    )


@pytest.fixture
def media_server():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(404 if self.path == "/missing" else 200)
            self.end_headers()
            self.wfile.write(b"http-bytes")

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,mime,filename,field",
    [
        ("image", "image/png", "a.png", "image_url"),
        ("video", "video/mp4", "v.mp4", "video_url"),
        ("audio", "audio/mpeg", "a.mp3", "data"),
        ("file", "application/pdf", "x.png", "file_url"),
    ],
)
async def test_inbound_media_preserves_bytes_type_and_authorized_workspace(
    runtime, discord_sdk, kind, mime, filename, field
):
    rt = await discord(runtime, discord_sdk)
    push(
        discord_sdk.work,
        text="look",
        attachments=[
            {
                "id": 9,
                "filename": filename,
                "content_type": mime,
                "data": "native-bytes",
            }
        ],
    )
    await eventually(lambda: len(rt.ws.requests) == 1)
    parts = rt.ws.requests[0].input[0].content
    assert len(parts) == 2
    assert parts[0].text == "look"
    assert parts[1].type == kind
    path = Path(getattr(parts[1], field))
    assert path.is_relative_to(rt.ws.workspace_dir / "media")
    assert path.read_bytes() == b"native-bytes"


@pytest.mark.asyncio
async def test_failed_attachment_does_not_drop_text_or_successful_media(
    runtime, discord_sdk
):
    rt = await discord(runtime, discord_sdk)
    push(
        discord_sdk.work,
        text="keep text",
        attachments=[
            {"id": 9, "failure": "broken"},
            {"id": 10, "filename": "../unsafe picture.png", "data": "good"},
        ],
    )
    await eventually(lambda: len(rt.ws.requests) == 1)
    parts = rt.ws.requests[0].input[0].content
    assert len(parts) == 2 and parts[0].text == "keep text"
    path = Path(parts[1].image_url)
    assert path.name == "10_..unsafepicture.png"
    assert path.read_bytes() == b"good"
    assert len(list((rt.ws.workspace_dir / "media").iterdir())) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,want",
    [
        ("", "acknowledged"),
        ("send-reject", "failed"),
        ("send-unknown", "unknown"),
    ],
)
async def test_data_url_display_filename_bytes_and_cleanup_on_every_result(
    runtime, discord_sdk, mode, want
):
    rt = await discord(runtime, discord_sdk)
    handle = await route(rt)
    set_mode(discord_sdk.work, mode)
    result = await send(
        rt,
        handle,
        parts=[
            {
                "type": "file",
                "file_url": "data:application/pdf;base64,cGRmLWRhdGE=",
                "filename": "report.pdf",
            }
        ],
    )
    assert result["state"] == want
    uploaded = rows(discord_sdk.work, "send")
    assert len(uploaded) == 1
    assert uploaded[0]["filename"] == "report.pdf"
    assert uploaded[0]["uploaded"] == list(b"pdf-data")
    assert uploaded[0]["file_open"] is True
    assert not Path(uploaded[0]["file_path"]).exists()
    assert closed_files(discord_sdk)[-1]["closed"] is True
    assert list((rt.ws.workspace_dir / "media").iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,field",
    [
        ("image", "image_url"),
        ("video", "video_url"),
        ("audio", "data"),
        ("file", "file_url"),
    ],
)
async def test_outbound_media_only_reads_authorized_local_bytes(
    runtime, discord_sdk, kind, field
):
    rt = await discord(runtime, discord_sdk)
    path = rt.ws.workspace_dir / "payload.dat"
    path.write_bytes(b"local-bytes")
    await rt.channel.send_content_parts(
        "discord:ch:123", [{"type": kind, field: path.as_uri()}], {}
    )
    uploaded = rows(discord_sdk.work, "send")
    assert len(uploaded) == 1
    assert uploaded[0]["content"] is None
    assert uploaded[0]["uploaded"] == list(b"local-bytes")
    assert path.read_bytes() == b"local-bytes"
    assert closed_files(discord_sdk)[-1]["closed"] is True


@pytest.mark.asyncio
async def test_http_download_preserves_name_and_skips_non_200(
    runtime, discord_sdk, media_server
):
    rt = await discord(runtime, discord_sdk)
    handle = await route(rt)
    result = await send(
        rt,
        handle,
        parts=[{"type": "file", "file_url": media_server + "/report.pdf"}],
    )
    assert result["state"] == "acknowledged"
    uploaded = rows(discord_sdk.work, "send")[0]
    assert uploaded["filename"] == "report.pdf"
    assert uploaded["uploaded"] == list(b"http-bytes")
    assert not Path(uploaded["file_path"]).exists()
    assert closed_files(discord_sdk)[-1]["closed"] is True
    result = await send(
        rt,
        handle,
        parts=[{"type": "file", "file_url": media_server + "/missing"}],
    )
    assert result["state"] == "acknowledged"
    assert len(rows(discord_sdk.work, "send")) == 1
    assert list((rt.ws.workspace_dir / "media").iterdir()) == []


@pytest.mark.asyncio
async def test_empty_parts_missing_urls_and_invalid_urls_have_no_upload(
    runtime, discord_sdk
):
    rt = await discord(runtime, discord_sdk)
    handle = await route(rt)
    from qwenpaw.plugins.execution.errors import RpcError

    await rt.channel.send_content_parts("discord:ch:123", [], {})
    with pytest.raises(RpcError):
        await send(rt, handle, parts=[])
    with pytest.raises(RpcError):
        await send(rt, handle, parts=[{"type": "image", "image_url": ""}])
    result = await send(
        rt, handle, parts=[{"type": "file", "file_url": "unsupported:thing"}]
    )
    assert result["state"] == "acknowledged"
    assert rows(discord_sdk.work, "send") == []
    assert closed_files(discord_sdk) == []


@pytest.mark.asyncio
async def test_workspace_a_cannot_upload_workspace_b_file(
    runtime, discord_sdk
):
    first = await discord(runtime, discord_sdk)
    second = await discord(
        runtime,
        discord_sdk,
        token="local-B",
        existing_loader=first.loader,
        workspace_name="workspace-B",
    )
    path = second.ws.workspace_dir / "secret.txt"
    path.write_bytes(b"workspace-B")
    handle = await route(first)
    result = await send(
        first, handle, parts=[{"type": "file", "file_url": path.as_uri()}]
    )
    assert result["state"] == "failed"
    assert result["reason_code"] == "MEDIA_PATH_UNAUTHORIZED"
    assert rows(discord_sdk.work, "send") == []
    assert path.read_bytes() == b"workspace-B"


@pytest.mark.asyncio
async def test_stop_cancels_inbound_download_before_admission(
    runtime, discord_sdk
):
    rt = await discord(runtime, discord_sdk)
    set_mode(discord_sdk.work, "download-block")
    push(discord_sdk.work, attachments=[{"id": 9}])
    await eventually(lambda: bool(rows(discord_sdk.work, "download")))
    pid = rt.process.health_snapshot()["pid"]
    assert (await rt.manager.stop_one("discord")).stopped
    assert not psutil.pid_exists(pid)
    assert rows(discord_sdk.work, "download-cancelled")
    assert rt.ws.requests == []
    assert list((rt.ws.workspace_dir / "media").iterdir()) == []


@pytest.mark.asyncio
async def test_stop_cancels_outbound_upload_and_closes_file(
    runtime, discord_sdk
):
    rt = await discord(runtime, discord_sdk)
    handle = await route(rt)
    set_mode(discord_sdk.work, "send-block")
    task = asyncio.create_task(
        send(
            rt,
            handle,
            parts=[
                {
                    "type": "file",
                    "file_url": "data:application/pdf;base64,cGRmLWRhdGE=",
                    "filename": "report.pdf",
                }
            ],
        )
    )
    try:
        await eventually(lambda: bool(rows(discord_sdk.work, "send")))
        assert (await rt.manager.stop_one("discord")).stopped
        assert rows(discord_sdk.work, "send-cancelled")
        assert closed_files(discord_sdk)[-1]["closed"] is True
        assert list((rt.ws.workspace_dir / "media").iterdir()) == []
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_blocked_attachment_does_not_stall_other_channel_and_duplicate_executes_once(
    runtime, discord_sdk
):
    rt = await discord(runtime, discord_sdk)
    set_mode(discord_sdk.work, "download-block")
    push(
        discord_sdk.work,
        ident=1,
        channel_id=123,
        attachments=[{"id": 9}],
        text="slow A",
    )
    await eventually(lambda: bool(rows(discord_sdk.work, "download")))
    push(
        discord_sdk.work,
        ident=1,
        channel_id=123,
        attachments=[{"id": 9}],
        text="slow A",
    )
    push(discord_sdk.work, ident=2, channel_id=456, text="fast B")
    try:
        await eventually(
            lambda: any(
                request.input[0].content[0].text == "fast B"
                for request in rt.ws.requests
            )
        )
        assert [
            request.input[0].content[0].text for request in rt.ws.requests
        ] == ["fast B"]
    finally:
        set_mode(discord_sdk.work, "")
        await callback_done(discord_sdk, 3)
    await eventually(lambda: len(rt.ws.requests) == 2)
    assert sorted(
        request.input[0].content[0].text for request in rt.ws.requests
    ) == ["fast B", "slow A"]
