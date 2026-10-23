# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,unused-argument
"""Independent generic custody and preparation cleanup contracts."""

import asyncio
from dataclasses import replace
import importlib
import json
from pathlib import Path
import shutil
import sys
import threading
from types import SimpleNamespace

import pytest


@pytest.fixture
def ownership():
    return importlib.import_module("qwenpaw.plugins.ownership")


def receipt(api, **changes):
    return api.RuntimeStopReceipt(
        **{
            "quiescent": True,
            "detail": "resource stopped",
            "exited": True,
            "returncode": 0,
            "forced": False,
            "residual": (),
        }
        | changes,
    )


def reserve(api, owners, root, *, plugin="indexer", scope="workspace-a"):
    return owners.reserve(
        plugin,
        api.RuntimeKey("worker", "image-index", scope),
        root,
        instance_id="image-index:" + scope,
    )


@pytest.mark.parametrize("plugin", ["indexer", "another-plugin"])
def test_reserve_rejects_occupied_slot_across_plugins(
    ownership,
    tmp_path,
    plugin,
):
    owners = ownership.RuntimeOwners()
    held = reserve(ownership, owners, tmp_path)
    with pytest.raises(RuntimeError):
        reserve(ownership, owners, tmp_path / "candidate", plugin=plugin)
    assert owners.leases() == (held,)


def test_distinct_scopes_and_capabilities_have_independent_custody(
    ownership,
    tmp_path,
):
    owners = ownership.RuntimeOwners()
    one = reserve(ownership, owners, tmp_path, scope="workspace-a")
    two = reserve(ownership, owners, tmp_path, scope="workspace-b")
    other = owners.reserve(
        "another-plugin",
        ownership.RuntimeKey("memory", "image-index", "workspace-a"),
        tmp_path / "memory",
        instance_id="memory:workspace-a",
    )
    named = owners.reserve(
        "another-plugin",
        ownership.RuntimeKey("worker", "thumbnail", "workspace-a"),
        tmp_path / "thumbnail",
        instance_id="thumbnail:workspace-a",
    )
    assert owners.leases("indexer") == (one, two)
    assert owners.leases("another-plugin") == (other, named)
    assert owners.leases("absent") == ()
    assert len(owners.leases()) == 4


@pytest.mark.parametrize(
    "change",
    [
        {"plugin_id": "other"},
        {"instance_id": "different"},
        {"generation": 999},
        {"code_root": "other"},
        {"key": "other"},
    ],
)
def test_release_requires_every_lease_identity_field(
    ownership,
    tmp_path,
    change,
):
    owners = ownership.RuntimeOwners()
    held = reserve(ownership, owners, tmp_path)
    if "code_root" in change:
        change = {"code_root": tmp_path / "other"}
    if "key" in change:
        change = {
            "key": ownership.RuntimeKey("worker", "image-index", "other"),
        }
    assert not owners.release(replace(held, **change), receipt(ownership))
    assert owners.leases() == (held,)
    assert owners.release(held, receipt(ownership))
    assert owners.leases() == ()


@pytest.mark.asyncio
async def test_old_stop_callback_cannot_release_new_generation(
    ownership,
    tmp_path,
):
    owners = ownership.RuntimeOwners()
    old = reserve(ownership, owners, tmp_path / "old")

    async def old_stop():
        stopped = receipt(ownership)
        owners.release(old, stopped)
        return stopped

    owners.attach(old, old_stop)
    assert owners.release(old, receipt(ownership))
    new = reserve(ownership, owners, tmp_path / "new")
    assert new.instance_id == old.instance_id
    assert new.generation > old.generation
    await old_stop()
    assert owners.leases() == (new,)
    assert not owners.release(old, receipt(ownership))


@pytest.mark.parametrize(
    "evidence",
    [
        {"quiescent": False, "detail": "accepted work still pending"},
        {"exited": False, "returncode": None},
        {"residual": ("DESCENDANT_RUNNING",)},
    ],
)
def test_incomplete_stop_evidence_retains_code_root(
    ownership,
    tmp_path,
    evidence,
):
    owners = ownership.RuntimeOwners()
    held = reserve(ownership, owners, tmp_path / "staging")
    assert not owners.release(held, receipt(ownership, **evidence))
    assert owners.leases() == (held,)
    assert held.code_root == tmp_path / "staging"
    assert owners.release(held, receipt(ownership))


