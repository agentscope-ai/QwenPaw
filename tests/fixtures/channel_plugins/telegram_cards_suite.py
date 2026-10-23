"""Native CallbackQuery, genuine Core approval and owned message effects."""

import asyncio

import pytest

from telegram_business_suite import forbid_host_sdk
from telegram_control_suite import approval_service, pending
from telegram_support import (
    eventually,
    fault_runtime,
    finish,
    push,
    route,
    rows,
    runtime,
    send,
    set_mode,
    telegram,
    telegram_sdk,
    bind_telegram_runtime,
)


async def card(
    runtime,
    sdk,
    monkeypatch,
    service,
    *,
    policy="exact_requester",
    body="raw *body*",
    thread=77,
    **settings,
):
    rt = await telegram(runtime, sdk, **settings)
    host = await bind_telegram_runtime(rt, monkeypatch)
    record = await pending(
        service,
        policy=policy,
        agent_id=rt.ws.agent_id,
        owner_agent_id=rt.ws.agent_id,
    )
    handle = await route(
        rt,
        "telegram:12345",
        {
            "chat_id": "12345",
            "message_thread_id": thread,
            "session_id": "telegram:12345",
            "root_session_id": "telegram:12345",
            "sender_id": "456",
            "user_id": "456",
        },
    )
    result = await send(
        rt,
        handle,
        approval={
            "request_id": record.request_id,
            "tool_name": "shell",
            "severity": "high",
        },
        parts=[{"type": "text", "text": body}],
    )
    assert result["state"] == "acknowledged"
    message = rows(sdk.work, "message-effect")[-1]["message"]
    buttons = message["reply_markup"]["inline_keyboard"][0]
    assert buttons[0]["callback_data"] == "tga:" + record.request_id
    assert buttons[1]["callback_data"] == "tgd:" + record.request_id
    assert message["text"] == (body or "🛡️ Tool Approval Required")
    assert message.get("message_thread_id") == thread
    await finish(rt, handle)
    return rt, host, record, message


def click(
    sdk,
    record,
    message,
    ident=1,
    *,
    actor=456,
    action="approve",
    **message_fields,
):
    return push(
        sdk.work,
        ident,
        callback="callback_query",
        data=("tga:" if action == "approve" else "tgd:") + record.request_id,
        **{
            "from": {
                "id": actor,
                "is_bot": False,
                "first_name": "Human",
                "username": "human",
            },
            "message": {**message, **message_fields},
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action,outcome,text",
    [
        ("approve", "approved", "Approved"),
        ("deny", "denied", "Denied"),
    ],
)
async def test_click_neutral_ack_real_actor_core_commit_before_edit(
    runtime, telegram_sdk, monkeypatch, approval_service, action, outcome, text
):
    rt, host, record, message = await card(
        runtime, telegram_sdk, monkeypatch, approval_service
    )
    click(telegram_sdk, record, message, action=action)
    await eventually(
        lambda: record.future.done()
        and bool(rows(telegram_sdk.work, "edit-effect"))
    )
    assert record.future.result().value == outcome
    ack = rows(telegram_sdk.work, "answerCallbackQuery")[-1]
    assert "received" in ack["arguments"]["text"].lower()
    assert "approved" not in ack["arguments"]["text"].lower()
    assert "denied" not in ack["arguments"]["text"].lower()
    edit = rows(telegram_sdk.work, "editMessageText")[-1]["arguments"]
    assert edit["chat_id"] == 12345
    assert edit["message_id"] == message["message_id"]
    assert edit["text"].startswith("raw *body*")
    assert text in edit["text"]
    assert "@human" in edit["text"]
    assert edit["reply_markup"] == {"inline_keyboard": []}
    assert rt.ws.requests[-1].user_id == "456"
    assert rt.ws.requests[-1].session_id == "telegram:12345"
    assert host.calls == []
    await eventually(lambda: rt.ws.requests[-1]._channel_control_state is None)


@pytest.mark.asyncio
async def test_exact_requester_denied_click_does_not_poison_later_legal_click(
    runtime, telegram_sdk, monkeypatch, approval_service
):
    rt, host, record, message = await card(
        runtime, telegram_sdk, monkeypatch, approval_service
    )
    click(telegram_sdk, record, message, actor=777)
    await eventually(
        lambda: len(rt.ws.requests) == 1
        and rt.ws.requests[-1]._channel_control_state is None
    )
    assert record.future.done() is False
    assert rows(telegram_sdk.work, "editMessageText") == []
    assert rt.ws.requests[-1].user_id == "777"
    click(telegram_sdk, record, message, 2, actor=456)
    await eventually(lambda: record.future.done() and len(rt.ws.requests) == 2)
    assert record.future.result().value == "approved"
    assert len(rt.ws.requests) == 2


@pytest.mark.asyncio
async def test_acl_denied_click_allows_later_valid_actor(
    runtime, telegram_sdk, monkeypatch, approval_service
):
    rt, host, record, message = await card(
        runtime,
        telegram_sdk,
        monkeypatch,
        approval_service,
        dm_policy="allowlist",
        access_control_dm=True,
        allow_from=["456"],
    )
    rt.channel._get_acl_store().add_to_whitelist("telegram", "456")
    click(telegram_sdk, record, message, actor=777)
    await eventually(
        lambda: bool(rows(telegram_sdk.work, "answerCallbackQuery"))
    )
    assert rt.ws.requests == []
    assert record.future.done() is False
    click(telegram_sdk, record, message, 2, actor=456)
    await eventually(lambda: record.future.done())
    assert record.future.result().value == "approved"
    assert rt.ws.requests[-1].user_id == "456"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"message_id": 999},
        {"message_thread_id": 88},
        {"chat": {"id": 99999, "type": "private"}},
    ],
)
async def test_forged_native_message_or_topic_never_admits_command(
    runtime, telegram_sdk, monkeypatch, approval_service, changes
):
    rt, host, record, message = await card(
        runtime, telegram_sdk, monkeypatch, approval_service
    )
    click(telegram_sdk, record, message, **changes)
    await eventually(
        lambda: bool(rows(telegram_sdk.work, "answerCallbackQuery"))
    )
    assert rt.ws.requests == []
    assert record.future.done() is False
    assert rows(telegram_sdk.work, "editMessageText") == []


