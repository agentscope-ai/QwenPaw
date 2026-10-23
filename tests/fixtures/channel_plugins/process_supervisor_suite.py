# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
"""Independent B2 evidence using the real worker and supervisor."""

import asyncio
from dataclasses import asdict, replace
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import socket

import psutil
import pytest
import pytest_asyncio

ROOT = Path(__file__).resolve().parents[3]
DRIVER = Path(__file__).with_name("shared_process_driver.py")


async def eventually(predicate, timeout=5):
    """Bound real process/state observation without fixed long sleeps."""
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


def alive(pid):
    """An unreaped zombie has exited and no longer owns connections."""
    if not pid:
        return False
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def digest(root):
    """Independently reproduce the declared source artifact digest."""
    result = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            name = path.relative_to(root).as_posix().encode()
            data = path.read_bytes()
            result.update(len(name).to_bytes(8, "big"))
            result.update(name)
            result.update(len(data).to_bytes(8, "big"))
            result.update(data)
    return result.hexdigest()


@pytest.fixture
def launch(api, tmp_path):
    """Create only channel code/metadata; never persist launch credentials."""
    count = 0

    def make(mode="normal", requirements="", **overrides):
        nonlocal count
        count += 1
        code = tmp_path / f"code-{count}"
        code.mkdir()
        marker = tmp_path / f"marker-{count}"
        prefix = f"MODE = {mode!r}\nMARKER = {str(marker)!r}\n"
        (code / "driver.py").write_text(prefix + DRIVER.read_text())
        descriptor = json.loads(
            (ROOT / "plugins/channel/feishu/channel.json").read_text(),
        )
        descriptor["entrypoint"].update(module="driver", qualname="Driver")
        (code / "channel.json").write_text(json.dumps(descriptor))
        (code / "requirements.txt").write_text(requirements)
        spec = api.LaunchSpec(
            **{
                "python_executable": sys.executable,
                "support_root": ROOT / "src",
                "code_root": code,
                "descriptor_path": code / "channel.json",
                "source_revision": digest(code),
                "channel_key": "feishu",
                "instance_id": f"workspace-{count}",
                "generation": 1,
                "qwenpaw_version": "2.2.2b4",
                "config": {},
                "startup_timeout": 2,
                "shutdown_timeout": 0.5,
                **overrides,
            },
        )
        return spec, marker

    return make


@pytest_asyncio.fixture
async def processes(api):
    """Failed assertions still clean up every supervisor-owned worker."""
    owned = []

    def make():
        process = api.ChannelProcess()
        owned.append(process)
        return process

    yield make
    for process in owned:
        await asyncio.wait_for(process.stop(timeout=2), 5)


async def ticker_until(task):
    """Count parent scheduling while real child work stalls or floods."""
    ticks = 0
    while not task.done():
        ticks += 1
        await asyncio.sleep(0.01)
    return ticks


@pytest.fixture
def api():
    """Missing production API is an assertion rather than collection error."""
    name = "qwenpaw.app.channels.process_supervisor"
    assert importlib.util.find_spec(name), "B2 ChannelProcess API is missing"
    return importlib.import_module(name)


@pytest.mark.asyncio
async def test_readonly_and_disabled_never_spawn(api, launch, monkeypatch):
    """Health, construction and disabled launch do no external work."""

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Readonly path spawned a process")

    spec, _ = launch(enabled=False)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    monkeypatch.setattr(subprocess.Popen, "__init__", forbidden)
    process = api.ChannelProcess()
    process.register_method("fixture.inbound", lambda _p, _r: {})
    assert process.health_snapshot()["state"] == "idle"
    health = await process.start(spec)
    assert health["state"] == "disabled" and health["pid"] is None
    with pytest.raises(api.ChannelProcessError) as caught:
        await process.call("fixture.probe")
    assert caught.value.reason_code == "NOT_READY"
    assert (await process.stop()).exited


