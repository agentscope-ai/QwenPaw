"""Preview coalescing through the real host, native worker and Slack API."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from extension_process_suite import durable_snapshot
from slack_suite import forbid_host_sdk
from slack_support import (
    finish,
    rows,
    set_mode,
    slack,
)

pytest_plugins = ["slack_support"]


@pytest.mark.asyncio
async def test_host_coalesces_each_response_and_type_without_timer_and_sends_full_final(
    runtime,
    slack_sdk,
    monkeypatch,
):
    import qwenpaw.app.channels.isolated_proxy as host

    rt = await slack(runtime, slack_sdk, streaming_enabled=True)
    clock = [0.0]
    monkeypatch.setattr(
        host, "time", SimpleNamespace(monotonic=lambda: clock[0])
    )
    original, calls = rt.process.call, []

    async def observe(method, params, **kwargs):
        if method == "channel.send":
            calls.append(deepcopy(params))
        return await original(method, params, **kwargs)

    monkeypatch.setattr(rt.process, "call", observe)
    metas = [{"slack_channel_id": "C123"}, {"slack_channel_id": "C123"}]
    streams = [
        (meta, kind) for meta in metas for kind in ("message", "reasoning")
    ]
    for meta, kind in streams:
        await rt.channel.on_streaming_start(None, "C123", None, meta, kind)
    for meta, kind in streams:
        await rt.channel.on_streaming_delta(
            None, "C123", None, meta, kind, f"{kind}:0"
        )
    baseline_tasks = set(asyncio.all_tasks())
    for tick in range(1, 100):
        clock[0] = tick / 1000
        for meta, kind in streams:
            await rt.channel.on_streaming_delta(
                None, "C123", None, meta, kind, f"{kind}:{tick}"
            )
    deltas = [row for row in calls if row["operation"] == "stream.delta"]
    assert len(deltas) == 4
    assert len({(row["to_handle"], row["stream_type"]) for row in deltas}) == 4
    assert all(row["accumulated_text"].endswith(":0") for row in deltas)
    assert set(asyncio.all_tasks()) - baseline_tasks == set()
    clock[0] = 0.201
    for meta, kind in streams:
        await rt.channel.on_streaming_delta(
            None, "C123", None, meta, kind, f"latest {kind}"
        )
    deltas = [row for row in calls if row["operation"] == "stream.delta"]
    assert len(deltas) == 8
    assert all(
        row["accumulated_text"].endswith("latest " + row["stream_type"])
        for row in deltas[4:]
    )
    expected = []
    clock[0] = 0.202
    for index, (meta, kind) in enumerate(streams):
        text = f"完整 {index} " + "汉ab" * 3800
        expected.append(("💭 " if kind == "reasoning" else "") + text)
        await rt.channel.on_streaming_end(None, "C123", None, meta, kind, text)
        assert (
            rows(slack_sdk.work, "chat.update")[-1]["arguments"]["text"]
            == expected[-1]
        )
    finals = [row for row in calls if row["operation"] == "stream.end"]
    assert [row["accumulated_text"] for row in finals] == expected
    assert [len(row["accumulated_text"].encode()) for row in finals] == [
        len(text.encode()) for text in expected
    ]
    assert all(meta["_isolated_streams"] == {} for meta in metas)
    for meta in metas:
        await finish(rt, meta["response_handle"])


@pytest.mark.asyncio
async def test_known_capacity_suppresses_previews_and_full_final_survives_real_worker(
    runtime,
    slack_sdk,
    monkeypatch,
):
    import qwenpaw.app.channels.isolated_proxy as host

    rt = await slack(runtime, slack_sdk, streaming_enabled=True)
    clock = [0.0]
    monkeypatch.setattr(
        host, "time", SimpleNamespace(monotonic=lambda: clock[0])
    )
    full, streams, suppressed = "汉" * 9000, [], []
    for index in range(32):
        meta = {"slack_channel_id": "C123"}
        await rt.channel.on_streaming_start(
            None, "C123", None, meta, "message"
        )
        if "message" not in meta.get("_isolated_streams", {}):
            break
        await rt.channel.on_streaming_delta(
            None, "C123", None, meta, "message", full
        )
        streams.append(meta)
        if meta["_isolated_streams"]["message"].get("preview_full"):
            suppressed.append(meta)
    assert suppressed
    final_texts = {id(meta): full for meta in streams}
    for meta in suppressed:
        before = deepcopy(durable_snapshot(rt, meta["response_handle"]))
        count = len(rows(slack_sdk.work, "chat.update"))
        clock[0] += 1
        await rt.channel.on_streaming_delta(
            None, "C123", None, meta, "message", full + " latest"
        )
        assert durable_snapshot(rt, meta["response_handle"]) == before
        assert len(rows(slack_sdk.work, "chat.update")) == count
        assert not meta.get("_reply_unknown")
        final_texts[id(meta)] = full + " latest"
    for meta in streams:
        final = final_texts[id(meta)]
        await rt.channel.on_streaming_end(
            None, "C123", None, meta, "message", final
        )
        assert (
            rows(slack_sdk.work, "chat.update")[-1]["arguments"]["text"]
            == final
        )
        await finish(rt, meta["response_handle"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,state", [("unknown", "unknown"), ("reject", "failed")]
)
async def test_preview_sdk_uncertainty_and_other_failures_still_propagate(
    runtime, slack_sdk, mode, state
):
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError

    rt = await slack(runtime, slack_sdk, streaming_enabled=True)
    meta = {"slack_channel_id": "C123"}
    await rt.channel.on_streaming_start(None, "C123", None, meta, "message")
    set_mode(slack_sdk.work, "chat.update-" + mode)
    with pytest.raises(ChannelDeliveryError) as caught:
        await rt.channel.on_streaming_delta(
            None, "C123", None, meta, "message", "preview"
        )
    assert caught.value.state == state
    assert not meta["_isolated_streams"]["message"].get("preview_full")
    assert len(rows(slack_sdk.work, "chat.update")) == 1
    assert bool(meta.get("_reply_unknown")) == (state == "unknown")
