# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-argument,too-many-statements
"""Generic shared-environment admission and publication regressions."""

import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
import hashlib
from importlib import metadata
import inspect
import json
from pathlib import Path
import sys
import sysconfig
import threading
from types import SimpleNamespace
import zipfile

import pytest
from packaging.markers import default_environment

from qwenpaw.plugins import dependency_gate as gate
from qwenpaw.plugins import install_lock
from qwenpaw.plugins.dependency_usage import (
    DependencyDeclaration,
    DependencyEnvironment,
    DependencyUsageRegistry,
)
from qwenpaw.plugins.execution.dependencies import DependencySnapshot
from qwenpaw.plugins.execution.dependencies import repair_marker
from qwenpaw.plugins.ownership import (
    RuntimeKey,
    RuntimeOwners,
)

ROOT = Path(__file__).resolve().parents[3]


def prepare_api():
    return gate.prepare_shared_dependencies


def coordinator():
    return install_lock.environment_coordinator


def evidence(
    site,
    *,
    versions=None,
    python_version="3.12",
    package_sites=None,
):
    site = Path(site).resolve()
    sites = tuple(
        str(Path(path).resolve()) for path in (package_sites or (site,))
    )
    return DependencySnapshot.from_mapping(
        {
            "executable": sys.executable,
            "prefix": str(site.parent),
            "sites": [*sites, sysconfig.get_path("stdlib"), str(ROOT / "src")],
            "dependency_sites": list(sites),
            "marker_environment": {
                **default_environment(),
                "python_version": python_version,
            },
            "supported_tags": ["py3-none-any"],
            "distributions": {
                name: {
                    "version": version,
                    "metadata_path": str(
                        site / (name.replace("-", "_") + ".dist-info"),
                    ),
                    "requires_dist": [],
                    "top_level": [name.replace("-", "_")],
                }
                for name, version in (versions or {}).items()
            },
        },
    )


class Audit:
    """Complete snapshots stand in for child inspection, never the Gate."""

    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.entered = asyncio.Event()
        self.calls = 0

    async def audit(self, spec):
        assert spec.identity == "opaque-generic-spec"
        self.calls += 1
        self.entered.set()
        rows = dict(self.snapshot.distributions)
        for site in self.snapshot.dependency_sites or ():
            for dist in metadata.distributions(path=[site]):
                name = dist.metadata["Name"].lower().replace("_", "-")
                rows[name] = {
                    "version": dist.version,
                    "metadata_path": str(dist._path),
                    "requires_dist": tuple(dist.requires or ()),
                    "top_level": tuple(
                        (dist.read_text("top_level.txt") or "").splitlines(),
                    ),
                }
        return SimpleNamespace(
            snapshot=replace(self.snapshot, distributions=rows),
        )


def materialize_host_metadata(snapshot):
    """Give imported host evidence an honest metadata-only refresh source."""
    for name, row in snapshot.distributions.items():
        info = Path(row["metadata_path"])
        info.mkdir(parents=True, exist_ok=True)
        (info / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {row['version']}\n"
            + "".join(
                f"Requires-Dist: {value}\n" for value in row["requires_dist"]
            ),
        )
        (info / "top_level.txt").write_text("\n".join(row["top_level"]) + "\n")


def inputs(tmp_path, requirements="", snapshot=None):
    site = tmp_path / "site"
    site.mkdir(exist_ok=True)
    reqs = tmp_path / "requirements.txt"
    reqs.write_text(requirements)
    return (
        site,
        reqs,
        Audit(snapshot or evidence(site)),
        DependencyUsageRegistry(RuntimeOwners()),
        SimpleNamespace(identity="opaque-generic-spec"),
    )


@pytest.mark.asyncio
async def test_alias_exclusion_keeps_independent_targets_free(
    tmp_path,
):
    coordinate = coordinator()
    site = tmp_path / "site"
    site.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(site, target_is_directory=True)
    waiting, admitted = asyncio.Event(), asyncio.Event()

    async def admit():
        waiting.set()
        async with coordinate((alias,)):
            admitted.set()

    async with coordinate((site,)):
        operation = asyncio.create_task(admit())
        try:
            await asyncio.wait_for(waiting.wait(), 2)
            assert not admitted.is_set()
            async with coordinate((tmp_path / "independent",)):
                assert not admitted.is_set()
        finally:
            if operation.done():
                await operation
    await asyncio.wait_for(operation, 2)
    assert admitted.is_set()


