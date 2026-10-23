# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""C4 evidence over actual isolated workers and trusted local wheel files."""

import asyncio
import base64
from dataclasses import replace
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import zipfile

import pytest

from process_supervisor_suite import alive, digest, eventually
from qwenpaw.plugins.dependency_maintenance import lease_environment

pytest_plugins = ["process_supervisor_suite"]


def metadata(site, name="c4-fixture-sdk", version="2.5", requires=()):
    """Minimal installed distribution whose module has no side effects."""
    site.mkdir(parents=True, exist_ok=True)
    package = name.replace("-", "_").replace(".", "_")
    (site / f"{package}.py").write_text("VALUE = 'local-child-sdk'\n")
    dist = site / f"{package}-{version}.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
        + "".join(f"Requires-Dist: {item}\n" for item in requires),
    )
    (dist / "top_level.txt").write_text(package + "\n")
    return dist


def wheel(
    tmp_path,
    name="c4-fixture-sdk",
    version="2.5",
    requires=(),
    extra=None,
):
    """Build a complete plain wheel without a build tool or package index."""
    package = name.replace("-", "_")
    info = f"{package}-{version}.dist-info"
    files = {
        f"{package}.py": b"VALUE = 'local-wheel-sdk'\n",
        f"{info}/METADATA": (
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
            + "".join(f"Requires-Dist: {item}\n" for item in requires)
        ).encode(),
        f"{info}/WHEEL": (
            "Wheel-Version: 1.0\nGenerator: independent-c4-test\n"
            "Root-Is-Purelib: true\nTag: py3-none-any\n"
        ).encode(),
        f"{info}/top_level.txt": (package + "\n").encode(),
        **(extra or {}),
    }
    rows = []
    for member, data in files.items():
        checksum = base64.urlsafe_b64encode(hashlib.sha256(data).digest())
        encoded = checksum.decode().rstrip("=")
        rows.append(f"{member},sha256={encoded},{len(data)}\n")
    record = "".join(rows) + f"{info}/RECORD,,\n"
    files[f"{info}/RECORD"] = record.encode()
    path = tmp_path / f"{package}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        for member, data in files.items():
            archive.writestr(member, data)
    gate = importlib.import_module("qwenpaw.plugins.dependency_gate")
    assert hasattr(gate, "WheelAddition"), "C4 local wheel API missing"
    return gate.WheelAddition(
        path,
        hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def gate_api():
    gate = importlib.import_module("qwenpaw.plugins.dependency_gate")
    assert hasattr(
        gate,
        "prepare_shared_dependencies",
    ), "C4 preparation missing"
    return gate


def preparation_inputs(spec):
    """Channel fixtures provide explicit generic Gate inputs."""
    from qwenpaw.plugins.dependency_usage import DependencyUsageRegistry
    from qwenpaw.plugins.ownership import RuntimeOwners

    return {
        "plugin_id": spec.channel_key,
        "requirements_file": spec.code_root / "requirements.txt",
        "usage_registry": DependencyUsageRegistry(RuntimeOwners()),
    }


def driver(spec, marker, mode="normal", port=9):
    """Nested real Driver with visible forbidden lifecycle counters."""
    package = spec.code_root / "nested"
    package.mkdir()
    (package / "__init__.py").write_text("")
    source = f"""import os, pathlib, threading
MARKER = pathlib.Path({str(marker)!r})
def record(event):
    with MARKER.open('a') as stream:
        stream.write(event + '\\n')
pathlib.Path(str(MARKER) + '.pid').write_text(str(os.getpid()))
record('import')
"""
    if mode == "import_failure":
        source += "raise RuntimeError('candidate import failed')\n"
    elif mode == "import_hang":
        source += "threading.Event().wait()\n"
    elif mode == "network":
        source += (
            "import socket\n"
            f"socket.socket().connect(('127.0.0.1', {port}))\n"
        )
    elif mode == "sendto":
        source += (
            "import sys\n"
            "sys.audit('socket.sendto', None, ('127.0.0.1', 9))\n"
        )
    elif mode == "spawn":
        source += (
            "import subprocess, sys\n"
            "subprocess.Popen([sys.executable, '-c', 'pass'])\n"
        )
    source += """class Driver:
    def __init__(self):
        record('constructor')
    def bind(self, context):
        record('bind')
    async def start(self, config):
        record('start')
    async def stop(self):
        record('stop')
"""
    if mode == "bad_interface":
        source = source.replace("async def stop(self):", "def stop(self):")
    elif mode == "bad_constructor":
        source = source.replace(
            "def __init__(self):",
            "def __init__(self, required):",
        )
    elif mode == "bad_signature":
        source = source.replace(
            "async def start(self, config):",
            "async def start(self):",
        )
    (package / "driver.py").write_text(source)
    descriptor = json.loads(spec.descriptor_path.read_text())
    descriptor["entrypoint"].update(module="nested.driver", qualname="Driver")
    spec.descriptor_path.write_text(json.dumps(descriptor))
    return replace(spec, source_revision=digest(spec.code_root))


@pytest.mark.asyncio
async def test_actual_target_audit_excludes_parent_candidate_and_pth(
    launch,
    processes,
    tmp_path,
    monkeypatch,
):
    site = tmp_path / "site"
    metadata(site)
    pth_marker = tmp_path / "pth-executed"
    (site / "evil.pth").write_text(
        f"import pathlib; pathlib.Path({str(pth_marker)!r}).touch()\n",
    )
    parent = tmp_path / "parent"
    metadata(parent, "c4-parent-only")
    monkeypatch.syspath_prepend(str(parent))
    spec, marker = launch(
        requirements=(
            "c4-fixture-sdk>=2,<3\n"
            "c4-parent-only>=1\nc4-candidate-fake>=1\n"
        ),
        dependency_paths=(site,),
    )
    metadata(spec.code_root, "c4-candidate-fake")
    trusted_shadow = tmp_path / "trusted-shadow-executed"
    for module in ("packaging", "inspect"):
        (spec.code_root / f"{module}.py").write_text(
            f"__import__('pathlib').Path({str(trusted_shadow)!r}).touch()\n"
            "raise AssertionError('candidate shadow executed during audit')\n",
        )
    spec = driver(spec, marker)
    result = await processes().audit(spec)
    assert result.cleanup.exited and result.cleanup.residual == ()
    assert (
        Path(result.snapshot.executable).resolve()
        == Path(sys.executable).resolve()
    )
    assert result.snapshot.distributions["c4-fixture-sdk"]["version"] == "2.5"
    assert "c4-parent-only" not in result.snapshot.distributions
    assert "c4-candidate-fake" not in result.snapshot.distributions
    assert not marker.exists() and not pth_marker.exists()
    assert not trusted_shadow.exists()
    decision = gate_api().evaluate_shared_dependencies(
        spec.code_root / "requirements.txt",
        result.snapshot,
        plugin_id="fixture",
    )
    assert not decision.already_satisfied and not decision.allow_install
    assert len(decision.missing) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    [
        "marker",
        "version",
        "import_only",
        "invalid",
        "duplicate",
        "missing_metadata",
    ],
)
async def test_target_markers_and_metadata_fail_closed(
    launch,
    processes,
    tmp_path,
    kind,
):
    site = tmp_path / "site"
    site.mkdir()
    requirements = "c4-fixture-sdk>=2,<3\n"
    if kind == "marker":
        requirements = "c4-absent-sdk; python_version<'0'\n"
    elif kind == "import_only":
        (site / "c4_fixture_sdk.py").write_text("VALUE=1\n")
    else:
        metadata(site, version="1.0" if kind == "version" else "2.5")
        if kind == "invalid":
            metadata(site, version="not-a-version")
        if kind == "duplicate":
            metadata(site, version="3.1")
        if kind == "missing_metadata":
            (site / "c4_fixture_sdk-2.5.dist-info" / "METADATA").unlink()
    spec, _ = launch(requirements=requirements, dependency_paths=(site,))
    process = processes()
    if kind in {"invalid", "duplicate", "missing_metadata"}:
        with pytest.raises(RuntimeError):
            await process.audit(spec)
        assert process.last_cleanup.exited
    else:
        result = await process.audit(spec)
        decision = gate_api().evaluate_shared_dependencies(
            spec.code_root / "requirements.txt",
            result.snapshot,
            plugin_id="fixture",
        )
        assert decision.already_satisfied is (kind == "marker")
        assert not decision.allow_install