@pytest.mark.asyncio
async def test_ready_connecting_then_connected_and_two_instances(
    launch,
    processes,
):
    """Readiness and identity belong to each independently owned process."""
    first, second = processes(), processes()
    one, _ = launch()
    two, _ = launch()
    health_one, health_two = await asyncio.gather(
        first.start(one),
        second.start(two),
    )
    assert health_one["platform_state"] in {"connecting", "connected"}
    assert health_two["platform_state"] in {"connecting", "connected"}
    probes = await asyncio.gather(
        first.call("fixture.probe"),
        second.call("fixture.probe"),
    )
    assert probes[0]["pid"] != probes[1]["pid"]
    assert probes[0]["identity"]["instance_id"] == one.instance_id
    assert probes[1]["identity"]["instance_id"] == two.instance_id
    assert probes[0]["isolated"] == probes[1]["isolated"] == 1
    stopped = await first.stop()
    assert stopped.exited and not stopped.forced and stopped.returncode == 0
    assert not alive(probes[0]["pid"])
    assert (await second.call("fixture.probe"))["pid"] == probes[1]["pid"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["import_hang", "connect_hang"])
async def test_blocked_sdk_keeps_parent_loop_responsive(
    api,
    launch,
    processes,
    mode,
):
    """A stdlib blocking import/connection runs only in a real worker."""
    spec, marker = launch(mode, startup_timeout=0.4)
    process = processes()
    starting = asyncio.create_task(process.start(spec))
    ticker = asyncio.create_task(ticker_until(starting))
    if mode == "import_hang":
        with pytest.raises(api.ChannelProcessError):
            await starting
        assert await ticker >= 5
        assert marker.exists()
        assert not alive(int(marker.read_text()))
    else:
        health = await starting
        await ticker
        await eventually(marker.exists)
        child_marker = Path(str(marker) + ".child")
        assert child_marker.is_file()
        child_pid = int(child_marker.read_text())
        assert child_pid != health["pid"] and alive(child_pid)
        assert health["state"] == "ready"
        assert health["platform_state"] == "connecting"
        stopping = asyncio.create_task(process.stop(timeout=0.5))
        ticks = await ticker_until(stopping)
        result = await stopping
        assert ticks >= 1 and result.exited and result.forced
        assert not alive(int(marker.read_text()))
        assert not alive(child_pid)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    ["missing_sdk", "missing_entry", "source", "identity"],
)
async def test_child_rejects_invalid_launch_before_readiness(
    api,
    launch,
    processes,
    change,
):
    """Audit and trusted source/identity validation occur in the real child."""
    spec, _ = launch(
        requirements=(
            "b2-uninstalled-sdk-314159>=1\n" if change == "missing_sdk" else ""
        ),
    )
    if change == "source":
        spec = replace(spec, source_revision="0" * 64)
    if change == "identity":
        spec = replace(spec, channel_key="dingtalk")
    if change == "missing_entry":
        descriptor = json.loads(spec.descriptor_path.read_text())
        descriptor["entrypoint"]["qualname"] = "MissingDriver"
        spec.descriptor_path.write_text(json.dumps(descriptor))
        spec = replace(spec, source_revision=digest(spec.code_root))
    process = processes()
    with pytest.raises(api.ChannelProcessError):
        await process.start(spec)
    assert process.health_snapshot()["state"] == "failed"
    assert not alive(process.health_snapshot()["pid"])


@pytest.mark.asyncio
async def test_flood_is_drained_discarded_and_cannot_corrupt_rpc(
    launch,
    processes,
):
    """Multi-megabyte stdout/stderr logs preserve framed protocol traffic."""
    spec, _ = launch("flood", startup_timeout=5)
    process = processes()
    starting = asyncio.create_task(process.start(spec))
    ticker = asyncio.create_task(ticker_until(starting))
    await starting
    await ticker
    assert (await process.call("fixture.probe"))["pid"]
    health = process.health_snapshot()
    assert health["log_bytes"] >= 6 * 1024 * 1024
    assert len(json.dumps(health)) < 4096
    assert "external-platform-log" not in repr(health)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["descendant", "stop_hang"])
