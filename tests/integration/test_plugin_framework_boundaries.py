# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""One real non-Channel adapter through the delivered framework boundaries."""

from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys

import psutil
import pytest
import pytest_asyncio

import qwenpaw
from qwenpaw.plugins.lifecycle import UnloadMode
from qwenpaw.plugins.ownership import RuntimeStopReceipt
from qwenpaw.plugins.registry import PluginRegistry
from qwenpaw.plugins.settings import persist_plugin_settings
from qwenpaw.plugins.updates import marker_path
from tests.fixtures.plugin_execution import non_channel_backend as fixture
from tests.integration.test_c7_released_process import (
    _c7_extracted_release,
)

c7_extracted_release = _c7_extracted_release
ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "tests/fixtures/plugin_execution/non_channel_backend.py"


def alive(pid):
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def lives(host):
    return tuple(
        sorted(
            (
                lease
                for lease in host.registry.runtime_owners.leases(fixture.KEY)
                if lease.key.kind == fixture.KIND
            ),
            key=lambda lease: lease.key.scope_id,
        ),
    )


async def probes(host):
    return [
        await host.registry.runtime_owners.resource(lease).process.call(
            "fixture.probe",
        )
        for lease in lives(host)
    ]


def assert_clean(host):
    assert not host.registry.runtime_owners.leases(fixture.KEY)
    assert not host.registry.dependency_usage.snapshot(None).uses
    if host.backend.ledger.exists():
        assert all(
            not alive(int(pid))
            for pid in host.backend.ledger.read_text().splitlines()
        )


@pytest_asyncio.fixture
async def host(tmp_path, monkeypatch):
    assert Path(qwenpaw.__file__).resolve().is_relative_to(ROOT / "src")
    monkeypatch.setattr(PluginRegistry, "_instance", None)
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_config_path",
        lambda: tmp_path / "config.json",
    )
    value = fixture.host(tmp_path, ROOT / "src", PluginRegistry())
    yield value
    for lease in value.registry.runtime_owners.leases():
        resource = value.registry.runtime_owners.resource(lease)
        if resource is not None:
            resource.blocked = False
    await value.registry.runtime_owners.stop_all(fixture.KEY)
    await value.loader.lifecycle.unload_all(UnloadMode.UNLOAD)
    assert_clean(value)


async def install(host, *, enabled=True):
    persist_plugin_settings(
        fixture.KEY,
        enabled=enabled,
        config={"label": "old"},
    )
    addition = fixture.wheel(host.root)
    record = await host.loader.load_plugin_from_path(
        fixture.source(host.root / "candidate"),
        config={"enabled": enabled, "label": "old"},
        wheels=(addition,),
    )
    if not enabled:
        record = await host.loader.repair_dependencies(
            fixture.KEY,
            wheels=(addition,),
        )
    return record