@pytest.mark.asyncio
async def test_opaque_resource_follows_exact_lease_until_confirmed_release(
    ownership,
    tmp_path,
):
    owners = ownership.RuntimeOwners()
    held = reserve(ownership, owners, tmp_path / "old")
    resource = object()

    async def stop():
        return receipt(ownership, residual=("BUSY",))

    owners.attach(held, stop, resource=resource)
    assert owners.resource(held) is resource
    await owners.stop_all("indexer")
    assert owners.resource(held) is resource
    assert owners.release(held, receipt(ownership))
    assert owners.resource(held) is None
    current = reserve(ownership, owners, tmp_path / "new")
    replacement = object()
    owners.attach(current, stop, resource=replacement)
    assert owners.resource(current) is replacement
    assert owners.resource(held) is None
    assert owners.resource(replace(current, generation=999)) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["exception", "residual"])
async def test_stop_all_keeps_failed_resource_and_retries_independently(
    ownership,
    tmp_path,
    failure,
):
    owners = ownership.RuntimeOwners()
    stuck = reserve(ownership, owners, tmp_path / "stuck")
    healthy = reserve(
        ownership,
        owners,
        tmp_path / "healthy",
        scope="workspace-b",
    )
    unrelated = reserve(
        ownership,
        owners,
        tmp_path / "unrelated",
        plugin="other",
        scope="workspace-c",
    )
    retry = False
    stopped = receipt(ownership, forced=True, returncode=-9)

    async def stop_stuck():
        if not retry:
            if failure == "exception":
                raise OSError("controlled current stop failure")
            return receipt(ownership, residual=("PROCESS_RUNNING",))
        return stopped

    async def stop_healthy():
        return receipt(ownership)

    owners.attach(stuck, stop_stuck)
    owners.attach(healthy, stop_healthy)
    reports = await owners.stop_all("indexer")
    assert len(reports) == 2
    assert any(not value.quiescent or value.residual for value in reports)
    if failure == "exception":
        assert any(
            "controlled current stop failure" in value.detail
            for value in reports
        )
    assert owners.leases() == (stuck, unrelated)
    retry = True
    assert await owners.stop_all("indexer") == (stopped,)
    assert owners.leases() == (unrelated,)


@pytest.mark.asyncio
async def test_cancelled_stop_cannot_forget_resource(ownership, tmp_path):
    owners = ownership.RuntimeOwners()
    held = reserve(ownership, owners, tmp_path)
    entered = asyncio.Event()
    finish = asyncio.Event()

    async def stop():
        entered.set()
        await finish.wait()
        return receipt(ownership)

    owners.attach(held, stop)
    stopping = asyncio.create_task(owners.stop_all("indexer"))
    await asyncio.wait_for(entered.wait(), 1)
    stopping.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stopping
    assert owners.leases() == (held,)
    finish.set()
    await owners.stop_all("indexer")
    assert owners.leases() == ()


@pytest.fixture
def loader(tmp_path, fresh_registry, monkeypatch):
    from qwenpaw.plugins.loader import PluginLoader

    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "working")
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_config_path",
        lambda: tmp_path / "config.json",
    )
    monkeypatch.delenv("QWENPAW_RUNTIME_PROVISIONER", raising=False)
    return PluginLoader([tmp_path / "plugins"])


def source(root, version="1.0.0"):
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "id": "indexer",
                "name": "Indexer",
                "version": version,
                "type": "general",
                "entry": {"backend": "main.py"},
            },
        ),
    )
    (root / "main.py").write_text("def register(api): pass\n")
    return root


@pytest.mark.asyncio
async def test_generic_custody_blocks_no_record_install_and_uninstall(
    ownership,
    loader,
    tmp_path,
):
    installed = source(loader.plugin_dirs[0] / "indexer")
    incoming = source(tmp_path / "incoming", "2.0.0")
    held = reserve(ownership, loader.registry.runtime_owners, installed)
    original = (installed / "plugin.json").read_bytes()
    assert loader.retains_preparation_source(installed.parent)
    assert not loader.retains_preparation_source(incoming)
    with pytest.raises(RuntimeError, match="needs_restart"):
        await loader.load_plugin_from_path(incoming, config={"enabled": False})
    report = await loader._uninstall_without_instance("indexer")
    assert not report.quiescent and report.needs_restart
    assert (installed / "plugin.json").read_bytes() == original
    assert incoming.is_dir()
    assert loader.registry.runtime_owners.leases() == (held,)