async def test_stop_reaps_real_descendant_and_escalates(
    launch,
    processes,
    mode,
):
    """Ownership includes children even when TERM is ignored."""
    spec, marker = launch(mode)
    process = processes()
    health = await process.start(spec)
    await eventually(marker.exists)
    child = int(marker.read_text())
    assert alive(child)
    result = await process.stop(timeout=0.6)
    assert result.exited and result.returncode is not None
    assert result.residual == ()
    if mode == "stop_hang":
        assert result.forced
    await eventually(lambda: not alive(child))
    assert not alive(health["pid"])


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["start", "stop"])
async def test_cancelled_lifecycle_finishes_owned_cleanup(
    api,
    launch,
    processes,
    phase,
):
    """Cancellation cannot lose a PID or permit overlapping workers."""
    spec, marker = launch("import_hang" if phase == "start" else "stop_hang")
    process = processes()
    if phase == "stop":
        await process.start(spec)
        operation = asyncio.create_task(process.stop(timeout=0.6))
        await eventually(
            lambda: process.health_snapshot()["state"] == "stopping",
        )
    else:
        operation = asyncio.create_task(process.start(spec))
    await eventually(marker.exists)
    pid = process.health_snapshot()["pid"]
    with pytest.raises(api.ChannelProcessError) as caught:
        await process.start(spec)
    assert caught.value.reason_code == "PROCESS_OWNED"
    operation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(operation, 5)
    assert not alive(pid) and not alive(int(marker.read_text()))
    replacement, _ = launch()
    await process.start(replacement)
    assert (await process.call("fixture.probe"))["pid"] != pid


@pytest.mark.asyncio
async def test_timeout_and_cancel_record_exact_ids_without_replay(
    api,
    launch,
    processes,
):
    """A committed request with no receipt remains unknown across restart."""
    spec, ledger = launch(restart_limit=1, restart_backoff=0.05)
    process = processes()
    await process.start(spec)
    with pytest.raises(api.ChannelCallUnknown) as caught:
        await process.call("fixture.commit", timeout=0.1)
    error = caught.value
    committed = json.loads(ledger.read_text())
    assert error.reason_code == "PLATFORM_RESULT_UNKNOWN"
    assert error.method == "fixture.commit" and error.generation == 1
    assert error.request_id == committed["request_id"]
    calling = asyncio.create_task(process.call("fixture.slow"))
    await asyncio.sleep(0.05)
    calling.cancel()
    with pytest.raises(asyncio.CancelledError):
        await calling
    records = process.health_snapshot()["unknown_outcomes"]
    assert {row["method"] for row in records} == {
        "fixture.commit",
        "fixture.slow",
    }
    assert all(row["generation"] == 1 for row in records)
    assert all(
        set(row)
        == {
            "request_id",
            "method",
            "generation",
            "reason_code",
        }
        for row in records
    )
    with pytest.raises(api.ChannelCallUnknown):
        await process.call("fixture.crash")
    await eventually(
        lambda: process.health_snapshot()["generation"] == 2
        and process.health_snapshot()["state"] == "ready",
    )
    assert ledger.read_text().count("\n") == 1
    assert (await process.call("fixture.probe"))["identity"]["generation"] == 2
    assert records[0] in process.health_snapshot()["unknown_outcomes"]
    await process.call("fixture.stale")
    await asyncio.sleep(0.05)
    assert process.health_snapshot()["platform_state"] == "connected"


@pytest.mark.asyncio
async def test_known_unsent_schema_rejection_is_not_unknown(
    launch,
    processes,
):
    """Local non-JSON input was never an uncertain platform action."""
    from qwenpaw.channel_protocol.errors import ProtocolValidationError

    spec, _ = launch()
    process = processes()
    await process.start(spec)
    with pytest.raises(ProtocolValidationError):
        await process.call("fixture.probe", {"bad": object()})
    assert process.health_snapshot()["unknown_outcomes"] == []
    assert (await process.call("fixture.probe"))["pid"]


@pytest.mark.asyncio
async def test_restart_is_capped_and_previous_tree_is_gone(
    api,
    launch,
    processes,
):
    """Crash restart cannot overlap a retained descendant or loop forever."""
    spec, marker = launch("descendant", restart_limit=1)
    process = processes()
    first = await process.start(spec)
    child = int(marker.read_text())
    with pytest.raises(api.ChannelCallUnknown):
        await process.call("fixture.crash")
    await eventually(
        lambda: process.health_snapshot()["generation"] == 2
        and process.health_snapshot()["state"] == "ready",
    )
    assert not alive(first["pid"]) and not alive(child)
    assert process.health_snapshot()["restart_count"] == 1
    with pytest.raises(api.ChannelCallUnknown):
        await process.call("fixture.crash")
    await eventually(lambda: process.health_snapshot()["state"] == "failed")
    await asyncio.sleep(0.25)
    assert process.health_snapshot()["generation"] == 2
    assert not alive(int(marker.read_text()))