async def assert_live(host, record, *, label="old", version="1.0.0"):
    leases, results = lives(host), await probes(host)
    assert len(leases) == len(results) == 2
    assert {lease.key.scope_id for lease in leases} == {"alpha", "beta"}
    assert len({result["pid"] for result in results}) == 2
    for lease, result in zip(leases, results):
        assert alive(result["pid"])
        assert result["identity"] == {
            "plugin_id": fixture.KEY,
            "instance_id": lease.instance_id,
            "generation": lease.generation,
        }
        assert result["isolated"] == 1 and result["blocked"] == []
        assert Path(result["source"]) == record.source_path / "worker.py"
        assert Path(result["support"]).is_relative_to(host.backend.support)
        assert Path(result["sdk"]).is_relative_to(host.backend.site)
        assert result["config"]["label"] == label
        assert result["config"]["version"] == version
        assert (
            host.registry.dependency_usage._bindings[lease][0]
            is record.instance.token
        )
    assert "f4_fixture_sdk" not in sys.modules
    runtime = [
        use
        for use in host.registry.dependency_usage.snapshot(None).uses
        if use.origin == "runtime"
    ]
    assert {(use.instance_id, use.generation) for use in runtime} == {
        (lease.instance_id, lease.generation) for lease in leases
    }
    assert all(use.snapshot is not None and use.active for use in runtime)
    return results


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["install", "repair", "load"])
@pytest.mark.parametrize("owns_environment", [False, True])
async def test_non_channel_dependency_owner_controls_real_publication(
    host,
    monkeypatch,
    operation,
    owns_environment,
):
    """All public preparation paths respect the delegate's write authority."""
    monkeypatch.setattr(
        host.loader.lifecycle.delegate,
        "owns_dependency_env",
        lambda _plugin_id: owns_environment,
    )
    persist_plugin_settings(
        fixture.KEY,
        enabled=operation != "repair",
        config={"label": "old"},
    )
    source = fixture.source(
        (host.loader.plugin_dirs[0] / fixture.KEY)
        if operation == "load"
        else host.root / "candidate",
    )
    addition = fixture.wheel(host.root)
    if operation == "repair":
        record = await host.loader.load_plugin_from_path(
            source,
            config={"enabled": False, "label": "old"},
        )
        assert record.status == "inactive"
        source = record.source_path
    source_before, site_before, loaded_before = (
        fixture.digest(source),
        fixture.digest(host.backend.site),
        host.loader.get_loaded_plugin(fixture.KEY),
    )
    error = None
    try:
        if operation == "install":
            record = await host.loader.load_plugin_from_path(
                source,
                config={"enabled": True, "label": "old"},
                wheels=(addition,),
            )
        elif operation == "repair":
            record = await host.loader.repair_dependencies(
                fixture.KEY,
                wheels=(addition,),
            )
        else:
            # This backend's acquisition is a controlled local wheel,
            # published by the real shared Gate rather than an index client.
            host.backend.available_wheels = (addition,)
            _, manifest = host.loader.read_source_manifest(source)
            record = await host.loader.load_plugin(
                manifest,
                source,
                {"enabled": True, "label": "old"},
                allow_install=True,
            )
    except RuntimeError as exc:
        error = exc
    assert fixture.digest(source) == source_before
    if owns_environment:
        assert error is None
        assert (host.backend.site / "f4_fixture_sdk.py").read_text() == (
            "VERSION = '1.0'\n"
        )
        assert fixture.digest(host.backend.site) != site_before
        if operation == "repair":
            assert record.status == "inactive" and not record.enabled
            assert_clean(host)
        else:
            assert record.status == "active"
            await assert_live(host, record)
        return
    assert fixture.digest(host.backend.site) == site_before
    assert not (host.backend.site / "f4_fixture_sdk.py").exists() and not (
        host.backend.ledger.exists()
    )
    assert not any(event[0] == "definition" for event in host.backend.events)
    assert_clean(host)
    if operation == "load":
        assert error is None and record.status == "failed"
        assert fixture.SDK in " ".join(record.diagnostics)
        assert host.loader.lifecycle.get_instance(fixture.KEY).state.value == (
            "failed"
        )
    else:
        assert error is not None and fixture.SDK in str(error)
        if operation == "install":
            assert host.loader.get_loaded_plugin(fixture.KEY) is None
            assert not (host.loader.plugin_dirs[0] / fixture.KEY).exists()
        else:
            assert host.loader.get_loaded_plugin(fixture.KEY) is loaded_before
            assert record.status == "inactive" and not record.enabled


@pytest.mark.asyncio
async def test_non_channel_foreign_environment_allows_existing_evidence(
    host,
    monkeypatch,
):
    record = await install(host, enabled=False)
    source_before = fixture.digest(record.source_path)
    site_before = fixture.digest(host.backend.site)
    monkeypatch.setattr(
        host.loader.lifecycle.delegate,
        "owns_dependency_env",
        lambda _plugin_id: False,
    )
    # A publishable acquisition offer must remain unused while auditing v1.
    host.backend.available_wheels = (fixture.wheel(host.root, "2.0"),)
    record = await host.loader.lifecycle.set_enabled(fixture.KEY, True)
    assert record.status == "active"
    await assert_live(host, record)
    report = await host.loader.lifecycle.update_config(
        fixture.KEY,
        {"label": "new"},
    )
    assert report.ok, report.errors
    record = host.loader.get_loaded_plugin(fixture.KEY)
    await assert_live(host, record, label="new")
    assert fixture.digest(record.source_path) == source_before
    assert fixture.digest(host.backend.site) == site_before
    assert not list(host.backend.site.glob("*2.0.dist-info"))


