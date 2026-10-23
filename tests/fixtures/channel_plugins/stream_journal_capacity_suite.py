"""Bound stream preview receipts without losing durable delivery evidence."""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import pytest

from g2_shared_response_suite import Peer
from qwenpaw.channel_protocol.models import (
    IdentityParams,
    SendParams,
    ResponseFinishParams,
    ResponseOutcome,
)
from qwenpaw.channel_protocol.shared_worker import DriverContext
from qwenpaw.channel_protocol.outbound_budget import send_budget
from qwenpaw.channel_protocol.response_lifecycle import (
    ResponseResourceRef,
    ResponseStateError,
)


@pytest.mark.asyncio
async def test_budget_context_preserves_domain_exception_identity_and_reason():
    error = ResponseStateError("RESPONSE_CLOSED", "response route is closed")
    with pytest.raises(ResponseStateError) as caught:
        with send_budget():
            raise error
    assert caught.value is error
    assert caught.value.reason_code == "RESPONSE_CLOSED"
    assert caught.value.retryable is False


@pytest.mark.asyncio
async def test_real_qq_native_receipt_uses_legacy_checkpoint_reservation(
    monkeypatch,
):
    import hashlib

    source = Path(__file__).resolve().parents[3] / "plugins/channel/qq"
    monkeypatch.syspath_prepend(str(source))
    from qwenpaw_channel_qq.driver import QQDriver

    driver, peer = QQDriver(), Peer()
    identity = IdentityParams("qq", "workspace-native-reserve", 1)
    driver.bind(DriverContext(peer, identity))
    handle = "qq:reply:legacy-reserve"
    try:
        await driver._persist_route(handle, {"sender_id": "user-A"})
        params = SendParams.from_mapping(
            {
                **identity.to_mapping(),
                "delivery_id": "native-send",
                "to_handle": handle,
                "operation": "message.create",
                "content_parts": [{"type": "text", "text": "native"}],
            }
        )
        body = b'{"content":"native"}'
        attrs = {
            "method": "POST",
            "path": "/v2/users/user-A/messages",
            "body_sha256": hashlib.sha256(body).hexdigest(),
            "body_bytes": str(len(body)),
            "content_type": "application/json",
            "delivery_id": params.delivery_id,
            "msg_seq": "1",
        }
        await driver._record_native(params, 1, attrs)
        row = peer.state["qq.shared.responses"][0]
        assert row["response_handle"] == handle
        assert row["resource_refs"] == [
            {
                "kind": "qq.native",
                "resource_id": "native-send:1",
                "attributes": attrs,
            }
        ]
    finally:
        peer._receipt_dir.cleanup()


class SlackAPI:
    """Only the external Slack API is replaced; Driver and Platform are real."""

    def __init__(self):
        self.effects = []
        self.update_unknown = False

    async def chat_postMessage(self, **arguments):
        self.effects.append(("post", arguments))
        return {"ok": True, "ts": str(len(self.effects))}

    async def chat_update(self, **arguments):
        self.effects.append(("update", arguments))
        if self.update_unknown:
            raise TimeoutError("Slack accepted request; response unavailable")
        return {"ok": True}

    async def chat_delete(self, **arguments):
        self.effects.append(("delete", arguments))
        return {"ok": True}


@pytest.fixture
def slack_driver():
    source = Path(__file__).resolve().parents[3] / "plugins/channel/slack"
    sys.path.insert(0, str(source))
    from qwenpaw_channel_slack.driver import SlackDriver
    from qwenpaw_channel_slack.platform import SlackPlatform
    from qwenpaw_channel_slack.sender import SlackSender

    driver, peer, api = SlackDriver(), Peer(), SlackAPI()
    identity = IdentityParams("slack", "workspace-journal", 1)
    driver.bind(DriverContext(peer, identity))
    config = {"streaming_enabled": True}
    platform = SlackPlatform(config, None, None)
    platform._client = api
    platform._sender = SlackSender(platform)
    platform.connected = True
    driver._platform, driver._config, driver._connected = (
        platform,
        config,
        True,
    )
    yield SimpleNamespace(driver=driver, peer=peer, api=api, identity=identity)
    sys.path.remove(str(source))
    peer._receipt_dir.cleanup()


