# -*- coding: utf-8 -*-
"""Independent G3 actual Service/Loader/owner lifecycle and OS-boundary proof."""

import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import psutil
import pytest

from management_process_suite import (
    KEY,
    ROOT,
    active_management,
    assert_exact_use,
    assert_released,
    eventually,
    inspection_spec,
    local_management_http,
    management_runtime,
    management_sample_source,
    parameters,
    parent_import_boundary,
)


@pytest.mark.asyncio
async def test_service_owns_actual_child_until_operation_and_cleanup_complete(
    management_runtime, local_management_http
):
    from qwenpaw.plugins.ownership import RuntimeKey, RuntimeSourceBusyError

    rt = await management_runtime()
    local_management_http.reply_gate.clear()
    operation = asyncio.create_task(
        rt.service.execute(
            "workspace-A",
            KEY,
            "qrcode.poll",
            parameters(local_management_http, "qrcode.poll"),
            timeout=3,
        )
    )
    await eventually(lambda: len(local_management_http.requests) == 1)
    (lease,) = active_management(rt)
    process = rt.owners.resource(lease)
    pid = process.health_snapshot()["pid"]
    assert lease.key == RuntimeKey("management", KEY, "workspace-A")
    assert local_management_http.requests[0]["pid"] == pid != os.getpid()
    assert process.dependency_snapshot is not None
    assert process.health_snapshot()["platform_state"] != "connected"
    assert_exact_use(rt, lease)
    with pytest.raises(RuntimeSourceBusyError):
        with rt.owners.mutation(rt.record.source_path):
            raise AssertionError("management source mutation admitted")
    local_management_http.reply_gate.set()
    result = await operation
    assert result.to_mapping()["result"]["credentials"] == {
        "api_token": "fixture-result-secret"
    }
    assert_released(rt, lease, process, pid)


@pytest.mark.asyncio
async def test_service_unknown_fetch_is_not_reissued(
    management_runtime, local_management_http
):
    from qwenpaw.app.channels.management import ManagementError

    rt = await management_runtime()
    local_management_http.response = {"__exit_worker": True}
    with pytest.raises(ManagementError) as unknown:
        await rt.service.execute(
            "workspace-A",
            KEY,
            "qrcode.fetch",
            parameters(local_management_http),
            timeout=3,
        )
    assert unknown.value.reason_code == "PLATFORM_RESULT_UNKNOWN"
    assert unknown.value.side_effect_possible is True
    assert len(local_management_http.requests) == 1
    assert not active_management(rt)


@pytest.mark.asyncio
async def test_service_timeout_does_not_return_secret_and_next_poll_reuses_continuation(
    management_runtime, local_management_http
):
    from qwenpaw.app.channels.management import ManagementError

    rt = await management_runtime()
    local_management_http.reply_gate.clear()
    with pytest.raises(ManagementError) as timeout:
        await rt.service.execute(
            "workspace-A",
            KEY,
            "qrcode.poll",
            parameters(local_management_http, "qrcode.poll"),
            timeout=0.25,
        )
    assert timeout.value.reason_code == "MANAGEMENT_TIMEOUT"
    assert timeout.value.side_effect_possible is True
    assert str(timeout.value) == "MANAGEMENT_TIMEOUT"
    assert len(local_management_http.requests) == 1
    assert not active_management(rt)
    first = local_management_http.requests[0]
    local_management_http.reply_gate.set()
    result = await rt.service.execute(
        "workspace-A",
        KEY,
        "qrcode.poll",
        parameters(local_management_http, "qrcode.poll"),
        timeout=3,
    )
    second = local_management_http.requests[1]
    assert second["request_id"] != first["request_id"]
    assert second["continuation"] == first["continuation"]
    assert result.to_mapping()["result"]["status"] == "confirmed"