def wheel(tmp_path, name="f32-sdk", version="2.0", requires=()):
    package = name.replace("-", "_")
    info = f"{package}-{version}.dist-info"
    files = {
        f"{package}.py": b"VALUE = 'safe-local-addition'\n",
        f"{info}/METADATA": (
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
            + "".join(f"Requires-Dist: {req}\n" for req in requires)
        ).encode(),
        f"{info}/WHEEL": (
            b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\n"
            b"Tag: py3-none-any\n"
        ),
        f"{info}/top_level.txt": (package + "\n").encode(),
    }
    entries = []
    for member, data in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest())
        entries.append(
            f"{member},sha256={digest.decode().rstrip('=')},{len(data)}\n",
        )
    record = "".join(entries) + f"{info}/RECORD,,\n"
    files[f"{info}/RECORD"] = record.encode()
    path = tmp_path / f"{package}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        for member, data in files.items():
            archive.writestr(member, data)
    return gate.WheelAddition(
        path,
        hashlib.sha256(path.read_bytes()).hexdigest(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case,allowed",
    [
        ("retained", True),
        ("top-level", False),
        ("non-wheel", False),
        ("wrong-name", False),
        ("wrong-version", False),
        ("new-child", False),
        ("child-closure", False),
    ],
)
async def test_transitive_wheel_url_retains_only_original_installed_child(
    tmp_path,
    case,
    allowed,
):
    """A URL cannot turn an added row into evidence of pre-existing code."""
    site, reqs, process, usage, spec = inputs(tmp_path, "f32-parent==1.0\n")
    child = wheel(
        tmp_path,
        name="f32-child",
        version="1.0",
        requires=(
            "f32-leaf>=2" if case == "child-closure" else "f32-leaf==1",
        ),
    )
    leaf = wheel(tmp_path, name="f32-leaf", version="1.0")
    for addition in (leaf,) if case == "new-child" else (leaf, child):
        with zipfile.ZipFile(addition.path) as archive:
            archive.extractall(site)
    url = child.path.as_uri()
    if case == "non-wheel":
        url = child.path.with_suffix(".tar.gz").as_uri()
    elif case == "wrong-name":
        url = leaf.path.as_uri()
    elif case == "wrong-version":
        url = (tmp_path / "f32_child-2.0-py3-none-any.whl").as_uri()
    reference = "f32-child @ " + url
    parent = wheel(
        tmp_path,
        name="f32-parent",
        version="1.0",
        requires=(reference,),
    )
    if case == "top-level":
        reqs.write_text(reference + "\n")
    before = {
        str(path.relative_to(site)): path.read_bytes()
        for path in site.rglob("*")
        if path.is_file()
    }
    additions = (parent, child) if case == "new-child" else (parent,)

    async def prepare():
        return await gate.prepare_shared_dependencies(
            process,
            spec,
            plugin_id="url-contract",
            requirements_file=reqs,
            usage_registry=usage,
            install_target=site,
            wheels=additions,
        )

    if allowed:
        result = await prepare()
        assert result.distributions["f32-parent"]["version"] == "1.0"
        assert result.distributions["f32-child"]["version"] == "1.0"
        assert (site / "f32_parent.py").is_file()
        assert all(
            (site / name).read_bytes() == data for name, data in before.items()
        )
    else:
        with pytest.raises(gate.SharedDependencyError) as caught:
            await prepare()
        if case == "child-closure":
            assert caught.value.reason_code == "DEPENDENCY_RESTART_REQUIRED"
            assert "f32-leaf>=2" in caught.value.decision.host_conflicts
        else:
            assert caught.value.reason_code == "DEPENDENCY_PLAN_UNVERIFIED"
            assert caught.value.decision.unsupported
        after = {
            str(path.relative_to(site)): path.read_bytes()
            for path in site.rglob("*")
            if path.is_file()
        }
        assert after == before
    assert not repair_marker(site).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    ["unchanged", "addition", "requires-dist", "origin"],
)
async def test_resolver_snapshot_change_refuses_before_publication(
    tmp_path,
    change,
):
    """A fresh audit must not silently rebase a completed resolver plan."""
    site, reqs, process, usage, spec = inputs(tmp_path, "f32-parent==1.0\n")
    child = wheel(tmp_path, name="f32-child", version="1.0")
    with zipfile.ZipFile(child.path) as archive:
        archive.extractall(site)
    expected = (await process.audit(spec)).snapshot
    if change == "addition":
        peer = wheel(tmp_path, name="f32-peer", version="1.0")
        with zipfile.ZipFile(peer.path) as archive:
            archive.extractall(site)
    elif change == "requires-dist":
        metadata_path = site / "f32_child-1.0.dist-info/METADATA"
        metadata_path.write_text(
            metadata_path.read_text() + "Requires-Dist: f32-peer==1.0\n",
        )
    elif change == "origin":
        (site / "f32_child-1.0.dist-info").rename(
            site / "f32_child-1.0.0.dist-info",
        )
    before = {
        str(path.relative_to(site)): path.read_bytes()
        for path in site.rglob("*")
        if path.is_file()
    }
    parent = wheel(tmp_path, name="f32-parent", version="1.0")

    async def prepare():
        return await gate.prepare_shared_dependencies(
            process,
            spec,
            plugin_id="resolution-contract",
            requirements_file=reqs,
            usage_registry=usage,
            install_target=site,
            wheels=(parent,),
            expected_snapshot=expected,
        )

    if change == "unchanged":
        result = await prepare()
        assert result.distributions["f32-parent"]["version"] == "1.0"
        assert all(
            (site / name).read_bytes() == data for name, data in before.items()
        )
        assert not repair_marker(site).exists()
        return
    with pytest.raises(gate.SharedDependencyError) as caught:
        await prepare()
    assert caught.value.reason_code == "DEPENDENCY_RESTART_REQUIRED"
    assert caught.value.decision.require_restart
    after = {
        str(path.relative_to(site)): path.read_bytes()
        for path in site.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert not (site / "f32_parent.py").exists()
    assert not repair_marker(site).exists()


def declare(usage, plugin, snapshot, requirements, *, revision="old"):
    token = usage.declare(
        DependencyDeclaration(
            plugin,
            revision,
            requirements,
            DependencyEnvironment.from_snapshot(snapshot),
        ),
    )
    if snapshot is not None:
        usage.refine(token, snapshot)
    return token


async def install(
    tmp_path,
    *,
    usage=None,
    process=None,
    requirements="f32-sdk==2.0\n",
):
    prepare = prepare_api()
    site, reqs, audit, registry, spec = inputs(tmp_path, requirements)
    return await prepare(
        process or audit,
        spec,
        plugin_id="edge",
        requirements_file=reqs,
        usage_registry=usage or registry,
        install_target=site,
        wheels=(wheel(tmp_path),),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "consumer,candidate",
    [("channel-feishu", "edge"), ("edge", "channel-feishu")],
)
async def test_cross_kind_declared_conflict_prevents_any_package_write(
    tmp_path,
    consumer,
    candidate,
):
    prepare = prepare_api()
    site, reqs, process, usage, spec = inputs(tmp_path, "f32-sdk==2.0\n")
    declare(usage, consumer, evidence(site), ("f32-sdk<2",))
    with pytest.raises(gate.SharedDependencyError) as error:
        await prepare(
            process,
            spec,
            plugin_id=candidate,
            requirements_file=reqs,
            usage_registry=usage,
            install_target=site,
            wheels=(wheel(tmp_path),),
        )
    assert error.value.reason_code in {
        "DEPENDENCY_RESTART_REQUIRED",
        "DEPENDENCY_PLAN_UNVERIFIED",
    }
    assert consumer in str(error.value) or any(
        row.get("plugin_id") == consumer
        for row in error.value.decision.affected_instances
    )
    assert not list(site.iterdir()) and not repair_marker(site).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "consumer_python,requirement,blocked",
    [
        ("3.10", "f32-sdk<2; python_version<'3.11'", True),
        ("3.12", "f32-sdk<2; python_version<'3.11'", False),
    ],
)
async def test_consumers_use_their_own_marker_environment(
    tmp_path,
    consumer_python,
    requirement,
    blocked,
):
    prepare_api()
    site = tmp_path / "site"
    usage = DependencyUsageRegistry(RuntimeOwners())
    declare(
        usage,
        "consumer",
        evidence(site, python_version=consumer_python),
        (requirement,),
    )
    if blocked:
        with pytest.raises(gate.SharedDependencyError):
            await install(tmp_path, usage=usage)
        assert not list(site.iterdir())
    else:
        result = await install(tmp_path, usage=usage)
        assert result.distributions["f32-sdk"]["version"] == "2.0"