@pytest.mark.asyncio
@pytest.mark.parametrize("occupied", ["target", "staging"])
async def test_directory_swap_refuses_roots_held_by_another_plugin(
    ownership,
    loader,
    tmp_path,
    occupied,
):
    installed = source(loader.plugin_dirs[0] / "indexer")
    incoming = source(tmp_path / "incoming", "2.0.0")
    staging = installed.with_name("indexer.indexer.staging")
    root = (
        installed if occupied == "target" else staging
    ) / "active-component"
    root.mkdir(parents=True)
    marker = root / "in-use"
    marker.write_text("held by other plugin")
    held = reserve(
        ownership,
        loader.registry.runtime_owners,
        root,
        plugin="another-plugin",
    )
    original = (installed / "plugin.json").read_bytes()
    with pytest.raises(RuntimeError, match="needs_restart"):
        await loader._swap_plugin_dir("indexer", installed, incoming)
    assert (installed / "plugin.json").read_bytes() == original
    assert marker.read_text() == "held by other plugin"
    assert incoming.is_dir()
    assert loader.registry.runtime_owners.leases() == (held,)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled", [False, True])
async def test_swap_excludes_new_root_custody_until_filesystem_thread_settles(
    ownership,
    loader,
    tmp_path,
    monkeypatch,
    cancelled,
):
    installed = source(loader.plugin_dirs[0] / "indexer")
    incoming = source(tmp_path / "incoming", "2.0.0")
    (installed / "code.txt").write_text("old")
    (incoming / "code.txt").write_text("new")
    entered = asyncio.Event()
    proceed = threading.Event()
    loop = asyncio.get_running_loop()
    copytree = shutil.copytree

    def blocked_copy(src, dst, *args, **kwargs):
        if Path(src) == incoming:
            loop.call_soon_threadsafe(entered.set)
            assert proceed.wait(5), "filesystem thread was not released"
        return copytree(src, dst, *args, **kwargs)

    monkeypatch.setattr(shutil, "copytree", blocked_copy)
    swapping = asyncio.create_task(
        loader._swap_plugin_dir("indexer", installed, incoming),
    )
    try:
        await asyncio.wait_for(entered.wait(), 1)
        with pytest.raises(RuntimeError):
            reserve(
                ownership,
                loader.registry.runtime_owners,
                installed,
                plugin="another-plugin",
            )
        if cancelled:
            swapping.cancel()
            await asyncio.sleep(0)
            assert not swapping.done()
            with pytest.raises(RuntimeError):
                reserve(
                    ownership,
                    loader.registry.runtime_owners,
                    installed,
                    plugin="another-plugin",
                )
        assert (installed / "code.txt").read_text() == "old"
    finally:
        proceed.set()
        if swapping.cancelling():
            with pytest.raises(asyncio.CancelledError):
                await swapping
        else:
            await swapping
    # A reservation cannot survive while its source changes underneath it.
    assert loader.registry.runtime_owners.leases() == ()
    held = reserve(
        ownership,
        loader.registry.runtime_owners,
        installed,
        plugin="another-plugin",
    )
    assert (held.code_root / "code.txt").read_text() == (
        "old" if cancelled else "new"
    )
    if cancelled:
        from qwenpaw.plugins.updates import marker_path

        assert not marker_path("indexer").exists()
        assert not installed.with_name("indexer.indexer.staging").exists()
    assert loader.registry.runtime_owners.release(held, receipt(ownership))


