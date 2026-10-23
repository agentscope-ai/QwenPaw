"""Host disk work must finish before a channel generation can hand off."""

import asyncio
import json
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import pytest

from process_supervisor_suite import digest, eventually
from qwenpaw.app.channels.isolated_proxy import IsolatedChannelProxy
from qwenpaw.app.channels.manager import ChannelManager
from qwenpaw.app.channels.process_supervisor import ChannelProcess, LaunchSpec
from qwenpaw.channel_protocol.models import HostStateParams
from qwenpaw.plugins.lifecycle import QuiescenceError
from qwenpaw.plugins.ownership import RuntimeKey, RuntimeOwners

ROOT = Path(__file__).resolve().parents[3]
DRIVER = """
import os

class Driver:
    def bind(self, context):
        self.context = context
        context.peer.register_method('fixture.probe', self.probe)
        context.peer.register_method('fixture.write', self.write)

    async def start(self, config):
        self.checkpoint = config.get('checkpoint', False)
        await self.context.set_platform_state('connected')

    async def stop(self):
        if self.checkpoint:
            await self.write({'key': 'checkpoint', 'value': 'stopped'}, None)

    async def probe(self, params, request):
        return {'pid': os.getpid(), 'identity': self.context.identity.to_mapping()}

    async def write(self, params, request):
        return await self.context.peer.call('host.state.put', {
            **self.context.identity.to_mapping(),
            'key': params.get('key', 'handoff'), 'schema_version': 1,
            'value': params['value'],
        }, timeout=15)
"""


async def no_agent(*_args, **_kwargs):
    raise AssertionError("State-only fixture must not invoke an Agent")


@pytest.fixture
def proxies(tmp_path):
    code = tmp_path / "driver"
    code.mkdir()
    private_env = {
        key: os.environ[key]
        for key in (
            "QWENPAW_WORKING_DIR",
            "QWENPAW_SECRET_DIR",
            "QWENPAW_BACKUP_DIR",
        )
    }
    (code / "driver.py").write_text(
        "import os\nos.environ.update(" + repr(private_env) + ")\n" + DRIVER
    )
    descriptor = json.loads(
        (ROOT / "plugins/channel/feishu/channel.json").read_text()
    )
    descriptor["entrypoint"].update(module="driver", qualname="Driver")
    (code / "channel.json").write_text(json.dumps(descriptor))
    (code / "requirements.txt").write_text("")

    def make(generation=1, *, checkpoint=False):
        return IsolatedChannelProxy(
            no_agent,
            launch_spec=LaunchSpec(
                python_executable=sys.executable,
                support_root=ROOT / "src",
                code_root=code,
                descriptor_path=code / "channel.json",
                source_revision=digest(code),
                channel_key="feishu",
                instance_id="state-handoff",
                generation=generation,
                qwenpaw_version="2.2.2b4",
                config={"enabled": True, "checkpoint": checkpoint},
                startup_timeout=3,
                shutdown_timeout=0.2,
            ),
            channel_process=ChannelProcess(),
            workspace_dir=tmp_path / "workspace",
        )

    return make


class DiskGate:
    """Pause one real disk operation without blocking the event loop."""

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()

    def run(self, operation, *args, **kwargs):
        self.entered.set()
        if not self.release.wait(15):
            raise TimeoutError("Test did not release the disk operation")
        try:
            return operation(*args, **kwargs)
        finally:
            self.finished.set()

    async def wait(self):
        assert await asyncio.to_thread(
            self.entered.wait, 5
        ), "Disk was not reached"


def gate_replace(monkeypatch, owner, key="handoff", value="old"):
    gate, replace = DiskGate(), os.replace

    def gated(source, destination, *args, **kwargs):
        if (
            Path(destination) == owner._state_path()
            and json.loads(Path(source).read_text()).get(key, {}).get("value")
            == value
            and not gate.entered.is_set()
        ):
            return gate.run(replace, source, destination, *args, **kwargs)
        return replace(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "replace", gated)
    return gate


def state_params(owner, key="handoff", value="old"):
    return HostStateParams(
        **owner._identity().to_mapping(),
        key=key,
        schema_version=1,
        value=value,
    )


async def assert_io_pending(owner):
    with pytest.raises(RuntimeError, match="^CHANNEL_STOP_INCOMPLETE$"):
        await asyncio.wait_for(owner.stop(), 3)
    assert owner.last_stop_result.exited
    assert owner.last_stop_result.residual == ("HOST_STATE_IO_PENDING",)