@pytest.mark.asyncio
async def test_stop_disables_backoff_restart(api, launch, processes):
    """Explicit stop must revoke pending restart before its first await."""
    spec, _ = launch(restart_limit=3, restart_backoff=0.5)
    process = processes()
    await process.start(spec)
    with pytest.raises(api.ChannelCallUnknown):
        await process.call("fixture.crash")
    await eventually(lambda: process.health_snapshot()["state"] == "backoff")
    assert (await process.stop()).exited
    await asyncio.sleep(0.65)
    health = process.health_snapshot()
    assert health["state"] == "stopped" and health["generation"] == 1
    assert not alive(health["pid"])


@pytest.mark.asyncio
async def test_host_registration_survives_fresh_generation(
    api,
    launch,
    processes,
):
    """Each fresh peer binds public handlers and rejects reserved names."""
    spec, _ = launch(restart_limit=1)
    process = processes()
    seen = []

    def host(params, _request):
        seen.append(params)
        return {"generation": params["generation"]}

    process.register_method("fixture.host", host)
    for reserved in ("shared.state", "shared.stop", "runner.hello"):
        with pytest.raises(ValueError):
            process.register_method(reserved, host)
    await process.start(spec)
    assert await process.call("fixture.reverse") == {"generation": 1}
    with pytest.raises(api.ChannelCallUnknown):
        await process.call("fixture.crash")
    await eventually(
        lambda: process.health_snapshot()["generation"] == 2
        and process.health_snapshot()["state"] == "ready",
    )
    assert await process.call("fixture.reverse") == {"generation": 2}
    assert [params["instance_id"] for params in seen] == [spec.instance_id] * 2