@pytest.mark.asyncio
async def test_actual_target_excludes_other_private_site_consumers(
    tmp_path,
):
    prepare_api()
    target, private, common = (
        tmp_path / name for name in ("site", "private", "common")
    )
    private.mkdir()
    common.mkdir()
    usage = DependencyUsageRegistry(RuntimeOwners())
    declare(
        usage,
        "independent",
        evidence(
            private,
            versions={"f32-sdk": "1.0"},
            package_sites=(private, common),
        ),
        ("f32-sdk==1.0",),
    )
    process = Audit(evidence(target, package_sites=(target, common)))
    result = await install(tmp_path, usage=usage, process=process)
    assert result.distributions["f32-sdk"]["version"] == "2.0"
    assert not list(private.iterdir()) and not list(common.iterdir())


@pytest.mark.asyncio
async def test_empty_shared_target_is_relevant_across_different_interpreters(
    tmp_path,
):
    prepare_api()
    site = tmp_path / "site"
    usage = DependencyUsageRegistry(RuntimeOwners())
    other = replace(evidence(site), executable=str(tmp_path / "other-python"))
    declare(usage, "other-interpreter", other, ("f32-sdk<2",))
    with pytest.raises(gate.SharedDependencyError):
        await install(tmp_path, usage=usage)
    assert not list(site.iterdir())


@pytest.mark.asyncio
async def test_unknown_host_environment_does_not_trust_history(
    tmp_path,
):
    prepare_api()
    usage = DependencyUsageRegistry(RuntimeOwners())
    old = evidence(tmp_path / "former-site", versions={"f32-sdk": "1.0"})
    token = declare(usage, "host", old, ("f32-sdk==1.0",))
    usage.observe_host(token, old)
    usage.observe_host(token, None)
    usage.withdraw(token)
    host = next(use for use in usage.snapshot().uses if use.origin == "host")
    assert host.environment is None and host.snapshot is not None
    with pytest.raises(gate.SharedDependencyError) as error:
        await install(tmp_path, usage=usage)
    assert error.value.reason_code == "DEPENDENCY_PLAN_UNVERIFIED"
    assert not list((tmp_path / "site").iterdir())


@pytest.mark.asyncio
async def test_withdrawn_host_protects_only_imported_requirements(
    tmp_path,
):
    prepare_api()
    site = tmp_path / "site"
    usage = DependencyUsageRegistry(RuntimeOwners())
    imported = evidence(site, versions={"f32-imported": "1.0"})
    materialize_host_metadata(imported)
    token = declare(
        usage,
        "host",
        imported,
        ("f32-imported==1.0", "f32-sdk<2"),
    )
    usage.observe_host(token, imported)
    usage.withdraw(token)
    process = Audit(imported)
    result = await install(tmp_path, usage=usage, process=process)
    assert result.distributions["f32-sdk"]["version"] == "2.0"
    assert result.distributions["f32-imported"]["version"] == "1.0"