@pytest.mark.asyncio
async def test_expired_cache_never_rebuilds_from_request_id(
    runtime, telegram_sdk, monkeypatch, approval_service
):
    rt, host, record, message = await card(
        runtime, telegram_sdk, monkeypatch, approval_service
    )
    await rt.loader.lifecycle.set_enabled("telegram", False)
    await rt.loader.lifecycle.set_enabled("telegram", True)
    click(telegram_sdk, record, message)
    await eventually(
        lambda: bool(rows(telegram_sdk.work, "answerCallbackQuery"))
    )
    assert rt.ws.requests == []
    assert record.future.done() is False
    assert rows(telegram_sdk.work, "editMessageText") == []


@pytest.mark.asyncio
async def test_two_legal_clicks_commit_once_and_second_cannot_rewrite_decision(
    runtime, telegram_sdk, monkeypatch, approval_service
):
    rt, host, record, message = await card(
        runtime, telegram_sdk, monkeypatch, approval_service
    )
    click(telegram_sdk, record, message)
    await eventually(
        lambda: record.future.done()
        and bool(rows(telegram_sdk.work, "editMessageText"))
    )
    click(telegram_sdk, record, message, 2, action="deny")
    await eventually(
        lambda: len(rows(telegram_sdk.work, "answerCallbackQuery")) == 2
    )
    assert record.future.result().value == "approved"
    assert await approval_service.get_request(record.request_id) is None
    assert len(rows(telegram_sdk.work, "editMessageText")) == 1


@pytest.mark.asyncio
async def test_card_edit_unknown_keeps_commit_without_replay(
    runtime, telegram_sdk, monkeypatch, approval_service
):
    rt, host, record, message = await card(
        runtime, telegram_sdk, monkeypatch, approval_service
    )
    set_mode(telegram_sdk.work, "editMessageText-unknown")
    click(telegram_sdk, record, message)
    await eventually(
        lambda: record.future.done()
        and bool(rows(telegram_sdk.work, "editMessageText-exit"))
    )
    assert record.future.result().value == "approved"
    assert await approval_service.get_request(record.request_id) is None
    click(telegram_sdk, record, message, 2)
    await eventually(
        lambda: len(rows(telegram_sdk.work, "answerCallbackQuery")) == 2
    )
    assert len(rows(telegram_sdk.work, "editMessageText")) == 1
    assert (
        len(
            [
                v
                for v in rows(telegram_sdk.work, "sendMessage")
                if "reply_markup" in v["arguments"]
            ]
        )
        == 1
    )


@pytest.mark.asyncio
async def test_neutral_ack_error_still_admits_authorized_command(
    runtime, telegram_sdk, monkeypatch, approval_service
):
    rt, host, record, message = await card(
        runtime, telegram_sdk, monkeypatch, approval_service
    )
    set_mode(telegram_sdk.work, "answerCallbackQuery-server")
    click(telegram_sdk, record, message)
    await eventually(
        lambda: record.future.done()
        and bool(rows(telegram_sdk.work, "editMessageText"))
    )
    assert record.future.result().value == "approved"
    assert rt.ws.requests[-1].user_id == "456"
    assert len(rows(telegram_sdk.work, "answerCallbackQuery")) == 1
    assert len(rows(telegram_sdk.work, "editMessageText")) == 1
    assert host.calls == []


