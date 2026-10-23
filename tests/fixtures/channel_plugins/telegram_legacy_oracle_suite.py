"""Narrow native witnesses for remaining retired Telegram observations."""

import pytest

from telegram_business_suite import forbid_host_sdk
from telegram_cards_suite import card, click
from telegram_control_suite import approval_service
from telegram_fix1_suite import observe_worker_sends
from telegram_support import (
    eventually,
    fault_runtime,
    push,
    rows,
    runtime,
    set_mode,
    telegram,
    telegram_sdk,
)


@pytest.fixture
def legacy_sdk(telegram_sdk):
    # Extend only the external Bot API service. Native PTB/HTTPX stay real;
    # the original frozen shared service fixture is unchanged.
    boundary = telegram_sdk.site / "qwenpaw_telegram_test_boundary.py"
    with boundary.open("a") as output:
        output.write("""

_legacy_effect = effect

async def effect(kind, token, request, arguments=None):
    if kind == "editMessageText" and mode(token) == "edit-not-modified":
        return httpx.Response(
            400,
            json={"ok": False, "error_code": 400,
                  "description": "Bad Request: message is not modified"},
            request=request,
        )
    return await _legacy_effect(kind, token, request, arguments)

_legacy_native_message = native_message

def native_message(token, arguments, *, edit=False):
    # Telegram resolves a textual target to a numeric Chat.id in responses.
    # The request ledger keeps the exact original chat_id supplied to PTB.
    chat = str(arguments.get("chat_id", "12345"))
    if not chat.lstrip("-").isdigit():
        arguments = {**arguments, "chat_id": 12345}
    return _legacy_native_message(token, arguments, edit=edit)
""")
    return telegram_sdk


@pytest.mark.asyncio
@pytest.mark.parametrize("meta", [None, {}])
async def test_sender_fallback_keeps_user_session_and_native_target(
    runtime, legacy_sdk, meta
):
    rt = await telegram(runtime, legacy_sdk)
    session = rt.channel.resolve_session_id("user123", meta)
    assert session == "telegram:user123"
    payload = {
        "sender_id": "user123",
        "content_parts": [{"type": "text", "text": "original default"}],
    }
    if meta is not None:
        payload["meta"] = meta
    request = rt.channel.build_agent_request_from_native(payload)
    assert request.user_id == "user123"
    assert request.session_id == "telegram:user123"
    assert request.channel == "telegram"
    assert len(request.input) == 1
    handle = rt.channel.get_to_handle_from_request(request)
    await rt.channel.send(handle, "fallback target", {})
    actual = rows(legacy_sdk.work, "sendMessage")
    assert len(actual) == 1
    assert actual[0]["arguments"]["chat_id"] == "user123"
    assert actual[0]["arguments"]["text"] == "fallback target"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user,session,want",
    [
        ("user123", "", "user123"),
        ("unused", "telegram:@channel", "@channel"),
    ],
)
async def test_standard_target_fallback_keeps_exact_native_destination(
    runtime, legacy_sdk, user, session, want
):
    rt = await telegram(runtime, legacy_sdk)
    handle = rt.channel.to_handle_from_target(user_id=user, session_id=session)
    await rt.channel.send(handle, "target body", {})
    actual = rows(legacy_sdk.work, "sendMessage")
    assert len(actual) == 1
    assert actual[0]["arguments"]["chat_id"] == want
    assert actual[0]["arguments"]["text"] == "target body"


