# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
"""Independent generic execution contracts over real subprocess IPC."""

import asyncio
from dataclasses import replace
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys

import psutil
import pytest
import pytest_asyncio
from packaging.markers import default_environment
from packaging.tags import sys_tags

ROOT = Path(__file__).resolve().parents[3]
WORKER = Path(__file__).with_name("generic_worker.py")


def digest(root):
    result = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            name, data = (
                path.relative_to(root).as_posix().encode(),
                path.read_bytes(),
            )
            result.update(len(name).to_bytes(8, "big"))
            result.update(name)
            result.update(len(data).to_bytes(8, "big"))
            result.update(data)
    return result.hexdigest()


def alive(pid):
    if not pid:
        return False
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


async def eventually(predicate, timeout=5):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


@pytest.fixture
def api():
    return importlib.import_module("qwenpaw.plugins.execution")


@pytest.fixture
def launch(api, tmp_path):
    count = 0

    def make(mode="normal", **overrides):
        nonlocal count
        count += 1
        code, marker = (
            tmp_path / f"worker-{count}",
            tmp_path / f"ledger-{count}",
        )
        code.mkdir()
        (code / "worker.py").write_text(
            f"MODE={mode!r}\nMARKER={str(marker)!r}\n" + WORKER.read_text(),
        )
        return (
            api.PluginLaunchSpec(
                **{
                    "python_executable": sys.executable,
                    "support_root": ROOT / "src",
                    "code_root": code,
                    "source_revision": digest(code),
                    "plugin_id": "fixture.image-indexer",
                    "instance_id": f"workspace-{count}",
                    "generation": 1,
                    "entrypoint": "worker:Worker",
                    "config": {},
                    "startup_timeout": 2,
                    "shutdown_timeout": 0.4,
                    **overrides,
                },
            ),
            marker,
        )

    return make


@pytest_asyncio.fixture
async def processes(api):
    owned = []

    def make():
        process = api.PluginProcess()
        owned.append(process)
        return process

    yield make
    for process in owned:
        await asyncio.wait_for(process.stop(timeout=2), 5)


@pytest.mark.parametrize("generation", [True, 1.0, 1, 2])
def test_hello_generation_requires_integer_identity(launch, generation):
    """Python equality cannot admit bool/float as a generation integer."""
    from qwenpaw.plugins.execution.errors import ProtocolValidationError
    from qwenpaw.plugins.execution.runtime import validate_hello

    spec, _ = launch()
    tag = next(sys_tags())
    hello = {
        "plugin_id": spec.plugin_id,
        "instance_id": spec.instance_id,
        "generation": generation,
        "protocol_version": 1,
        "source_revision": spec.source_revision,
        "python_abi": f"{tag.interpreter}-{tag.abi}",
        "platform_tag": tag.platform,
        "marker_environment": default_environment(),
        "dependencies": [],
    }
    if type(generation) is int and generation == spec.generation:
        assert validate_hello(hello, spec) is None
    else:
        with pytest.raises(ProtocolValidationError):
            validate_hello(hello, spec)


@pytest.mark.asyncio
async def test_disabled_and_readonly_do_not_spawn_or_import_worker(
    api,
    launch,
    monkeypatch,
):
    def forbidden(*_args, **_kwargs):
        raise AssertionError(
            "Readonly or disabled operation spawned a process",
        )

    spec, marker = launch("import_hang", enabled=False)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    monkeypatch.setattr(subprocess.Popen, "__init__", forbidden)
    process = api.PluginProcess()
    process.register_method("fixture.host", lambda _params, _request: {})
    assert process.health_snapshot()["state"] == "idle"
    assert not marker.exists() and "worker" not in sys.modules
    health = await process.start(spec)
    assert health["state"] == "disabled" and health["pid"] is None
    with pytest.raises(api.ProcessError) as caught:
        await process.call("fixture.probe")
    assert caught.value.reason_code == "NOT_READY"
    assert (await process.stop()).exited
    assert not marker.exists() and "worker" not in sys.modules