@pytest.mark.asyncio
async def test_stop_settles_native_callback_ack_before_release(
    runtime, telegram_sdk, monkeypatch, approval_service
):
    import psutil

    rt, host, record, message = await card(
        runtime, telegram_sdk, monkeypatch, approval_service
    )
    set_mode(telegram_sdk.work, "answerCallbackQuery-block")
    pid = rt.process.health_snapshot()["pid"]
    click(telegram_sdk, record, message)
    await eventually(
        lambda: bool(rows(telegram_sdk.work, "answerCallbackQuery"))
    )
    stopped = await rt.manager.stop_one("telegram")
    assert stopped.stopped is True
    assert stopped.forced is False
    assert not psutil.pid_exists(pid)
    assert rows(telegram_sdk.work, "answerCallbackQuery-cancelled")
    assert len(rows(telegram_sdk.work, "answerCallbackQuery-exit")) == 1
    assert record.future.done() is False
    assert rt.ws.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user,display,body,thread",
    [
        (
            {
                "id": 456,
                "is_bot": False,
                "first_name": "Real Name",
                "username": "real_user",
            },
            "@real_user",
            "raw *body*",
            77,
        ),
        (
            {"id": 456, "is_bot": False, "first_name": "Real Name"},
            "Real Name",
            "",
            None,
        ),
        (
            {"id": 456, "is_bot": False, "first_name": ""},
            "456",
            "raw *body*",
            None,
        ),
    ],
)
async def test_real_native_actor_display_and_compact_result_keep_owned_context(
    runtime,
    telegram_sdk,
    monkeypatch,
    approval_service,
    user,
    display,
    body,
    thread,
):
    rt, host, record, message = await card(
        runtime,
        telegram_sdk,
        monkeypatch,
        approval_service,
        body=body,
        thread=thread,
    )
    push(
        telegram_sdk.work,
        callback="callback_query",
        **{
            "from": user,
            "message": message,
            "data": "tga:" + record.request_id,
        },
    )
    await eventually(lambda: bool(rows(telegram_sdk.work, "editMessageText")))
    edited = rows(telegram_sdk.work, "editMessageText")[-1]["arguments"]
    assert edited["message_id"] == message["message_id"]
    assert edited["reply_markup"] == {"inline_keyboard": []}
    if body:
        assert edited["text"] == (
            f"{body}\n\n✅ Approved by {display}  |  Tool: shell"
        )
        assert "parse_mode" not in edited
    else:
        assert edited["text"] == (
            f"✅ *Approved* by *{display}*  \\|  Tool: `shell`"
        )
        assert edited["parse_mode"] == "MarkdownV2"
    assert rt.ws.requests[-1].user_id == "456"
    assert record.future.result().value == "approved"
    assert host.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [None, "foreign:id", ""])
async def test_non_guard_native_callback_cannot_enqueue_or_edit_a_card(
    runtime, telegram_sdk, monkeypatch, approval_service, data
):
    rt, host, record, message = await card(
        runtime, telegram_sdk, monkeypatch, approval_service
    )
    push(
        telegram_sdk.work,
        callback="callback_query",
        data=data,
        message=message,
    )
    push(telegram_sdk.work, 2, text="sentinel after ignored callback")
    await eventually(lambda: len(rt.ws.requests) == 1)
    assert rt.ws.requests[0].input[0].content[0].text == (
        "sentinel after ignored callback"
    )
    assert not record.future.done()
    assert rows(telegram_sdk.work, "answerCallbackQuery") == []
    assert rows(telegram_sdk.work, "editMessageText") == []


@pytest.mark.asyncio
async def test_missing_actor_expires_without_cached_requester(
    runtime, telegram_sdk, monkeypatch, approval_service
):
    rt, host, record, message = await card(
        runtime, telegram_sdk, monkeypatch, approval_service
    )
    push(
        telegram_sdk.work,
        callback="callback_query",
        **{
            "from": None,
            "message": message,
            "data": "tga:" + record.request_id,
        },
    )
    push(telegram_sdk.work, 2, text="sentinel after missing actor")
    await eventually(lambda: len(rt.ws.requests) == 1)
    assert rt.ws.requests[0].input[0].content[0].text == (
        "sentinel after missing actor"
    )
    assert not record.future.done()
    assert (
        rows(telegram_sdk.work, "answerCallbackQuery")[0]["arguments"]["text"]
        == "This approval button has expired."
    )
    assert rows(telegram_sdk.work, "editMessageText") == []
