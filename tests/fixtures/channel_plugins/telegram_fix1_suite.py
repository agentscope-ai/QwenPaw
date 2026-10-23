"""Frozen-review regressions for real worker custody and SDK inputs."""

import asyncio
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from extension_sample import ROOT
from telegram_business_suite import forbid_host_sdk
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
from g2_official_process_suite import prepare


def observe_worker_sends(rt):
    observations = []
    original = rt.process.call

    async def observe(method, params, **kwargs):
        result = await original(method, params, **kwargs)
        if method == "channel.send":
            observations.append((deepcopy(params), deepcopy(result)))
        return result

    rt.process.call = observe
    return observations


def persisted_attempt(rt, params):
    from qwenpaw.channel_protocol.response_lifecycle import (
        ResponseRouteSnapshot,
    )
    from qwenpaw.channel_protocol.response_receipts import (
        ResponseReceiptStore,
        receipt_key,
    )

    state = json.loads(rt.channel._state_path().read_text())
    archive = ResponseReceiptStore(
        rt.channel._state_path().with_suffix(".receipts.sqlite3"),
    ).get(receipt_key("telegram.shared.responses", params["to_handle"]))
    snapshots = (
        [archive]
        if archive is not None
        else state["telegram.shared.responses"]["value"]
    )
    matching = [
        ResponseRouteSnapshot.from_mapping(row)
        for row in snapshots
        if row["response_handle"] == params["to_handle"]
    ]
    assert len(matching) == 1, "uncertain delivery lost durable route custody"
    snapshot = matching[0]
    matches = [
        ref
        for ref in snapshot.resource_refs
        if ref.kind == "telegram.attempt"
        and ref.resource_id == params["delivery_id"]
    ]
    assert len(matches) == 1, (
        "uncertain delivery lost journal custody",
        state,
    )
    attempt = dict(matches[0].attributes)
    assert (
        attempt["fingerprint"]
        == hashlib.sha256(
            json.dumps(
                {
                    key: value
                    for key, value in params.items()
                    if key != "generation"
                },
                sort_keys=True,
            ).encode(),
        ).hexdigest()
    )
    return attempt


async def restart_and_replay_unknown(rt, params, result):
    """Read the durable receipt in a fresh worker and never repeat SDK effects."""
    receipt = persisted_attempt(rt, params)
    old_pid = rt.process.health_snapshot()["pid"]
    await rt.loader.lifecycle.set_enabled("telegram", False)
    await rt.loader.lifecycle.set_enabled("telegram", True)
    rt.channel = await rt.manager.get_channel("telegram")
    rt.process = rt.channel.channel_process
    assert rt.process.health_snapshot()["pid"] != old_pid
    replay = {**params, **identity(rt)}
    assert persisted_attempt(rt, replay) == receipt
    assert await rt.process.call("channel.send", replay) == result
    assert persisted_attempt(rt, replay) == receipt


@pytest.mark.asyncio
async def test_media_notice_rejection_keeps_operation_unknown_and_no_replay(
    runtime, telegram_sdk
):
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError

    rt = await telegram(runtime, telegram_sdk)
    observed = observe_worker_sends(rt)
    set_mode(telegram_sdk.work, "media-error-notice-reject")
    parts = [
        {"type": "text", "text": "already sent"},
        {"type": "image", "image_url": "data:image/png;base64,invalid!"},
    ]
    meta = {}
    with pytest.raises(ChannelDeliveryError):
        await rt.channel.send_content_parts("12345", parts, meta)
    params, result = observed[-1]
    assert len(rows(telegram_sdk.work, "sendMessage")) == 2
    assert len(rows(telegram_sdk.work, "message-effect")) == 1
    assert rows(telegram_sdk.work, "sendPhoto") == []

    assert result["state"] == "unknown", (result, meta)
    assert persisted_attempt(rt, params)["state"] == "unknown"
    assert meta["_reply_unknown"] is True
    pending = deepcopy(meta["_pending_delivery"])
    assert pending["delivery_id"] == params["delivery_id"]
    assert await rt.process.call("channel.send", params) == result
    with pytest.raises(ChannelDeliveryError) as repeated:
        await rt.channel.send_content_parts("12345", parts, meta)
    assert repeated.value.state == "unknown"
    assert meta["_pending_delivery"] == pending
    with pytest.raises(ChannelDeliveryError) as changed:
        await rt.channel.send_content_parts(
            "12345", [{"type": "text", "text": "changed"}], meta
        )
    assert changed.value.state == "unknown"
    assert len(rows(telegram_sdk.work, "sendMessage")) == 2
    assert len(rows(telegram_sdk.work, "message-effect")) == 1

    await restart_and_replay_unknown(rt, params, result)
    assert len(rows(telegram_sdk.work, "sendMessage")) == 2
    assert len(rows(telegram_sdk.work, "message-effect")) == 1
    assert rows(telegram_sdk.work, "sendPhoto") == []


