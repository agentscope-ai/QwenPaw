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


class HostImportGuard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "telegram" or fullname.startswith(
            ("telegram.", "qwenpaw_channel_telegram")
        ):
            raise AssertionError(
                "Telegram implementation imported in host: " + fullname
            )


@pytest.fixture(autouse=True)
def forbid_host_sdk():
    guard = HostImportGuard()
    sys.meta_path.insert(0, guard)
    yield
    sys.meta_path.remove(guard)


@pytest.mark.asyncio
@pytest.mark.parametrize("callback", ["message", "edited_message"])
@pytest.mark.parametrize(
    "chat_type", ["private", "group", "supergroup", "channel"]
)
async def test_native_callback_legacy_session_topic_actor_and_host_reply(
    runtime, telegram_sdk, callback, chat_type
):
    rt = await telegram(runtime, telegram_sdk)
    push(
        telegram_sdk.work,
        callback=callback,
        chat={"id": 12345, "type": chat_type},
        message_thread_id=77,
    )
    await eventually(
        lambda: len(rt.ws.requests) == 1
        and bool(rows(telegram_sdk.work, "sendMessage"))
    )
    request = rt.ws.requests[0]
    assert request.session_id == "telegram:12345"
    assert request.user_id == "456"
    assert request.channel == "telegram"
    assert request.input[0].content[0].text == "Hello bot"
    assert request.channel_meta["chat_id"] == "12345"
    assert request.channel_meta["message_thread_id"] == 77
    assert request.channel_meta["username"] == "human"
    assert request.channel_meta["message_id"] == "1"
    assert request.channel_meta["is_group"] is (chat_type != "private")
    posted = rows(telegram_sdk.work, "sendMessage")[-1]
    assert posted["arguments"]["chat_id"] == 12345
    assert posted["arguments"]["message_thread_id"] == 77
    assert posted["arguments"]["text"] == "host answer"
    assert posted["pid"] == rt.process.health_snapshot()["pid"] != os.getpid()
    assert Path(posted["sdk_source"]).is_relative_to(telegram_sdk.site)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text,entities,want,command,mentioned",
    [
        (
            "/help",
            [{"type": "bot_command", "offset": 0, "length": 5}],
            "/help",
            True,
            False,
        ),
        (
            "@test_bot hi",
            [{"type": "mention", "offset": 0, "length": 9}],
            "hi",
            False,
            True,
        ),
        (
            "😀 @test_bot hi",
            [{"type": "mention", "offset": 3, "length": 9}],
            "😀  hi",
            False,
            True,
        ),
        (
            "Bot hi",
            [
                {
                    "type": "text_mention",
                    "offset": 0,
                    "length": 3,
                    "user": {"id": 999, "is_bot": True, "first_name": "Bot"},
                }
            ],
            "Bot hi",
            False,
            True,
        ),
    ],
)
async def test_native_entities_command_and_utf16_mentions(
    runtime, telegram_sdk, text, entities, want, command, mentioned
):
    rt = await telegram(runtime, telegram_sdk)
    push(telegram_sdk.work, text=text, entities=entities)
    await eventually(lambda: len(rt.ws.requests) == 1)
    request = rt.ws.requests[0]
    assert request.input[0].content[0].text == want
    assert request.channel_meta["has_bot_command"] is command
    assert request.channel_meta["bot_mentioned"] is mentioned


@pytest.mark.asyncio
async def test_require_mention_and_real_host_acl_deny_then_allow(
    runtime, telegram_sdk
):
    rt = await telegram(
        runtime,
        telegram_sdk,
        require_mention=True,
        group_policy="allowlist",
        access_control_group=True,
        allow_from=["456"],
        deny_message="denied",
    )
    rt.channel._get_acl_store().add_to_whitelist("telegram", "456")
    push(telegram_sdk.work, chat={"id": 12345, "type": "supergroup"})
    push(
        telegram_sdk.work,
        2,
        chat={"id": 12345, "type": "supergroup"},
        text="@test_bot hi",
        entities=[{"type": "mention", "offset": 0, "length": 9}],
        **{"from": {"id": 777, "is_bot": False, "first_name": "Other"}},
    )
    push(
        telegram_sdk.work,
        3,
        chat={"id": 12345, "type": "supergroup"},
        text="@test_bot allowed",
        entities=[{"type": "mention", "offset": 0, "length": 9}],
    )
    await eventually(lambda: len(rt.ws.requests) == 1)
    assert rt.ws.requests[0].input[0].content[0].text == "allowed"
    assert rt.ws.requests[0].user_id == "456"


