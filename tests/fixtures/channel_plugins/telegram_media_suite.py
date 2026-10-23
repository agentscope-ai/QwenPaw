"""Real PTB callbacks and worker replies observed at the HTTP service."""

import asyncio
import base64
import importlib.abc
import os
from pathlib import Path
import sys
from urllib.parse import quote, unquote, urlsplit

import pytest

from telegram_support import (
    TOKEN,
    eventually,
    fault_runtime,
    finish,
    identity,
    push,
    route,
    rows,
    runtime,
    send,
    set_mode,
    telegram,
    telegram_sdk,
)


from telegram_business_suite import forbid_host_sdk


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "part,endpoint,field",
    [
        (
            {"type": "image", "image_url": "https://x.test/i"},
            "sendPhoto",
            "photo",
        ),
        (
            {"type": "video", "video_url": "https://x.test/v"},
            "sendVideo",
            "video",
        ),
        ({"type": "audio", "data": "https://x.test/a"}, "sendAudio", "audio"),
        (
            {"type": "file", "file_url": "https://x.test/f"},
            "sendDocument",
            "document",
        ),
    ],
)
async def test_public_single_media_uses_native_endpoint_without_text_notice(
    runtime, telegram_sdk, part, endpoint, field
):
    rt = await telegram(runtime, telegram_sdk)
    await rt.channel.send_media(
        "12345", part, {"message_thread_id": 88, "bot_prefix": "P"}
    )
    actual = rows(telegram_sdk.work, endpoint)[-1]["arguments"]
    assert actual["chat_id"] == 12345
    assert actual["message_thread_id"] == 88
    assert actual[field] == next(v for k, v in part.items() if k != "type")
    assert rows(telegram_sdk.work, "sendMessage") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", [None, "report.pdf"])
async def test_data_document_true_multipart_bytes_and_filename_without_disk(
    runtime, telegram_sdk, filename
):
    rt = await telegram(runtime, telegram_sdk)
    media_dir = rt.ws.workspace_dir / "media"
    before = {
        path.relative_to(media_dir): path.read_bytes()
        for path in media_dir.rglob("*")
        if path.is_file()
    }
    part = {
        "type": "file",
        "file_url": "data:application/pdf;base64,cGRmLWRhdGE=",
    }
    if filename:
        part["filename"] = filename
    await rt.channel.send_media("12345", part, {})
    files = rows(telegram_sdk.work, "sendDocument")[-1]["files"]
    assert files["document"]["filename"] == (filename or "document.pdf")
    assert base64.b64decode(files["document"]["bytes_b64"]) == b"pdf-data"
    assert list(rt.ws.workspace_dir.rglob("*.pdf")) == []
    assert {
        path.relative_to(media_dir): path.read_bytes()
        for path in media_dir.rglob("*")
        if path.is_file()
    } == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "media,part_type",
    [
        (
            {
                "photo": [
                    {
                        "file_id": "small",
                        "file_unique_id": "s",
                        "width": 5,
                        "height": 5,
                    },
                    {
                        "file_id": "largest",
                        "file_unique_id": "l",
                        "width": 50,
                        "height": 50,
                    },
                ]
            },
            "image",
        ),
        (
            {
                "document": {
                    "file_id": "document",
                    "file_unique_id": "d",
                    "file_name": "report.pdf",
                }
            },
            "file",
        ),
        (
            {
                "video": {
                    "file_id": "video",
                    "file_unique_id": "v",
                    "width": 50,
                    "height": 50,
                    "duration": 1,
                }
            },
            "video",
        ),
        (
            {
                "voice": {
                    "file_id": "voice",
                    "file_unique_id": "v",
                    "duration": 1,
                }
            },
            "audio",
        ),
        (
            {
                "audio": {
                    "file_id": "audio",
                    "file_unique_id": "a",
                    "duration": 1,
                }
            },
            "audio",
        ),
    ],
)
async def test_native_download_bytes_and_file_uri_reach_host_agent(
    runtime, telegram_sdk, media, part_type
):
    rt = await telegram(runtime, telegram_sdk)
    push(telegram_sdk.work, text=None, caption="caption", **media)
    await eventually(
        lambda: len(rt.ws.requests) == 1
        and bool(rows(telegram_sdk.work, "sendMessage"))
    )
    assert rows(telegram_sdk.work, "sendMessage")[-1]["arguments"]["text"] == (
        "host answer"
    )
    parts = rt.ws.requests[0].input[0].content
    assert parts[0].text == "caption"
    assert parts[1].type.value == part_type
    value = getattr(
        parts[1],
        {
            "image": "image_url",
            "file": "file_url",
            "video": "video_url",
            "audio": "data",
        }[part_type],
    )
    path = Path(unquote(urlsplit(value).path))
    assert path.is_relative_to(rt.ws.workspace_dir)
    assert path.read_bytes() == b"downloaded media bytes"
    assert path.suffix == ".jpg"
    expected = "largest" if "photo" in media else next(iter(media))
    assert (
        rows(telegram_sdk.work, "getFile")[-1]["arguments"]["file_id"]
        == expected
    )