@pytest.mark.asyncio
async def test_final_send_rejection_after_delete_keeps_unknown_no_replay(
    runtime, telegram_sdk
):
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError

    rt = await telegram(runtime, telegram_sdk, streaming_enabled=True)
    observed = observe_worker_sends(rt)
    meta = {}
    await rt.channel.on_streaming_start(None, "12345", None, meta, "message")
    placeholder = rows(telegram_sdk.work, "message-effect")[0]["message"]
    set_mode(telegram_sdk.work, "sendMessage-reject")
    with pytest.raises(ChannelDeliveryError):
        await rt.channel.on_streaming_end(
            None, "12345", None, meta, "message", "x" * 5000
        )
    params, result = observed[-1]
    assert params["operation"] == "stream.end"
    assert [
        r["arguments"]["message_id"]
        for r in rows(telegram_sdk.work, "deleteMessage")
    ] == [placeholder["message_id"]]
    assert len(rows(telegram_sdk.work, "sendMessage")) == 2
    assert len(rows(telegram_sdk.work, "message-effect")) == 1
    assert persisted_attempt(rt, params)["state"] == "unknown", (result, meta)
    assert result["state"] == "unknown"
    assert meta["_reply_unknown"] is True
    pending = deepcopy(meta["_pending_delivery"])
    assert pending["delivery_id"] == params["delivery_id"]
    assert await rt.process.call("channel.send", params) == result
    with pytest.raises(ChannelDeliveryError) as repeated:
        await rt.channel.on_streaming_end(
            None, "12345", None, meta, "message", "x" * 5000
        )
    assert repeated.value.state == "unknown"
    assert meta["_pending_delivery"] == pending
    assert len(rows(telegram_sdk.work, "sendMessage")) == 2
    assert len(rows(telegram_sdk.work, "deleteMessage")) == 1
    assert len(rows(telegram_sdk.work, "message-effect")) == 1

    await restart_and_replay_unknown(rt, params, result)
    assert len(rows(telegram_sdk.work, "sendMessage")) == 2
    assert len(rows(telegram_sdk.work, "deleteMessage")) == 1
    assert len(rows(telegram_sdk.work, "message-effect")) == 1


@pytest.mark.asyncio
async def test_original_audio_bytes_schema_reaches_native_identifier_unchanged(
    runtime, telegram_sdk
):
    from qwenpaw.schemas import AudioContent, ContentType

    rt = await telegram(runtime, telegram_sdk)
    part = AudioContent(type=ContentType.AUDIO, data=b"audio_data")
    assert part.data == "audio_data"
    assert not (rt.source / "audio_data").exists()
    await rt.channel.send_media("12345", part, {"message_thread_id": 88})
    actual = rows(telegram_sdk.work, "sendAudio")[-1]
    assert actual["arguments"]["audio"] == "audio_data"
    assert actual["arguments"]["chat_id"] == 12345
    assert actual["arguments"]["message_thread_id"] == 88
    assert actual["files"] == {}
    assert rows(telegram_sdk.work, "sendMessage") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["file", "directory", "dangling-symlink"])