@pytest.mark.asyncio
async def test_frozen_parent_uses_selected_real_python(
    launch,
    processes,
    monkeypatch,
):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    spec, _ = launch()
    result = await processes().audit(spec)
    assert result.cleanup.exited
    assert (
        result.snapshot.marker_environment["python_version"]
        == f"{sys.version_info.major}.{sys.version_info.minor}"
    )


@pytest.mark.asyncio
async def test_probe_imports_nested_driver_with_zero_lifecycle_calls(
    launch,
    processes,
):
    spec, marker = launch(
        config={"credential": "never-deliver-to-probe"},
        restart_limit=4,
    )
    spec = driver(spec, marker)
    process = processes()
    result = await process.probe(spec)
    pid = int(Path(str(marker) + ".pid").read_text())
    assert (
        result.hello
        and result.cleanup.exited
        and result.cleanup.residual == ()
    )
    assert marker.read_text().splitlines() == ["import"]
    assert not alive(pid)
    assert process.health_snapshot()["pid"] is None
    await asyncio.sleep(0.15)
    assert marker.read_text().splitlines() == ["import"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode",
    [
        "import_failure",
        "bad_interface",
        "bad_constructor",
        "bad_signature",
        "import_hang",
        "network",
        "sendto",
        "spawn",
    ],
)
async def test_bad_candidate_probe_reaped_old_service_stays_responsive(
    launch,
    processes,
    mode,
):
    serving, _ = launch()
    old = processes()
    await old.start(serving)
    old_pid = (await old.call("fixture.probe"))["pid"]
    candidate, marker = launch(startup_timeout=2)
    candidate = driver(candidate, marker, mode)
    process = processes()
    with pytest.raises(RuntimeError) as caught:
        await process.probe(candidate)
    if mode in {"network", "sendto", "spawn"}:
        assert caught.value.reason_code == "PROBE_NETWORK_OR_PROCESS_DENIED"
    assert process.last_cleanup.exited
    assert process.last_cleanup.residual == ()
    assert (await old.call("fixture.probe"))["pid"] == old_pid
    assert marker.read_text().splitlines() == ["import"]
    assert not alive(int(Path(str(marker) + ".pid").read_text()))