@pytest.mark.asyncio
async def test_explicit_shared_site_under_isolation_and_no_pth_execution(
    launch,
    processes,
    tmp_path,
):
    """Only the actual child's explicit site supplies required SDK metadata."""
    site = tmp_path / "shared-site"
    site.mkdir()
    (site / "b2_shared_sdk.py").write_text("VALUE = 'child-only-sdk'\n")
    metadata = site / "b2_shared_sdk-2.5.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: b2-shared-sdk\nVersion: 2.5\n",
    )
    executed = tmp_path / "pth-executed"
    (site / "arbitrary.pth").write_text(
        f"import pathlib; pathlib.Path({str(executed)!r}).touch()\n",
    )
    assert importlib.util.find_spec("b2_shared_sdk") is None
    spec, _ = launch(
        "shared_site",
        requirements="b2-shared-sdk>=2,<3\n",
        dependency_paths=(site,),
    )
    process = processes()
    await process.start(spec)
    probe = await process.call("fixture.probe")
    assert probe["site"] == "child-only-sdk" and probe["isolated"] == 1
    assert not executed.exists()
    assert "b2_shared_sdk" not in sys.modules


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["normal", "secret_failure"])
async def test_credentials_are_private_even_in_sdk_exception_and_logs(
    launch,
    processes,
    tmp_path,
    caplog,
    mode,
):
    """Private config and raw failures never become public diagnostics."""
    secret = "B2-private-credential-8675309"
    spec, _ = launch(mode, config={"credential": secret})
    assert secret not in repr(spec)
    process = processes()
    health = await process.start(spec)
    argv = psutil.Process(health["pid"]).cmdline()
    assert not any(secret in arg for arg in argv)
    if mode == "normal":
        probe = await process.call("fixture.probe")
        assert probe["credential_received"]
        assert not probe["credential_in_argv"]
        assert not probe["credential_in_env"]
    else:
        await eventually(
            lambda: process.health_snapshot()["platform_state"] == "failed",
        )
        assert process.health_snapshot()["last_error"]
    assert secret not in repr(process.health_snapshot()) + caplog.text
    await process.stop()
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert secret.encode() not in path.read_bytes(), path


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["import_hang", "connect_hang"])
async def test_parent_killed_while_stdlib_sdk_is_blocked(
    launch,
    tmp_path,
    mode,
):
    """Watchdog must be armed before a blocked Driver import/connection."""
    spec, marker = launch(mode, startup_timeout=30)
    # This is test-host input with no credentials, never a worker launch file.
    path = tmp_path / "host-input.json"
    value = asdict(spec)
    for key in ("support_root", "code_root", "descriptor_path"):
        value[key] = str(value[key])
    value["dependency_paths"] = []
    path.write_text(json.dumps(value))
    host_code = """
import asyncio,json,sys
from pathlib import Path
from qwenpaw.app.channels.process_supervisor import ChannelProcess,LaunchSpec
async def main():
    value=json.loads(Path(sys.argv[1]).read_text())
    for key in ('support_root','code_root','descriptor_path'):
        value[key]=Path(value[key])
    value['dependency_paths']=tuple(Path(p) for p in value['dependency_paths'])
    process=ChannelProcess()
    await process.start(LaunchSpec(**value))
    await asyncio.Event().wait()
asyncio.run(main())
"""
    host = subprocess.Popen(
        [sys.executable, "-I", "-c", host_code, str(path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    worker = None
    descendant_pid = None
    try:
        await eventually(marker.exists, timeout=8)
        worker = int(marker.read_text())
        descendant_pid = int(Path(str(marker) + ".child").read_text())
        assert alive(worker)
        assert alive(descendant_pid)
        host.kill()
        await asyncio.to_thread(host.wait, timeout=5)
        await eventually(lambda: not alive(worker), timeout=5)
        await eventually(lambda: not alive(descendant_pid), timeout=5)
    finally:
        if host.poll() is None:
            host.kill()
            await asyncio.to_thread(host.wait, timeout=5)
        if alive(worker):
            psutil.Process(worker).kill()
        if alive(descendant_pid):
            psutil.Process(descendant_pid).kill()


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="Needs actual Windows pipes/job",
)
@pytest.mark.asyncio
async def test_native_windows_pipe_and_owned_tree(launch, processes):
    """Windows execution validates actual pipes and owned descendants."""
    spec, marker = launch("descendant")
    process = processes()
    health = await process.start(spec)
    child = int(marker.read_text())
    assert (await process.call("fixture.probe"))["pid"] == health["pid"]
    assert (await process.stop()).exited
    await eventually(lambda: not alive(child))


@pytest_asyncio.fixture
async def rpc_pair():
    """Real OS byte streams exercise the reused framing/RPC ID extension."""
    from qwenpaw.channel_protocol.framing import FramedTransport
    from qwenpaw.channel_protocol.rpc import RpcPeer

    left, right = socket.socketpair()
    left.setblocking(False)
    right.setblocking(False)
    streams = await asyncio.gather(
        asyncio.open_connection(sock=left),
        asyncio.open_connection(sock=right),
    )
    peers = [RpcPeer(FramedTransport(*stream)) for stream in streams]
    await asyncio.gather(*(peer.start() for peer in peers))
    yield peers
    await asyncio.gather(*(peer.aclose() for peer in peers))


@pytest.mark.asyncio
async def test_rpc_default_explicit_collision_and_cancellation_ids(rpc_pair):
    """Explicit IDs preserve defaults, collisions and remote cancellation."""
    core, runner = rpc_pair
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def echo(_params, request):
        return request.id

    async def hold(_params, _request):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    runner.register_method("fixture.echo", echo)
    runner.register_method("fixture.hold", hold)
    assert await core.call("fixture.echo") == "rpc-1"
    assert (
        await core.call("fixture.echo", request_id="chosen-id") == "chosen-id"
    )
    pending = asyncio.create_task(
        core.call("fixture.hold", request_id="rpc-2"),
    )
    await asyncio.wait_for(entered.wait(), 1)
    with pytest.raises(ValueError, match="pending"):
        await core.call("fixture.echo", request_id="rpc-2")
    assert await core.call("fixture.echo") == "rpc-3"
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    await asyncio.wait_for(cancelled.wait(), 1)
    # Explicit IDs stay unique for a peer; late replies cannot poison a new ID.
    assert (
        await core.call("fixture.echo", request_id="after-cancel")
        == "after-cancel"
    )
    await eventually(lambda: core.duplicate_responses == 1)
    assert await core.call("fixture.echo", request_id=17) == 17


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_id", [True, "", 1.5, [], {}])
async def test_rpc_invalid_explicit_id_is_rejected_locally(rpc_pair, bad_id):
    """No malformed explicit ID enters the framed wire."""
    core, _runner = rpc_pair
    with pytest.raises(ValueError):
        await core.call("fixture.echo", request_id=bad_id)


@pytest.mark.asyncio
async def test_pending_admission_is_bounded_and_rejection_known(
    launch,
    processes,
):
    """Full pending queues reject before transmission without uncertainty."""
    from qwenpaw.channel_protocol.errors import RpcError
    from qwenpaw.channel_protocol.rpc import RPC_BACKPRESSURE

    spec, _ = launch()
    process = processes()
    await process.start(spec)
    pending = [
        asyncio.create_task(process.call("fixture.slow")) for _ in range(64)
    ]
    try:
        await asyncio.sleep(0.1)
        with pytest.raises(RpcError) as caught:
            await process.call("fixture.probe")
        assert caught.value.code == RPC_BACKPRESSURE
        assert process.health_snapshot()["unknown_outcomes"] == []
    finally:
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)


@pytest.mark.asyncio
async def test_unknown_records_are_bounded_without_payloads(launch, processes):
    """Long-lived failures cannot grow diagnostics or expose credentials."""
    spec, _ = launch()
    process = processes()
    await process.start(spec)
    for _ in range(5):
        calls = [
            process.call(
                "fixture.slow",
                {"credential": "hidden"},
                timeout=0.03,
            )
            for _ in range(30)
        ]
        results = await asyncio.gather(*calls, return_exceptions=True)
        assert all(
            getattr(result, "reason_code", None) == "PLATFORM_RESULT_UNKNOWN"
            for result in results
        )
    records = process.health_snapshot()["unknown_outcomes"]
    assert len(records) == 128
    assert "credential" not in repr(records) and "hidden" not in repr(records)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["before_spawn", "after_spawn"])