async def test_basename_local_objects_never_become_native_audio_uploads(
    runtime, telegram_sdk, tmp_path, kind
):
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError
    from qwenpaw.schemas import AudioContent

    rt = await telegram(runtime, telegram_sdk)
    value = rt.source / "audio_data"
    if kind == "file":
        value.write_bytes(b"private local file")
    elif kind == "directory":
        value.mkdir()
    else:
        value.symlink_to(tmp_path / "does-not-exist")
    assert value.exists() or value.is_symlink()
    with pytest.raises(ChannelDeliveryError) as caught:
        await rt.channel.send_media(
            "12345", AudioContent(data=b"audio_data"), {}
        )
    assert caught.value.state == "failed"
    assert caught.value.reason_code == "MEDIA_URL_UNAUTHORIZED"
    assert caught.value.side_effect_possible is False
    assert rows(telegram_sdk.work, "sendAudio") == []
    assert rows(telegram_sdk.work, "sendMessage") == []
    if kind == "file":
        assert value.read_bytes() == b"private local file"
    elif kind == "directory":
        assert value.is_dir() and list(value.iterdir()) == []
    else:
        assert value.is_symlink() and not value.exists()


@pytest.mark.asyncio
async def test_native_typing_action_and_chat_are_the_original_values(
    runtime, telegram_sdk
):
    rt = await telegram(runtime, telegram_sdk, show_typing=True)
    handle = await route(rt, "12345")
    assert (await prepare(rt, handle))["state"] == "acknowledged"
    await eventually(lambda: bool(rows(telegram_sdk.work, "sendChatAction")))
    arguments = rows(telegram_sdk.work, "sendChatAction")[0]["arguments"]
    assert arguments["chat_id"] == 12345
    assert arguments["action"] == "typing"
    await finish(rt, handle)
    await eventually(
        lambda: bool(rows(telegram_sdk.work, "sendChatAction-exit"))
    )


def test_real_file_download_creates_an_absent_nested_media_directory(
    telegram_sdk, tmp_path
):
    code = """
import asyncio, sys
from pathlib import Path
sys.path[:0] = sys.argv[1:4]
from telegram import Bot
from qwenpaw_channel_telegram.platform import _download_telegram_file
async def main():
    nested = Path(sys.argv[4]) / "nested" / "media"
    assert not nested.exists()
    bot = Bot("123:local-A")
    await bot.initialize()
    try:
        result = await _download_telegram_file(
            bot=bot, file_id="file123", media_dir=nested,
        )
        assert nested.exists()
        assert result is not None
        assert Path(result).parent == nested
        assert Path(result).read_bytes() == b"downloaded media bytes"
    finally:
        await bot.shutdown()
asyncio.run(main())
"""
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            code,
            str(telegram_sdk.site),
            str(ROOT / "src"),
            str(ROOT / "plugins/channel/telegram"),
            str(tmp_path),
        ],
        env={
            **os.environ,
            "QWENPAW_WORKING_DIR": str(tmp_path / "host"),
            "QWENPAW_SECRET_DIR": str(tmp_path / "secrets"),
            "QWENPAW_BACKUP_DIR": str(tmp_path / "backups"),
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        rows(telegram_sdk.work, "getFile")[0]["arguments"]["file_id"]
        == "file123"
    )
    assert len(rows(telegram_sdk.work, "file-bytes")) == 1


def test_native_ptb_reference_does_not_open_an_existing_shadow_file(
    telegram_sdk, tmp_path
):
    local = tmp_path / "audio_data"
    local.write_bytes(b"private bytes must not be uploaded")
    code = """
import asyncio,sys
sys.path.insert(0,sys.argv[1])
from telegram import Audio, Bot
async def main():
    bot=Bot("123:local-A")
    await bot.initialize()
    try:
        value=Audio(file_id="audio_data",file_unique_id="",duration=0)
        await bot.send_audio(chat_id=12345,audio=value)
    finally:
        await bot.shutdown()
asyncio.run(main())
"""
    result = subprocess.run(
        [str(telegram_sdk.python), "-I", "-c", code, str(telegram_sdk.site)],
        cwd=tmp_path,
        env={
            **os.environ,
            "QWENPAW_WORKING_DIR": str(tmp_path / "host"),
            "QWENPAW_SECRET_DIR": str(tmp_path / "secrets"),
            "QWENPAW_BACKUP_DIR": str(tmp_path / "backups"),
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    actual = rows(telegram_sdk.work, "sendAudio")[0]
    assert actual["arguments"]["audio"] == "audio_data"
    assert actual["files"] == {}
    assert local.read_bytes() == b"private bytes must not be uploaded"
