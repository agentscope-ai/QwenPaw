"""W2 exact retained management lease with concurrent actual workers.

Reuses G3's actual Loader, Service, IPC and HTTP platform boundary. Only OS
signal permission for one exact live PID is refused to make cleanup fail.
"""

import asyncio

import psutil
import pytest

from qwenpaw.app.channels.management import ManagementError
from qwenpaw.plugins.execution.process_tree import ProcessTree

from management_process_suite import (
    KEY,
    active_management,
    assert_released,
    eventually,
    local_management_http,
    management_runtime,
    parameters,
    parent_import_boundary,
)


@pytest.mark.asyncio
async def test_cleanup_error_identifies_exact_qr_lease_and_never_stops_other_verify(
    management_runtime,
    local_management_http,
    monkeypatch,
):
    rt = await management_runtime()
    local_management_http.reply_gate.clear()
    verify = asyncio.create_task(
        rt.service.execute(
            "B",
            KEY,
            "connection.verify",
            parameters(local_management_http, "connection.verify"),
            timeout=8,
        )
    )
    fetch = None
    retained = None
    try:
        await eventually(lambda: len(local_management_http.requests) == 1)
        (other,) = active_management(rt)
        other_process = rt.owners.resource(other)
        other_pid = other_process.health_snapshot()["pid"]
        fetch = asyncio.create_task(
            rt.service.execute(
                "A",
                KEY,
                "qrcode.fetch",
                parameters(local_management_http, behavior="swallow"),
                timeout=5,
            )
        )
        await eventually(lambda: len(local_management_http.requests) == 2)
        retained = next(
            l for l in active_management(rt) if l.key.scope_id == "A"
        )
        process = rt.owners.resource(retained)
        pid = process.health_snapshot()["pid"]
        signal = ProcessTree.signal

        def refuse_exact_pid(tree, *, force):
            if tree.pid != pid:
                signal(tree, force=force)

        with monkeypatch.context() as os_boundary:
            os_boundary.setattr(ProcessTree, "signal", refuse_exact_pid)
            fetch.cancel()
            with pytest.raises(ManagementError) as failed:
                await fetch
            assert failed.value.reason_code == "MANAGEMENT_CLEANUP_FAILED"
            assert failed.value.lease is retained
            assert (
                failed.value.needs_restart and not failed.value.receipt.stopped
            )
            assert rt.owners.resource(retained) is process
            assert psutil.pid_exists(pid) and psutil.pid_exists(other_pid)
            assert other in rt.owners.leases(KEY) and not verify.done()
            # The bounded stop receipt can precede completion of that exact
            # cleanup task. Finish the refused attempt before asking for a
            # new OS-permitted attempt; do not mistake coalescing for retry.
            async with asyncio.timeout(1):
                await asyncio.shield(process._stop_task)
        receipt = await rt.owners.stop(failed.value.lease)
        assert receipt.stopped
        assert_released(rt, retained, process, pid)
        assert other in rt.owners.leases(KEY) and psutil.pid_exists(other_pid)
        assert not verify.done()
        local_management_http.reply_gate.set()
        result = await verify
        assert result.to_mapping()["result"]["verdict"] == "passed"
        assert_released(rt, other, other_process, other_pid)
        assert len(local_management_http.requests) == 2
    finally:
        local_management_http.reply_gate.set()
        for task in (fetch, verify):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(
            *(t for t in (fetch, verify) if t is not None),
            return_exceptions=True,
        )
        if retained is not None:
            await rt.owners.stop(retained)