@pytest.mark.asyncio
async def test_service_capability_rejected_before_new_child(
    management_runtime, local_management_http
):
    from qwenpaw.app.channels.management import ManagementError

    rt = await management_runtime(
        capabilities=["channel.generic.v1", "channel.management.verify.v1"]
    )
    import_pid = rt.sample.marker.read_text()
    with pytest.raises(ManagementError) as denied:
        await rt.service.execute(
            "workspace-A",
            KEY,
            "qrcode.fetch",
            parameters(local_management_http),
            timeout=3,
        )
    assert denied.value.reason_code == "MANAGEMENT_UNSUPPORTED"
    assert denied.value.side_effect_possible is False
    assert rt.sample.marker.read_text() == import_pid
    assert not local_management_http.requests
    assert not active_management(rt)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_config",
    [
        {"workspace_dir": "/fixture/private"},
        {"token_file": "/fixture/private"},
        {"python_executable": sys.executable},
        {"entrypoint": "os:system"},
        {"credential_keys": ["untrusted_credential"]},
        {"api_token": object()},
    ],
)
async def test_service_projection_cannot_inject_paths_execution_or_credential_authority(
    management_runtime, local_management_http, bad_config
):
    from qwenpaw.app.channels.management import ManagementError

    rt = await management_runtime()
    import_pid = rt.sample.marker.read_text()
    with pytest.raises(ManagementError) as denied:
        await rt.service.execute(
            "workspace-A",
            KEY,
            "qrcode.fetch",
            parameters(local_management_http, **bad_config),
            timeout=3,
        )
    assert denied.value.reason_code == "MANAGEMENT_INVALID_REQUEST"
    assert denied.value.side_effect_possible is False
    assert not active_management(rt)
    assert not local_management_http.requests
    assert rt.sample.marker.read_text() == import_pid


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {
            "status": "confirmed",
            "credentials": {"untrusted_credential": "fixture-result-secret"},
        },
        {
            "status": "confirmed",
            "credentials": {"api_token": "fixture-result-secret"},
            "__identity_override": {"workspace_id": "workspace-B"},
        },
    ],
)
async def test_service_rejects_child_credentials_without_trusted_identity_and_keys(
    management_runtime, local_management_http, payload
):
    from qwenpaw.app.channels.management import ManagementError

    rt = await management_runtime()
    local_management_http.response = payload
    with pytest.raises(ManagementError) as denied:
        await rt.service.execute(
            "workspace-A",
            KEY,
            "qrcode.poll",
            parameters(local_management_http, "qrcode.poll"),
            timeout=3,
        )
    assert denied.value.reason_code == "MANAGEMENT_INVALID_RESULT"
    assert str(denied.value) == "MANAGEMENT_INVALID_RESULT"
    assert "fixture-result-secret" not in str(denied.value)
    assert len(local_management_http.requests) == 1
    assert not active_management(rt)
    assert not psutil.pid_exists(local_management_http.requests[0]["pid"])


@pytest.mark.asyncio
async def test_management_capacity_is_four_across_service_instances(
    management_runtime, local_management_http
):
    from qwenpaw.app.channels.management import (
        ChannelManagementService,
        ManagementError,
        ManagementCancelled,
    )

    rt = await management_runtime()
    other = ChannelManagementService(rt.loader)
    local_management_http.reply_gate.clear()
    tasks = [
        asyncio.create_task(
            rt.service.execute(
                "workspace-" + str(index),
                KEY,
                "qrcode.fetch",
                parameters(local_management_http),
                timeout=3,
            )
        )
        for index in range(4)
    ]
    try:
        await eventually(lambda: len(local_management_http.requests) == 4)
        assert len(active_management(rt)) == 4
        with pytest.raises(ManagementError) as busy:
            await other.execute(
                "workspace-fifth",
                KEY,
                "qrcode.fetch",
                parameters(local_management_http),
                timeout=3,
            )
        assert busy.value.reason_code == "MANAGEMENT_BUSY"
        assert len(local_management_http.requests) == 4
        await other.aclose()
        assert all(not task.done() for task in tasks)
        assert len(active_management(rt)) == 4
        await rt.service.aclose()
        for task in tasks:
            with pytest.raises(ManagementCancelled) as cancelled:
                await task
            assert cancelled.value.reason_code == "MANAGEMENT_CANCELLED"
        assert not active_management(rt)
        assert all(
            not psutil.pid_exists(row["pid"])
            for row in local_management_http.requests
        )
        await rt.service.aclose()
        with pytest.raises(ManagementError) as closed:
            await rt.service.execute(
                "workspace-A",
                KEY,
                "qrcode.fetch",
                parameters(local_management_http),
                timeout=3,
            )
        assert closed.value.reason_code == "MANAGEMENT_CLOSED"
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await other.aclose()