@pytest.mark.asyncio
async def test_cancelled_probe_settles_cleanup(launch, processes):
    spec, marker = launch(startup_timeout=5)
    spec = driver(spec, marker, "import_hang")
    process = processes()
    task = asyncio.create_task(process.probe(spec))
    await eventually(marker.exists)
    pid = int(Path(str(marker) + ".pid").read_text())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    assert process.last_cleanup.exited and not alive(pid)
    assert marker.read_text().splitlines() == ["import"]


@pytest.mark.asyncio
async def test_known_local_wheel_addition_then_satisfied_zero_wheel_read(
    launch,
    processes,
    tmp_path,
):
    site = tmp_path / "site"
    site.mkdir()
    spec, _ = launch(
        requirements="c4-fixture-sdk==2.5\n",
        dependency_paths=(site,),
    )
    lease_environment(spec.dependency_paths)
    addition = wheel(tmp_path)
    gate = gate_api()
    snapshot = await gate.prepare_shared_dependencies(
        processes(),
        spec,
        **preparation_inputs(spec),
        install_target=site,
        wheels=(addition,),
    )
    assert snapshot.distributions["c4-fixture-sdk"]["version"] == "2.5"
    assert (
        site / "c4_fixture_sdk.py"
    ).read_text() == "VALUE = 'local-wheel-sdk'\n"
    addition.path.unlink()
    reused = await gate.prepare_shared_dependencies(
        processes(),
        spec,
        **preparation_inputs(spec),
        install_target=site,
        wheels=(addition,),
    )
    assert reused.distributions["c4-fixture-sdk"]["version"] == "2.5"
    assert not list(site.glob("*.repair*"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    [
        "existing",
        "transitive",
        "unknown_transitive",
        "collision",
        "pth",
        "escape",
        "hash",
    ],
)
async def test_unsafe_addition_refused_without_site_mutation(
    launch,
    processes,
    tmp_path,
    kind,
):
    site = tmp_path / "site"
    site.mkdir()
    if kind == "existing":
        metadata(site, version="1.0")
    if kind == "collision":
        (site / "c4_fixture_sdk.py").write_text("existing-owner\n")
    if kind == "transitive":
        metadata(site, "c4-transitive-sdk", version="1.0")
    extra = {"startup.pth": b"import os\n"} if kind == "pth" else {}
    if kind == "escape":
        extra = {"../outside.py": b"bad\n"}
    addition = wheel(
        tmp_path,
        requires=("c4-transitive-sdk>=2",)
        if kind in {"transitive", "unknown_transitive"}
        else (),
        extra=extra,
    )
    if kind == "hash":
        addition = replace(addition, sha256="0" * 64)
    before = {
        p.relative_to(site): p.read_bytes()
        for p in site.rglob("*")
        if p.is_file()
    }
    spec, _ = launch(
        requirements="c4-fixture-sdk==2.5\n",
        dependency_paths=(site,),
    )
    lease_environment(spec.dependency_paths)
    with pytest.raises(RuntimeError):
        await gate_api().prepare_shared_dependencies(
            processes(),
            spec,
            **preparation_inputs(spec),
            install_target=site,
            wheels=(addition,),
        )
    after = {
        p.relative_to(site): p.read_bytes()
        for p in site.rglob("*")
        if p.is_file()
    }
    assert before == after and not (tmp_path / "outside.py").exists()


@pytest.mark.asyncio
async def test_held_environment_lock_means_zero_package_writes(
    launch,
    processes,
    tmp_path,
):
    lock = importlib.import_module("qwenpaw.plugins.install_lock")
    assert hasattr(lock, "environment_install_lock_path")
    site = tmp_path / "site"
    site.mkdir()
    spec, _ = launch(
        requirements="c4-fixture-sdk==2.5\n",
        dependency_paths=(site,),
    )
    lease_environment(spec.dependency_paths)
    addition = wheel(tmp_path)
    with lock.plugin_install_lock(lock.environment_install_lock_path(site)):
        with pytest.raises(RuntimeError):
            await gate_api().prepare_shared_dependencies(
                processes(),
                spec,
                **preparation_inputs(spec),
                install_target=site,
                wheels=(addition,),
                lock_timeout=0,
            )
    assert not list(site.iterdir())


@pytest.mark.asyncio
async def test_two_real_hosts_contend_and_reuse_known_addition(
    launch,
    tmp_path,
):
    from dataclasses import asdict

    site = tmp_path / "site"
    site.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(site, target_is_directory=True)
    addition = wheel(tmp_path)
    script = r"""
import asyncio, json, sys
from pathlib import Path

source = Path(sys.argv[5]).resolve()
sys.path.insert(0, str(source))
import qwenpaw

assert Path(qwenpaw.__file__).resolve().is_relative_to(source)
from qwenpaw.plugins.dependency_gate import (
    WheelAddition,
    prepare_shared_dependencies,
)
from qwenpaw.app.channels.process_supervisor import ChannelProcess, LaunchSpec
from qwenpaw.plugins.dependency_usage import DependencyUsageRegistry
from qwenpaw.plugins.dependency_maintenance import lease_environment
from qwenpaw.plugins.ownership import RuntimeOwners


async def main():
    value = json.loads(Path(sys.argv[1]).read_text())
    for key in ("support_root", "code_root", "descriptor_path"):
        value[key] = Path(value[key])
    value["dependency_paths"] = tuple(
        Path(p) for p in value["dependency_paths"]
    )
    lease_environment(value["dependency_paths"])
    process = ChannelProcess()
    result = await prepare_shared_dependencies(
        process,
        LaunchSpec(**value),
        plugin_id=value["channel_key"],
        requirements_file=value["code_root"] / "requirements.txt",
        usage_registry=DependencyUsageRegistry(RuntimeOwners()),
        install_target=Path(sys.argv[2]),
        wheels=(WheelAddition(Path(sys.argv[3]), sys.argv[4]),),
        lock_timeout=8,
    )
    print(result.distributions["c4-fixture-sdk"]["version"], flush=True)


asyncio.run(main())
"""
    hosts = []
    source_root = (
        Path(os.environ["QWENPAW_C7_RELEASE_ROOT"])
        if "QWENPAW_C7_RELEASE_ROOT" in os.environ
        else Path(__file__).resolve().parents[3]
    ) / "src"
    for index, target in enumerate((site, alias)):
        spec, _ = launch(
            requirements="c4-fixture-sdk==2.5\n",
            dependency_paths=(target,),
        )
        value = asdict(spec)
        for key in ("support_root", "code_root", "descriptor_path"):
            value[key] = str(value[key])
        value["dependency_paths"] = [str(p) for p in value["dependency_paths"]]
        path = tmp_path / f"host-{index}.json"
        path.write_text(json.dumps(value))
        hosts.append(
            await asyncio.create_subprocess_exec(
                sys.executable,
                "-I",
                "-c",
                script,
                str(path),
                str(target),
                str(addition.path),
                addition.sha256,
                str(source_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            ),
        )
    try:
        outputs = await asyncio.wait_for(
            asyncio.gather(*(host.communicate() for host in hosts)),
            25,
        )
        for host, (stdout, stderr) in zip(hosts, outputs):
            assert host.returncode == 0, stderr.decode()
            assert stdout.decode().strip() == "2.5"
        assert (site / "c4_fixture_sdk.py").exists()
        assert len(list(site.glob("*.dist-info"))) == 1
    finally:
        for host in hosts:
            if host.returncode is None:
                host.kill()
                await host.wait()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["partial", "cancel"])
async def test_interrupted_publication_retains_repair_blocker(
    launch,
    processes,
    tmp_path,
    monkeypatch,
    failure,
):
    import threading

    gate = gate_api()
    assert hasattr(gate, "_write_additions")
    site = tmp_path / "site"
    site.mkdir()
    spec, _ = launch(
        requirements="c4-fixture-sdk==2.5\n",
        dependency_paths=(site,),
    )
    lease_environment(spec.dependency_paths)
    addition = wheel(tmp_path)
    entered, release = threading.Event(), threading.Event()

    def interrupt(target, files):
        path = next(name for name in files if name.endswith(".py"))
        (target / path).write_bytes(files[path])
        entered.set()
        if failure == "cancel":
            assert release.wait(5), "test did not release owned writer"
        else:
            raise OSError("injected partial write failure")

    monkeypatch.setattr(gate, "_write_additions", interrupt)
    operation = asyncio.create_task(
        gate.prepare_shared_dependencies(
            processes(),
            spec,
            **preparation_inputs(spec),
            install_target=site,
            wheels=(addition,),
        ),
    )
    try:
        await eventually(entered.is_set)
        if failure == "cancel":
            operation.cancel()
            await asyncio.sleep(0.03)
            assert (
                not operation.done()
            ), "writer ownership lost on cancellation"
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(operation, 5)
        else:
            with pytest.raises(RuntimeError):
                await operation
        dependencies = importlib.import_module(
            "qwenpaw.plugins.execution.dependencies",
        )
        assert dependencies.repair_marker(site).exists()
        with pytest.raises(RuntimeError):
            await gate.prepare_shared_dependencies(
                processes(),
                spec,
                **preparation_inputs(spec),
            )
    finally:
        release.set()
        await asyncio.gather(operation, return_exceptions=True)


@pytest.mark.asyncio
async def test_probe_cleanup_failure_retains_owned_handle_for_retry(
    api,
    launch,
    processes,
    monkeypatch,
):
    from qwenpaw.plugins.execution.process import PluginProcess, StopResult

    original = PluginProcess._cleanup_owned
    retained = []

    async def residue(self, _budget, *, graceful):
        assert graceful is False
        retained.append(self)
        return StopResult(False, None, True, ("INJECTED_RESIDUAL",))

    spec, marker = launch()
    spec = driver(spec, marker)
    process = processes()
    monkeypatch.setattr(PluginProcess, "_cleanup_owned", residue)
    try:
        with pytest.raises(api.ChannelProcessError) as caught:
            await process.probe(spec)
        assert caught.value.reason_code == "PROBE_CLEANUP_FAILED"
        handle = caught.value.process
        assert handle in retained
        assert not handle.last_cleanup.exited
        assert "INJECTED_RESIDUAL" in handle.last_cleanup.residual
        with pytest.raises(api.ChannelProcessError) as owned:
            await handle.start(spec)
        assert owned.value.reason_code == "PROCESS_OWNED"
    finally:
        monkeypatch.setattr(PluginProcess, "_cleanup_owned", original)
        for handle in retained:
            assert (await handle.stop(timeout=2)).exited
    assert not alive(int(Path(str(marker) + ".pid").read_text()))


@pytest.mark.asyncio
async def test_absent_install_site_is_never_created(
    launch,
    processes,
    tmp_path,
):
    site = tmp_path / "unprovisioned-site"
    spec, _ = launch(
        requirements="c4-fixture-sdk==2.5\n",
        dependency_paths=(site,),
    )
    addition = wheel(tmp_path)
    with pytest.raises(RuntimeError):
        await gate_api().prepare_shared_dependencies(
            processes(),
            spec,
            **preparation_inputs(spec),
            install_target=site,
            wheels=(addition,),
        )
    assert not site.exists()


@pytest.mark.asyncio
async def test_dirty_satisfied_environment_still_blocks_activation(
    launch,
    processes,
    tmp_path,
):
    site = tmp_path / "site"
    metadata(site)
    dependencies = importlib.import_module(
        "qwenpaw.plugins.execution.dependencies",
    )
    dependencies.repair_marker(site).write_text(
        "previous partial publication\n",
    )
    spec, _ = launch(
        requirements="c4-fixture-sdk==2.5\n",
        dependency_paths=(site,),
    )
    with pytest.raises(RuntimeError):
        await gate_api().prepare_shared_dependencies(
            processes(),
            spec,
            **preparation_inputs(spec),
        )


@pytest.mark.asyncio
async def test_probe_rejects_candidate_sdk_shadow(
    launch,
    processes,
    tmp_path,
):
    site = tmp_path / "site"
    metadata(site)
    spec, marker = launch(
        requirements="c4-fixture-sdk==2.5\n",
        dependency_paths=(site,),
    )
    spec = driver(spec, marker)
    (spec.code_root / "c4_fixture_sdk.py").write_text(
        "VALUE='candidate-shadow'\n",
    )
    path = spec.code_root / "nested/driver.py"
    path.write_text("import c4_fixture_sdk\n" + path.read_text())
    spec = replace(spec, source_revision=digest(spec.code_root))
    process = processes()
    with pytest.raises(RuntimeError):
        await process.probe(spec)
    assert process.last_cleanup.exited
    assert marker.read_text().splitlines() == ["import"]


@pytest.mark.asyncio
async def test_installed_support_layout_preserves_sdk_metadata_in_same_site(
    launch,
    processes,
    tmp_path,
):
    import shutil
    from process_supervisor_suite import ROOT

    site = tmp_path / "installed-site"
    site.mkdir()
    for relative in ("qwenpaw/plugins/execution", "qwenpaw/channel_protocol"):
        shutil.copytree(ROOT / "src" / relative, site / relative)
    shutil.copyfile(
        ROOT / "src/qwenpaw/plugins/dependency_maintenance.py",
        site / "qwenpaw/plugins/dependency_maintenance.py",
    )
    metadata(site)
    spec, marker = launch(
        requirements="c4-fixture-sdk==2.5\n",
        dependency_paths=(site,),
        support_root=site,
    )
    spec = driver(spec, marker)
    result = await processes().audit(spec)
    assert result.snapshot.distributions["c4-fixture-sdk"]["version"] == "2.5"
    assert not marker.exists()
    probed = await processes().probe(spec)
    assert probed.cleanup.exited and probed.hello
    assert marker.read_text().splitlines() == ["import"]


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["before_spawn", "after_spawn"])
async def test_probe_spawn_race_and_repeated_cancel_keep_owned_child(
    launch,
    processes,
    monkeypatch,
    phase,
):
    spec, marker = launch(startup_timeout=5, shutdown_timeout=1)
    spec = driver(spec, marker, "import_hang")
    original = asyncio.create_subprocess_exec
    entered, release = asyncio.Event(), asyncio.Event()
    spawned = []

    async def delayed(*args, **kwargs):
        if phase == "after_spawn":
            spawned.append(await original(*args, **kwargs))
        entered.set()
        await release.wait()
        if phase == "before_spawn":
            spawned.append(await original(*args, **kwargs))
        return spawned[0]

    monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed)
    process = processes()
    operation = asyncio.create_task(process.probe(spec))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        operation.cancel()
        await asyncio.sleep(0.01)
        operation.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(operation, 5)
        assert len(spawned) == 1
        assert process.last_cleanup.exited
        assert not alive(spawned[0].pid)
    finally:
        release.set()
        await asyncio.gather(operation, return_exceptions=True)


