"""Unknown receipt durability through the real host RPC and SQLite boundary."""

import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

import g2_shared_response_suite as core
from qwenpaw.app.channels.isolated_proxy import IsolatedChannelProxy
from qwenpaw.channel_protocol.errors import RpcError
from qwenpaw.channel_protocol.models import HostStateParams, IdentityParams
from qwenpaw.channel_protocol.shared_worker import DriverContext


class HostPeer(core.Peer):
    def __init__(self, workspace):
        super().__init__()
        owner = object.__new__(IsolatedChannelProxy)
        owner._workspace_dir = workspace
        owner.channel = "plain"
        owner._launch_spec = SimpleNamespace(
            instance_id="workspace-A", generation=1
        )
        owner.channel_process = SimpleNamespace(
            health_snapshot=lambda: {"generation": 1}
        )
        owner._state, owner._state_lock = {}, asyncio.Lock()
        owner._state_closed = False
        self.owner = owner
        self.fail_archive = self.fail_live_removal = False
        self.lose_archive_ack = False
        self.fail_ack_readback = self.fail_next_receipt_get = False

    async def call(self, name, params):
        if name.startswith("host.receipt."):
            if name.endswith(".get") and self.fail_next_receipt_get:
                self.fail_next_receipt_get = False
                raise ConnectionError("archive readback unavailable")
            if name.endswith(".put") and self.fail_archive:
                raise OSError("archive unavailable")
            result = await self.owner._host_receipt(
                name.rsplit(".", 1)[1], params
            )
            if name.endswith(".put") and self.lose_archive_ack:
                self.lose_archive_ack = False
                self.fail_next_receipt_get = self.fail_ack_readback
                raise ConnectionError("archive acknowledgement lost")
            return result
        if name.startswith("host.state."):
            if (
                name.endswith(".put")
                and self.fail_live_removal
                and not params["value"]
            ):
                raise OSError("live removal unavailable")
            return await self.owner._host_state(name.rsplit(".", 1)[1], params)
        return await super().call(name, params)


def bound(workspace):
    driver, peer = core.NonCardDriver(), HostPeer(workspace)
    identity = IdentityParams("plain", "workspace-A", 1)
    driver.bind(DriverContext(peer, identity))

    async def lost_ack(params):
        driver.effects.append(("send", params.delivery_id))
        raise TimeoutError("platform acknowledgement lost")

    driver._perform_send = lost_ack
    return driver, peer, identity.to_mapping()


def state_params(identity, key="responses", value=None):
    return HostStateParams(**identity, key=key, schema_version=1, value=value)


def legacy_receipt(
    index=0, *, pending=False, reason="PLATFORM_RESULT_UNKNOWN"
):
    handle = f"plain:reply:{index}"
    return {
        "response_handle": handle,
        "kind": "terminal",
        "version": 5,
        "route_refs": [],
        "resource_refs": [
            {
                "kind": "plain.attempt",
                "resource_id": f"delivery-{index}",
                "attributes": {
                    "fingerprint": "a" * 64,
                    "operation": "message.create",
                    "state": "unknown",
                    "reason_code": reason,
                    "target_delivery_id": "",
                    "sequence": "0",
                },
            }
        ],
        "outcome": "completed",
        "cleanup_state": "pending" if pending else "complete",
        "closed_at_ms": 1,
        "cleanup_completed_at_ms": None if pending else 2,
        "expires_at_ms": None if pending else 9999999999999,
    }


async def send_unknown(driver, peer, identity, handle="plain:reply:old"):
    await core.open_route(peer, identity, handle)
    params = core.send_params(identity, handle)
    result = await peer.methods["channel.send"](params, None)
    assert result["state"] == "unknown"
    return params, result


async def assert_closed(peer, identity, handle):
    try:
        await core.open_route(peer, identity, handle)
    except Exception as exc:
        assert getattr(exc, "reason_code", str(exc)) == "RESPONSE_CLOSED"
    else:
        pytest.fail("archived handle was reopened")


