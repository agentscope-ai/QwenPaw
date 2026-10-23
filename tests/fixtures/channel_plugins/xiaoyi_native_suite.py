"""Native XiaoYi wire effects and real shared delivery/finish ownership."""
import asyncio
import json
import platform as host_platform

import pytest

pytest.register_assert_rewrite("xiaoyi_native_support")
from xiaoyi_native_support import (  # noqa: E402
    eventually,
    inbound,
    open_route,
    send,
)

pytest_plugins = ["xiaoyi_native_support"]
pytestmark = pytest.mark.asyncio


async def test_auth_init_dual_connections_and_custom_url_disables_backup(
    native_driver, modules, tmp_path
):
    driver, _, _, gateway = native_driver
    await eventually(lambda: len(gateway.frames) == 2)
    assert set(gateway.headers) == {"primary", "backup"}
    for server, message in gateway.frames:
        assert server in {"primary", "backup"}
        assert message["msgType"] == "clawd_bot_init"
        assert message["agentId"] == "local-agent"
        assert json.loads(message["msgDetail"]) == {
            "agentId": "local-agent",
            "hostname": host_platform.node(),
        }
    assert (await driver._platform.health_check())["status"] == "healthy"
    states = []

    async def state(value):
        states.append(value)

    custom = modules["platform"].XiaoYiPlatform(
        {
            "ak": "local-ak",
            "sk": "local-sk",
            "agent_id": "local-agent",
            "ws_url": gateway.primary,
            "workspace_dir": str(tmp_path / "custom"),
        },
        None,
        state,
    )
    try:
        await custom.start()
        assert custom._conn_primary.connected
        assert custom._conn_backup is None
        assert states == ["connecting", "connected"]
    finally:
        await custom.stop()


async def test_dual_native_ids_dedupe_but_identical_text_with_new_id_is_admitted(  # noqa: E501
    native_driver,
):
    driver, peer, identity, gateway = native_driver
    value = inbound(request=1001, task=2001, message="native-1")
    await asyncio.gather(gateway.push(value), gateway.push(value, "backup"))
    await eventually(lambda: len(peer.batches) == 1)
    # A barrier through both receive loops makes duplicate processing
    # observable.
    await gateway.push(inbound(request=1002, task=2002, message="native-2"))
    await gateway.push(
        inbound(request=1003, task=2003, message="native-3"), "backup"
    )
    await eventually(lambda: len(peer.batches) == 3)
    events = [batch["events"][0] for batch in peer.batches]
    assert len({event["event_id"] for event in events}) == 3
    assert all(
        event["content_parts"] == [{"type": "text", "text": "hello"}]
        for event in events
    )
    first = events[0]
    assert {key: first[key] for key in identity} == identity
    assert first["sender_id"] == first["acl_sender_id"] == "session-A"
    assert first["metadata"]["session_id"] == "xiaoyi:session-A"
    assert first["metadata"]["task_id"] == 2001
    assert first["conversation"] == {
        "id": "session-A",
        "type": "dm",
        "thread_id": None,
    }
    route = driver._route_attrs(first["response_handle"])
    assert route["task_id"] == "2001" and route["message_id"] == "1001"
    assert await send(peer, identity, first["response_handle"]) == {
        "delivery_id": "delivery-A",
        "state": "acknowledged",
        "retryable": False,
    }
    await eventually(lambda: len(gateway.results()) == 1)
    server, result = gateway.results()[0]
    assert server == route["server_name"]
    assert result["taskId"] == 2001
    envelope = next(
        frame
        for _, frame in gateway.frames
        if frame.get("msgType") == "agent_response"
    )
    assert json.loads(envelope["msgDetail"])["id"] == 1001
    assert envelope["taskId"] == 2001