@pytest.mark.asyncio
async def test_valid_sdk_sized_wheel_exceeds_lark_real_record_profile(
    launch,
    processes,
    tmp_path,
):
    site = tmp_path / "site"
    site.mkdir()
    addition = wheel(
        tmp_path,
        extra={f"c4_payload/file-{index}.txt": b"x" for index in range(11123)},
    )
    spec, _ = launch(
        requirements="c4-fixture-sdk==2.5\n",
        dependency_paths=(site,),
    )
    lease_environment(spec.dependency_paths)
    snapshot = await gate_api().prepare_shared_dependencies(
        processes(),
        spec,
        **preparation_inputs(spec),
        install_target=site,
        wheels=(addition,),
    )
    assert snapshot.distributions["c4-fixture-sdk"]["version"] == "2.5"
    assert len(list((site / "c4_payload").iterdir())) == 11123


@pytest.mark.asyncio
async def test_generic_loader_boot_zero_download_and_explicit_staged_addition(
    tmp_path,
    monkeypatch,
):
    import shutil
    from types import SimpleNamespace
    import venv
    from qwenpaw.plugins.loader import PluginLoader
    from qwenpaw.plugins.registry import PluginRegistry

    target = tmp_path / "native-target"
    await asyncio.to_thread(
        venv.EnvBuilder(system_site_packages=True, with_pip=False).create,
        target,
    )
    python = target / (
        "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
    )
    source = tmp_path / "legacy-source"
    source.mkdir()
    requirements = source / "requirements.txt"
    requirements.write_text("c4-fixture-sdk==2.5\n")
    addition = wheel(tmp_path)
    calls = []
    previous = PluginRegistry._instance
    PluginRegistry._instance = None
    try:
        loader = PluginLoader([source.parent])

        audited = []
        acquire = loader._acquire_dependency_wheels

        async def acquire_audited(process, spec, snapshot, *args, **kwargs):
            audited.append(snapshot)
            return await acquire(process, spec, snapshot, *args, **kwargs)

        monkeypatch.setattr(
            loader, "_acquire_dependency_wheels", acquire_audited
        )

        def stage_wheels(command, **kwargs):
            assert kwargs["plugin_id"] == "c4-legacy"
            assert command[command.index("-m") + 1] == "pip"
            assert "wheel" in command and "install" not in command
            assert "--target" not in command
            assert command[0] == str(python)
            assert "-I" in command
            constraints = Path(command[command.index("--constraint") + 1])
            assert len(audited) == 1
            assert set(constraints.read_text().splitlines()) == {
                f"{name}=={row['version']}"
                for name, row in audited[0].distributions.items()
            }
            staging = Path(command[command.index("--wheel-dir") + 1])
            assert staging.is_dir()
            assert not staging.is_relative_to(target)
            assert constraints.parent == staging
            shutil.copyfile(addition.path, staging / addition.path.name)
            calls.append(command)
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr(
            loader,
            "_run_subprocess_with_streaming_log",
            stage_wheels,
        )
        boot = await loader._ensure_dependencies_installed(source, "c4-legacy")
        assert (
            not boot.already_satisfied and not boot.allow_install and not calls
        )
        monkeypatch.setattr(sys, "executable", str(python))
        decision = await loader._prepare_python_dependencies(
            requirements,
            "c4-legacy",
        )
        assert decision.already_satisfied and len(calls) == 1
        site = next(target.rglob("site-packages"))
        assert (site / "c4_fixture_sdk.py").exists()
        calls.clear()
        addition.path.unlink()
        decision = await loader._prepare_python_dependencies(
            requirements,
            "c4-legacy",
        )
        assert decision.already_satisfied and not calls
    finally:
        PluginRegistry._instance = previous


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "shadow",
    ["earlier_site", "namespace_submodule", "symlink"],
)
@pytest.mark.parametrize("operation", ["probe", "start"])
async def test_probe_rejects_metadata_import_origin_disagreement(
    launch,
    processes,
    tmp_path,
    shadow,
    operation,
):
    actual = tmp_path / "metadata-site"
    actual.mkdir()
    if shadow == "earlier_site":
        metadata(actual)
        earlier = tmp_path / "earlier-site"
        earlier.mkdir()
        (earlier / "c4_fixture_sdk.py").write_text("VALUE='orphan-shadow'\n")
        requirement = "c4-fixture-sdk==2.5\n"
        imports = "import c4_fixture_sdk\n"
        paths = (earlier, actual)
    elif shadow == "namespace_submodule":
        dist = metadata(actual, "c4-namespace-sdk")
        (dist / "top_level.txt").write_text("c4_namespace\n")
        package = actual / "c4_namespace"
        package.mkdir()
        (package / "sdk.py").write_text("VALUE='actual-namespace-sdk'\n")
        requirement = "c4-namespace-sdk==2.5\n"
        imports = "import c4_namespace.sdk\n"
        paths = (actual,)
    else:
        metadata(actual)
        foreign = tmp_path / "unowned-outside-site"
        foreign.mkdir()
        orphan = foreign / "c4_fixture_sdk.py"
        orphan.write_text("VALUE='symlink-outside-owner'\n")
        (actual / "c4_fixture_sdk.py").unlink()
        (actual / "c4_fixture_sdk.py").symlink_to(orphan)
        requirement = "c4-fixture-sdk==2.5\n"
        imports = "import c4_fixture_sdk\n"
        paths = (actual,)
    spec, marker = launch(requirements=requirement, dependency_paths=paths)
    spec = driver(spec, marker)
    if shadow == "namespace_submodule":
        package = spec.code_root / "c4_namespace"
        package.mkdir()
        (package / "sdk.py").write_text("VALUE='candidate-namespace-shadow'\n")
    entry = spec.code_root / "nested/driver.py"
    entry.write_text(imports + entry.read_text())
    spec = replace(spec, source_revision=digest(spec.code_root))
    process = processes()
    with pytest.raises(RuntimeError) as caught:
        await getattr(process, operation)(spec)
    assert caught.value.reason_code == "DEPENDENCY_ORIGIN_INVALID"
    assert process.last_cleanup.exited
    if marker.exists():
        assert marker.read_text().splitlines() == ["import"]
        assert not alive(int(Path(str(marker) + ".pid").read_text()))


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["installed", "wheel"])
@pytest.mark.parametrize("header", ["Name", "Version"])
async def test_conflicting_singleton_metadata_is_rejected(
    launch,
    processes,
    tmp_path,
    source,
    header,
):
    site = tmp_path / "site"
    site.mkdir()
    conflicting = "c4-another-sdk" if header == "Name" else "0.1"
    if source == "installed":
        dist = metadata(site)
        path = dist / "METADATA"
        path.write_text(path.read_text() + f"{header}: {conflicting}\n")
    spec, marker = launch(
        requirements="c4-fixture-sdk==2.5\n",
        dependency_paths=(site,),
    )
    spec = driver(spec, marker)
    process = processes()
    if source == "installed":
        with pytest.raises(RuntimeError):
            await process.probe(spec)
        assert process.last_cleanup.exited
        assert not marker.exists()
    else:
        raw = (
            "Metadata-Version: 2.1\nName: c4-fixture-sdk\nVersion: 2.5\n"
            f"{header}: {conflicting}\n"
        ).encode()
        addition = wheel(
            tmp_path,
            extra={"c4_fixture_sdk-2.5.dist-info/METADATA": raw},
        )
        lease_environment(spec.dependency_paths)
        with pytest.raises(RuntimeError):
            await gate_api().prepare_shared_dependencies(
                process,
                spec,
                **preparation_inputs(spec),
                install_target=site,
                wheels=(addition,),
            )
        assert not list(site.iterdir())