@pytest.mark.asyncio
async def test_same_chat_topics_share_session_but_distinct_updates_execute(
    runtime, telegram_sdk
):
    rt = await telegram(runtime, telegram_sdk)
    push(telegram_sdk.work, 1, message_thread_id=11, text="same")
    push(telegram_sdk.work, 2, message_thread_id=22, text="same")
    await eventually(lambda: len(rt.ws.requests) == 2)
    assert [r.session_id for r in rt.ws.requests] == [
        "telegram:12345",
        "telegram:12345",
    ]
    assert [r.channel_meta["message_thread_id"] for r in rt.ws.requests] == [
        11,
        22,
    ]
    push(telegram_sdk.work, 2, message_thread_id=22, text="same")
    push(
        telegram_sdk.work,
        3,
        callback="edited_message",
        message_id=2,
        text="edited",
    )
    await eventually(lambda: len(rt.ws.requests) == 3)
    assert rt.ws.requests[-1].input[0].content[0].text == "edited"


@pytest.mark.asyncio
async def test_service_replayed_stable_update_reaches_sdk_but_executes_once(
    runtime, telegram_sdk
):
    import json
    from telegram_support import TOKEN

    rt = await telegram(runtime, telegram_sdk)
    original = push(telegram_sdk.work, 17, text="once only")
    await eventually(lambda: len(rt.ws.requests) == 1)
    (telegram_sdk.work / quote(TOKEN, safe="") / "replay.json").write_text(
        json.dumps([original])
    )
    await eventually(
        lambda: bool(rows(telegram_sdk.work, "service-replayed-update"))
    )
    push(telegram_sdk.work, 18, text="after duplicate")
    await eventually(lambda: len(rt.ws.requests) == 2)
    assert [r.input[0].content[0].text for r in rt.ws.requests] == [
        "once only",
        "after duplicate",
    ]
    assert (
        rows(telegram_sdk.work, "service-replayed-update")[0]["update_ids"][0]
        == 17
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "proxy,auth,want",
    [
        ("", "", None),
        (
            "http://proxy.example.test:8080",
            "",
            "http://proxy.example.test:8080",
        ),
        (
            "http://proxy.example.test:8080",
            "user:pass",
            "http://user:pass@proxy.example.test:8080",
        ),
    ],
)
async def test_real_ptb_builder_propagates_proxy_to_both_native_http_clients(
    runtime, telegram_sdk, proxy, auth, want
):
    rt = await telegram(
        runtime, telegram_sdk, http_proxy=proxy, http_proxy_auth=auth
    )
    assert rows(telegram_sdk.work, "getMe")[0]["client_proxy"] == want
    assert rows(telegram_sdk.work, "getUpdates")[0]["client_proxy"] == want
    assert rt.process.health_snapshot()["pid"]


@pytest.mark.asyncio
async def test_empty_native_message_does_not_admit_agent_request(
    runtime, telegram_sdk
):
    rt = await telegram(runtime, telegram_sdk)
    push(telegram_sdk.work, 1, text=None)
    push(telegram_sdk.work, 2, text="sentinel after empty input")
    await eventually(lambda: len(rt.ws.requests) == 1)
    assert (
        rt.ws.requests[0].input[0].content[0].text
        == "sentinel after empty input"
    )


@pytest.mark.asyncio
async def test_native_edited_message_without_username_keeps_empty_username(
    runtime, telegram_sdk
):
    rt = await telegram(runtime, telegram_sdk)
    push(
        telegram_sdk.work,
        17,
        callback="edited_message",
        message_id=100,
        text="edited without username",
        message_thread_id=None,
        chat={"id": 123456, "type": "private"},
        **{
            "from": {
                "id": 789,
                "is_bot": False,
                "first_name": "No Username",
                "username": None,
            }
        },
    )
    await eventually(
        lambda: len(rt.ws.requests) == 1
        and bool(rows(telegram_sdk.work, "sendMessage"))
    )
    request = rt.ws.requests[0]
    assert request.channel_meta["is_group"] is False
    assert request.channel_meta["username"] == ""
    assert request.channel_meta["message_id"] == "100"
    assert request.channel_meta["message_thread_id"] is None
    assert request.user_id == "789"
    assert request.session_id == "telegram:123456"
    assert request.input[0].content[0].text == "edited without username"
    assert (
        rows(telegram_sdk.work, "sendMessage")[-1]["arguments"]["chat_id"]
        == 123456
    )


@pytest.mark.asyncio
async def test_native_full_metadata_keeps_each_original_message_field(
    runtime, telegram_sdk
):
    rt = await telegram(runtime, telegram_sdk)
    push(
        telegram_sdk.work,
        1,
        message_id=100,
        message_thread_id=50,
        chat={"id": 123456, "type": "group"},
        **{
            "from": {
                "id": 789,
                "is_bot": False,
                "first_name": "Test",
                "username": "testuser",
            }
        },
    )
    await eventually(lambda: len(rt.ws.requests) == 1)
    result = rt.ws.requests[0].channel_meta
    assert result["chat_id"] == "123456"
    assert result["user_id"] == "789"
    assert result["username"] == "testuser"
    assert result["message_id"] == "100"
    assert result["is_group"] is True
    assert result["message_thread_id"] == 50