async def test_denied_admission_retry_retains_first_payload_native_route(
    native_driver,
):
    driver, peer, _, gateway = native_driver
    peer.accept = False
    value = inbound(
        request="original-request", task="original-task", message="stable"
    )
    await gateway.push(value)
    await eventually(lambda: len(peer.batches) == 1)
    first = peer.batches[0]["events"][0]
    peer.accept = True
    retry = inbound(
        request="different-request",
        task="different-task",
        message="stable",
        text="mutated duplicate",
    )
    await gateway.push(retry, "backup")
    await eventually(lambda: len(peer.batches) == 2)
    second = peer.batches[1]["events"][0]
    assert second == first
    assert (
        driver._route_attrs(first["response_handle"])["server_name"]
        == "primary"
    )
    assert first["metadata"]["task_id"] == "original-task"
    await gateway.push(inbound(message="barrier"), "backup")
    await eventually(lambda: len(peer.batches) == 3)
    assert (
        len(
            [
                batch
                for batch in peer.batches
                if batch["events"][0]["event_id"] == first["event_id"]
            ]
        )
        == 2
    )


async def test_native_validation_text_join_empty_missing_session_and_control_order(  # noqa: E501
    native_driver,
):
    driver, peer, _, gateway = native_driver
    bad = inbound(message="bad-agent")
    bad["agentId"] = "foreign-agent"
    await gateway.push(bad)
    empty = inbound(message="empty", text="")
    await gateway.push(empty)
    missing = inbound(message="no-session")
    missing["params"].pop("sessionId")
    await gateway.push(missing)
    good = inbound(message="good")
    good["params"]["message"]["parts"] = [
        {"kind": "text", "text": "first"},
        {"kind": "text", "text": "second"},
    ]
    await gateway.connections["primary"].send_str("not json")
    await gateway.push(good)
    await eventually(lambda: len(peer.batches) == 1)
    assert peer.batches[0]["events"][0]["content_parts"] == [
        {"type": "text", "text": "first second"}
    ]
    assert driver._platform._session_task_map["session-A"] == "task-A"
    await gateway.push(
        {"method": "tasks/cancel", "id": "cancel-id", "sessionId": "session-A"}
    )
    await eventually(lambda: len(gateway.results()) == 1)
    assert driver._platform._session_task_map["session-A"] == "task-A"
    assert gateway.results()[0][1] == {
        "status": {"state": "canceled"},
        "id": "cancel-id",
    }
    await gateway.push(
        {"method": "clearContext", "id": "clear-id", "sessionId": "session-A"}
    )
    await eventually(lambda: len(gateway.results()) == 2)
    assert "session-A" not in driver._platform._session_task_map
    assert gateway.results()[1][1] == {"status": {"state": "cleared"}}
    assert len(peer.batches) == 1


async def test_native_http_download_sanitizes_file_and_preserves_failed_placeholder(  # noqa: E501
    native_driver, tmp_path
):
    driver, peer, _, gateway = native_driver
    value = inbound(message="media")
    value["params"]["message"]["parts"] = [
        {
            "kind": "file",
            "file": {
                "uri": gateway.base + "/asset/image",
                "name": "../../unsafe image",
                "mimeType": "image/png",
            },
        },
        {
            "kind": "file",
            "file": {
                "uri": gateway.base + "/asset/missing",
                "name": "missing.pdf",
                "mimeType": "application/pdf",
            },
        },
    ]
    await gateway.push(value)
    await eventually(lambda: len(peer.batches) == 1)
    parts = peer.batches[0]["events"][0]["content_parts"]
    assert parts[0] == {
        "type": "text",
        "text": "[missing.pdf: download failed]",
    }
    assert parts[1]["type"] == "image"
    from pathlib import Path

    path = Path(parts[1]["image_url"])
    assert path.resolve().is_relative_to(tmp_path.resolve())
    assert "/../" not in str(path) and " " not in path.name
    assert path.read_bytes() == gateway.asset
    assert driver._platform._media_session is not None