@pytest.mark.asyncio
async def test_group_card_callback_keeps_bound_session_root_actor_and_topic(
    runtime, legacy_sdk, monkeypatch, approval_service
):
    rt, host, record, message = await card(
        runtime, legacy_sdk, monkeypatch, approval_service, thread=33
    )
    click(
        legacy_sdk,
        record,
        message,
        chat={"id": 12345, "type": "supergroup"},
    )
    await eventually(
        lambda: record.future.done()
        and bool(rows(legacy_sdk.work, "edit-effect"))
    )
    request = rt.ws.requests[0]
    assert len(rt.ws.requests) == 1
    assert request.channel == "telegram"
    assert request.user_id == "456"
    assert request.session_id == "telegram:12345"
    assert request.root_session_id == "telegram:12345"
    assert request.channel_meta["chat_id"] == "12345"
    assert request.channel_meta["user_id"] == "456"
    assert request.channel_meta["is_group"] is True
    assert request.channel_meta["message_thread_id"] == 33
    assert request.channel_meta["root_session_id"] == "telegram:12345"
    assert request.input[0].content[0].text == (
        "/approval approve " + record.request_id
    )
    assert record.future.result().value == "approved"
    assert host.calls == []
    edited = rows(legacy_sdk.work, "editMessageText")
    assert len(edited) == 1
    assert edited[0]["arguments"]["chat_id"] == 12345
    assert edited[0]["arguments"]["message_id"] == message["message_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("ack_fails", [False, True])
async def test_processed_click_never_reenters_agent_even_when_ack_fails(
    runtime, legacy_sdk, monkeypatch, approval_service, ack_fails
):
    rt, host, record, message = await card(
        runtime, legacy_sdk, monkeypatch, approval_service
    )
    click(legacy_sdk, record, message)
    await eventually(
        lambda: record.future.done()
        and bool(rows(legacy_sdk.work, "edit-effect"))
    )
    await eventually(lambda: rt.ws.requests[0]._channel_control_state is None)
    requests_before = list(rt.ws.requests)
    sends_before = list(rows(legacy_sdk.work, "sendMessage"))
    if ack_fails:
        set_mode(legacy_sdk.work, "answerCallbackQuery-server")
    click(legacy_sdk, record, message, 2)
    await eventually(
        lambda: len(rows(legacy_sdk.work, "answerCallbackQuery-exit")) == 2
    )
    # A later ordinary update proves the SDK callback dispatcher advanced.
    # It must be the only new Agent request after the processed callback.
    push(legacy_sdk.work, 3, text="sentinel after processed callback")
    await eventually(
        lambda: any(
            r.input[0].content[0].text == "sentinel after processed callback"
            for r in rt.ws.requests
        )
    )
    await eventually(
        lambda: len(rows(legacy_sdk.work, "sendMessage"))
        >= len(sends_before) + 1
        and rows(legacy_sdk.work, "sendMessage")[-1]["arguments"]["text"]
        == "actual agent answer"
    )
    assert rt.ws.requests[:-1] == requests_before
    assert rt.ws.requests[-1].input[0].content[0].text == (
        "sentinel after processed callback"
    )
    assert len(rows(legacy_sdk.work, "editMessageText")) == 1
    # The sentinel gets the normal host answer; no duplicate callback reply.
    assert len(rows(legacy_sdk.work, "sendMessage")) == len(sends_before) + 1
    assert record.future.result().value == "approved"
    assert await approval_service.get_request(record.request_id) is None
    assert len(host.calls) == 1


@pytest.mark.asyncio
async def test_not_modified_card_edit_is_acknowledged_and_stays_processed(
    runtime, legacy_sdk, monkeypatch, approval_service
):
    rt, host, record, message = await card(
        runtime, legacy_sdk, monkeypatch, approval_service
    )
    observed = observe_worker_sends(rt)
    set_mode(legacy_sdk.work, "edit-not-modified")
    click(legacy_sdk, record, message)
    await eventually(
        lambda: record.future.done()
        and any("approval_resolution" in params for params, _ in observed)
    )
    params, result = next(
        (params, result)
        for params, result in observed
        if "approval_resolution" in params
    )
    assert "approval_resolution" in params
    assert result["state"] == "acknowledged", result
    assert record.future.result().value == "approved"
    assert await approval_service.get_request(record.request_id) is None
    assert host.calls == []
    assert len(rows(legacy_sdk.work, "editMessageText")) == 1
    assert rows(legacy_sdk.work, "edit-effect") == []
    requests_before = list(rt.ws.requests)
    sends_before = list(rows(legacy_sdk.work, "sendMessage"))
    click(legacy_sdk, record, message, 2)
    await eventually(
        lambda: len(rows(legacy_sdk.work, "answerCallbackQuery-exit")) == 2
    )
    push(legacy_sdk.work, 3, text="sentinel after not-modified")
    await eventually(
        lambda: len(rows(legacy_sdk.work, "sendMessage"))
        >= len(sends_before) + 1
        and rows(legacy_sdk.work, "sendMessage")[-1]["arguments"]["text"]
        == "actual agent answer"
    )
    assert rt.ws.requests[:-1] == requests_before
    assert (
        rt.ws.requests[-1].input[0].content[0].text
        == "sentinel after not-modified"
    )
    assert len(rows(legacy_sdk.work, "sendMessage")) == len(sends_before) + 1
    assert len(rows(legacy_sdk.work, "editMessageText")) == 1


@pytest.mark.asyncio
async def test_original_http_media_value_and_topic_reach_native_sdk(
    runtime, legacy_sdk
):
    rt = await telegram(runtime, legacy_sdk)
    await rt.channel.send_media(
        "12345",
        {"type": "image", "image_url": "http://example.com/image.jpg"},
        {"message_thread_id": 789},
    )
    actual = rows(legacy_sdk.work, "sendPhoto")
    assert len(actual) == 1
    assert actual[0]["arguments"]["chat_id"] == 12345
    assert actual[0]["arguments"]["photo"] == "http://example.com/image.jpg"
    assert actual[0]["arguments"]["message_thread_id"] == 789
    assert rows(legacy_sdk.work, "sendMessage") == []


def test_real_file_url_helper_preserves_original_return_contracts(
    legacy_sdk, tmp_path
):
    import os
    import subprocess
    import sys
    from extension_sample import ROOT

    code = """
import asyncio,json,sys
from pathlib import Path
from urllib.parse import quote
sys.path[:0]=sys.argv[1:4]
from telegram import Bot, File
from telegram.error import TelegramError
from qwenpaw_channel_telegram.platform import _resolve_telegram_file_url
site=Path(sys.argv[1])
work=Path((site/'telegram-test-work').read_text())/quote('123:local-A',safe='')
work.mkdir(exist_ok=True)
class PureFileResult:
    # Explicit pure-helper dependency boundary, not native getFile behavior.
    async def get_file(self,file_id):
        if file_id=='error':
            raise TelegramError('pure helper error')
        return File(file_id='external',file_unique_id='unique',
            file_path='http://external.server.com/file.jpg')
async def main():
    pure=PureFileResult()
    result=await _resolve_telegram_file_url(
        bot=pure,file_id='external',bot_token='123:local-A')
    assert result=='http://external.server.com/file.jpg',result
    result=await _resolve_telegram_file_url(
        bot=pure,file_id='error',bot_token='123:local-A')
    assert result=='',result
    for base,want in [
        ('','https://api.telegram.org/file/bot123:local-A/photos/test.jpg'),
        ('https://tg-api.example.com',
         'https://tg-api.example.com/file/bot123:local-A/photos/test.jpg'),
    ]:
        bot=Bot('123:local-A',**({'base_url':base+'/bot',
            'base_file_url':base+'/file/bot'} if base else {}))
        await bot.initialize()
        try:
            (work/'file.json').write_text(json.dumps(
                {'file_path':'photos/test.jpg'}))
            result=await _resolve_telegram_file_url(
                bot=bot,file_id='relative',bot_token='123:local-A',
                base_url=base)
            assert result==want,(result,want)
            (work/'mode').write_text('getFile-server')
            result=await _resolve_telegram_file_url(
                bot=bot,file_id='error',bot_token='123:local-A',
                base_url=base)
            assert result=='',result
            (work/'mode').unlink()
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
            str(legacy_sdk.site),
            str(ROOT / "src"),
            str(ROOT / "plugins/channel/telegram"),
        ],
        env={
            **os.environ,
            "QWENPAW_WORKING_DIR": str(tmp_path / "host"),
            "QWENPAW_SECRET_DIR": str(tmp_path / "secrets"),
            "QWENPAW_BACKUP_DIR": str(tmp_path / "backups"),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert [
        row["arguments"]["file_id"] for row in rows(legacy_sdk.work, "getFile")
    ] == ["relative", "error"] * 2