@pytest.mark.asyncio
async def test_old_lease_blocks_same_plugin_candidate_without_exemption(
    tmp_path,
):
    prepare = prepare_api()
    site, reqs, process, usage, spec = inputs(tmp_path, "f32-sdk==2.0\n")
    owners = RuntimeOwners()
    usage = DependencyUsageRegistry(owners)
    token = declare(usage, "edge", evidence(site), ("f32-sdk<2",))
    lease = owners.reserve(
        "edge",
        RuntimeKey("component", "sdk", "old"),
        tmp_path,
        instance_id="old-instance",
    )
    usage.bind(lease, token)
    usage.observe(lease, evidence(site))
    usage.withdraw(token)
    candidate = declare(usage, "edge", None, ("f32-sdk==2.0",), revision="new")
    with pytest.raises(gate.SharedDependencyError) as error:
        await prepare(
            process,
            spec,
            plugin_id="edge",
            requirements_file=reqs,
            usage_registry=usage,
            admission_token=candidate,
            install_target=site,
            wheels=(wheel(tmp_path),),
        )
    assert any(
        row.get("instance_id") == "old-instance"
        and row.get("generation") == lease.generation
        for row in error.value.decision.affected_instances
    )
    assert not list(site.iterdir())


@pytest.mark.asyncio
async def test_waiting_preparation_refreshes_consumers_before_publication(
    tmp_path,
):
    prepare = prepare_api()
    coordinate = coordinator()
    site, reqs, process, usage, spec = inputs(tmp_path, "f32-sdk==2.0\n")
    started = asyncio.Event()

    async def candidate():
        started.set()
        return await prepare(
            process,
            spec,
            plugin_id="edge",
            requirements_file=reqs,
            usage_registry=usage,
            install_target=site,
            wheels=(wheel(tmp_path),),
        )

    async with coordinate((site,)):
        operation = asyncio.create_task(candidate())
        try:
            await asyncio.wait_for(started.wait(), 2)
            assert not operation.done()
            declare(
                usage,
                "arrived-while-waiting",
                evidence(site),
                ("f32-sdk<2",),
            )
        finally:
            if operation.done():
                await operation
    with pytest.raises(gate.SharedDependencyError):
        await asyncio.wait_for(operation, 3)
    assert not list(site.iterdir()) and not repair_marker(site).exists()


@pytest.mark.asyncio
async def test_locked_audit_reuses_peer_install_without_reading_deleted_wheel(
    tmp_path,
):
    prepare = prepare_api()
    coordinate = coordinator()
    site, reqs, process, usage, spec = inputs(tmp_path, "f32-sdk==2.0\n")
    addition = wheel(tmp_path)
    started = asyncio.Event()

    async def candidate():
        started.set()
        return await prepare(
            process,
            spec,
            plugin_id="edge",
            requirements_file=reqs,
            usage_registry=usage,
            install_target=site,
            wheels=(addition,),
        )

    async with coordinate((site,)):
        operation = asyncio.create_task(candidate())
        await asyncio.wait_for(started.wait(), 2)
        with zipfile.ZipFile(addition.path) as archive:
            archive.extractall(site)
        addition.path.unlink()
    result = await asyncio.wait_for(operation, 3)
    assert result.distributions["f32-sdk"]["version"] == "2.0"
    assert not repair_marker(site).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["prewrite", "postwrite"])
async def test_latest_usage_is_checked_at_publication_boundaries(
    tmp_path,
    monkeypatch,
    boundary,
):
    prepare_api()
    site = tmp_path / "site"
    usage = DependencyUsageRegistry(RuntimeOwners())
    process = Audit(evidence(site))
    if boundary == "prewrite":
        from qwenpaw.plugins import wheel_additions

        original = wheel_additions.validate_additions

        def validate(*args):
            validated = original(*args)
            declare(usage, "latest", evidence(site), ("f32-sdk<2",))
            return validated

        monkeypatch.setattr(wheel_additions, "validate_additions", validate)
    else:
        original_audit = process.audit

        async def audit(spec):
            result = await original_audit(spec)
            if (site / "f32_sdk.py").exists():
                declare(usage, "latest", result.snapshot, ("f32-sdk<2",))
            return result

        process.audit = audit
    with pytest.raises(gate.SharedDependencyError):
        await install(tmp_path, usage=usage, process=process)
    if boundary == "prewrite":
        assert not list(site.iterdir()) and not repair_marker(site).exists()
    else:
        assert (site / "f32_sdk.py").exists() and repair_marker(site).exists()


@pytest.mark.asyncio
async def test_installed_distribution_never_replaced_implicitly(
    tmp_path,
):
    prepare_api()
    site = tmp_path / "site"
    site.mkdir()
    owned = site / "f32_sdk.py"
    owned.write_bytes(b"existing-owner\n")
    process = Audit(evidence(site, versions={"f32-sdk": "1.0"}))
    with pytest.raises(gate.SharedDependencyError) as error:
        await install(tmp_path, process=process)
    assert error.value.reason_code == "DEPENDENCY_RESTART_REQUIRED"
    assert (
        owned.read_bytes() == b"existing-owner\n"
        and len(list(site.iterdir())) == 1
    )


@pytest.mark.asyncio
async def test_inherited_dirty_marker_is_never_cleared_even_when_satisfied(
    tmp_path,
):
    prepare = prepare_api()
    site, reqs, process, usage, spec = inputs(tmp_path, "f32-sdk==2.0\n")
    process.snapshot = evidence(site, versions={"f32-sdk": "2.0"})
    marker = repair_marker(site)
    marker.write_text("inherited partial files require explicit repair\n")
    with pytest.raises(gate.SharedDependencyError) as error:
        await prepare(
            process,
            spec,
            plugin_id="edge",
            requirements_file=reqs,
            usage_registry=usage,
            install_target=site,
            wheels=(wheel(tmp_path),),
        )
    assert error.value.reason_code == "DEPENDENCY_REPAIR_REQUIRED"
    assert (
        marker.read_text()
        == "inherited partial files require explicit repair\n"
    )
    assert not list(site.iterdir())