async def test_send_chunk4000_and_two_finish_frames_are_ordered_and_independent(  # noqa: E501
    native_driver,
):
    driver, peer, identity, gateway = native_driver
    handle = await open_route(
        peer,
        identity,
        task_id="task",
        message_id="request",
        server_name="backup",
    )
    result = await send(peer, identity, handle, text="A" * 8001)
    assert result["state"] == "acknowledged"
    from qwenpaw.channel_protocol.models import ResponseFinishParams

    finish = ResponseFinishParams.from_mapping(
        {**identity, "response_handle": handle, "outcome": "completed"}
    )
    await peer.methods["channel.response.finish"](finish, None)
    await eventually(lambda: len(gateway.results()) == 5)
    results = [result for _, result in gateway.results()]
    assert [
        len(result["artifact"]["parts"][0]["text"]) for result in results[:3]
    ] == [4000, 4000, 1]
    assert [result["kind"] for result in results] == [
        "artifact-update"
    ] * 3 + ["status-update", "artifact-update"]
    assert (
        results[3]["status"]["state"] == "completed"
        and results[3]["final"] is False
    )
    assert results[4]["final"] is True and results[4]["artifact"]["parts"] == [
        {"kind": "text", "text": ""}
    ]
    assert all(server == "backup" for server, _ in gateway.results())
    await peer.methods["channel.response.finish"](finish, None)
    assert len(gateway.results()) == 5
    snapshot = driver._routes.snapshot(handle)
    assert snapshot.cleanup_state.value == "complete"
    assert {
        ref.resource_id: dict(ref.attributes)["state"]
        for ref in snapshot.resource_refs
        if ref.kind == "xiaoyi.finish"
    } == {"completed": "acknowledged", "final": "acknowledged"}


async def test_unknown_native_write_has_truthful_receipt_and_no_shared_replay(
    native_driver, modules, monkeypatch
):
    driver, peer, identity, gateway = native_driver
    handle = await open_route(peer, identity, task_id="task")
    conn = driver._platform._conn_primary
    original = conn.send_json
    attempts = []

    async def write_then_lose_receipt(value):
        attempts.append(value)
        await original(value)
        raise modules["errors"].XiaoYiDeliveryError(
            "PLATFORM_RESULT_UNKNOWN", side_effect_possible=True
        )

    monkeypatch.setattr(conn, "send_json", write_then_lose_receipt)
    result = await send(peer, identity, handle)
    assert (
        result["state"] == "unknown"
        and result["reason_code"] == "PLATFORM_RESULT_UNKNOWN"
    )
    assert await send(peer, identity, handle) == result
    assert len(attempts) == 1
    await eventually(lambda: len(gateway.results()) == 1)
    snapshot = driver._routes.snapshot(handle)
    attempts_saved = [
        ref
        for ref in snapshot.resource_refs
        if ref.kind == "xiaoyi.attempt" and ref.resource_id == "delivery-A"
    ]
    assert len(attempts_saved) == 1
    assert dict(attempts_saved[0].attributes)["state"] == "unknown"
    assert driver._delivery_resource(handle, "delivery-A") is None


async def test_partial_delivery_is_unknown_after_first_real_frame(
    native_driver, modules, monkeypatch
):
    driver, peer, identity, gateway = native_driver
    handle = await open_route(peer, identity, task_id="task")
    transport = driver._platform
    original = transport._send_to_route
    calls = []

    async def first_written_then_known_refusal(route, value):
        calls.append(value)
        if len(calls) == 2:
            raise modules["errors"].XiaoYiDeliveryError("NOT_CONNECTED")
        await original(route, value)

    monkeypatch.setattr(
        transport, "_send_to_route", first_written_then_known_refusal
    )
    result = await send(peer, identity, handle, text="B" * 4001)
    assert (
        result["state"] == "unknown"
        and result["reason_code"] == "PARTIAL_DELIVERY"
    )
    assert await send(peer, identity, handle, text="B" * 4001) == result
    assert len(calls) == 2
    await eventually(lambda: len(gateway.results()) == 1)