@pytest.mark.asyncio
@pytest.mark.parametrize("authority", ["delegate", "explicit"])
async def test_non_channel_foreign_environment_reload_preserves_old_custody(
    host,
    monkeypatch,
    authority,
):
    old = await install(host)
    original = await assert_live(host, old)
    old_leases = lives(host)
    source_before = fixture.digest(old.source_path)
    site_before = fixture.digest(host.backend.site)
    candidate = fixture.source(
        host.root / "foreign-reload",
        "2.0.0",
        requirement="==2.0",
    )
    candidate_before = fixture.digest(candidate)
    addition = fixture.wheel(host.root, "2.0")
    if authority == "delegate":
        monkeypatch.setattr(
            host.loader.lifecycle.delegate,
            "owns_dependency_env",
            lambda _plugin_id: False,
        )
        host.backend.available_wheels = (addition,)
        report = await host.loader.lifecycle.reload(
            fixture.KEY,
            new_source=candidate,
            allow_install=True,
        )
    else:
        async with host.loader.plugin_lifecycle(fixture.KEY):
            report = await host.loader.reload_plugin_unlocked(
                fixture.KEY,
                new_source=candidate,
                allow_install=True,
                owns_dependency_env=False,
                wheels=(addition,),
            )
    assert not report.ok and report.unchanged and not report.needs_restart
    assert fixture.SDK in " ".join(report.errors)
    assert host.loader.get_loaded_plugin(fixture.KEY) is old
    assert lives(host) == old_leases
    assert await probes(host) == original
    assert fixture.digest(old.source_path) == source_before
    assert fixture.digest(candidate) == candidate_before
    assert fixture.digest(host.backend.site) == site_before
    assert not marker_path(fixture.KEY).exists()
    assert not any(
        lease.key.kind == "preparation"
        for lease in host.registry.runtime_owners.leases(fixture.KEY)
    )


@pytest.mark.asyncio
async def test_non_channel_install_enable_ipc_config_disable_two_scopes(host):
    record = await install(host, enabled=False)
    assert record.status == "inactive" and not record.enabled
    assert not host.backend.ledger.exists()
    assert not lives(host) and not host.backend.events.count(
        ("definition", record.source_path),
    )
    assert host.loader.lifecycle.delegate.owns_commit(fixture.KEY)
    assert host.loader.lifecycle.delegate.owns_dependency_env(fixture.KEY)
    assert record.source_path != host.root / "candidate"
    before_discovery = list(host.backend.events)
    assert [
        manifest.id for manifest, _path in host.loader.discover_plugins()
    ] == [fixture.KEY]
    assert host.backend.events == before_discovery
    assert not host.backend.ledger.exists()

    record = await host.loader.lifecycle.set_enabled(fixture.KEY, True)
    assert record.status == "active"
    results = await assert_live(host, record)
    old_leases = lives(host)
    first = host.registry.runtime_owners.resource(old_leases[0]).process
    assert (
        await first.call("fixture.reverse", {"indexed": 7})
        == results[0]["identity"]
    )
    assert host.backend.notices == [{"indexed": 7}]
    binding = record.backend_binding

    report = await host.loader.lifecycle.update_config(
        fixture.KEY,
        {"label": "new"},
    )
    assert report.ok, report.errors
    record = host.loader.get_loaded_plugin(fixture.KEY)
    assert record.backend_binding is binding
    await assert_live(host, record, label="new")
    assert all(
        new.generation == old.generation + 1
        for old, new in zip(old_leases, lives(host))
    )
    assert all(not alive(result["pid"]) for result in results)
    assert (
        await host.loader.lifecycle.set_enabled(fixture.KEY, False)
    ).quiescent
    assert_clean(host)

    record = await host.loader.lifecycle.set_enabled(fixture.KEY, True)
    await assert_live(host, record, label="new")
    assert (
        await host.loader.lifecycle.unload(fixture.KEY, UnloadMode.UNINSTALL)
    ).quiescent
    assert not record.source_path.exists()
    assert (host.backend.site / "f4_fixture_sdk.py").exists()
    assert_clean(host)