@pytest.mark.asyncio
async def test_disabled_public_delivery_fails_without_effects(
    runtime, telegram_sdk
):
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError
    from qwenpaw.config.config import TelegramConfig
    from qwenpaw.plugins.channel_adapter import describe_channel
    from g2_legacy_configuration_suite import proxy_for

    rt = await telegram(runtime, telegram_sdk, bot_prefix="keep")
    await rt.loader.lifecycle.set_enabled("telegram", False)
    baseline = rows(telegram_sdk.work)
    with pytest.raises(RuntimeError, match="CHANNEL_NOT_CONNECTED"):
        await rt.channel.send("12345", "stale global reference", {})
    disabled = proxy_for(
        describe_channel(rt.source, rt.record.manifest),
        TelegramConfig(
            enabled=False, bot_token="123:local-A", bot_prefix="keep"
        ),
        workspace_dir=rt.ws.workspace_dir,
    )
    for operation in (
        lambda: disabled.send("12345", "blocked", {}),
        lambda: disabled.send_content_parts(
            "12345", [{"type": "text", "text": "blocked"}], {}
        ),
        lambda: disabled.send_media(
            "12345", {"type": "image", "image_url": "https://x.test/i"}, {}
        ),
    ):
        with pytest.raises(ChannelDeliveryError) as caught:
            await operation()
        assert caught.value.state == "failed"
        assert caught.value.reason_code == "CHANNEL_DISABLED"
    assert rows(telegram_sdk.work) == baseline
    assert rt.channel.channel_process.health_snapshot()["pid"] is None
    assert disabled.channel_process.health_snapshot()["pid"] is None
    assert disabled.bot_prefix == "keep"
    assert rt.ws._config.channels.telegram.bot_prefix == "keep"


@pytest.mark.asyncio
async def test_local_workspace_upload_retains_true_bytes_filename_and_topic(
    runtime, telegram_sdk
):
    rt = await telegram(runtime, telegram_sdk)
    media = rt.ws.workspace_dir / "media" / "local.png"
    media.parent.mkdir(parents=True, exist_ok=True)
    media.write_bytes(b"local image bytes")
    await rt.channel.send_media(
        "12345",
        {"type": "image", "image_url": media.as_uri()},
        {"message_thread_id": 77},
    )
    value = rows(telegram_sdk.work, "sendPhoto")[-1]
    assert value["files"]["photo"]["filename"] == "local.png"
    assert (
        base64.b64decode(value["files"]["photo"]["bytes_b64"])
        == b"local image bytes"
    )
    assert value["arguments"]["message_thread_id"] == 77


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind", ["missing", "oversized", "outside", "symlink", "invalid-data"]
)
async def test_unavailable_or_unowned_media_never_uploads(
    runtime, telegram_sdk, tmp_path, kind
):
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError

    rt = await telegram(runtime, telegram_sdk)
    owned = rt.ws.workspace_dir / "media" / "image.png"
    owned.parent.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"must remain private")
    if kind == "oversized":
        with owned.open("wb") as output:
            output.truncate(50 * 1024 * 1024 + 1)
    elif kind == "symlink":
        owned.symlink_to(outside)
    value = outside.as_uri() if kind == "outside" else owned.as_uri()
    if kind == "invalid-data":
        value = "data:image/png;base64,invalid!"
    meta = {}
    part = {"type": "image", "image_url": value}
    with pytest.raises(ChannelDeliveryError) as caught:
        await rt.channel.send_media("12345", part, meta)
    has_notice = kind in {"missing", "oversized", "invalid-data"}
    assert caught.value.state == ("unknown" if has_notice else "failed")
    assert caught.value.side_effect_possible is has_notice
    assert rows(telegram_sdk.work, "sendPhoto") == []
    notices = rows(telegram_sdk.work, "sendMessage")
    expected = {
        "missing": "Media file not found: image.png",
        "oversized": (
            "File too large to send via Telegram: image.png "
            "(50.0 MB, Telegram bot limit: 50 MB)"
        ),
        "invalid-data": "Could not decode media data URL.",
    }
    assert [row["arguments"]["text"] for row in notices] == (
        [expected[kind]] if has_notice else []
    )
    if has_notice:
        with pytest.raises(ChannelDeliveryError) as repeated:
            await rt.channel.send_media("12345", part, meta)
        assert repeated.value.state == "unknown"
        assert rows(telegram_sdk.work, "sendMessage") == notices
        assert rows(telegram_sdk.work, "sendPhoto") == []
    assert outside.read_bytes() == b"must remain private"