@pytest.mark.asyncio
async def test_real_host_restart_replays_unknown_and_conflict_without_effects(
    tmp_path,
):
    driver, peer, identity = bound(tmp_path)
    params, result = await send_unknown(driver, peer, identity)
    await core.finish(peer, identity, params.to_handle)
    restarted, restored, identity = bound(tmp_path)
    await restarted._restore_responses()
    assert await restored.methods["channel.send"](params, None) == result
    conflict = await restored.methods["channel.send"](
        core.send_params(identity, params.to_handle, text="changed payload"),
        None,
    )
    assert conflict["state"] == "failed"
    assert conflict["reason_code"] == "DELIVERY_CONFLICT"
    closed = await restored.methods["channel.send"](
        core.send_params(identity, params.to_handle, "new-operation"), None
    )
    assert closed["state"] == "failed"
    assert closed["reason_code"] == "RESPONSE_CLOSED"
    await assert_closed(restored, identity, params.to_handle)
    await core.finish(restored, identity, params.to_handle)
    assert restarted.effects == []
    assert (await restored.owner._host_state("get", state_params(identity)))[
        "value"
    ] == []
    await core.open_route(restored, identity, "plain:reply:fresh")


@pytest.mark.asyncio
async def test_real_host_over_128_unknowns_survive_restart_without_live_loading(
    tmp_path,
):
    driver, peer, identity = bound(tmp_path)
    original = None
    for index in range(160):
        params, result = await send_unknown(
            driver, peer, identity, f"plain:reply:{index}"
        )
        if index == 0:
            original = params, result
        await core.finish(peer, identity, params.to_handle)
    restarted, restored, _ = bound(tmp_path)
    await restarted._restore_responses()
    assert restarted._routes.snapshots() == ()
    assert len(restarted._locks) == 0
    for index in range(128):
        await send_unknown(
            restarted, restored, identity, f"plain:reply:active-{index}"
        )
    effects = list(restarted.effects)
    assert len(effects) == len(restarted._locks) == 128
    assert (
        await restored.methods["channel.send"](original[0], None)
        == original[1]
    )
    assert restarted.effects == effects
    try:
        await core.open_route(restored, identity, "plain:reply:overflow")
    except Exception as exc:
        assert getattr(exc, "reason_code", str(exc)) == "RESPONSE_SCOPE_LIMIT"
    else:
        pytest.fail("129th active route was admitted")


@pytest.mark.asyncio
async def test_migrate_legacy_128_complete_unknowns_before_new_work(tmp_path):
    from qwenpaw.channel_protocol.response_receipts import receipt_key

    driver, peer, identity = bound(tmp_path)
    rows = [legacy_receipt(index) for index in range(128)]
    await peer.owner._host_state("put", state_params(identity, value=rows))
    await driver._restore_responses()
    assert (await peer.owner._host_state("get", state_params(identity)))[
        "value"
    ] == []
    for index in (0, 127):
        archived = await peer.owner._host_receipt(
            "get",
            state_params(
                identity, receipt_key("responses", f"plain:reply:{index}")
            ),
        )
        assert (
            archived["value"]["resource_refs"] == rows[index]["resource_refs"]
        )
        await assert_closed(peer, identity, f"plain:reply:{index}")
    await core.open_route(peer, identity, "plain:reply:new")
    restarted, _, _ = bound(tmp_path)
    await restarted._restore_responses()
    assert [row.response_handle for row in restarted._routes.snapshots()] == [
        "plain:reply:new"
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["archive", "live_removal"])
async def test_failed_archive_or_checkpoint_restart_does_not_duplicate(
    tmp_path, boundary
):
    driver, peer, identity = bound(tmp_path)
    params, result = await send_unknown(driver, peer, identity)
    setattr(peer, "fail_" + boundary, True)
    with pytest.raises(RpcError) as failure:
        await core.finish(peer, identity, params.to_handle)
    assert failure.value.data["reason_code"] == "RESPONSE_FINISH_FAILED"
    restarted, restored, _ = bound(tmp_path)
    await restarted._restore_responses()
    assert await restored.methods["channel.send"](params, None) == result
    await core.finish(restored, identity, params.to_handle)
    await assert_closed(restored, identity, params.to_handle)
    assert restarted.effects == []
    again, again_peer, _ = bound(tmp_path)
    await again._restore_responses()
    assert await again_peer.methods["channel.send"](params, None) == result
    assert again.effects == []