async def event_set(event):
    async with asyncio.timeout(3):
        while not event.is_set():
            await asyncio.sleep(0.005)


@pytest.mark.asyncio
async def test_repeated_cancel_retains_writer_and_exclusion(
    tmp_path,
    monkeypatch,
):
    prepare_api()
    coordinate = coordinator()
    site = tmp_path / "site"
    entered, release = threading.Event(), threading.Event()
    admitted = asyncio.Event()

    def partial_writer(target, files):
        relative = next(name for name in files if name.endswith(".py"))
        (target / relative).write_bytes(files[relative])
        entered.set()
        assert release.wait(5), "test did not release owned writer"

    async def peer():
        async with coordinate((site,)):
            admitted.set()

    monkeypatch.setattr(gate, "_write_additions", partial_writer)
    operation = asyncio.create_task(install(tmp_path))
    waiter = None
    try:
        await event_set(entered)
        operation.cancel()
        await asyncio.sleep(0)
        operation.cancel()
        waiter = asyncio.create_task(peer())
        await asyncio.sleep(0)
        assert not operation.done() and not admitted.is_set()
        with pytest.raises(install_lock.InstallLockError):
            with install_lock.plugin_install_lock(
                install_lock.environment_install_lock_path(site),
                timeout=0,
            ):
                pytest.fail(
                    "cancel released file exclusion while writer owned",
                )
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(operation, 3)
        await asyncio.wait_for(waiter, 3)
        assert admitted.is_set() and repair_marker(site).exists()
    finally:
        release.set()
        await asyncio.gather(
            *(task for task in (operation, waiter) if task),
            return_exceptions=True,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["load", "enable"])
async def test_real_loader_admission_waits_for_writer_and_verification(
    tmp_path,
    monkeypatch,
    fresh_registry,
    entry,
):
    prepare = prepare_api()
    coordinator()
    from qwenpaw.plugins.architecture import PluginManifest, PluginType
    from qwenpaw.plugins.execution_backend import (
        DefinitionResult,
        PluginDescription,
    )
    from qwenpaw.plugins.loader import PluginLoader
    from qwenpaw.plugins.registry import PluginRegistry

    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_config_path",
        lambda: tmp_path / "config.json",
    )
    publisher = PluginLoader([tmp_path / "publisher"])
    monkeypatch.setattr(PluginRegistry, "_instance", None)
    loader = PluginLoader([tmp_path / "plugins"])
    site, reqs, process, _usage, spec = inputs(tmp_path, "f32-sdk==2.0\n")
    usage = publisher.registry.dependency_usage
    consumer_usage = loader.registry.dependency_usage
    assert usage is not consumer_usage
    source = tmp_path / "plugins" / "consumer"
    source.mkdir(parents=True)
    (source / "requirements.txt").write_text("f32-sdk==2.0\n")
    (source / "definition.json").write_text("{}")
    raw = {
        "id": "consumer",
        "name": "consumer",
        "version": "1.0.0",
        "type": "general",
        "entry": {"descriptor": "definition.json"},
    }
    (source / "plugin.json").write_text(json.dumps(raw))
    definition_entered = asyncio.Event()
    admission_started = asyncio.Event()
    writer_entered, writer_release = threading.Event(), threading.Event()
    verification_entered, verification_release = (
        asyncio.Event(),
        asyncio.Event(),
    )

    class TrustedAdapter:
        def describe(self, root, manifest):
            return PluginDescription(
                manifest,
                root,
                root / "requirements.txt",
                {},
            )

        def dependency_targets(self, description):
            return (site,)

        async def prepare(self, description, **kwargs):
            return evidence(site, versions={"f32-sdk": "2.0"})

        async def audit_dependencies(self, description):
            return evidence(site, versions={"f32-sdk": "2.0"})

        async def load_definition(
            self,
            description,
            config,
            *,
            saved_definition=None,
        ):
            definition_entered.set()
            return DefinitionResult(
                SimpleNamespace(register=lambda api: None),
                dependency_snapshot=evidence(
                    site,
                    versions={"f32-sdk": "2.0"},
                ),
            )

        async def before_activate(self, description):
            pass

    loader.backend_resolver.register_descriptor(
        PluginType.GENERAL,
        TrustedAdapter(),
    )
    if entry == "enable":
        inactive = await loader.load_plugin(
            PluginManifest.from_dict(raw),
            source,
            {"enabled": False},
        )
        assert (
            inactive.status == "inactive" and not definition_entered.is_set()
        )
    original_writer, original_audit = gate._write_additions, process.audit

    def writer(target, files):
        writer_entered.set()
        assert writer_release.wait(5)
        original_writer(target, files)

    async def audit(spec):
        result = await original_audit(spec)
        if (site / "f32_sdk.py").exists():
            verification_entered.set()
            await verification_release.wait()
        return result

    async def admit():
        admission_started.set()
        if entry == "enable":
            return await loader.lifecycle.set_enabled("consumer", True)
        return await loader.load_plugin(PluginManifest.from_dict(raw), source)

    process.audit = audit
    monkeypatch.setattr(gate, "_write_additions", writer)
    publication = asyncio.create_task(
        prepare(
            process,
            spec,
            plugin_id="publisher",
            requirements_file=reqs,
            usage_registry=usage,
            install_target=site,
            wheels=(wheel(tmp_path),),
        ),
    )
    admission = None
    try:
        await event_set(writer_entered)
        admission = asyncio.create_task(admit())
        await asyncio.wait_for(admission_started.wait(), 2)
        assert not definition_entered.is_set() and not admission.done()
        assert not any(
            use.plugin_id == "consumer"
            for use in consumer_usage.snapshot().uses
        )
        writer_release.set()
        await asyncio.wait_for(verification_entered.wait(), 2)
        assert not definition_entered.is_set() and not admission.done()
        assert not any(
            use.plugin_id == "consumer"
            for use in consumer_usage.snapshot().uses
        )
        verification_release.set()
        await asyncio.wait_for(publication, 3)
        record = await asyncio.wait_for(admission, 3)
        assert record.status == "active", record.diagnostics
        rows = [
            use
            for use in consumer_usage.snapshot().uses
            if use.plugin_id == "consumer" and use.origin == "declaration"
        ]
        assert len(rows) == 1 and rows[0].requirements == ("f32-sdk==2.0",)
        assert rows[0].environment is not None
    finally:
        writer_release.set()
        verification_release.set()
        await asyncio.gather(
            *(task for task in (publication, admission) if task),
            return_exceptions=True,
        )
        if loader.get_loaded_plugin("consumer") is not None:
            await loader.unload_plugin("consumer")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["unknown", "stale", "cached-definition"])