@pytest.mark.asyncio
async def test_nested_mutation_keeps_outer_exclusion_and_refuses_other_tasks(
    ownership,
    tmp_path,
):
    owners = ownership.RuntimeOwners()
    root = tmp_path / "source"

    async def compete():
        with owners.mutation(root / "nested"):
            pytest.fail("independent task entered an overlapping mutation")

    with owners.mutation(root):
        with owners.mutation(root / "nested"):
            with pytest.raises(RuntimeError):
                reserve(ownership, owners, root)
        with pytest.raises(RuntimeError):
            await asyncio.create_task(compete())
        with pytest.raises(RuntimeError):
            reserve(ownership, owners, root)
        independent = reserve(ownership, owners, tmp_path / "unrelated")
        assert owners.release(independent, receipt(ownership))
    held = reserve(ownership, owners, root)
    assert owners.release(held, receipt(ownership))


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["residual", "exception"])
async def test_shutdown_finds_orphan_generic_resource_and_retains_failed_stop(
    ownership,
    loader,
    tmp_path,
    failure,
):
    from qwenpaw.plugins.lifecycle import UnloadMode

    code = source(loader.plugin_dirs[0] / "indexer")
    marker = tmp_path / "resource-running"
    marker.touch()
    owners = loader.registry.runtime_owners
    held = reserve(ownership, owners, code)
    retry = False

    async def stop():
        if not retry:
            if failure == "exception":
                raise OSError("orphan stop failed")
            return receipt(ownership, residual=("PROCESS_RUNNING",))
        marker.unlink()
        return receipt(ownership)

    owners.attach(held, stop)
    assert loader.get_loaded_plugin("indexer") is None
    assert loader.lifecycle.get_instance("indexer") is None
    reports = await loader.lifecycle.unload_all(UnloadMode.SHUTDOWN)
    assert len(reports) == 1 and reports[0].plugin_id == "indexer"
    assert not reports[0].quiescent and reports[0].needs_restart
    assert marker.exists() and owners.leases() == (held,)
    assert code.exists() and loader.retains_preparation_source(code)
    retry = True
    reports = await loader.lifecycle.unload_all(UnloadMode.SHUTDOWN)
    assert len(reports) == 1 and reports[0].quiescent
    assert not reports[0].needs_restart
    assert not marker.exists() and owners.leases() == ()
    assert code.exists()


@pytest.mark.asyncio
async def test_orphan_shutdown_continues_after_independent_preparation_failure(
    ownership,
    loader,
    tmp_path,
):
    from qwenpaw.plugins.lifecycle import UnloadMode

    owners = loader.registry.runtime_owners
    preparation = owners.reserve(
        "indexer",
        ownership.RuntimeKey("preparation", "indexer", "global"),
        tmp_path / "staging",
        instance_id="probe:indexer",
    )
    worker = reserve(ownership, owners, tmp_path / "worker")
    calls = []

    async def stop_preparation():
        calls.append("preparation")
        return receipt(
            ownership,
            quiescent=False,
            exited=False,
            residual=("PREPARATION_RUNNING",),
        )

    async def stop_worker():
        calls.append("worker")
        return receipt(ownership)

    owners.attach(preparation, stop_preparation)
    owners.attach(worker, stop_worker)
    assert loader.get_loaded_plugin("indexer") is None
    assert loader.lifecycle.get_instance("indexer") is None
    reports = await loader.lifecycle.unload_all(UnloadMode.SHUTDOWN)
    assert "worker" in calls
    assert calls.count("worker") == calls.count("preparation") == 1
    assert owners.leases("indexer") == (preparation,)
    assert len(reports) == 1
    assert not reports[0].quiescent and reports[0].needs_restart
    assert loader.retains_preparation_source(tmp_path / "staging")


def test_preparation_constructor_failure_releases_only_unstarted_resource(
    ownership,
    loader,
    tmp_path,
):
    from qwenpaw.plugins.execution import StopResult

    def fail_before_resource():
        raise ValueError("constructor failed before launch")

    with pytest.raises(ValueError, match="constructor failed"):
        loader._own_preparation(
            "indexer",
            fail_before_resource,
            tmp_path,
            instance_id="dependency:indexer",
        )
    assert loader.registry.runtime_owners.leases("indexer") == ()

    class Unstarted:
        async def stop(self):
            return StopResult(True, None, False)

    process, held = loader._own_preparation(
        "indexer",
        Unstarted,
        tmp_path,
        instance_id="dependency:indexer",
    )
    assert isinstance(process, Unstarted)
    assert held.key == ownership.RuntimeKey("preparation", "indexer", "global")
    assert loader.registry.runtime_owners.leases("indexer") == (held,)
    assert loader.registry.runtime_owners.release(held, receipt(ownership))