@pytest.mark.asyncio
async def test_stale_pending_json_defers_to_archived_complete_receipt(
    tmp_path,
):
    from qwenpaw.channel_protocol.response_receipts import receipt_key

    driver, peer, identity = bound(tmp_path)
    params, result = await send_unknown(driver, peer, identity)
    # A crash can leave an earlier pending snapshot beside a complete archive.
    pending = driver._routes.begin_finish(
        params.to_handle, core.ResponseOutcome.COMPLETED
    ).to_mapping()
    complete = deepcopy(pending)
    complete.update(
        version=pending["version"] + 1,
        route_refs=[],
        cleanup_state="complete",
        cleanup_completed_at_ms=pending["closed_at_ms"],
        expires_at_ms=9999999999999,
    )
    key = receipt_key("responses", params.to_handle)
    await peer.owner._host_receipt(
        "put", state_params(identity, key, complete)
    )
    await peer.owner._host_state(
        "put", state_params(identity, value=[pending])
    )
    restarted, restored, _ = bound(tmp_path)
    await restarted._restore_responses()
    assert await restored.methods["channel.send"](params, None) == result
    await core.finish(restored, identity, params.to_handle)
    assert restarted.effects == []
    assert (await restored.owner._host_state("get", state_params(identity)))[
        "value"
    ] == []
    await assert_closed(restored, identity, params.to_handle)


@pytest.mark.asyncio
async def test_pending_cleanup_stays_counted_and_cannot_be_archived(tmp_path):
    driver, peer, identity = bound(tmp_path)
    rows = [legacy_receipt(index, pending=True) for index in range(128)]
    await peer.owner._host_state("put", state_params(identity, value=rows))
    await driver._restore_responses()
    assert len(driver._routes.snapshots()) == 128
    try:
        await core.open_route(peer, identity, "plain:reply:overflow")
    except Exception as exc:
        assert getattr(exc, "reason_code", str(exc)) == "RESPONSE_SCOPE_LIMIT"
    else:
        pytest.fail("pending cleanup was removed to admit fresh work")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changed",
    [
        {"channel_key": "other"},
        {"instance_id": "other"},
        {"generation": 2},
    ],
)
async def test_real_receipt_rpc_rejects_foreign_worker_identity(
    tmp_path, changed
):
    from qwenpaw.channel_protocol.response_receipts import receipt_key

    _, peer, identity = bound(tmp_path)
    params = state_params(
        {**identity, **changed},
        receipt_key("responses", "plain:reply:0"),
        legacy_receipt(),
    )
    for operation in ("put", "get"):
        with pytest.raises(ValueError, match="STALE_GENERATION"):
            await peer.owner._host_receipt(operation, params)
    assert (
        not peer.owner._state_path().with_suffix(".receipts.sqlite3").exists()
    )


@pytest.mark.parametrize("mutation", ["pending", "acknowledged", "wrong_key"])
def test_receipt_store_rejects_noncomplete_or_mismatched_evidence(
    tmp_path, mutation
):
    from qwenpaw.channel_protocol.response_receipts import (
        ResponseReceiptStore,
        receipt_key,
    )

    store = ResponseReceiptStore(tmp_path / "receipts.sqlite3")
    row = legacy_receipt(pending=mutation == "pending")
    if mutation == "acknowledged":
        row["resource_refs"][0]["attributes"]["state"] = "acknowledged"
    key = receipt_key(
        "responses",
        "plain:reply:other" if mutation == "wrong_key" else "plain:reply:0",
    )
    with pytest.raises(ValueError):
        store.put(key, row)
    assert store.get(key) is None


def test_sqlite_archive_exceeds_live_json_limit_and_is_paginated(tmp_path):
    from qwenpaw.channel_protocol.response_receipts import (
        ResponseReceiptStore,
        receipt_key,
    )

    path = tmp_path / "receipts.sqlite3"
    store = ResponseReceiptStore(path)
    total = 0
    for index in range(280):
        value = legacy_receipt(index, reason="X" * 4096)
        total += len(json.dumps(value).encode())
        store.put(receipt_key("responses", value["response_handle"]), value)
    assert total > 1024 * 1024
    reopened = ResponseReceiptStore(path)
    first = reopened.list(namespace="responses", limit=13, offset=0)
    second = reopened.list(namespace="responses", limit=13, offset=13)
    assert len(first) == len(second) == 13
    assert {row["key"] for row in first}.isdisjoint(
        row["key"] for row in second
    )
    assert reopened.list(namespace="other", limit=13, offset=0) == []
    assert reopened.get(
        receipt_key("responses", "plain:reply:279")
    ) == legacy_receipt(279, reason="X" * 4096)
    # Connections must be closed after operations (including on Windows).
    moved = path.with_name("moved.sqlite3")
    path.rename(moved)
    moved.unlink()