async def test_real_loader_requires_current_evidence_before_definition_import(
    tmp_path,
    monkeypatch,
    fresh_registry,
    mode,
):
    from qwenpaw.plugins.architecture import PluginManifest, PluginType
    from qwenpaw.plugins.execution_backend import (
        DefinitionResult,
        PluginDescription,
    )
    from qwenpaw.plugins.loader import PluginLoader

    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_config_path",
        lambda: tmp_path / "config.json",
    )
    source = tmp_path / "plugins" / "guarded"
    source.mkdir(parents=True)
    (source / "requirements.txt").write_text("f32-sdk==2.0\n")
    (source / "definition.json").write_text("{}")
    raw = {
        "id": "guarded",
        "name": "guarded",
        "version": "1.0.0",
        "type": "general",
        "entry": {"descriptor": "definition.json"},
    }
    (source / "plugin.json").write_text(json.dumps(raw))
    site = tmp_path / "site"
    site.mkdir()
    imported = asyncio.Event()

    class TrustedAdapter:
        def describe(self, root, manifest):
            return PluginDescription(
                manifest,
                root,
                root / "requirements.txt",
                {},
            )

        def dependency_targets(self, description):
            return (site,) if mode != "unknown" else ()

        async def prepare(self, description, **kwargs):
            return (
                evidence(site, versions={"f32-sdk": "2.0"})
                if mode != "unknown"
                else None
            )

        async def audit_dependencies(self, description):
            versions = (
                {"f32-sdk": "1.0"}
                if mode == "stale"
                else {
                    "f32-sdk": "2.0",
                    "f32-latest-evidence": "1.0",
                }
            )
            return (
                evidence(site, versions=versions)
                if mode != "unknown"
                else None
            )

        async def load_definition(
            self,
            description,
            config,
            *,
            saved_definition=None,
        ):
            imported.set()
            return DefinitionResult(
                SimpleNamespace(register=lambda api: None),
                dependency_snapshot=evidence(
                    site,
                    versions={"f32-sdk": "2.0"},
                ),
            )

        async def before_activate(self, description):
            pass

    loader = PluginLoader([source.parent])
    loader.backend_resolver.register_descriptor(
        PluginType.GENERAL,
        TrustedAdapter(),
    )
    try:
        record = await loader.load_plugin(
            PluginManifest.from_dict(raw),
            source,
        )
        if mode == "cached-definition":
            assert record.status == "active", record.diagnostics
            current = next(
                use
                for use in fresh_registry.dependency_usage.snapshot().uses
                if use.plugin_id == "guarded" and use.origin == "declaration"
            )
            assert (
                "f32-latest-evidence" in current.snapshot.distributions
            ), "cached DefinitionResult overwrote final locked audit evidence"
        else:
            assert (
                record.status == "failed"
            ), "unknown/stale evidence authorized definition execution"
            assert not imported.is_set()
            assert any(
                "DEPENDENCY_" in message for message in record.diagnostics
            )
    finally:
        if loader.get_loaded_plugin("guarded") is not None:
            await loader.unload_plugin("guarded")