async def test_stop_waits_actual_ws_http_and_reader_tasks_and_retains_failed_owner(  # noqa: E501
    native_driver, monkeypatch
):
    driver, _, _, gateway = native_driver
    transport = driver._platform
    # Create the owned real HTTP session through an actual native file request.
    await gateway.push(
        {
            **inbound(message="download-before-stop"),
            "params": {
                "sessionId": "session-A",
                "id": "t",
                "message": {
                    "messageId": "download-before-stop",
                    "parts": [
                        {
                            "kind": "file",
                            "file": {
                                "uri": gateway.base + "/asset/image",
                                "name": "image.png",
                                "mimeType": "image/png",
                            },
                        }
                    ],
                },
            },
        }
    )
    await eventually(lambda: transport._media_session is not None)
    connections = [transport._conn_primary, transport._conn_backup]
    owned_tasks = [
        task
        for conn in connections
        for task in (conn._receive_task, conn._heartbeat_task)
    ]
    session = transport._media_session
    original = session.close
    entered, release = asyncio.Event(), asyncio.Event()

    async def blocked_actual_close():
        entered.set()
        await release.wait()
        await original()

    monkeypatch.setattr(session, "close", blocked_actual_close)
    stopping = asyncio.create_task(driver.stop())
    try:
        await entered.wait()
        assert not stopping.done()
        assert driver._platform is transport and transport._stopping
        assert all(task.done() for task in owned_tasks)
        assert all(
            conn._ws is None and conn._session is None for conn in connections
        )
        assert not session.closed
    finally:
        release.set()
        await stopping
    assert session.closed and driver._platform is None
    assert all(task.done() for task in owned_tasks)


@pytest.mark.parametrize("possible", [False, True])
async def test_finish_partial_failure_keeps_independent_receipts_without_replaying_completed(  # noqa: E501
    native_driver, modules, monkeypatch, possible
):
    from qwenpaw.channel_protocol.errors import RpcError
    from qwenpaw.channel_protocol.models import ResponseFinishParams

    driver, peer, identity, gateway = native_driver
    handle = await open_route(
        peer, identity, task_id="finish-task", message_id="finish-request"
    )
    platform = driver._platform
    actual = platform.send_finish_step
    attempts = []
    fail = True

    async def fail_final_only(route, step):
        nonlocal fail
        attempts.append(step)
        if step == "final" and fail:
            if possible:
                await actual(route, step)
            raise modules["errors"].XiaoYiDeliveryError(
                "PLATFORM_RESULT_UNKNOWN" if possible else "NOT_CONNECTED",
                side_effect_possible=possible,
            )
        await actual(route, step)

    monkeypatch.setattr(platform, "send_finish_step", fail_final_only)
    finish = ResponseFinishParams.from_mapping(
        {**identity, "response_handle": handle, "outcome": "completed"}
    )
    with pytest.raises(RpcError) as caught:
        await peer.methods["channel.response.finish"](finish, None)
    assert caught.value.data["reason_code"] == "RESPONSE_FINISH_FAILED"
    snapshot = driver._routes.snapshot(handle)
    assert snapshot.cleanup_state.value != "complete"
    receipts = {
        ref.resource_id: dict(ref.attributes)
        for ref in snapshot.resource_refs
        if ref.kind == "xiaoyi.finish"
    }
    assert receipts["completed"]["state"] == "acknowledged"
    assert receipts["final"]["state"] == ("unknown" if possible else "failed")
    fail = False
    if possible:
        with pytest.raises(RpcError):
            await peer.methods["channel.response.finish"](finish, None)
        assert attempts == ["completed", "final"]
    else:
        await peer.methods["channel.response.finish"](finish, None)
        assert attempts == ["completed", "final", "final"]
        assert (
            driver._routes.snapshot(handle).cleanup_state.value == "complete"
        )
    await eventually(lambda: len(gateway.results()) == 2)
    assert [row[1]["kind"] for row in gateway.results()] == [
        "status-update",
        "artifact-update",
    ]


async def test_actual_http_close_failure_retains_owner_and_retry_closes_it(
    native_driver, monkeypatch
):
    driver, _, _, gateway = native_driver
    platform = driver._platform
    await platform._process_file_part(
        {
            "file": {
                "uri": gateway.base + "/asset/image",
                "name": "image.png",
                "mimeType": "image/png",
            }
        },
        [],
        [],
    )
    session = platform._media_session
    actual = session.close

    async def close_refused():
        raise RuntimeError("controlled HTTP close refusal")

    monkeypatch.setattr(session, "close", close_refused)
    with pytest.raises(RuntimeError, match="XIAOYI_STOP_INCOMPLETE"):
        await driver.stop()
    assert driver._platform is platform and platform._media_session is session
    assert not session.closed and platform._stopping
    monkeypatch.setattr(session, "close", actual)
    await driver.stop()
    assert session.closed and driver._platform is None