@pytest.mark.asyncio
@pytest.mark.parametrize("stop_failure", [None, "residual", "exception"])
@pytest.mark.parametrize("combined", [False, True])
async def test_python_audit_uses_fresh_stop_evidence_before_releasing_preparation(  # noqa: E501
    ownership,
    loader,
    tmp_path,
    monkeypatch,
    stop_failure,
    combined,
):
    from packaging.markers import default_environment
    from qwenpaw.plugins.execution import StopResult
    from qwenpaw.plugins.execution.dependencies import DependencySnapshot

    root = tmp_path / "candidate"
    root.mkdir()
    declaration_root = tmp_path / "combined" if combined else root
    declaration_root.mkdir(exist_ok=True)
    requirements = declaration_root / "requirements.txt"
    requirements.write_text("")
    owners = loader.registry.runtime_owners
    snapshot = DependencySnapshot(
        sys.executable,
        sys.prefix,
        (),
        default_environment(),
        (),
        {},
        dependency_sites=(),
    )
    generations = []
    staged_requirements = []
    source = {"source_path": root} if combined else {}

    class AuditProcess:
        def __init__(self):
            # Old success is deliberately insufficient for this cleanup.
            self.last_cleanup = StopResult(True, 0, False)

        async def audit(self, spec):
            (held,) = owners.leases("indexer")
            assert held.key == ownership.RuntimeKey(
                "preparation",
                "indexer",
                "global",
            )
            assert (
                held.code_root == root and held.generation == spec.generation
            )
            assert held.instance_id == spec.instance_id == "dependency:indexer"
            assert owners.resource(held) is self
            assert loader.retains_preparation_source(root)
            staged_requirements.append(spec.requirements_path)
            assert spec.requirements_path.read_text() == ""
            if combined:
                assert spec.code_root != root
                assert spec.requirements_path.parent == spec.code_root
                assert spec.requirements_path != requirements
            generations.append(spec.generation)
            self.dependency_observer(snapshot)
            return SimpleNamespace(snapshot=snapshot)

        async def stop(self):
            if stop_failure == "exception":
                raise OSError("current stop evidence unavailable")
            if stop_failure == "residual":
                return StopResult(False, None, True, ("PROCESS_RUNNING",))
            return StopResult(True, 0, False)

    monkeypatch.setattr(
        "qwenpaw.plugins.execution.PluginProcess",
        AuditProcess,
    )
    monkeypatch.setattr("qwenpaw.plugins.loader._is_frozen", lambda: False)
    if stop_failure:
        with pytest.raises(RuntimeError, match="needs_restart"):
            await loader._prepare_python_dependencies(
                requirements,
                "indexer",
                **source,
            )
        (held,) = owners.leases("indexer")
        assert held.code_root == root
        assert loader.retains_preparation_source(root)
        if combined:
            requirements.unlink()
            assert staged_requirements[0].is_file()
        stop_failure = None
        await loader._stop_preparation("indexer")
        if combined:
            assert not staged_requirements[0].parent.exists()
            requirements.write_text("")
        result = await loader._prepare_python_dependencies(
            requirements,
            "indexer",
            **source,
        )
        assert result.already_satisfied
        admissions = list(dict.fromkeys(generations))
        assert len(admissions) == 2 and admissions[1] > admissions[0]
    else:
        result = await loader._prepare_python_dependencies(
            requirements,
            "indexer",
            **source,
        )
        assert result.already_satisfied
    assert owners.leases("indexer") == ()
    if combined:
        assert all(not path.parent.exists() for path in staged_requirements)


@pytest.mark.asyncio
async def test_cancelled_python_audit_retains_resource_until_stop_retry(
    ownership,
    loader,
    tmp_path,
    monkeypatch,
):
    from qwenpaw.plugins.execution import StopResult

    root = tmp_path / "staging"
    root.mkdir()
    requirements = root / "requirements.txt"
    requirements.write_text("")
    entered = asyncio.Event()
    release = False
    owners = loader.registry.runtime_owners

    class StartingProcess:
        last_cleanup = None

        async def audit(self, spec):
            (held,) = owners.leases("indexer")
            assert (
                held.code_root == root and held.generation == spec.generation
            )
            entered.set()
            await asyncio.Future()

        async def stop(self):
            return (
                StopResult(True, 0, False)
                if release
                else StopResult(
                    False,
                    None,
                    True,
                    ("STARTUP_RESOURCE_RUNNING",),
                )
            )

    monkeypatch.setattr(
        "qwenpaw.plugins.execution.PluginProcess",
        StartingProcess,
    )
    monkeypatch.setattr("qwenpaw.plugins.loader._is_frozen", lambda: False)
    preparing = asyncio.create_task(
        loader._prepare_python_dependencies(requirements, "indexer"),
    )
    await asyncio.wait_for(entered.wait(), 1)
    preparing.cancel()
    with pytest.raises((asyncio.CancelledError, RuntimeError)):
        await preparing
    (held,) = owners.leases("indexer")
    assert held.code_root == root and loader.retains_preparation_source(root)
    release = True
    await owners.stop_all("indexer")
    assert owners.leases() == ()