@pytest.mark.asyncio
async def test_manifest_free_non_channel_worker_bidirectional_ipc(
    launch,
    processes,
):
    one, _ = launch()
    two, _ = launch()
    first, second = processes(), processes()
    notices = []
    first.register_notification(
        "fixture.notice",
        lambda params, _request: notices.append(params),
    )
    first.register_method(
        "fixture.host",
        lambda params, _request: {"received": params},
    )
    health_one, health_two = await asyncio.gather(
        first.start(one),
        second.start(two),
    )
    assert health_one["state"] == health_two["state"] == "ready"
    assert (
        "component_state" in health_one and "platform_state" not in health_one
    )
    assert not list(
        one.code_root.glob("*.json"),
    ), "Generic launch requires no manifest"
    probes = await asyncio.gather(
        first.call("fixture.probe"),
        second.call("fixture.probe"),
    )
    assert probes[0]["pid"] != probes[1]["pid"]
    for spec, probe in zip((one, two), probes):
        assert probe["identity"] == {
            "plugin_id": spec.plugin_id,
            "instance_id": spec.instance_id,
            "generation": 1,
        }
        assert probe["isolated"] == 1 and probe["blocked_modules"] == []
        assert probe["blocked_imports"] == []
    assert await first.call("fixture.reverse", {"indexed": 3}) == {
        "received": probes[0]["identity"],
    }
    await eventually(lambda: notices == [{"indexed": 3}])
    await eventually(
        lambda: first.health_snapshot()["component_state"] == "ready",
    )
    result = await first.stop()
    assert result.exited and not result.forced and result.returncode == 0
    assert not alive(probes[0]["pid"])
    assert (await second.call("fixture.probe"))["pid"] == probes[1]["pid"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["import_hang", "start_hang"])
async def test_external_blocking_work_stays_outside_parent(
    api,
    launch,
    processes,
    mode,
):
    spec, marker = launch(mode, startup_timeout=0.35)
    process, ticks = processes(), 0
    starting = asyncio.create_task(process.start(spec))
    while not starting.done():
        ticks += 1
        await asyncio.sleep(0.01)
    if mode == "import_hang":
        with pytest.raises(api.ProcessError):
            await starting
        assert marker.exists() and not alive(int(marker.read_text()))
    else:
        assert (await starting)["state"] == "ready"
        await eventually(marker.exists)
        assert process.health_snapshot()["component_state"] == "starting"
        result = await process.stop(timeout=0.3)
        assert result.exited and result.forced
        assert not alive(int(marker.read_text()))
    assert ticks >= 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    ["source", "entrypoint", "outside_requirements", "missing_dependency"],
)
async def test_trusted_code_and_dependencies_rejected(
    api,
    launch,
    processes,
    tmp_path,
    change,
):
    spec, _ = launch()
    if change == "source":
        spec = replace(spec, source_revision="0" * 64)
    elif change == "entrypoint":
        spec = replace(spec, entrypoint="worker:MissingWorker")
    else:
        requirements = (
            tmp_path if change == "outside_requirements" else spec.code_root
        ) / "requirements.txt"
        requirements.write_text("qwenpaw-generic-uninstalled-sdk-314159>=1\n")
        spec = replace(
            spec,
            requirements_path=requirements,
            source_revision=digest(spec.code_root),
        )
    process = processes()
    with pytest.raises(api.ProcessError):
        await process.start(spec)
    assert not alive(process.health_snapshot()["pid"])


@pytest.mark.asyncio
async def test_shared_dependencies_use_metadata_without_pth_execution(
    launch,
    processes,
    tmp_path,
):
    site = tmp_path / "shared-site"
    site.mkdir()
    (site / "generic_fixture_sdk.py").write_text("VALUE='child-only'\n")
    metadata = site / "generic_fixture_sdk-2.5.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: generic-fixture-sdk\nVersion: 2.5\n",
    )
    executed = tmp_path / "pth-executed"
    (site / "arbitrary.pth").write_text(
        f"import pathlib; pathlib.Path({str(executed)!r}).touch()\n",
    )
    spec, _ = launch("shared_site", dependency_paths=(site,))
    requirements = spec.code_root / "requirements.txt"
    requirements.write_text("generic-fixture-sdk>=2,<3\n")
    spec = replace(
        spec,
        requirements_path=requirements,
        source_revision=digest(spec.code_root),
    )
    process = processes()
    await process.start(spec)
    assert (await process.call("fixture.probe"))["sdk"] == "child-only"
    assert not executed.exists() and "generic_fixture_sdk" not in sys.modules