async def test_cancel_during_delayed_real_spawn_retains_ownership(
    api,
    launch,
    processes,
    monkeypatch,
    phase,
):
    """A late real spawn stays owned across bounded cancellation cleanup."""
    spec, _ = launch(shutdown_timeout=0.3)
    original = asyncio.create_subprocess_exec
    gate, entered = asyncio.Event(), asyncio.Event()
    spawned = []

    async def delayed_spawn(*args, **kwargs):
        if phase == "after_spawn":
            spawned.append(await original(*args, **kwargs))
        entered.set()
        await gate.wait()
        if phase == "before_spawn":
            spawned.append(await original(*args, **kwargs))
        return spawned[0]

    monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed_spawn)
    process = processes()
    operation = asyncio.create_task(process.start(spec))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(operation, 2)
        with pytest.raises(api.ChannelProcessError) as caught:
            await process.start(spec)
        assert caught.value.reason_code == "PROCESS_OWNED"
        result = await process.stop(timeout=0.2)
        assert not result.exited and "SPAWN_PENDING" in result.residual
    finally:
        gate.set()
    await eventually(lambda: bool(spawned))
    await eventually(lambda: not alive(spawned[0].pid))
    await eventually(lambda: process.health_snapshot()["pid"] is None)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", original)
    replacement, _ = launch()
    await process.start(replacement)
    assert (await process.call("fixture.probe"))["pid"] != spawned[0].pid


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["timeout", "cancel"])
async def test_default_rpc_ids_advance_past_timed_out_explicit_id(
    rpc_pair,
    outcome,
):
    """Default IDs cannot reuse explicit IDs after local pending removal."""
    from qwenpaw.channel_protocol.errors import RpcTimeoutError

    core, runner = rpc_pair
    entered, cancelled, release = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )
    observed = []

    async def hold(_params, request):
        observed.append(request.id)
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()
        return "late-result"

    async def echo(_params, request):
        observed.append(request.id)
        return request.id

    runner.register_method("fixture.hold", hold)
    runner.register_method("fixture.echo", echo)
    pending = asyncio.create_task(
        core.call("fixture.hold", request_id="rpc-1", timeout=0.05),
    )
    try:
        await asyncio.wait_for(entered.wait(), 1)
        if outcome == "cancel":
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
        else:
            with pytest.raises(RpcTimeoutError):
                await pending
        await asyncio.wait_for(cancelled.wait(), 1)
        assert await core.call("fixture.echo") == "rpc-2"
        assert observed == ["rpc-1", "rpc-2"]
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["before_spawn", "after_spawn"])
async def test_short_stop_budget_includes_concurrent_start_cleanup(
    api,
    launch,
    processes,
    monkeypatch,
    phase,
):
    """Short stop budgets cover startup with a larger cleanup budget."""
    spec, _ = launch(shutdown_timeout=1.2)
    original = asyncio.create_subprocess_exec
    entered, release = asyncio.Event(), asyncio.Event()
    spawned = []

    async def delayed_spawn(*args, **kwargs):
        if phase == "after_spawn":
            spawned.append(await original(*args, **kwargs))
        entered.set()
        await release.wait()
        if phase == "before_spawn":
            spawned.append(await original(*args, **kwargs))
        return spawned[0]

    monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed_spawn)
    process = processes()
    starting = asyncio.create_task(process.start(spec))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        begin = asyncio.get_running_loop().time()
        result = await process.stop(timeout=0.06)
        elapsed = asyncio.get_running_loop().time() - begin
        assert elapsed < 0.22, f"stop consumed {elapsed:.3f}s for 0.06s budget"
        assert not result.exited and result.residual
        with pytest.raises(api.ChannelProcessError) as caught:
            await process.start(spec)
        assert caught.value.reason_code == "PROCESS_OWNED"
    finally:
        release.set()
        await asyncio.gather(starting, return_exceptions=True)
    await eventually(lambda: bool(spawned))
    await eventually(lambda: not alive(spawned[0].pid))
    await eventually(lambda: process.health_snapshot()["pid"] is None)