def test_coordinator_waiters_cannot_starve_holder_default_executor(tmp_path):
    coordinate = coordinator()

    class ObservedExecutor(ThreadPoolExecutor):
        def __init__(self):
            super().__init__(max_workers=2)
            self.entered = []

        def submit(self, function, /, *args, **kwargs):
            entered = threading.Event()
            self.entered.append(entered)

            def run():
                entered.set()
                return function(*args, **kwargs)

            return super().submit(run)

    async def scenario():
        executor = ObservedExecutor()
        asyncio.get_running_loop().set_default_executor(executor)
        attempted = [asyncio.Event(), asyncio.Event()]
        site = tmp_path / "site"
        work = None
        waiters = []
        progressed = False

        async def waiter(index):
            attempted[index].set()
            async with coordinate((site,)):
                pass

        try:
            async with coordinate((site,)):
                baseline = len(executor.entered)
                waiters = [
                    asyncio.create_task(waiter(index)) for index in range(2)
                ]
                await asyncio.gather(*(event.wait() for event in attempted))
                # Flush acquisition tasks; old threaded waits occupy both
                # workers, new async waits need none. Observe actual workers.
                await asyncio.sleep(0)
                await asyncio.sleep(0)
                waiting_jobs = executor.entered[baseline:]
                for event in waiting_jobs:
                    await event_set(event)
                work = asyncio.create_task(asyncio.to_thread(lambda: 42))
                try:
                    progressed = (
                        await asyncio.wait_for(asyncio.shield(work), 1) == 42
                    )
                except TimeoutError:
                    progressed = False
            # Release holder before assertion so even the old implementation
            # drains its workers and loop shutdown cannot hang.
            await asyncio.wait_for(asyncio.gather(*waiters, work), 3)
            assert (
                progressed
            ), "coordinator waiters starved holder's two-thread executor"
        finally:
            await asyncio.gather(
                *(task for task in (*waiters, work) if task),
                return_exceptions=True,
            )

    asyncio.run(scenario())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target",
    [ROOT / "src", Path(sysconfig.get_path("stdlib"))],
)
async def test_explicit_root_cannot_authorize_trusted_tree_publication(
    tmp_path,
    monkeypatch,
    target,
):
    prepare = prepare_api()
    from qwenpaw.plugins.execution import dependencies

    called = []

    def never_write(destination, files):
        called.append(destination)
        raise AssertionError("test intercepted forbidden target write")

    @contextmanager
    def held_lock(*args, **kwargs):
        yield True

    # Intercept every possible side effect if admission is wrong. The target
    # remains the actual trusted root, so the safety decision is exercised.
    monkeypatch.setattr(gate, "_write_additions", never_write)
    monkeypatch.setattr(install_lock, "plugin_install_lock", held_lock)
    monkeypatch.setattr(
        dependencies,
        "repair_marker",
        lambda site: tmp_path / "intercepted-marker",
    )
    reqs = tmp_path / "requirements.txt"
    reqs.write_text("f32-sdk==2.0\n")
    with pytest.raises(gate.SharedDependencyError) as error:
        await prepare(
            Audit(evidence(target)),
            SimpleNamespace(identity="opaque-generic-spec"),
            plugin_id="edge",
            requirements_file=reqs,
            usage_registry=DependencyUsageRegistry(RuntimeOwners()),
            install_target=target,
            wheels=(wheel(tmp_path),),
        )
    assert error.value.reason_code == "DEPENDENCY_PLAN_UNVERIFIED"
    assert not called and not (tmp_path / "intercepted-marker").exists()


@pytest.mark.asyncio
async def test_gate_cannot_refine_foreign_plugin_admission_token(tmp_path):
    prepare = prepare_api()
    site, reqs, process, usage, spec = inputs(tmp_path, "f32-sdk==2.0\n")
    foreign = declare(usage, "different-plugin", None, ("f32-sdk==2.0",))
    with pytest.raises(gate.SharedDependencyError) as error:
        await prepare(
            process,
            spec,
            plugin_id="edge",
            requirements_file=reqs,
            usage_registry=usage,
            admission_token=foreign,
            install_target=site,
            wheels=(wheel(tmp_path),),
        )
    assert error.value.reason_code == "DEPENDENCY_PLAN_UNVERIFIED"
    row = next(
        use
        for use in usage.snapshot().uses
        if use.plugin_id == "different-plugin"
    )
    assert row.environment is None and row.snapshot is None
    assert not list(site.iterdir())