@pytest.mark.asyncio
async def test_unknown_results_remain_private_and_are_not_replayed(
    api,
    launch,
    processes,
):
    spec, ledger = launch(restart_limit=1, restart_backoff=0.02)
    process = processes()
    seen = []
    process.register_method(
        "fixture.host",
        lambda params, _request: seen.append(params) or params,
    )
    process.register_notification(
        "fixture.notice",
        lambda _params, _request: None,
    )
    first = await process.start(spec)
    with pytest.raises(api.CallUnknown) as caught:
        await process.call(
            "fixture.commit",
            {"credential": "hidden"},
            timeout=0.08,
        )
    assert (
        caught.value.request_id == json.loads(ledger.read_text())["request_id"]
    )
    assert (
        caught.value.method == "fixture.commit"
        and caught.value.generation == 1
    )
    calling = asyncio.create_task(process.call("fixture.slow"))
    await eventually(Path(str(ledger) + ".slow").exists)
    calling.cancel()
    with pytest.raises(asyncio.CancelledError):
        await calling
    records = process.health_snapshot()["unknown_outcomes"]
    assert {row["method"] for row in records} == {
        "fixture.commit",
        "fixture.slow",
    }
    assert all(
        set(row) == {"request_id", "method", "generation", "reason_code"}
        for row in records
    )
    assert "hidden" not in repr(records)
    with pytest.raises(api.CallUnknown):
        await process.call("fixture.crash")
    await eventually(
        lambda: process.health_snapshot()["generation"] == 2
        and process.health_snapshot()["state"] == "ready",
    )
    assert not alive(first["pid"]) and ledger.read_text().count("\n") == 1
    assert (await process.call("fixture.reverse", {}))["generation"] == 2
    assert seen[0]["generation"] == 2
    await process.call("fixture.stale")
    await asyncio.sleep(0.03)
    assert process.health_snapshot()["component_state"] == "ready"
    assert records[0] in process.health_snapshot()["unknown_outcomes"]
    with pytest.raises(api.CallUnknown):
        await process.call("fixture.crash")
    await eventually(lambda: process.health_snapshot()["state"] == "failed")
    assert process.health_snapshot()["generation"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["start", "stop"])
async def test_lifecycle_cancellation_retains_ownership_and_finishes_cleanup(
    api,
    launch,
    processes,
    phase,
):
    spec, marker = launch("import_hang" if phase == "start" else "stop_hang")
    process = processes()
    if phase == "stop":
        await process.start(spec)
        operation = asyncio.create_task(process.stop(timeout=0.4))
    else:
        operation = asyncio.create_task(process.start(spec))
    await eventually(marker.exists)
    pid = int(marker.read_text())
    with pytest.raises(api.ProcessError) as caught:
        await process.start(spec)
    assert caught.value.reason_code == "PROCESS_OWNED"
    operation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(operation, 5)
    assert not alive(pid)
    replacement, _ = launch()
    await process.start(replacement)
    assert (await process.call("fixture.probe"))["pid"] != pid


@pytest.mark.asyncio
async def test_stop_reaps_descendant_and_revokes_restart(
    api,
    launch,
    processes,
):
    spec, marker = launch("descendant", restart_limit=3, restart_backoff=0.4)
    process = processes()
    health = await process.start(spec)
    child = int(marker.read_text())
    assert alive(child)
    with pytest.raises(api.CallUnknown):
        await process.call("fixture.crash")
    await eventually(lambda: process.health_snapshot()["state"] == "backoff")
    result = await process.stop(timeout=0.6)
    assert result.exited and result.residual == ()
    await asyncio.sleep(0.5)
    assert process.health_snapshot()["state"] == "stopped"
    assert process.health_snapshot()["generation"] == 1
    assert not alive(child) and not alive(health["pid"])


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["flood", "secret_failure"])
async def test_logs_are_drained_and_launch_config_stays_private(
    launch,
    processes,
    tmp_path,
    caplog,
    mode,
):
    secret = "GENERIC-private-credential-8675309"
    spec, _ = launch(mode, config={"credential": secret})
    assert secret not in repr(spec)
    process = processes()
    health = await process.start(spec)
    assert not any(
        secret in value for value in psutil.Process(health["pid"]).cmdline()
    )
    if mode == "flood":
        probe = await process.call("fixture.probe")
        assert probe["credential_received"]
        assert (
            not probe["credential_in_argv"] and not probe["credential_in_env"]
        )
        assert process.health_snapshot()["log_bytes"] >= 6 * 1024 * 1024
    else:
        await eventually(
            lambda: process.health_snapshot()["component_state"] == "failed",
        )
        assert process.health_snapshot()["last_error"]
    diagnostics = json.dumps(process.health_snapshot())
    assert len(diagnostics) < 4096 and secret not in diagnostics + caplog.text
    assert "untrusted-log" not in diagnostics
    await process.stop()
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert secret.encode() not in path.read_bytes(), path