@pytest.mark.asyncio
async def test_non_channel_probe_rejection_and_post_commit_start_recovery(
    host,
    monkeypatch,
):
    old = await install(host)
    original = await assert_live(host, old)
    installed_digest = fixture.digest(old.source_path)
    failed = fixture.source(host.root / "bad-start", "2.0.0", failure="start")
    report = await host.loader.lifecycle.reload(fixture.KEY, new_source=failed)
    assert not report.ok and not report.needs_restart
    assert "FIXTURE_START_FAILED" in " ".join(report.errors)
    restored = host.loader.get_loaded_plugin(fixture.KEY)
    assert restored.status == "active"
    assert restored.backend_binding.backend is host.backend
    assert restored.source_path == old.source_path
    assert fixture.digest(restored.source_path) == installed_digest
    current = await assert_live(host, restored)
    assert all(not alive(result["pid"]) for result in original)
    ledger = [int(pid) for pid in host.backend.ledger.read_text().splitlines()]
    assert (
        len(ledger) >= 6
    ), "Candidate never reached both real business starts"
    assert all(
        not alive(pid)
        for pid in ledger
        if pid not in {row["pid"] for row in current}
    )
    assert not marker_path(fixture.KEY).exists()
    assert not list(restored.source_path.parent.glob("*.staging"))
    declarations = [
        use
        for use in host.registry.dependency_usage.snapshot(None).uses
        if use.origin == "declaration"
    ]
    assert len(declarations) == 1
    assert (
        declarations[0].source_revision
        == restored.backend_binding.description.source_identity
    )
    old_token = restored.instance.token
    rejected = fixture.source(
        host.root / "bad-probe",
        "2.0.0",
        failure="probe",
    )
    report = await host.loader.lifecycle.reload(
        fixture.KEY,
        new_source=rejected,
    )
    assert not report.ok and report.unchanged and not report.needs_restart
    assert "ENTRYPOINT" in " ".join(report.errors)
    assert host.loader.get_loaded_plugin(fixture.KEY) is restored
    assert restored.instance.token is old_token
    assert await probes(host) == current

    # Same C4 cleanup injection, now asserting the real Loader report boundary.
    from qwenpaw.plugins.execution import StopResult

    cleanup = fixture.PluginProcess._cleanup_owned

    async def residual(process, budget, *, graceful):
        if process._spec.code_root == rejected:
            return StopResult(False, None, True, ("F4_INSPECTION_RESIDUAL",))
        return await cleanup(process, budget, graceful=graceful)

    with monkeypatch.context() as control:
        control.setattr(fixture.PluginProcess, "_cleanup_owned", residual)
        report = await host.loader.lifecycle.reload(
            fixture.KEY,
            new_source=rejected,
        )
        assert not report.ok and report.unchanged and report.needs_restart
        retained = tuple(
            lease
            for lease in host.registry.runtime_owners.leases(fixture.KEY)
            if lease.key.kind == "preparation"
        )
        assert retained and all(
            lease.code_root == rejected for lease in retained
        )
        assert host.loader.retains_preparation_source(rejected)
        assert await probes(host) == current
    for lease in retained:
        receipt = await host.registry.runtime_owners.stop(lease)
        assert receipt.stopped
    assert not host.loader.retains_preparation_source(rejected)


@pytest.mark.asyncio
async def test_non_channel_active_dependency_conflict_preserves_shared_site(
    host,
):
    record = await install(host)
    original = await assert_live(host, record)
    bytes_before = fixture.digest(host.backend.site)
    candidate = fixture.source(
        host.root / "sdk-v2",
        "2.0.0",
        requirement="==2.0",
    )
    with pytest.raises(RuntimeError) as caught:
        await host.loader.load_plugin_from_path(
            candidate,
            force=True,
            wheels=(fixture.wheel(host.root, "2.0"),),
        )
    assert "DEPENDENCY_RESTART_REQUIRED" in str(
        caught.value,
    ) or fixture.SDK + "==2.0" in str(caught.value)
    assert fixture.digest(host.backend.site) == bytes_before
    assert host.loader.get_loaded_plugin(fixture.KEY) is record
    assert await probes(host) == original
    await assert_live(host, record)
    assert not marker_path(fixture.KEY).exists()
    assert not list(host.backend.site.glob("*2.0.dist-info"))


@pytest.mark.asyncio
async def test_non_channel_failed_stop_keeps_exact_custody_until_retry(host):
    record = await install(host)
    first = lives(host)[0]
    resource = host.registry.runtime_owners.resource(first)
    pid = (await resource.process.call("fixture.probe"))["pid"]
    resource.blocked = True
    report = await host.loader.lifecycle.unload(
        fixture.KEY,
        UnloadMode.UNINSTALL,
    )
    assert not report.quiescent and report.needs_restart
    assert alive(pid) and record.source_path.exists()
    assert first in host.registry.runtime_owners.leases(fixture.KEY)
    assert not host.registry.runtime_owners.release(
        replace(first, generation=first.generation + 1),
        RuntimeStopReceipt(True),
    )
    assert not host.registry.runtime_owners.release(
        first,
        RuntimeStopReceipt(True, residual=("still-held",)),
    )
    uses = host.registry.dependency_usage.snapshot(None).uses
    assert any(
        use.active
        and use.instance_id == first.instance_id
        and use.generation == first.generation
        for use in uses
    )
    assert (
        host.loader.lifecycle.get_instance(fixture.KEY).state.value == "failed"
    )
    rejected = fixture.source(
        host.root / "failed-stop-candidate",
        "2.0.0",
        failure="probe",
    )
    blocked = await host.loader.lifecycle.reload(
        fixture.KEY,
        new_source=rejected,
    )
    assert not blocked.ok and blocked.needs_restart
    assert alive(pid) and first in host.registry.runtime_owners.leases(
        fixture.KEY,
    )

    resource.blocked = False
    report = await host.loader.lifecycle.unload(
        fixture.KEY,
        UnloadMode.UNINSTALL,
    )
    assert report.quiescent, report.errors
    assert not alive(pid) and not record.source_path.exists()
    assert_clean(host)