async def release_and_finish(gate, *tasks):
    gate.release.set()
    if gate.entered.is_set():
        assert await asyncio.to_thread(gate.finished.wait, 5)
    return await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_manager_replacement_waits_for_host_disk_commit(
    proxies, monkeypatch
):
    old, replacement = proxies(), proxies(2)
    manager = ChannelManager([old])
    gate = gate_replace(monkeypatch, old)
    writing = None
    try:
        await manager.start_all()
        await eventually(
            lambda: old._started and not manager._pending_channel_starts(old)
        )
        probe = await old.channel_process.call("fixture.probe")
        assert probe["pid"] != os.getpid()
        owners = RuntimeOwners()
        lease = owners.reserve(
            "feishu",
            RuntimeKey("channel", "feishu", "workspace"),
            old._launch_spec.code_root,
            instance_id="state-handoff",
        )
        old._owner_registry = SimpleNamespace(runtime_owners=owners)
        old._runtime_lease = lease
        manager._attach_runtime(old)
        writing = asyncio.create_task(
            old.channel_process.call(
                "fixture.write", {"value": "old"}, timeout=15
            )
        )
        await gate.wait()

        with pytest.raises(
            QuiescenceError, match="CHANNEL_STOP_INCOMPLETE"
        ) as caught:
            await asyncio.wait_for(manager.replace_channel(replacement), 5)

        receipt = caught.value.receipt
        assert receipt.exited and not receipt.stopped
        assert receipt.residual == ("HOST_STATE_IO_PENDING",)
        assert old.last_stop_result.residual == ("HOST_STATE_IO_PENDING",)
        assert await manager.get_channel("feishu") is old
        assert owners.leases() == (lease,)
        assert owners.resource(lease) is old
        assert replacement.channel_process.health_snapshot()["pid"] is None
        assert not gate.finished.is_set()

        gate.release.set()
        assert await asyncio.to_thread(gate.finished.wait, 5)
        await manager.replace_channel(replacement)
        assert owners.leases() == ()
        assert await manager.get_channel("feishu") is replacement
        next_probe = await replacement.channel_process.call("fixture.probe")
        assert next_probe["pid"] != probe["pid"]
        assert next_probe["identity"]["generation"] == 2
        assert await replacement.channel_process.call(
            "fixture.write", {"value": "new"}
        ) == {"stored": True}
        assert json.loads(old._state_path().read_text()) == {
            "handoff": {"schema_version": 1, "value": "new"}
        }
    finally:
        gate.release.set()
        if gate.entered.is_set():
            assert await asyncio.to_thread(gate.finished.wait, 5)
        if writing is not None:
            await asyncio.gather(writing, return_exceptions=True)
        await manager.stop_all()
        for owner in (old, replacement):
            await owner.channel_process.stop(timeout=1)


@pytest.mark.asyncio
async def test_repeated_cancellation_cannot_release_a_live_disk_write(
    proxies, monkeypatch
):
    owner = proxies()
    gate = gate_replace(monkeypatch, owner)
    writing = asyncio.create_task(
        owner._host_state("put", state_params(owner))
    )
    try:
        await gate.wait()
        for _ in range(3):
            writing.cancel()
            await asyncio.sleep(0)
        assert (
            not writing.done()
        ), "Cancellation abandoned an active disk operation"
        await assert_io_pending(owner)
        assert not gate.finished.is_set()
        outcomes = await release_and_finish(gate, writing)
        assert isinstance(outcomes[0], asyncio.CancelledError)
        assert json.loads(owner._state_path().read_text()) == {
            "handoff": {"schema_version": 1, "value": "old"}
        }
        result = await owner.stop()
        assert result.exited and not result.residual
    finally:
        await release_and_finish(gate, writing)
        await owner.stop()


@pytest.mark.asyncio
async def test_same_path_proxies_serialize_and_reload_before_mutating(
    proxies, monkeypatch
):
    first, second = proxies(), proxies(2)
    await first._host_state("put", state_params(first, "seed", "keep"))
    assert await second._host_state("get", state_params(second, "seed")) == {
        "value": "keep"
    }
    gate = gate_replace(monkeypatch, first, "first", "one")
    writing = asyncio.create_task(
        first._host_state("put", state_params(first, "first", "one"))
    )
    second_started = asyncio.Event()

    async def write_second():
        second_started.set()
        return await second._host_state(
            "put", state_params(second, "second", "two")
        )

    queued = None
    try:
        await gate.wait()
        queued = asyncio.create_task(write_second())
        await second_started.wait()
        await asyncio.sleep(0)
        assert not queued.done()
        assert json.loads(first._state_path().read_text()) == {
            "seed": {"schema_version": 1, "value": "keep"}
        }
        assert await release_and_finish(gate, writing, queued) == [
            {"stored": True},
            {"stored": True},
        ]
        expected = {
            "seed": {"schema_version": 1, "value": "keep"},
            "first": {"schema_version": 1, "value": "one"},
            "second": {"schema_version": 1, "value": "two"},
        }
        assert json.loads(first._state_path().read_text()) == expected
        assert await first._host_state(
            "get", state_params(first, "second")
        ) == {"value": "two"}
    finally:
        await release_and_finish(gate, writing, *([queued] if queued else []))
        await first.stop()
        await second.stop()