async def open_stream(rt, name="start", kind="message", handle=None):
    if handle is None:
        handle = (
            await rt.peer.methods["channel.response.open"](
                {
                    **rt.identity.to_mapping(),
                    "to_handle": "slack:ch:C123",
                    "meta": {"slack_channel_id": "C123"},
                },
                None,
            )
        )["response_handle"]
    result = await stream(rt, handle, "start", name, 0, "...", kind=kind)
    assert result["state"] == "acknowledged"
    return handle


def stream_params(
    rt,
    handle,
    operation,
    delivery,
    sequence,
    text,
    *,
    target="start",
    kind="message",
):
    params = {
        **rt.identity.to_mapping(),
        "delivery_id": delivery,
        "to_handle": handle,
        "operation": "stream." + operation,
        "stream_type": kind,
        "sequence": sequence,
        "accumulated_text": text,
    }
    if operation != "start":
        params["target_delivery_id"] = target
    return SendParams.from_mapping(params)


async def stream(rt, handle, operation, delivery, sequence, text, **kwargs):
    return await rt.peer.methods["channel.send"](
        stream_params(
            rt, handle, operation, delivery, sequence, text, **kwargs
        ),
        None,
    )


def checkpoint(rt):
    return rt.peer.state["slack.shared.responses"]


def checkpoint_bytes(rt):
    return len(json.dumps(checkpoint(rt), ensure_ascii=False).encode("utf-8"))


async def restart(rt):
    driver = type(rt.driver)()
    driver.bind(DriverContext(rt.peer, rt.identity))
    driver._platform = rt.driver._platform
    driver._config, driver._connected = rt.driver._config, True
    await driver._restore_responses()
    rt.driver = driver


def attempts(rt, handle):
    return {
        ref["resource_id"]: ref["attributes"]
        for row in checkpoint(rt)
        if row["response_handle"] == handle
        for ref in row["resource_refs"]
        if ref["kind"] == "slack.attempt"
    }


@pytest.mark.asyncio
async def test_explicit_legacy_reservation_is_enforced_at_actual_checkpoint_capacity(
    slack_driver,
):
    rt = slack_driver
    handle = await open_stream(rt)
    result = await stream(
        rt, handle, "delta", "large-preview", 1, "汉" * 250_000
    )
    assert result["state"] == "acknowledged"
    assert 700 * 1024 < checkpoint_bytes(rt) < 768 * 1024
    await rt.driver._checkpoint(reserve_bytes=0)
    before, effects = deepcopy(checkpoint(rt)), list(rt.api.effects)
    with pytest.raises(ValueError, match="^RESPONSE_STATE_CAPACITY$"):
        await rt.driver._checkpoint(reserve_bytes=64 * 1024)
    assert checkpoint(rt) == before
    assert rt.api.effects == effects