@pytest.mark.asyncio
async def test_non_channel_unknown_adapter_and_missing_real_evidence_rejected(
    host,
    monkeypatch,
):
    candidate = fixture.source(host.root / "unknown")
    from qwenpaw.plugins.loader import PluginLoader

    other = PluginLoader([host.root / "other"])
    with pytest.raises(ValueError, match="No descriptor backend registered"):
        await other.load_plugin_from_path(candidate)
    assert not host.backend.ledger.exists()

    await install(host, enabled=False)

    async def missing(_description):
        return None

    monkeypatch.setattr(host.backend, "audit_dependencies", missing)
    record = await host.loader.lifecycle.set_enabled(fixture.KEY, True)
    assert record.status == "failed"
    assert "DEPENDENCY_PLAN_UNVERIFIED" in " ".join(record.diagnostics)
    assert not host.backend.ledger.exists()
    assert not any(event[0] == "definition" for event in host.backend.events)
    assert_clean(host)


def test_extracted_wheel_non_channel_loader_child_chain(
    c7_extracted_release,
    tmp_path,
):
    site = c7_extracted_release / "src"
    for name in (
        "execution_backend",
        "ownership",
        "dependency_usage",
        "python_backend",
    ):
        assert (site / "qwenpaw/plugins" / f"{name}.py").is_file()
    script = """import asyncio, importlib, pathlib, sys
site, helper, root = map(pathlib.Path, sys.argv[1:])
sys.path.insert(0, str(site.resolve()))
sys.path.append(str(helper.parent))
import qwenpaw
assert pathlib.Path(qwenpaw.__file__).resolve().is_relative_to(site.resolve())
fixture = importlib.import_module("non_channel_backend")
from qwenpaw.plugins.registry import PluginRegistry
from qwenpaw.plugins.lifecycle import UnloadMode
async def run():
    host = fixture.host(root, site, PluginRegistry())
    try:
        record = await host.loader.load_plugin_from_path(
            fixture.source(root / "candidate"), config={"label": "release"},
            wheels=(fixture.wheel(root),),
        )
        assert record.status == "active"
        leases = host.registry.runtime_owners.leases(fixture.KEY)
        assert {lease.key.scope_id for lease in leases} == {"alpha", "beta"}
        pids = []
        for lease in leases:
            process = host.registry.runtime_owners.resource(lease).process
            probe = await process.call("fixture.probe")
            pids.append(probe["pid"])
            origin = pathlib.Path(probe["support"])
            assert origin.is_relative_to(site.resolve())
            worker = record.source_path / "worker.py"
            assert pathlib.Path(probe["source"]) == worker
            assert probe["isolated"] == 1 and not probe["blocked"]
            reverse = await process.call("fixture.reverse", {"release": True})
            assert reverse == probe["identity"]
        assert len(set(pids)) == 2
        report = await host.loader.lifecycle.update_config(
            fixture.KEY, {"label": "release-new"},
        )
        assert report.ok, report.errors
    finally:
        reports = await host.loader.lifecycle.unload_all(UnloadMode.UNLOAD)
        assert all(report.quiescent for report in reports)
        assert not host.registry.runtime_owners.leases()
        assert not host.registry.dependency_usage.snapshot(None).uses
asyncio.run(run())
"""
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            script,
            str(site),
            str(HELPER),
            str(tmp_path),
        ],
        cwd=tmp_path,
        env={
            **os.environ,
            "PIP_NO_INDEX": "1",
            "QWENPAW_WORKING_DIR": str(tmp_path / "working"),
            "QWENPAW_SECRET_DIR": str(tmp_path / "secret"),
            "QWENPAW_CHANNEL_PRESET": "light",
            "QWENPAW_CHANNEL_BLOCK_BUILTINS": "1",
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
