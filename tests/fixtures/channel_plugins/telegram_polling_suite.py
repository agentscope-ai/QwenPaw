"""Native PTB retries, effective timeout, cleanup offset and owned teardown."""

import asyncio
from urllib.parse import quote

import psutil
import pytest

from telegram_business_suite import forbid_host_sdk
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure,minimum,maximum",
    [
        ("getUpdates-timeout", 0, 1),
        ("getUpdates-rate", 1.5, 2.5),
    ],
)
async def test_timeout_and_retry_after_never_reconnect(
    runtime, telegram_sdk, failure, minimum, maximum
):
    set_mode(telegram_sdk.work, failure)
    await telegram(runtime, telegram_sdk)
    await eventually(lambda: len(rows(telegram_sdk.work, "getUpdates")) >= 3)
    polls = rows(telegram_sdk.work, "getUpdates")
    delay = polls[1]["at"] - polls[0]["at"]
    assert minimum <= delay < maximum
    assert len(rows(telegram_sdk.work, "getMe")) == 1
    assert len(rows(telegram_sdk.work, "deleteWebhook")) == 1
    assert polls[0]["read_timeout"] == 30
    assert polls[0]["arguments"]["timeout"] == 10


@pytest.mark.asyncio
async def test_commands_urls_allowed_updates_and_cleanup_offset(
    runtime, telegram_sdk
):
    rt = await telegram(
        runtime, telegram_sdk, base_url=" https://tg-api.example.test/ "
    )
    push(telegram_sdk.work, 19, text="offset input")
    await eventually(lambda: len(rt.ws.requests) == 1)
    commands = rows(telegram_sdk.work, "setMyCommands")[0]["arguments"][
        "commands"
    ]
    assert [item["command"] for item in commands] == [
        "start",
        "new",
        "compact",
        "clear",
        "history",
        "model",
        "stop",
    ]
    calls = rows(telegram_sdk.work, "getUpdates")
    assert calls[0]["arguments"]["allowed_updates"] == [
        "message",
        "edited_message",
        "callback_query",
    ]
    assert (
        rows(telegram_sdk.work, "getMe")[0]["url"]
        == "https://tg-api.example.test/bot123:local-A/getMe"
    )
    pid = rt.process.health_snapshot()["pid"]
    stopped = await rt.manager.stop_one("telegram")
    assert stopped.stopped is True
    assert not psutil.pid_exists(pid)
    calls = rows(telegram_sdk.work, "getUpdates")
    assert calls[-1]["arguments"]["timeout"] == 0
    assert calls[-1]["arguments"]["offset"] == 20
    exits = rows(telegram_sdk.work, "getUpdates-exit")
    assert len(exits) == len(calls)
    assert {v["task"] for v in exits} == {v["task"] for v in calls}
    assert (
        len(rows(telegram_sdk.work, "http-close-enter"))
        == len(rows(telegram_sdk.work, "http-close-exit"))
        == 2
    )


@pytest.mark.asyncio
async def test_two_workspaces_have_distinct_native_ownership(
    runtime, telegram_sdk
):
    first = await telegram(runtime, telegram_sdk, workspace_name="A")
    second = await telegram(
        runtime,
        telegram_sdk,
        token="456:local-B",
        workspace_name="B",
        existing_loader=first.loader,
    )
    push(telegram_sdk.work, text="first workspace")
    push(telegram_sdk.work, token="456:local-B", text="second workspace")
    await eventually(
        lambda: len(first.ws.requests) == len(second.ws.requests) == 1
    )
    assert first.ws.requests[0].input[0].content[0].text == "first workspace"
    assert second.ws.requests[0].input[0].content[0].text == "second workspace"
    assert (
        first.ws.requests[0].session_id
        == second.ws.requests[0].session_id
        == "telegram:12345"
    )
    first_pid = first.process.health_snapshot()["pid"]
    second_pid = second.process.health_snapshot()["pid"]
    assert first_pid != second_pid
    assert (await first.manager.stop_one("telegram")).stopped
    assert not psutil.pid_exists(first_pid)
    assert psutil.pid_exists(second_pid)
    push(telegram_sdk.work, 2, token="456:local-B", text="second stays alive")
    await eventually(lambda: len(second.ws.requests) == 2)
    assert (
        second.ws.requests[-1].input[0].content[0].text == "second stays alive"
    )
    await first.loader.lifecycle.set_enabled("telegram", False)
    assert not psutil.pid_exists(second_pid)


@pytest.mark.asyncio
async def test_http_close_failure_forces_real_reap(runtime, telegram_sdk):
    rt = await telegram(runtime, telegram_sdk)
    set_mode(telegram_sdk.work, "http-close-fail")
    pid = rt.process.health_snapshot()["pid"]
    result = await rt.manager.stop_one("telegram")
    assert rows(telegram_sdk.work, "http-close-enter")
    assert rows(telegram_sdk.work, "http-close-exit") == []
    # Forced process exit is distinct from graceful SDK teardown.
    assert result.forced is True
    assert result.exited is True
    assert not psutil.pid_exists(pid)