@pytest.mark.asyncio
async def test_malicious_getfile_cannot_copy_outside_workspace(
    runtime, telegram_sdk, tmp_path
):
    import json

    rt = await telegram(runtime, telegram_sdk)
    outside = tmp_path / "host-secret.png"
    outside.write_bytes(b"host private bytes")
    profile = telegram_sdk.work / quote(TOKEN, safe="") / "file.json"
    profile.write_text(json.dumps({"file_path": str(outside)}))
    push(
        telegram_sdk.work,
        text="caption survives",
        photo=[
            {
                "file_id": "malicious",
                "file_unique_id": "m",
                "width": 5,
                "height": 5,
            }
        ],
    )
    await eventually(lambda: len(rt.ws.requests) == 1)
    parts = rt.ws.requests[0].input[0].content
    assert len(parts) == 1 and parts[0].text == "caption survives"
    assert not any(
        path.is_file() and path.read_bytes() == b"host private bytes"
        for path in rt.ws.workspace_dir.rglob("*.png")
    )
    assert rows(telegram_sdk.work, "file-bytes") == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "file_path,filename,want",
    [
        ("photos/file_no_ext", "image.png", ".png"),
        ("photos/path.webp", "image.png", ".webp"),
        ("photos/file_no_ext", "document", ".bin"),
    ],
)
async def test_native_download_suffix_precedence_and_recursive_directory(
    runtime, telegram_sdk, file_path, filename, want
):
    import json

    rt = await telegram(runtime, telegram_sdk)
    (telegram_sdk.work / quote(TOKEN, safe="") / "file.json").write_text(
        json.dumps({"file_path": file_path})
    )
    push(
        telegram_sdk.work,
        text="file input",
        document={
            "file_id": "f",
            "file_unique_id": "unique",
            "file_name": filename,
        },
    )
    await eventually(lambda: len(rt.ws.requests) == 1)
    value = rt.ws.requests[0].input[0].content[1].file_url
    path = Path(unquote(urlsplit(value).path))
    assert path.suffix == want
    assert path.read_bytes() == b"downloaded media bytes"
    assert len(path.stem) == 12


@pytest.mark.asyncio
async def test_file_service_error_keeps_caption_without_download(
    runtime, telegram_sdk
):
    rt = await telegram(runtime, telegram_sdk)
    set_mode(telegram_sdk.work, "getFile-server")
    push(
        telegram_sdk.work,
        text=None,
        caption="caption despite failed photo",
        photo=[
            {
                "file_id": "missing",
                "file_unique_id": "m",
                "width": 5,
                "height": 5,
            }
        ],
    )
    await eventually(lambda: len(rt.ws.requests) == 1)
    parts = rt.ws.requests[0].input[0].content
    assert len(parts) == 1 and parts[0].text == "caption despite failed photo"
    assert rows(telegram_sdk.work, "file-bytes") == []