@pytest.mark.asyncio
async def test_closed_peer_rejects_new_call_before_admission(
    api,
    launch,
    processes,
):
    """Disconnect cleanup cannot mark an unadmitted probe as unknown."""
    spec, marker = launch("descendant", shutdown_timeout=1.2)
    process = processes()
    await process.start(spec)
    child = int(marker.read_text())
    try:
        with pytest.raises(api.ChannelCallUnknown):
            await process.call("fixture.crash")
        assert alive(child), "Real descendant must prolong disconnect cleanup"
        with pytest.raises(api.ChannelProcessError) as caught:
            await process.call("fixture.probe")
        assert caught.value.reason_code == "NOT_READY"
        records = process.health_snapshot()["unknown_outcomes"]
        assert [row["method"] for row in records] == ["fixture.crash"]
    finally:
        await process.stop(timeout=1.5)
    await eventually(lambda: not alive(child))


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["extra", "missing"])
async def test_shared_stop_rejects_invalid_identity_without_stopping_worker(
    launch,
    processes,
    change,
):
    """The real child validates the complete closed stop request schema."""
    from qwenpaw.channel_protocol.errors import RpcError

    spec, _ = launch()
    process = processes()
    health = await process.start(spec)
    identity = {
        "channel_key": spec.channel_key,
        "instance_id": spec.instance_id,
        "generation": spec.generation,
    }
    invalid = dict(identity)
    if change == "extra":
        invalid["unexpected"] = True
    else:
        invalid.pop("generation")
    with pytest.raises(RpcError) as caught:
        await process.call("shared.stop", invalid)
    assert caught.value.code == -32602
    assert alive(health["pid"])
    assert process.health_snapshot()["state"] == "ready"
    assert (await process.call("fixture.probe"))["pid"] == health["pid"]
    result = await process.stop()
    assert result.exited and not result.forced and result.returncode == 0
    assert not alive(health["pid"])


@pytest.mark.asyncio
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Needs POSIX TERM observation",
)
async def test_short_stop_budget_includes_running_crash_cleanup(
    api,
    launch,
    processes,
):
    """An owned monitor cleanup also obeys the caller's smaller stop budget."""
    spec, marker = launch("descendant", shutdown_timeout=1.2)
    process = processes()
    await process.start(spec)
    child = int(marker.read_text())
    with pytest.raises(api.ChannelCallUnknown):
        await process.call("fixture.crash")
    await eventually(Path(str(marker) + ".child-term").exists)
    assert alive(child)
    begin = asyncio.get_running_loop().time()
    result = await process.stop(timeout=0.06)
    elapsed = asyncio.get_running_loop().time() - begin
    assert elapsed < 0.22, f"stop consumed {elapsed:.3f}s for 0.06s budget"
    assert result.exited or result.residual
    if not result.exited:
        with pytest.raises(api.ChannelProcessError) as caught:
            await process.start(spec)
        assert caught.value.reason_code == "PROCESS_OWNED"
    await eventually(lambda: not alive(child))