@pytest.mark.asyncio
async def test_management_source_revision_change_cannot_execute_modified_driver(
    management_runtime, local_management_http
):
    from qwenpaw.app.channels.management import ManagementError

    rt = await management_runtime()
    path = rt.record.source_path / KEY / "driver.py"
    original = path.read_bytes()
    try:
        path.write_bytes(
            original
            + b"\nraise AssertionError('unapproved mutated source executed')\n"
        )
        with pytest.raises(ManagementError) as denied:
            await rt.service.execute(
                "workspace-A",
                KEY,
                "qrcode.fetch",
                parameters(local_management_http),
                timeout=3,
            )
        assert denied.value.reason_code == "SOURCE_REVISION_MISMATCH"
        assert not active_management(rt)
        assert not local_management_http.requests
    finally:
        path.write_bytes(original)


@pytest.mark.asyncio
async def test_actual_management_dependency_use_is_visible_to_shared_repair_gate(
    management_runtime, local_management_http, tmp_path
):
    from qwenpaw.plugins.dependency_gate import evaluate_shared_dependencies

    rt = await management_runtime()
    local_management_http.reply_gate.clear()
    operation = asyncio.create_task(
        rt.service.execute(
            "workspace-A",
            KEY,
            "qrcode.fetch",
            parameters(local_management_http),
            timeout=3,
        )
    )
    try:
        await eventually(lambda: len(local_management_http.requests) == 1)
        (lease,) = active_management(rt)
        process = rt.owners.resource(lease)
        requirements = tmp_path / "repair-requirements.txt"
        requirements.write_text("packaging>=999999\n", encoding="utf-8")
        decision = evaluate_shared_dependencies(
            requirements,
            process.dependency_snapshot,
            plugin_id="repair-candidate",
            uses=rt.usage.snapshot().uses,
        )
        assert not decision.allow_install
        assert decision.require_restart
        assert decision.reason_code == "DEPENDENCY_RESTART_REQUIRED"
        assert any(
            row["instance_id"] == lease.instance_id
            and row["generation"] == lease.generation
            and row["active"]
            for row in decision.affected_instances
        )
        assert lease in rt.owners.leases(KEY)
        assert (
            process.health_snapshot()["pid"]
            == local_management_http.requests[0]["pid"]
        )
    finally:
        operation.cancel()
        await asyncio.gather(operation, return_exceptions=True)


@pytest.mark.asyncio
async def test_service_invalid_operation_and_timeout_never_spawn(
    management_runtime, local_management_http
):
    from qwenpaw.app.channels.management import ManagementError

    rt = await management_runtime()
    import_pid = rt.sample.marker.read_text()
    for timeout in (True, False, 0, -1, 65.001, float("nan"), float("inf")):
        with pytest.raises(ManagementError) as invalid:
            await rt.service.execute(
                "workspace-A",
                KEY,
                "qrcode.fetch",
                parameters(local_management_http),
                timeout=timeout,
            )
        assert invalid.value.reason_code == "MANAGEMENT_INVALID_REQUEST"
        assert invalid.value.side_effect_possible is False
    with pytest.raises(ManagementError) as invalid:
        await rt.service.execute(
            "workspace-A",
            KEY,
            "state.get",
            parameters(local_management_http),
            timeout=3,
        )
    assert invalid.value.reason_code == "MANAGEMENT_INVALID_REQUEST"
    assert rt.sample.marker.read_text() == import_pid
    assert not active_management(rt)
    assert not local_management_http.requests


@pytest.mark.asyncio
async def test_service_sdk_exception_and_health_are_secret_free(
    management_runtime, local_management_http, caplog
):
    from qwenpaw.app.channels.management import ManagementError

    rt = await management_runtime()
    with pytest.raises(ManagementError) as failed:
        await rt.service.execute(
            "workspace-A",
            KEY,
            "qrcode.fetch",
            parameters(
                local_management_http,
                behavior="raise",
                api_token="request-api-token-secret",
            ),
            timeout=3,
        )
    assert failed.value.reason_code == "PLATFORM_REQUEST_FAILED"
    assert str(failed.value) == "PLATFORM_REQUEST_FAILED"
    for secret in (
        "request-api-token-secret",
        "SDK leaked fixture-secret-and-password",
    ):
        assert secret not in str(failed.value)
        assert secret not in caplog.text
    assert not active_management(rt)
    assert not local_management_http.requests