@pytest.mark.asyncio
async def test_held_native_request_finally_must_settle_before_http_close(
    runtime, telegram_sdk
):
    rt = await telegram(runtime, telegram_sdk)
    set_mode(telegram_sdk.work, "getUpdates-finally-block")
    await eventually(
        lambda: bool(rows(telegram_sdk.work, "getUpdates-finally-enter"))
    )
    task = asyncio.create_task(rt.manager.stop_one("telegram"))
    await asyncio.sleep(0.1)
    assert task.done() is False
    assert rows(telegram_sdk.work, "http-close-enter") == []
    set_mode(telegram_sdk.work, "")
    result = await task
    assert result.stopped
    assert rows(telegram_sdk.work, "getUpdates-finally-interrupted") == []
    calls = rows(telegram_sdk.work, "getUpdates")
    exits = rows(telegram_sdk.work, "getUpdates-exit")
    assert len(calls) == len(exits)
    assert len(rows(telegram_sdk.work, "http-close-exit")) == 2


@pytest.mark.asyncio
async def test_long_poll_body_exits_in_existing_stop_budget(
    runtime, telegram_sdk
):
    rt = await telegram(runtime, telegram_sdk)
    baseline = len(rows(telegram_sdk.work, "getUpdates"))
    set_mode(telegram_sdk.work, "getUpdates-block")
    await eventually(
        lambda: len(rows(telegram_sdk.work, "getUpdates")) > baseline
    )
    result = await rt.manager.stop_one("telegram")
    assert result.stopped is True
    assert result.forced is False
    assert rows(telegram_sdk.work, "getUpdates-cancelled")
    calls, exits = rows(telegram_sdk.work, "getUpdates"), rows(
        telegram_sdk.work, "getUpdates-exit"
    )
    assert len(calls) == len(exits)
    assert len(rows(telegram_sdk.work, "http-close-exit")) == 2


@pytest.mark.asyncio
async def test_headers_then_blocked_body_cancel_once_and_close(
    runtime, telegram_sdk
):
    rt = await telegram(runtime, telegram_sdk)
    set_mode(telegram_sdk.work, "getUpdates-body-block")
    await eventually(
        lambda: bool(rows(telegram_sdk.work, "getUpdates-body-enter"))
    )
    assert rows(telegram_sdk.work, "getUpdates-body-exit") == []
    result = await rt.manager.stop_one("telegram")
    assert result.stopped is True
    assert result.forced is False
    assert len(rows(telegram_sdk.work, "getUpdates-body-cancelled")) == 1
    assert len(rows(telegram_sdk.work, "getUpdates-body-exit")) == 1
    enters = rows(telegram_sdk.work, "getUpdates-stream-close-enter")
    exits = rows(telegram_sdk.work, "getUpdates-stream-close-exit")
    assert sorted(v["request_id"] for v in enters) == sorted(
        v["request_id"] for v in exits
    )
    assert rows(telegram_sdk.work, "getUpdates-body-cancelled")[0][
        "request_id"
    ] in {v["request_id"] for v in exits}
    assert len(rows(telegram_sdk.work, "http-close-exit")) == 2


@pytest.mark.asyncio
async def test_body_read_stream_close_finally_is_awaited_without_second_cancel(
    runtime, telegram_sdk
):
    rt = await telegram(runtime, telegram_sdk)
    set_mode(telegram_sdk.work, "getUpdates-close-block")
    await eventually(
        lambda: bool(rows(telegram_sdk.work, "getUpdates-stream-close-enter"))
    )
    task = asyncio.create_task(rt.manager.stop_one("telegram"))
    await asyncio.sleep(0.1)
    assert task.done() is False
    assert rows(telegram_sdk.work, "http-close-enter") == []
    set_mode(telegram_sdk.work, "")
    result = await task
    assert result.stopped is True
    assert result.forced is False
    assert rows(telegram_sdk.work, "getUpdates-stream-close-interrupted") == []
    enters = rows(telegram_sdk.work, "getUpdates-stream-close-enter")
    exits = rows(telegram_sdk.work, "getUpdates-stream-close-exit")
    assert all(v["poll_timeout"] > 0 for v in enters)
    assert sorted(v["request_id"] for v in enters) == sorted(
        v["request_id"] for v in exits
    )
    assert len(rows(telegram_sdk.work, "http-close-exit")) == 2


@pytest.mark.asyncio
async def test_conflict_network_cycles_reset_each_other(runtime, telegram_sdk):
    import json
    from telegram_support import TOKEN

    directory = telegram_sdk.work / quote(TOKEN, safe="")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "poll-script.json").write_text(
        json.dumps(
            [
                {"code": 409},
                {"code": 503, "description": "service unavailable"},
                {"code": 409},
            ]
        )
    )
    rt = await telegram(runtime, telegram_sdk)
    async with asyncio.timeout(24):
        while len(rows(telegram_sdk.work, "getMe")) < 4:
            await asyncio.sleep(0.02)
    calls = rows(telegram_sdk.work)
    starts = [v for v in calls if v["kind"] == "getMe"][:4]
    for left, right in zip(starts, starts[1:]):
        closed = [
            v
            for v in calls
            if v["kind"] == "http-close-exit"
            and left["at"] < v["at"] < right["at"]
        ]
        assert len(closed) == 2
        assert 5 <= right["at"] - closed[-1]["at"] < 6
    await eventually(
        lambda: bool(rows(telegram_sdk.work, "getUpdates-success"))
    )
    assert rt.process.health_snapshot()["pid"]