@pytest.mark.asyncio
async def test_waiting_old_request_is_rejected_after_stop_closes_state(
    proxies, monkeypatch
):
    holder, old = proxies(2), proxies()
    gate = gate_replace(monkeypatch, holder)
    writing = asyncio.create_task(
        holder._host_state("put", state_params(holder))
    )
    queued_started = asyncio.Event()

    async def old_write():
        queued_started.set()
        return await old._host_state(
            "put", state_params(old, "retired", "forbidden")
        )

    queued = None
    try:
        await gate.wait()
        queued = asyncio.create_task(old_write())
        await queued_started.wait()
        await assert_io_pending(old)
        assert not queued.done()
        outcomes = await release_and_finish(gate, writing, queued)
        assert outcomes[0] == {"stored": True}
        assert isinstance(outcomes[1], ValueError)
        assert str(outcomes[1]) == "CHANNEL_STOPPING"
        assert json.loads(old._state_path().read_text()) == {
            "handoff": {"schema_version": 1, "value": "old"}
        }
        assert not (await old.stop()).residual
    finally:
        await release_and_finish(gate, writing, *([queued] if queued else []))
        await holder.stop()
        await old.stop()


@pytest.mark.asyncio
async def test_driver_stop_can_persist_its_final_checkpoint(proxies):
    owner = proxies(checkpoint=True)
    try:
        await owner.start()
        result = await owner.stop()
        assert result.exited and not result.forced and not result.residual
        assert json.loads(owner._state_path().read_text()) == {
            "checkpoint": {"schema_version": 1, "value": "stopped"}
        }
        with pytest.raises(ValueError, match="^CHANNEL_STOPPING$"):
            await owner._host_state("put", state_params(owner))
    finally:
        await owner.channel_process.stop(timeout=1)


@pytest.mark.asyncio
async def test_restart_keeps_state_closed_until_previous_io_finishes(
    proxies, monkeypatch
):
    owner = proxies()
    gate = gate_replace(monkeypatch, owner)
    writing = None
    try:
        await owner.start()
        old_probe = await owner.channel_process.call("fixture.probe")
        writing = asyncio.create_task(
            owner._host_state("put", state_params(owner))
        )
        await gate.wait()
        await assert_io_pending(owner)
        with pytest.raises(RuntimeError, match="^HOST_STATE_IO_PENDING$"):
            await asyncio.wait_for(owner.start(), 3)
        assert owner.channel_process.health_snapshot()["pid"] is None
        with pytest.raises(ValueError, match="^CHANNEL_STOPPING$"):
            await owner._host_state(
                "put", state_params(owner, "reopened", "forbidden")
            )

        assert await release_and_finish(gate, writing) == [{"stored": True}]
        await owner.stop()
        await owner.start()
        new_probe = await owner.channel_process.call("fixture.probe")
        assert new_probe["pid"] != old_probe["pid"]
        assert new_probe["identity"]["generation"] == 2
        assert await owner.channel_process.call(
            "fixture.write", {"value": "new"}
        ) == {"stored": True}
        assert json.loads(owner._state_path().read_text()) == {
            "handoff": {"schema_version": 1, "value": "new"}
        }
    finally:
        await release_and_finish(gate, *([writing] if writing else []))
        await owner.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["get", "put"])
async def test_receipt_sqlite_io_is_part_of_stop(
    proxies, monkeypatch, operation
):
    import sqlite3

    from response_receipt_archive_suite import legacy_receipt
    from qwenpaw.channel_protocol.response_receipts import (
        ResponseReceiptStore,
        receipt_key,
    )

    owner = proxies()
    store = ResponseReceiptStore(
        owner._state_path().with_suffix(".receipts.sqlite3")
    )
    receipt = legacy_receipt()
    key = receipt_key("responses", receipt["response_handle"])
    if operation == "get":
        store.put(key, receipt)
    gate = DiskGate()
    real_connect = sqlite3.connect

    class GatedConnection(sqlite3.Connection):
        def execute(self, statement, *args, **kwargs):
            boundary = (
                "SELECT value" if operation == "get" else "INSERT OR IGNORE"
            )
            if statement.startswith(boundary) and not gate.entered.is_set():
                return gate.run(super().execute, statement, *args, **kwargs)
            return super().execute(statement, *args, **kwargs)

    def connect(database, *args, **kwargs):
        if Path(database) == store.path:
            kwargs["factory"] = GatedConnection
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    io = asyncio.create_task(
        owner._host_receipt(operation, state_params(owner, key, receipt))
    )
    try:
        await gate.wait()
        await assert_io_pending(owner)
        assert not io.done()
        expected = (
            {"value": receipt} if operation == "get" else {"stored": True}
        )
        assert await release_and_finish(gate, io) == [expected]
        assert store.get(key) == receipt
        assert not (await owner.stop()).residual
        with pytest.raises(ValueError, match="^CHANNEL_STOPPING$"):
            await owner._host_receipt("get", state_params(owner, key))
    finally:
        await release_and_finish(gate, io)
        await owner.stop()