def test_manual_annotation_preserves_unknown_evidence_and_rejects_blank_note(
    tmp_path,
):
    from qwenpaw.channel_protocol.response_receipts import (
        ResponseReceiptStore,
        receipt_key,
    )

    path = tmp_path / "receipts.sqlite3"
    store = ResponseReceiptStore(path)
    key, value = receipt_key("responses", "plain:reply:0"), legacy_receipt()
    store.put(key, value)
    with pytest.raises(ValueError):
        store.resolve(key, " \t\n")
    assert store.get(key) == value
    store.resolve(
        key, "Operator checked destination; delivery remains uncertain"
    )
    store.put(
        key, value
    )  # Driver migration/retry must not erase the annotation.
    reopened = ResponseReceiptStore(path)
    assert reopened.get(key) == value
    listed = reopened.list(namespace="responses", limit=1, offset=0)
    assert (
        listed[0]["resolution_note"]
        == "Operator checked destination; delivery remains uncertain"
    )
    assert listed[0]["resolved_at_ms"] > 0
    changed = deepcopy(value)
    changed["resource_refs"][0]["attributes"]["fingerprint"] = "b" * 64
    with pytest.raises(ValueError):
        reopened.put(key, changed)
    assert reopened.get(key) == value


def test_cli_lists_pages_and_resolves_without_sending_or_erasing_evidence(
    tmp_path, monkeypatch
):
    from click.testing import CliRunner
    from qwenpaw.channel_protocol.response_receipts import (
        ResponseReceiptStore,
        receipt_key,
        receipt_path,
    )
    from qwenpaw.cli.receipts_cmd import receipts_group
    from qwenpaw.app.channels.process_supervisor import ChannelProcess

    def no_worker(*args, **kwargs):
        pytest.fail("receipt inspection must not launch a worker")

    monkeypatch.setattr(ChannelProcess, "start", no_worker)
    store = ResponseReceiptStore(receipt_path(tmp_path, "plain"))
    for index in range(3):
        store.put(
            receipt_key("responses", f"plain:reply:{index}"),
            legacy_receipt(index),
        )
    options = [
        "--workspace",
        str(tmp_path),
        "--channel",
        "plain",
        "--namespace",
        "responses",
    ]
    runner = CliRunner()
    first = runner.invoke(
        receipts_group, [*options, "list", "--limit", "1", "--offset", "0"]
    )
    second = runner.invoke(
        receipts_group, [*options, "list", "--limit", "1", "--offset", "1"]
    )
    assert first.exit_code == second.exit_code == 0, (
        first.output + second.output
    )
    a, b = json.loads(first.output), json.loads(second.output)
    assert len(a) == len(b) == 1 and a[0]["key"] != b[0]["key"]
    blank = runner.invoke(
        receipts_group, [*options, "resolve", "plain:reply:0", "--note", "   "]
    )
    assert blank.exit_code != 0
    resolved = runner.invoke(
        receipts_group,
        [*options, "resolve", "plain:reply:0", "--note", "Checked manually"],
    )
    assert resolved.exit_code == 0, resolved.output
    assert (
        store.get(receipt_key("responses", "plain:reply:0"))
        == legacy_receipt()
    )
    assert (
        store.list(namespace="responses", limit=3, offset=0)[0]["value"][
            "resource_refs"
        ][0]["attributes"]["state"]
        == "unknown"
    )
    assert (
        next(
            row
            for row in store.list(namespace="responses", limit=3, offset=0)
            if row["key"] == receipt_key("responses", "plain:reply:0")
        )["resolution_note"]
        == "Checked manually"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("readback_fails", [False, True])
async def test_archive_ack_loss_retry_does_not_repeat_platform_cleanup(
    tmp_path, readback_fails
):
    driver, peer, identity = bound(tmp_path)
    handle = await core.open_route(peer, identity)
    unknown_send = driver._perform_send
    driver._perform_send = core.NonCardDriver._perform_send.__get__(driver)
    acknowledged = await peer.methods["channel.send"](
        core.send_params(identity, handle), None
    )
    assert acknowledged["state"] == "acknowledged"
    driver._perform_send = unknown_send
    params = core.send_params(identity, handle, "delivery-uncertain")
    result = await peer.methods["channel.send"](params, None)
    assert result["state"] == "unknown"
    peer.lose_archive_ack = True
    peer.fail_ack_readback = readback_fails
    if readback_fails:
        with pytest.raises(RpcError) as failure:
            await core.finish(peer, identity, handle)
        assert failure.value.data["reason_code"] == "RESPONSE_FINISH_FAILED"
    else:
        await core.finish(peer, identity, handle)
    effects = [
        ("send", "delivery-one"),
        ("send", "delivery-uncertain"),
        ("final-edit", 3),
    ]
    assert driver.effects == effects
    await core.finish(peer, identity, handle)
    await core.open_route(peer, identity, "plain:reply:fresh")
    assert driver.effects == effects
    restarted, restored, _ = bound(tmp_path)
    await restarted._restore_responses()
    assert await restored.methods["channel.send"](params, None) == result
    await core.finish(restored, identity, handle)
    assert restarted.effects == []
    assert [row.response_handle for row in restarted._routes.snapshots()] == [
        "plain:reply:fresh"
    ]


@pytest.mark.asyncio
async def test_later_checkpoint_cannot_resurrect_archived_pending_snapshot(
    tmp_path,
):
    driver, peer, identity = bound(tmp_path)
    params, result = await send_unknown(driver, peer, identity)
    peer.fail_live_removal = True
    with pytest.raises(RpcError) as failure:
        await core.finish(peer, identity, params.to_handle)
    assert failure.value.data["reason_code"] == "RESPONSE_FINISH_FAILED"
    peer.fail_live_removal = False
    await core.open_route(peer, identity, "plain:reply:another")
    rows = (await peer.owner._host_state("get", state_params(identity)))[
        "value"
    ]
    assert [row["response_handle"] for row in rows] == ["plain:reply:another"]
    assert await peer.methods["channel.send"](params, None) == result
    assert driver.effects == [("send", "delivery-one")]


@pytest.mark.asyncio
async def test_receipt_rpc_validates_wire_schema_and_storage_version(tmp_path):
    from qwenpaw.channel_protocol.models import validate_method_params
    from qwenpaw.channel_protocol.response_receipts import receipt_key

    _, peer, identity = bound(tmp_path)
    packet = state_params(
        identity, receipt_key("responses", "plain:reply:0"), legacy_receipt()
    ).to_mapping()
    for method in ("host.receipt.get", "host.receipt.put"):
        parsed = validate_method_params(method, packet)
        assert isinstance(parsed, HostStateParams)
        assert parsed.to_mapping() == packet
    packet["schema_version"] = 2
    for operation in ("get", "put"):
        with pytest.raises(ValueError, match="RESPONSE_RECEIPT_VERSION"):
            await peer.owner._host_receipt(operation, packet)
    assert (
        not peer.owner._state_path().with_suffix(".receipts.sqlite3").exists()
    )


@pytest.mark.parametrize(
    "channel,module,class_name,native",
    [
        (
            "qq",
            "qwenpaw_channel_qq.driver",
            "QQDriver",
            {
                "kind": "qq.native",
                "resource_id": "delivery-one:0",
                "attributes": {
                    "delivery_id": "delivery-one",
                    "body_sha256": "b" * 64,
                    "body_bytes": "10",
                    "msg_id": "native-reply",
                    "msg_seq": "1",
                },
            },
        ),
        (
            "wecom",
            "qwenpaw_channel_wecom.driver",
            "WeComDriver",
            {
                "kind": "wecom.delivery",
                "resource_id": "delivery-one",
                "attributes": {
                    "unsettled": "true",
                    "stream_id": "native-stream",
                    "final": "true",
                },
            },
        ),
    ],
)
def test_official_compact_receipts_preserve_native_unknown_evidence(
    tmp_path, monkeypatch, channel, module, class_name, native
):
    import importlib
    from pathlib import Path
    from qwenpaw.channel_protocol.response_lifecycle import ResponseResourceRef
    from qwenpaw.channel_protocol.response_receipts import (
        ResponseReceiptStore,
        receipt_key,
    )

    monkeypatch.syspath_prepend(
        str(
            Path(__file__).resolve().parents[3]
            / "plugins"
            / "channel"
            / channel
        )
    )
    driver = getattr(importlib.import_module(module), class_name)()
    handle = channel + ":reply:native-evidence"
    driver._routes.open(
        handle,
        [
            ResponseResourceRef.create(
                channel + ".route", handle, {"room": "native-room"}
            )
        ],
    )
    driver._routes.record_delivery(
        handle,
        [
            ResponseResourceRef.create(
                channel + ".attempt",
                "delivery-one",
                {
                    "fingerprint": "a" * 64,
                    "operation": "message.create",
                    "state": "unknown",
                    "reason_code": "PLATFORM_RESULT_UNKNOWN",
                    "target_delivery_id": "",
                    "sequence": "0",
                },
            ),
            ResponseResourceRef.from_mapping(native),
        ],
    )
    driver._routes.begin_finish(handle, core.ResponseOutcome.COMPLETED)
    value = driver._compact_receipt(
        driver._routes.cleanup_candidate(
            handle, core.ResponseOutcome.COMPLETED
        )
    ).to_mapping()
    path = tmp_path / "receipts.sqlite3"
    key = receipt_key(channel + ".shared.responses", handle)
    ResponseReceiptStore(path).put(key, value)
    restored = ResponseReceiptStore(path).get(key)
    assert native in restored["resource_refs"]
    assert any(
        ref["attributes"].get("state") == "unknown"
        for ref in restored["resource_refs"]
    )


def test_cli_agent_scope_uses_authoritative_workspace_reference(
    tmp_path, monkeypatch
):
    from click.testing import CliRunner
    from qwenpaw.channel_protocol.response_receipts import (
        ResponseReceiptStore,
        receipt_key,
        receipt_path,
    )
    from qwenpaw.cli.receipts_cmd import receipts_group
    import qwenpaw.config as config_api
    from qwenpaw.config import config

    # Agent-level optional/stale workspace fields do not determine runtime scope.
    workspace = tmp_path / "actual-workspace"
    settings = SimpleNamespace(
        agents=SimpleNamespace(
            profiles={"bot": SimpleNamespace(workspace_dir=str(workspace))}
        )
    )
    monkeypatch.setattr(config_api, "load_config", lambda: settings)
    monkeypatch.setattr(
        config,
        "load_agent_config",
        lambda agent_id: SimpleNamespace(
            workspace_dir=str(tmp_path / "stale-workspace")
        ),
    )
    value = legacy_receipt()
    key = receipt_key("responses", value["response_handle"])
    ResponseReceiptStore(receipt_path(workspace, "plain")).put(key, value)
    result = CliRunner().invoke(
        receipts_group,
        [
            "--agent-id",
            "bot",
            "--channel",
            "plain",
            "--namespace",
            "responses",
            "list",
        ],
    )
    assert result.exit_code == 0, result.output
    assert [row["value"] for row in json.loads(result.output)] == [value]


@pytest.mark.asyncio
async def test_xiaoyi_acknowledged_finish_steps_keep_normal_live_receipt(
    tmp_path, monkeypatch
):
    from pathlib import Path
    from qwenpaw.channel_protocol.response_receipts import receipt_key

    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[3] / "plugins/channel/xiaoyi")
    )
    from qwenpaw_channel_xiaoyi.driver import XiaoYiDriver

    driver, peer = XiaoYiDriver(), core.Peer()
    identity = IdentityParams("xiaoyi", "workspace-A", 1)
    driver.bind(DriverContext(peer, identity))
    steps = []

    async def send_finish_step(route, step):
        assert route == {
            "session_id": "native-session",
            "task_id": "native-task",
        }
        steps.append(step)

    driver._platform = SimpleNamespace(
        connected=True, send_finish_step=send_finish_step
    )
    driver._connected = True
    handle = "xiaoyi:reply:ack-finish"
    await driver._persist_route(
        handle, {"session_id": "native-session", "task_id": "native-task"}
    )
    await core.finish(peer, identity.to_mapping(), handle)
    await core.finish(peer, identity.to_mapping(), handle)
    assert steps == ["completed", "final"]
    snapshot = driver._routes.snapshot(handle)
    assert snapshot.cleanup_state is core.ResponseCleanupState.COMPLETE
    assert {
        (ref.resource_id, dict(ref.attributes)["state"])
        for ref in snapshot.resource_refs
    } == {("completed", "acknowledged"), ("final", "acknowledged")}
    assert peer.state["xiaoyi.shared.responses"] == [snapshot.to_mapping()]
    archived = await peer.call(
        "host.receipt.get",
        {"key": receipt_key("xiaoyi.shared.responses", handle)},
    )
    assert archived == {"value": None}
    restarted = XiaoYiDriver()
    restarted.bind(DriverContext(peer, identity))
    await restarted._restore_responses()
    await core.finish(peer, identity.to_mapping(), handle)
    assert steps == ["completed", "final"]
    assert (
        restarted._routes.snapshot(handle).cleanup_state
        is core.ResponseCleanupState.COMPLETE
    )