@pytest.mark.asyncio
async def test_nonstream_send_keeps_legacy_receipt_reserve_before_sdk(
    slack_driver,
):
    rt = slack_driver
    handle = (
        await rt.peer.methods["channel.response.open"](
            {
                **rt.identity.to_mapping(),
                "to_handle": "slack:ch:C123",
                "meta": {},
            },
            None,
        )
    )["response_handle"]

    def opaque(text):
        return ResponseResourceRef.create(
            "slack.opaque", "legacy-nonstream-evidence", {"text": text}
        )

    rt.driver._routes.record_delivery(handle, [opaque("")])
    await rt.driver._checkpoint()
    filler_bytes = 768 * 1024 - 900 - checkpoint_bytes(rt)
    rt.driver._routes.record_delivery(
        handle, [opaque("汉" * (filler_bytes // 3) + "x" * (filler_bytes % 3))]
    )
    await rt.driver._checkpoint()
    assert 768 * 1024 - checkpoint_bytes(rt) == 900
    params = SendParams.from_mapping(
        {
            **rt.identity.to_mapping(),
            "delivery_id": "near-cap-send",
            "to_handle": handle,
            "operation": "message.create",
            "content_parts": [
                {"type": "text", "text": "small ordinary message"}
            ],
        }
    )
    original, admitted_free_bytes = rt.peer.call, []

    async def observe_intent(name, values):
        if name == "host.state.put" and any(
            ref["resource_id"] == params.delivery_id
            and ref["attributes"].get("state") == "unknown"
            for row in values["value"]
            for ref in row["resource_refs"]
        ):
            size = len(
                json.dumps(values["value"], ensure_ascii=False).encode()
            )
            admitted_free_bytes.append(768 * 1024 - size)
        return await original(name, values)

    rt.peer.call = observe_intent
    result = await rt.peer.methods["channel.send"](params, None)
    assert all(256 <= free < 1024 for free in admitted_free_bytes)
    assert rt.api.effects == [], (result, admitted_free_bytes, rt.api.effects)
    assert result["state"] == "failed"
    assert result["reason_code"] == "RESPONSE_STATE_CAPACITY"


@pytest.mark.asyncio
async def test_thousands_of_real_slack_previews_leave_room_for_full_final(
    slack_driver,
):
    rt = slack_driver
    handle = await open_stream(rt)
    failures, samples = [], []
    for sequence in range(1, 3201):
        result = await stream(
            rt,
            handle,
            "delta",
            f"delta-{sequence}",
            sequence,
            "汉ab" * sequence,
        )
        if result["state"] != "acknowledged":
            failures.append((sequence, result))
        if sequence in (400, 1200, 3200):
            samples.append(checkpoint_bytes(rt))
    final = "汉ab" * 3200 + " 完整结尾"
    result = await stream(rt, handle, "end", "end", 3201, final)
    assert result["state"] == "acknowledged", (result, failures[:1], samples)
    assert rt.api.effects[-1] == (
        "update",
        {"channel": "C123", "ts": "1", "text": final, "mrkdwn": True},
    )
    assert len(rt.api.effects[-1][1]["text"].encode("utf-8")) == len(
        final.encode("utf-8")
    )
    assert failures == []
    assert max(samples) < 256 * 1024, samples
    assert samples[-1] - samples[0] < 64 * 1024, samples
    assert checkpoint_bytes(rt) < 768 * 1024


@pytest.mark.asyncio
async def test_compacted_replays_stay_stale_and_recent_fingerprints_survive_restart(
    slack_driver,
):
    rt = slack_driver
    handle = await open_stream(rt)
    for sequence in range(1, 25):
        assert (
            await stream(
                rt,
                handle,
                "delta",
                f"delta-{sequence}",
                sequence,
                str(sequence),
            )
        )["state"] == "acknowledged"
    await restart(rt)
    before = list(rt.api.effects)
    for text in ("1", "changed old text"):
        result = await stream(rt, handle, "delta", "delta-1", 1, text)
        assert result["state"] == "failed"
        assert result["reason_code"] == "STREAM_SEQUENCE_STALE"
    assert (await stream(rt, handle, "delta", "delta-24", 24, "24"))[
        "state"
    ] == "acknowledged"
    changed = await stream(
        rt, handle, "delta", "delta-24", 24, "conflicting text"
    )
    assert changed["reason_code"] == "DELIVERY_CONFLICT"
    assert rt.api.effects == before
    assert len(attempts(rt, handle)) <= 5


@pytest.mark.asyncio
async def test_legacy_restore_compacts_only_confirmed_deltas_and_keeps_other_evidence(
    slack_driver,
):
    rt = slack_driver
    handle = await open_stream(rt)
    await stream(rt, handle, "delta", "delta-1800", 1800, "latest")
    row = deepcopy(checkpoint(rt)[0])
    row["resource_refs"] = [
        ref
        for ref in row["resource_refs"]
        if ref["resource_id"] != "delta-1800"
    ]
    for sequence in range(1, 1801):
        params = stream_params(
            rt, handle, "delta", f"delta-{sequence}", sequence, "latest"
        )
        row["resource_refs"].append(
            {
                "kind": "slack.attempt",
                "resource_id": params.delivery_id,
                "attributes": {
                    "fingerprint": rt.driver._operation_fingerprint(params),
                    "operation": "stream.delta",
                    "state": "acknowledged",
                    "reason_code": "",
                    "target_delivery_id": "start",
                    "sequence": str(sequence),
                },
            }
        )
    pinned = []
    for name, operation, state in (
        ("unknown-delta", "stream.delta", "unknown"),
        ("failed-delta", "stream.delta", "failed"),
        ("message", "message.create", "acknowledged"),
        ("old-end", "stream.end", "acknowledged"),
    ):
        ref = deepcopy(row["resource_refs"][-1])
        ref["resource_id"] = name
        ref["attributes"].update(
            operation=operation, state=state, target_delivery_id="other"
        )
        pinned.append(ref)
    row["resource_refs"].extend(pinned)
    row["resource_refs"].sort(
        key=lambda ref: (ref["kind"], ref["resource_id"])
    )
    rt.peer.state["slack.shared.responses"] = [row]
    assert checkpoint_bytes(rt) > 400 * 1024
    await restart(rt)
    assert checkpoint_bytes(rt) < 32 * 1024
    restored = checkpoint(rt)[0]["resource_refs"]
    assert all(ref in restored for ref in pinned)
    assert "start" in attempts(rt, handle)
    before = list(rt.api.effects)
    result = await stream(rt, handle, "delta", "delta-1", 1, "latest")
    assert result["state"] == "failed"
    assert result["reason_code"] == "STREAM_SEQUENCE_STALE"
    assert rt.api.effects == before


@pytest.mark.asyncio
async def test_unknown_delta_is_never_evicted_or_bypassed_by_other_stream_compaction(
    slack_driver,
):
    rt = slack_driver
    handle = await open_stream(rt)
    rt.api.update_unknown = True
    unknown = await stream(
        rt, handle, "delta", "uncertain", 1, "maybe delivered"
    )
    assert unknown["state"] == "unknown"
    rt.api.update_unknown = False
    await open_stream(rt, "reasoning", "reasoning", handle)
    for sequence in range(1, 25):
        assert (
            await stream(
                rt,
                handle,
                "delta",
                f"reason-{sequence}",
                sequence,
                str(sequence),
                target="reasoning",
                kind="reasoning",
            )
        )["state"] == "acknowledged"
    unknown_receipt = deepcopy(attempts(rt, handle)["uncertain"])
    await restart(rt)
    assert attempts(rt, handle)["uncertain"] == unknown_receipt
    before = list(rt.api.effects)
    assert (
        await stream(rt, handle, "delta", "uncertain", 1, "maybe delivered")
    )["state"] == "unknown"
    assert (await stream(rt, handle, "delta", "uncertain", 1, "changed"))[
        "reason_code"
    ] == "DELIVERY_CONFLICT"
    assert (
        await stream(
            rt, handle, "end", "end", 2, "must not bypass uncertainty"
        )
    )["state"] == "unknown"
    assert rt.api.effects == before


@pytest.mark.asyncio
async def test_failed_ack_checkpoint_preserves_unknown_intent_during_compaction(
    slack_driver, monkeypatch
):
    rt = slack_driver
    handle = await open_stream(rt)
    for sequence in range(1, 5):
        await stream(
            rt, handle, "delta", f"delta-{sequence}", sequence, str(sequence)
        )
    import qwenpaw_channel_slack.platform as platform

    monkeypatch.setattr(
        platform,
        "time",
        SimpleNamespace(monotonic=lambda: time.monotonic() + 2),
    )
    before_effects = len(rt.api.effects)
    original, writes = rt.peer.call, 0

    async def fail_ack(name, params):
        nonlocal writes
        if name == "host.state.put":
            writes += 1
            if writes == 2:
                raise OSError("checkpoint write failed after Slack effect")
        return await original(name, params)

    rt.peer.call = fail_ack
    result = await stream(rt, handle, "delta", "delta-5", 5, "five")
    assert result["state"] == "unknown"
    assert len(rt.api.effects) == before_effects + 1
    assert rt.api.effects[-1][1]["text"] == "five"
    rt.peer.call = original
    assert attempts(rt, handle)["delta-5"]["state"] == "unknown"
    await restart(rt)
    before = list(rt.api.effects)
    assert (await stream(rt, handle, "delta", "delta-5", 5, "five"))[
        "state"
    ] == "unknown"
    assert (await stream(rt, handle, "delta", "later", 6, "six"))[
        "state"
    ] == "unknown"
    assert rt.api.effects == before


@pytest.mark.asyncio
async def test_competing_utf8_streams_refuse_previews_before_sdk_and_can_all_finalize(
    slack_driver,
):
    rt = slack_driver
    admitted, refused = [], []
    full = "汉" * 9000
    for index in range(40):
        try:
            handle = await open_stream(rt)
        except ValueError as exc:
            assert str(exc) == "RESPONSE_STATE_CAPACITY"
            refused.append((index, "route"))
            break
        before = list(rt.api.effects)
        result = await stream(rt, handle, "delta", f"delta-{index}", 1, full)
        if result["state"] == "acknowledged":
            admitted.append((handle, full))
        else:
            assert result["state"] == "failed"
            assert result["reason_code"] == "RESPONSE_STATE_CAPACITY"
            assert rt.api.effects == before
            refused.append((index, "delta"))
            admitted.append((handle, full))
    assert refused, checkpoint_bytes(rt)
    assert admitted
    for index, (handle, text) in enumerate(admitted):
        result = await stream(rt, handle, "end", f"final-{index}", 2, text)
        assert result["state"] == "acknowledged", (
            index,
            result,
            checkpoint_bytes(rt),
        )
        assert rt.api.effects[-1][1]["text"] == text
        assert len(rt.api.effects[-1][1]["text"].encode()) == len(
            text.encode()
        )
        await rt.peer.methods["channel.response.finish"](
            ResponseFinishParams(
                **rt.identity.to_mapping(),
                response_handle=handle,
                outcome=ResponseOutcome.COMPLETED,
            ),
            None,
        )
        assert checkpoint_bytes(rt) <= 768 * 1024


@pytest.mark.asyncio
async def test_all_128_active_streams_keep_final_and_cleanup_capacity(
    slack_driver,
):
    rt = slack_driver
    handles = [await open_stream(rt) for _ in range(128)]
    for index, handle in enumerate(handles):
        assert (
            await stream(
                rt, handle, "delta", f"delta-{index}", 1, f"预览{index}"
            )
        )["state"] == "acknowledged"
    assert len(checkpoint(rt)) == 128
    for index, handle in enumerate(handles):
        final = f"完整最终内容{index}"
        assert (await stream(rt, handle, "end", f"end-{index}", 2, final))[
            "state"
        ] == "acknowledged"
        assert rt.api.effects[-1][1]["text"] == final
        await rt.peer.methods["channel.response.finish"](
            ResponseFinishParams(
                **rt.identity.to_mapping(),
                response_handle=handle,
                outcome=ResponseOutcome.COMPLETED,
            ),
            None,
        )
    assert checkpoint_bytes(rt) < 768 * 1024


@pytest.mark.asyncio
async def test_inflight_preview_growth_is_reserved_across_response_admissions(
    slack_driver, monkeypatch
):
    rt = slack_driver
    first, second = await open_stream(rt), await open_stream(rt)
    entered, release = asyncio.Event(), asyncio.Event()
    original = rt.api.chat_update

    async def blocked_update(**arguments):
        result = await original(**arguments)
        if arguments["ts"] == "1":
            entered.set()
            await release.wait()
        return result

    monkeypatch.setattr(rt.api, "chat_update", blocked_update)
    full = "汉" * 136_000
    pending = asyncio.create_task(
        stream(rt, first, "delta", "first-delta", 1, full)
    )
    try:
        await asyncio.wait_for(entered.wait(), 2)
        before = list(rt.api.effects)
        second_result = await stream(
            rt, second, "delta", "second-delta", 1, full
        )
        after_second = list(rt.api.effects)
    finally:
        release.set()
        first_result = await pending
    assert second_result["state"] == "failed", (second_result, first_result)
    assert second_result["reason_code"] == "RESPONSE_STATE_CAPACITY"
    assert after_second == before
    assert first_result["state"] == "acknowledged"
    assert checkpoint_bytes(rt) < 768 * 1024
    for index, handle in enumerate((first, second)):
        offset = len(rt.api.effects)
        result = await stream(rt, handle, "end", f"end-{index}", 2, full)
        assert result["state"] == "acknowledged"
        delivered = "".join(
            arguments["text"]
            for kind, arguments in rt.api.effects[offset:]
            if kind == "post"
        )
        assert delivered == full
        assert len(delivered.encode()) == len(full.encode())
        await rt.peer.methods["channel.response.finish"](
            ResponseFinishParams(
                **rt.identity.to_mapping(),
                response_handle=handle,
                outcome=ResponseOutcome.COMPLETED,
            ),
            None,
        )
