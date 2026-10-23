"""Original Slack routing and exact send formatting through actual workers."""

import pytest

from slack_suite import forbid_host_sdk
from slack_support import (
    fault_runtime,
    finish,
    route,
    rows,
    runtime,
    send,
    slack,
    slack_sdk,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target,meta,channel,thread",
    [
        ("C123:1234567890.123456", {}, "C123", "1234567890.123456"),
        (
            "C123",
            {"slack_thread_ts": "1234567890.123456"},
            "C123",
            "1234567890.123456",
        ),
        (
            "",
            {
                "slack_channel_id": "C123",
                "slack_thread_ts": "1234567890.123456",
            },
            "C123",
            "1234567890.123456",
        ),
        (
            "slack:thread:C123:1234567890.123456",
            {},
            "C123",
            "1234567890.123456",
        ),
        (
            "slack:ch:C123",
            {"slack_thread_ts": "1234567890.123456"},
            "C123",
            None,
        ),
        ("slack:dm:U123", {"slack_channel_id": "D456"}, "D456", None),
        ("slack:dm:U123", {}, "U123", None),
        (
            "U123",
            {
                "slack_channel_id": "C123",
                "slack_thread_ts": "1234567890.123456",
            },
            "C123",
            "1234567890.123456",
        ),
    ],
)
async def test_original_route_forms_observe_actual_sdk_target(
    runtime, slack_sdk, target, meta, channel, thread
):
    rt = await slack(runtime, slack_sdk)
    handle = await route(rt, target, meta)
    result = await send(
        rt, handle, parts=[{"type": "text", "text": "route body"}]
    )
    assert result["state"] == "acknowledged"
    posted = rows(slack_sdk.work, "chat.postMessage")[-1]["arguments"]
    assert posted["channel"] == channel
    assert posted.get("thread_ts") == thread
    await finish(rt, handle)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "parts,want",
    [
        ([{"type": "text", "text": "**Hello**"}], "[SlackBot] \n*Hello*"),
        (
            [{"type": "text", "text": "  leading and trailing  \n"}],
            "[SlackBot] \n  leading and trailing  \n",
        ),
        (
            [{"type": "text", "text": "\n```python\nx = 1\n```\n"}],
            "[SlackBot] \n\n```python\nx = 1\n```\n",
        ),
        (
            [
                {"type": "text", "text": "first"},
                {"type": "refusal", "refusal": "second"},
            ],
            "[SlackBot] \nfirst\nsecond",
        ),
    ],
)
async def test_host_parts_exact_prefix_text_and_metadata(
    runtime, slack_sdk, parts, want
):
    rt = await slack(runtime, slack_sdk, bot_prefix="[SlackBot] ")
    await rt.channel.send_content_parts(
        "C123", parts, {"bot_prefix": "[META] "}
    )
    assert (
        rows(slack_sdk.work, "chat.postMessage")[-1]["arguments"]["text"]
        == want
    )


@pytest.mark.asyncio
async def test_direct_send_applies_slack_configured_prefix_once(
    runtime, slack_sdk
):
    rt = await slack(runtime, slack_sdk, bot_prefix="[SlackBot] ")
    await rt.channel.send("C123", "Hello", {"bot_prefix": "[META] "})
    assert (
        rows(slack_sdk.work, "chat.postMessage")[-1]["arguments"]["text"]
        == "[SlackBot] \nHello"
    )


@pytest.mark.asyncio
async def test_known_worker_validation_error_does_not_claim_unknown(
    runtime, slack_sdk
):
    from qwenpaw.plugins.execution.errors import RpcError

    rt = await slack(runtime, slack_sdk)
    meta = {}
    with pytest.raises(RpcError) as caught:
        await rt.channel.send("C123", None, meta)
    assert caught.value.code == -32602
    assert meta.get("_reply_unknown") is not True
    assert "response_handle" not in meta
    assert rows(slack_sdk.work, "chat.postMessage") == []
    await rt.channel.send("C123", "valid after rejected input", meta)
    assert len(rows(slack_sdk.work, "chat.postMessage")) == 1
    assert (
        rows(slack_sdk.work, "chat.postMessage")[0]["arguments"]["text"]
        == "valid after rejected input"
    )
    assert meta.get("_reply_unknown") is not True


@pytest.mark.asyncio
async def test_default_whitespace_parts_have_no_effect_or_active_orphan(
    runtime,
):
    from extension_process_suite import inspect

    rt = await runtime()
    meta = {}
    await rt.channel.send_content_parts(
        "room-A", [{"type": "text", "text": " \n\t "}], meta
    )
    evidence = await inspect(rt)
    assert rt.ws.requests == []
    assert [row["operation"] for row in evidence["effects"]] == ["finish"]
    assert "response_handle" not in meta
    assert "_pending_delivery" not in meta
    assert len(evidence["routes"]) == 1
    receipt = evidence["routes"][0]
    assert receipt["kind"] == "terminal"
    assert receipt["cleanup_state"] == "complete"
    assert receipt["route_refs"] == receipt["resource_refs"] == []