@pytest.mark.asyncio
async def test_registration_restores_context_and_child_cannot_borrow(
    tmp_path,
    fresh_registry,
    monkeypatch,
):
    from qwenpaw.plugins.architecture import PluginManifest, PluginType
    from qwenpaw.plugins.execution_backend import (
        DefinitionResult,
        PluginDescription,
    )
    from qwenpaw.plugins.loader import PluginLoader
    from qwenpaw.plugins.dependency_usage import current_admission_token

    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_config_path",
        lambda: tmp_path / "config.json",
    )
    site = tmp_path / "site"
    site.mkdir()
    loader = PluginLoader([tmp_path / "plugins"])
    usage = fresh_registry.dependency_usage
    sources, manifests = {}, {}
    for plugin in ("outer", "inner"):
        source = tmp_path / "plugins" / plugin
        source.mkdir(parents=True)
        (source / "requirements.txt").write_text("")
        (source / "definition.json").write_text("{}")
        raw = {
            "id": plugin,
            "name": plugin,
            "version": "1.0.0",
            "type": "general",
            "entry": {"descriptor": "definition.json"},
        }
        (source / "plugin.json").write_text(json.dumps(raw))
        sources[plugin], manifests[plugin] = source, PluginManifest.from_dict(
            raw,
        )
    child_release = asyncio.Event()
    child = None
    tokens = {}

    def token(description, source_path=None):
        # The forwarding helper may strengthen its signature with exact
        # source identity; both versions exercise the real lifecycle scope.
        parameters = inspect.signature(current_admission_token).parameters
        if len(parameters) == 1:
            # Runtime introspection selects the historical one-arg API.
            # pylint: disable-next=no-value-for-parameter
            return current_admission_token(usage)
        return current_admission_token(
            usage,
            description.manifest.id,
            source_path or description.source_path,
        )

    class TrustedAdapter:
        def describe(self, root, manifest):
            return PluginDescription(
                manifest,
                root,
                root / "requirements.txt",
                {},
            )

        def dependency_targets(self, description):
            return (site,)

        async def prepare(self, description, **kwargs):
            nonlocal child
            tokens[description.manifest.id] = token(description)
            assert tokens[description.manifest.id] is not None
            assert token(description, tmp_path / "different-source") is None
            usage.refine(tokens[description.manifest.id], evidence(site))
            if description.manifest.id == "outer":

                async def inherited():
                    await child_release.wait()
                    return token(description)

                child = asyncio.create_task(inherited())
                nested = await loader.load_plugin(
                    manifests["inner"],
                    sources["inner"],
                )
                assert nested.status == "active", nested.diagnostics
                assert token(description) is tokens["outer"]
                assert tokens["inner"] is not tokens["outer"]
            return evidence(site)

        async def audit_dependencies(self, description):
            return evidence(site)

        async def load_definition(
            self,
            description,
            config,
            *,
            saved_definition=None,
        ):
            return DefinitionResult(SimpleNamespace(register=lambda api: None))

        async def before_activate(self, description):
            pass

    loader.backend_resolver.register_descriptor(
        PluginType.GENERAL,
        TrustedAdapter(),
    )
    try:
        record = await loader.load_plugin(manifests["outer"], sources["outer"])
        assert record.status == "active", record.diagnostics
        child_release.set()
        assert (
            await asyncio.wait_for(child, 2) is None
        ), "create_task borrowed parent's admission token"
        assert token(loader._binding_for_record(record).description) is None
    finally:
        child_release.set()
        if child is not None:
            await asyncio.gather(child, return_exceptions=True)
        for plugin in ("outer", "inner"):
            if loader.get_loaded_plugin(plugin) is not None:
                await loader.unload_plugin(plugin)


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked", [False, True])
async def test_host_closure_keeps_distinct_requested_extra_paths(
    tmp_path,
    blocked,
):
    """A base visit must not suppress a later extra-conditioned constraint."""
    prepare_api()
    site = tmp_path / "site"
    host_site = tmp_path / "host-site"
    versions = {"f32-left": "1.0", "f32-right": "1.0", "f32-bridge": "1.0"}
    observed = evidence(
        host_site,
        versions=versions,
        python_version="3.10",
        package_sites=(host_site, site),
    )
    distributions = {
        name: dict(row) for name, row in observed.distributions.items()
    }
    distributions["f32-left"]["requires_dist"] = ["f32-bridge[red]==1.0"]
    distributions["f32-right"]["requires_dist"] = ["f32-bridge[blue]==1.0"]
    distributions["f32-bridge"]["requires_dist"] = [
        "f32-sdk>=2; extra=='red' and python_version<'3.11'",
        "f32-sdk<2; extra=='blue'" if blocked else "f32-sdk>=2; extra=='blue'",
    ]
    # Red is compatible here, Blue's differing path is the decisive branch;
    # reverse declaration iteration must not mask it through a visited name.
    observed = replace(observed, distributions=distributions)
    materialize_host_metadata(observed)
    usage = DependencyUsageRegistry(RuntimeOwners())
    token = declare(usage, "imported-host", observed, ())
    usage.observe_host(token, observed)
    usage.withdraw(token)
    if blocked:
        with pytest.raises(gate.SharedDependencyError) as error:
            await install(tmp_path, usage=usage)
        assert error.value.reason_code == "DEPENDENCY_RESTART_REQUIRED"
        assert not list(site.iterdir())
    else:
        result = await install(tmp_path, usage=usage)
        assert result.distributions["f32-sdk"]["version"] == "2.0"


@pytest.mark.asyncio
@pytest.mark.parametrize("shared_origin", [False, True])
async def test_public_admission_preserves_private_consumer_inventory(
    tmp_path,
    shared_origin,
):
    private_a, private_b, common = (
        tmp_path / name for name in ("private-a", "private-b", "common")
    )
    for site in (private_a, private_b, common):
        site.mkdir()
    usage = DependencyUsageRegistry(RuntimeOwners())
    consumer = evidence(
        common if shared_origin else private_b,
        versions={"f32-sdk": "1.0"},
        package_sites=(private_b, common),
    )
    declare(usage, "consumer", consumer, ("f32-sdk==1.0",))
    candidate = declare(
        usage,
        "edge",
        None,
        ("f32-sdk==2.0",),
        revision="candidate",
    )
    preliminary = evidence(
        common if shared_origin else private_a,
        versions={"f32-sdk": "2.0"},
        package_sites=(private_a, common),
    )
    latest = evidence(
        common if shared_origin else private_a,
        versions={"f32-sdk": "2.0", "f32-fresh-audit": "1.0"},
        package_sites=(private_a, common),
    )
    process = Audit(latest)

    async def audit():
        result = await process.audit(
            SimpleNamespace(identity="opaque-generic-spec"),
        )
        return result.snapshot

    async def admit():
        return await gate.admit_shared_dependencies(
            audit,
            plugin_id="edge",
            requirements_file=None,
            usage_registry=usage,
            admission_token=candidate,
            snapshot=preliminary,
        )

    if shared_origin:
        with pytest.raises(gate.SharedDependencyError) as error:
            await admit()
        assert error.value.reason_code == "DEPENDENCY_RESTART_REQUIRED"
    else:
        admitted = await admit()
        assert "f32-fresh-audit" in admitted.distributions
        retained = next(
            use
            for use in usage.snapshot().uses
            if use.plugin_id == "consumer" and use.origin == "declaration"
        )
        assert retained.snapshot.distributions["f32-sdk"]["version"] == "1.0"
        assert retained.requirements == ("f32-sdk==1.0",)
    assert process.calls >= 1
    assert all(
        not list(site.iterdir()) for site in (private_a, private_b, common)
    )
