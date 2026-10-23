# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,unused-argument
# pylint: disable=too-many-statements
"""Independent F3.1 dependency custody and actual-environment contracts."""

import importlib
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
from types import SimpleNamespace
import venv

import pytest
from packaging.markers import default_environment

from qwenpaw.plugins.execution.dependencies import DependencySnapshot
from qwenpaw.plugins.execution.process import PluginLaunchSpec, PluginProcess
from qwenpaw.plugins.ownership import RuntimeKey, RuntimeStopReceipt

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.asyncio
async def test_catalogue_role_never_hides_live_or_pending_consumers(
    usage_api,
    fresh_registry,
    tmp_path,
):
    from qwenpaw.plugins.dependency_gate import (
        SharedDependencyError,
        admit_shared_dependencies,
        prepare_shared_dependencies,
    )

    usage = public_usage(usage_api, fresh_registry)
    site = tmp_path / "site"
    one = evidence(site, dependency_sites=(str(site),))
    two = evidence(site, version="2.0", dependency_sites=(str(site),))
    catalog = usage.declare(
        declaration(
            usage_api,
            "catalog",
            None,
            requirements=("fixture-sdk==2.0",),
        ),
        pending=False,
    )
    assert not rows(usage)

    async def audit_one():
        return one

    async def audit_two():
        return two

    lease = reserve(fresh_registry, tmp_path, "catalog")
    usage.bind(lease, catalog)
    assert rows(usage, "runtime")[0].environment is None
    with pytest.raises(
        SharedDependencyError,
        match="environment evidence unavailable",
    ):
        await admit_shared_dependencies(
            audit_one,
            plugin_id="peer",
            requirements_file=None,
            usage_registry=usage,
            snapshot=one,
        )
    assert fresh_registry.runtime_owners.release(
        lease,
        RuntimeStopReceipt(True),
    )
    assert not rows(usage)

    # Supplementary evidence does not turn a static catalogue into admission.
    usage.refine(catalog, one)
    assert not rows(usage, "declaration")
    with pytest.raises(SharedDependencyError, match="fixture-sdk==2.0"):
        await admit_shared_dependencies(
            audit_one,
            plugin_id="catalog",
            requirements_file=None,
            usage_registry=usage,
            admission_token=catalog,
            snapshot=one,
        )
    assert not rows(
        usage,
        "declaration",
    ), "Failed admission promoted catalogue"

    async def audit_two_spec(_spec):
        return SimpleNamespace(snapshot=two)

    prepared = await prepare_shared_dependencies(
        SimpleNamespace(audit=audit_two_spec),
        SimpleNamespace(),
        plugin_id="catalog",
        requirements_file=None,
        usage_registry=usage,
        admission_token=catalog,
    )
    assert prepared.distributions["fixture-sdk"]["version"] == "2.0"
    assert not rows(usage, "declaration"), "Preparation promoted catalogue"

    observed = await admit_shared_dependencies(
        audit_two,
        plugin_id="catalog",
        requirements_file=None,
        usage_registry=usage,
        admission_token=catalog,
        snapshot=two,
    )
    assert observed.distributions["fixture-sdk"]["version"] == "2.0"
    (promoted,) = rows(usage, "declaration")
    assert promoted.plugin_id == "catalog" and promoted.requirements == (
        "fixture-sdk==2.0",
    )
    assert (
        not promoted.active
    ), "Admitted declaration falsely claims a live lease"

    unknown = usage.declare(declaration(usage_api, "unknown-pending", None))
    assert any(use.plugin_id == "unknown-pending" for use in rows(usage))
    with pytest.raises(
        SharedDependencyError,
        match="environment evidence unavailable",
    ):
        await admit_shared_dependencies(
            audit_two,
            plugin_id="catalog",
            requirements_file=None,
            usage_registry=usage,
            admission_token=catalog,
            snapshot=two,
        )
    usage.withdraw(unknown)
    usage.withdraw(catalog)
    assert not rows(usage)


@pytest.fixture
def usage_api():
    name = "qwenpaw.plugins.dependency_usage"
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name != name:
            raise
        return None


def public_usage(api, registry):
    assert api is not None, "F3.1 generic dependency usage is missing"
    assert hasattr(
        registry,
        "dependency_usage",
    ), "Registry must expose generic usage"
    return registry.dependency_usage


def environment(api, site, *, executable=None, python_version="3.12"):
    markers = {**default_environment(), "python_version": python_version}
    return api.DependencyEnvironment(
        executable or sys.executable,
        (str(site),),
        markers,
    )


def evidence(site, *, executable=None, version="1.0", dependency_sites=None):
    """Full audit scope deliberately contains shared stdlib/support roots."""
    package_root = str(Path(site).resolve())
    data = {
        "executable": executable or sys.executable,
        "prefix": str(Path(site).parent),
        "sites": [
            package_root,
            sysconfig.get_path("stdlib"),
            str(ROOT / "src"),
        ],
        "marker_environment": default_environment(),
        "supported_tags": ["py3-none-any"],
        "distributions": {
            "fixture-sdk": {
                "version": version,
                "metadata_path": package_root + "/fixture_sdk.dist-info",
                "requires_dist": [],
                "top_level": ["fixture_sdk"],
            },
        },
    }
    if dependency_sites is not None:
        data["dependency_sites"] = list(dependency_sites)
    return DependencySnapshot.from_mapping(data)


def declaration(api, plugin, env, *, revision="old", requirements=None):
    return api.DependencyDeclaration(
        plugin,
        revision,
        ("fixture-sdk==1.0",) if requirements is None else requirements,
        env,
    )


def reserve(
    registry,
    tmp_path,
    plugin="demo",
    *,
    kind="component",
    scope="w1",
):
    return registry.runtime_owners.reserve(
        plugin,
        RuntimeKey(kind, plugin, scope),
        tmp_path / plugin,
        instance_id=f"{scope}:{plugin}",
    )


def rows(usage, origin=None, env=None):
    return tuple(
        use
        for use in usage.snapshot(env).uses
        if origin is None or use.origin == origin
    )


def test_exact_declaration_tokens_do_not_overwrite_versions(
    usage_api,
    fresh_registry,
    tmp_path,
):
    usage = public_usage(usage_api, fresh_registry)
    env = environment(usage_api, tmp_path / "site")
    old = usage.declare(declaration(usage_api, "demo", env))
    candidate = usage.declare(
        declaration(
            usage_api,
            "demo",
            env,
            revision="candidate",
            requirements=("fixture-sdk==2.0",),
        ),
    )
    duplicate = usage.declare(declaration(usage_api, "demo", env))
    assert old != duplicate
    before = usage.snapshot(env)
    assert {use.source_revision for use in before.uses} == {"old", "candidate"}
    usage.withdraw(candidate)
    usage.withdraw(old)
    usage.withdraw(old)
    surviving = rows(usage, "declaration", env)
    assert len(surviving) == 1
    assert surviving[0].requirements == ("fixture-sdk==1.0",)
    assert {use.source_revision for use in before.uses} == {"old", "candidate"}
    assert usage.snapshot(env).revision != before.revision


def test_all_consumer_kinds_share_public_usage_query(
    usage_api,
    fresh_registry,
    tmp_path,
):
    usage = public_usage(usage_api, fresh_registry)
    env = environment(usage_api, tmp_path / "site")
    for kind in ("channel", "image-indexer", "python"):
        plugin = "fixture-" + kind
        token = usage.declare(declaration(usage_api, plugin, env))
        lease = reserve(fresh_registry, tmp_path, plugin, kind=kind)
        usage.bind(lease, token)
        usage.observe(
            lease,
            evidence(env.sites[0], dependency_sites=env.sites),
        )
    running = rows(usage, "runtime", env)
    assert {use.plugin_id for use in running} == {
        "fixture-channel",
        "fixture-image-indexer",
        "fixture-python",
    }
    assert all(use.active and use.generation == 1 for use in running)
    assert all(
        use.snapshot.versions == {"fixture-sdk": "1.0"} for use in running
    )
    assert all(use.requirements == ("fixture-sdk==1.0",) for use in running)


def test_bound_old_lease_retains_requirements_after_candidate_withdrawal(
    usage_api,
    fresh_registry,
    tmp_path,
):
    usage = public_usage(usage_api, fresh_registry)
    env = environment(usage_api, tmp_path / "site")
    old = usage.declare(declaration(usage_api, "demo", env))
    lease = reserve(fresh_registry, tmp_path)
    usage.bind(lease, old)
    usage.bind(lease, old)
    candidate = usage.declare(
        declaration(
            usage_api,
            "demo",
            env,
            revision="candidate",
            requirements=("fixture-sdk==2.0",),
        ),
    )
    with pytest.raises((ValueError, RuntimeError)):
        usage.bind(lease, candidate)
    usage.withdraw(candidate)
    usage.withdraw(old)
    usage.observe(lease, evidence(env.sites[0], dependency_sites=env.sites))
    current = rows(usage, "runtime", env)
    assert len(current) == 1
    assert current[0].source_revision == "old"
    assert current[0].requirements == ("fixture-sdk==1.0",)
    assert current[0].generation == lease.generation


def test_bind_rejects_foreign_or_withdrawn_declaration_token(
    usage_api,
    fresh_registry,
    tmp_path,
):
    usage = public_usage(usage_api, fresh_registry)
    env = environment(usage_api, tmp_path / "site")
    foreign = usage.declare(declaration(usage_api, "other-plugin", env))
    withdrawn = usage.declare(declaration(usage_api, "demo", env))
    usage.withdraw(withdrawn)
    lease = reserve(fresh_registry, tmp_path)
    for invalid in (foreign, withdrawn):
        with pytest.raises((ValueError, RuntimeError)):
            usage.bind(lease, invalid)
    current = rows(usage, "runtime")[0]
    assert current.requirements is None and current.source_revision is None


def test_stop_failure_and_stale_observation_preserve_current_generation(
    usage_api,
    fresh_registry,
    tmp_path,
):
    usage = public_usage(usage_api, fresh_registry)
    owners = fresh_registry.runtime_owners
    env = environment(usage_api, tmp_path / "site")
    token = usage.declare(declaration(usage_api, "demo", env))
    old = reserve(fresh_registry, tmp_path)
    usage.bind(old, token)
    usage.observe(old, evidence(env.sites[0], dependency_sites=env.sites))
    before = usage.snapshot(env)
    assert not owners.release(old, RuntimeStopReceipt(False, exited=True))
    assert not owners.release(old, RuntimeStopReceipt(True, exited=False))
    assert not owners.release(
        old,
        RuntimeStopReceipt(True, residual=("child",)),
    )
    assert (
        rows(usage, "runtime", env)[0].snapshot.versions["fixture-sdk"]
        == "1.0"
    )
    assert owners.release(old, RuntimeStopReceipt(True))
    assert not rows(usage, "runtime", env)
    assert usage.snapshot(env).revision != before.revision
    fresh = reserve(fresh_registry, tmp_path)
    usage.bind(fresh, token)
    usage.observe(
        fresh,
        evidence(env.sites[0], version="2.0", dependency_sites=env.sites),
    )
    usage.observe(
        old,
        evidence(env.sites[0], version="9.0", dependency_sites=env.sites),
    )
    assert not owners.release(old, RuntimeStopReceipt(True))
    current = rows(usage, "runtime", env)
    assert len(current) == 1
    assert current[0].generation == fresh.generation > old.generation
    assert current[0].snapshot.versions["fixture-sdk"] == "2.0"


def test_unknown_consumer_is_visible_before_bind_or_audit(
    usage_api,
    fresh_registry,
    tmp_path,
):
    usage = public_usage(usage_api, fresh_registry)
    env = environment(usage_api, tmp_path / "unrelated-site")
    lease = reserve(fresh_registry, tmp_path, "unknown")
    use = rows(usage, "runtime", env)[0]
    assert use.active and use.instance_id == lease.instance_id
    assert (
        use.requirements is None
        and use.environment is None
        and use.snapshot is None
    )
    with pytest.raises((ValueError, RuntimeError)):
        usage.observe(lease, evidence(env.sites[0]))
    unknown = usage.declare(
        usage_api.DependencyDeclaration("unknown", "rev", None, None),
    )
    usage.bind(lease, unknown)
    assert rows(usage, "runtime", env)[0].requirements is None
    usage.observe_host(unknown, None)
    usage.withdraw(unknown)
    host = rows(usage, "host", env)[0]
    assert host.active and host.environment is None and host.snapshot is None


def test_environment_overlap_uses_package_sites_not_binary_or_shared_stdlib(
    usage_api,
    fresh_registry,
    tmp_path,
):
    usage = public_usage(usage_api, fresh_registry)
    sites = [
        tmp_path / "venv-a/site-packages",
        tmp_path / "venv-b/site-packages",
    ]
    for index, site in enumerate(sites):
        site.mkdir(parents=True)
        token = usage.declare(declaration(usage_api, f"plugin-{index}", None))
        lease = reserve(fresh_registry, tmp_path, f"plugin-{index}")
        usage.bind(lease, token)
        usage.observe(lease, evidence(site, dependency_sites=(str(site),)))
    assert {
        use.plugin_id
        for use in rows(
            usage,
            env=environment(usage_api, sites[0]),
        )
    } == {"plugin-0"}

    alias = tmp_path / "shared-alias"
    alias.symlink_to(sites[0], target_is_directory=True)
    other = usage.declare(
        declaration(
            usage_api,
            "other-python",
            environment(
                usage_api,
                alias,
                executable="/other/interpreter/bin/python",
                python_version="3.9",
            ),
            requirements=("fixture-sdk<2; python_version<'3.10'",),
        ),
    )
    included = rows(usage, "declaration", environment(usage_api, sites[0]))
    consumer = next(use for use in included if use.plugin_id == "other-python")
    assert consumer.environment.marker_environment["python_version"] == "3.9"
    assert consumer.requirements == ("fixture-sdk<2; python_version<'3.10'",)
    usage.withdraw(other)


def test_legacy_snapshot_without_dependency_sites_keeps_environment_unknown(
    usage_api,
    fresh_registry,
    tmp_path,
):
    usage = public_usage(usage_api, fresh_registry)
    token = usage.declare(declaration(usage_api, "legacy", None))
    lease = reserve(fresh_registry, tmp_path, "legacy")
    usage.bind(lease, token)
    observed = evidence(tmp_path / "old-site")
    usage.observe(lease, observed)
    use = rows(
        usage,
        "runtime",
        environment(usage_api, tmp_path / "new-site"),
    )[0]
    assert use.environment is None
    assert use.snapshot.versions == {"fixture-sdk": "1.0"}


def test_host_import_evidence_outlives_declaration_without_runtime_lease(
    usage_api,
    fresh_registry,
    tmp_path,
):
    usage = public_usage(usage_api, fresh_registry)
    env = environment(usage_api, tmp_path / "site")
    token = usage.declare(declaration(usage_api, "python-plugin", env))
    observed = evidence(env.sites[0], dependency_sites=env.sites)
    usage.observe_host(token, observed)
    before = usage.snapshot(env)
    observed.distributions["fixture-sdk"]["version"] = "9.0"
    usage.withdraw(token)
    host = rows(usage, "host", env)
    assert len(host) == 1 and host[0].active
    assert host[0].instance_id is None and host[0].generation is None
    assert host[0].snapshot.versions == {"fixture-sdk": "1.0"}
    assert next(
        use for use in before.uses if use.origin == "host"
    ).snapshot.versions == {
        "fixture-sdk": "1.0",
    }
    assert not fresh_registry.runtime_owners.leases()


def test_refine_retains_exact_token_without_unknown_duplicate(
    usage_api,
    fresh_registry,
    tmp_path,
):
    usage = public_usage(usage_api, fresh_registry)
    token = usage.declare(declaration(usage_api, "admitted", None))
    site = tmp_path / "actual-site"
    usage.refine(token, evidence(site, dependency_sites=(str(site),)))
    uses = rows(usage, "declaration")
    assert len(uses) == 1 and uses[0].source_revision == "old"
    assert uses[0].requirements == ("fixture-sdk==1.0",)
    assert not rows(
        usage,
        env=environment(usage_api, tmp_path / "separate-site"),
    )
    usage.withdraw(token)
    assert not rows(usage)


def test_snapshots_detach_declaration_markers_and_observation_output(
    usage_api,
    fresh_registry,
    tmp_path,
):
    usage = public_usage(usage_api, fresh_registry)
    markers = {**default_environment(), "python_version": "3.12"}
    env = usage_api.DependencyEnvironment(
        sys.executable,
        (str(tmp_path / "site"),),
        markers,
    )
    token = usage.declare(declaration(usage_api, "demo", env))
    markers["python_version"] = "0.0"
    declared = rows(usage, "declaration")[0]
    assert declared.environment.marker_environment["python_version"] == "3.12"
    lease = reserve(fresh_registry, tmp_path)
    usage.bind(lease, token)
    usage.observe(lease, evidence(env.sites[0], dependency_sites=env.sites))
    before = usage.snapshot(None)
    previous = next(use for use in before.uses if use.origin == "runtime")
    prior_version = "1.0"
    try:
        previous.snapshot.distributions["fixture-sdk"]["version"] = "9.0"
        prior_version = "9.0"
    except TypeError:
        pass  # Immutable output evidence also satisfies detached snapshots.
    assert rows(usage, "runtime")[0].snapshot.versions == {
        "fixture-sdk": "1.0",
    }
    usage.observe(
        lease,
        evidence(env.sites[0], version="2.0", dependency_sites=env.sites),
    )
    assert previous.snapshot.versions == {"fixture-sdk": prior_version}
    assert rows(usage, "runtime")[0].snapshot.versions == {
        "fixture-sdk": "2.0",
    }


def test_dependency_site_transport_preserves_legacy_uncertainty(tmp_path):
    legacy = evidence(tmp_path / "site").to_mapping()
    legacy.pop("dependency_sites", None)
    restored = DependencySnapshot.from_mapping(legacy)
    assert hasattr(
        restored,
        "dependency_sites",
    ), "F3.1 actual package-root evidence is missing"
    assert restored.dependency_sites is None
    known_empty = DependencySnapshot.from_mapping(
        {
            **legacy,
            "distributions": {},
            "dependency_sites": [],
        },
    )
    assert known_empty.dependency_sites == ()
    assert known_empty.to_mapping()["dependency_sites"] == []
    for invalid in (["relative"], [str(tmp_path / "not-audited")]):
        with pytest.raises(ValueError):
            DependencySnapshot.from_mapping(
                {**legacy, "dependency_sites": invalid},
            )


def source_digest(root):
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            name = path.relative_to(root).as_posix().encode()
            data = path.read_bytes()
            digest.update(len(name).to_bytes(8, "big"))
            digest.update(name)
            digest.update(len(data).to_bytes(8, "big"))
            digest.update(data)
    return digest.hexdigest()


def install_metadata(site, name, version="1.0"):
    site.mkdir(parents=True, exist_ok=True)
    (site / (name.replace("-", "_") + ".py")).write_text("VALUE = 1\n")
    info = site / (name.replace("-", "_") + "-" + version + ".dist-info")
    info.mkdir()
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
    )
    (info / "top_level.txt").write_text(name.replace("-", "_") + "\n")


def child_environment(root):
    """An independent venv with trusted support installed in its site."""
    import packaging

    venv.EnvBuilder(with_pip=False).create(root)
    python = root / (
        "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
    )
    result = subprocess.run(
        [
            str(python),
            "-I",
            "-c",
            "import sysconfig; print(sysconfig.get_path('purelib'))",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    site = Path(result.stdout.strip())
    shutil.copytree(
        ROOT / "src/qwenpaw/plugins/execution",
        site / "qwenpaw/plugins/execution",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    # The trusted worker acquires its real environment lease before importing
    # plugins. Retain that stdlib-only sibling with the copied runtime.
    shutil.copyfile(
        ROOT / "src/qwenpaw/plugins/dependency_maintenance.py",
        site / "qwenpaw/plugins/dependency_maintenance.py",
    )
    shutil.copytree(
        Path(packaging.__file__).parent,
        site / "packaging",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    install_metadata(site, "f31-child-sdk")
    return python, site


async def audit_child(tmp_path, python, support, *, paths=(), label="child"):
    code = tmp_path / label
    code.mkdir()
    (code / "component.py").write_text(
        "raise AssertionError('audit imported candidate')\n",
    )
    (code / "requirements.txt").write_text("f31-child-sdk==1.0\n")
    spec = PluginLaunchSpec(
        python_executable=str(python),
        support_root=support,
        code_root=code,
        source_revision=source_digest(code),
        plugin_id="f31-" + label,
        instance_id=label,
        generation=1,
        entrypoint="component:Component",
        config={},
        requirements_path=code / "requirements.txt",
        dependency_paths=paths,
    )
    process = PluginProcess()
    try:
        result = await process.audit(spec)
        assert result.cleanup.exited and result.cleanup.residual == ()
        return result.snapshot
    finally:
        assert (await process.stop()).exited


@pytest.mark.asyncio
async def test_actual_child_venvs_share_stdlib_but_not_dependency_sites(
    usage_api,
    fresh_registry,
    tmp_path,
):
    usage = public_usage(usage_api, fresh_registry)
    snapshots = []
    for label in ("venv-a", "venv-b"):
        python, site = child_environment(tmp_path / label)
        observed = await audit_child(
            tmp_path,
            python,
            site,
            label="code-" + label,
        )
        assert str(site.resolve()) in observed.dependency_sites
        assert observed.versions == {"f31-child-sdk": "1.0"}
        assert (
            str(Path(sysconfig.get_path("stdlib")).resolve()) in observed.sites
        )
        assert (
            str(Path(sysconfig.get_path("stdlib")).resolve())
            not in observed.dependency_sites
        )
        token = usage.declare(
            declaration(
                usage_api,
                label,
                None,
                requirements=("f31-child-sdk==1.0",),
            ),
        )
        lease = reserve(fresh_registry, tmp_path, label)
        usage.bind(lease, token)
        usage.observe(lease, observed)
        snapshots.append(observed)
    query = usage_api.DependencyEnvironment(
        snapshots[0].executable,
        snapshots[0].dependency_sites,
        snapshots[0].marker_environment,
    )
    assert {use.plugin_id for use in rows(usage, env=query)} == {"venv-a"}


@pytest.mark.asyncio
async def test_child_keeps_empty_explicit_and_visible_pth_roots(tmp_path):
    python, site = child_environment(tmp_path / "venv")
    empty, custom = tmp_path / "empty-shared-target", tmp_path / "custom-pth"
    empty.mkdir()
    custom.mkdir()
    (site / "visible-custom.pth").write_text(str(custom) + "\n")
    observed = await audit_child(tmp_path, python, site, paths=(empty,))
    assert hasattr(
        observed,
        "dependency_sites",
    ), "F3.1 actual package-root evidence is missing"
    assert {str(site), str(empty), str(custom)} <= set(
        observed.dependency_sites,
    )
    assert not any(
        name.startswith("component") for name in observed.distributions
    )


@pytest.fixture
def loader_host(tmp_path, fresh_registry, monkeypatch):
    from qwenpaw.plugins.loader import PluginLoader

    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_config_path",
        lambda: tmp_path / "config.json",
    )
    return PluginLoader([tmp_path / "plugins"])


def python_source(root, *, plugin="ordinary", body="pass"):
    from qwenpaw.plugins.architecture import PluginManifest

    root.mkdir(parents=True)
    raw = {
        "id": plugin,
        "name": plugin,
        "version": "1.0.0",
        "type": "general",
        "entry": {"backend": "main.py"},
    }
    (root / "plugin.json").write_text(json.dumps(raw))
    (root / "main.py").write_text(body)
    return PluginManifest.from_dict(raw)


@pytest.mark.asyncio
async def test_disabled_python_discovery_is_static_and_has_no_consumer(
    usage_api,
    loader_host,
    tmp_path,
):
    usage = public_usage(usage_api, loader_host.registry)
    source = loader_host.plugin_dirs[0] / "disabled"
    manifest = python_source(
        source,
        plugin="disabled",
        body="raise AssertionError('disabled source imported')\n",
    )
    (source / "requirements.txt").write_text("f31-never-imported-sdk==1.0\n")
    record = await loader_host.load_plugin(
        manifest,
        source,
        {"enabled": False},
    )
    assert record.status == "inactive" and not record.enabled
    assert not rows(usage)
    assert not loader_host.registry.runtime_owners.leases()


@pytest.mark.asyncio
async def test_python_host_records_actual_and_later_imports_before_withdrawal(
    usage_api,
    loader_host,
    tmp_path,
    monkeypatch,
):
    usage = public_usage(usage_api, loader_host.registry)
    site = tmp_path / "host-site"
    for name in ("f31-initial-sdk", "f31-later-sdk", "f31-unused-sdk"):
        install_metadata(site, name)
    monkeypatch.syspath_prepend(str(site))
    source = loader_host.plugin_dirs[0] / "ordinary"
    parsed = python_source(
        source,
        body=(
            "import f31_initial_sdk\n"
            "class Definition:\n"
            "    def register(self, api): pass\n"
            "    def import_later(self):\n"
            "        import f31_later_sdk\n"
            "plugin = Definition()\n"
        ),
    )
    requirements = (
        "f31-initial-sdk==1.0",
        "f31-later-sdk==1.0",
        "f31-unused-sdk==1.0",
    )
    (source / "requirements.txt").write_text("\n".join(requirements) + "\n")
    try:
        record = await loader_host.load_plugin(parsed, source)
        assert record.status == "active", record.diagnostics
        declared = rows(usage, "declaration")
        assert len(declared) == 1 and declared[0].requirements == requirements
        initial = {
            name
            for use in rows(usage, "host")
            if use.snapshot
            for name in use.snapshot.distributions
        }
        assert "f31-initial-sdk" in initial
        assert (
            "f31-later-sdk" not in initial and "f31-unused-sdk" not in initial
        )
        record.instance.import_later()
        assert (
            await loader_host.lifecycle.set_enabled("ordinary", False)
        ).quiescent
        assert not rows(usage, "declaration")
        retained = {
            name
            for use in rows(usage, "host")
            if use.snapshot
            for name in use.snapshot.distributions
        }
        assert {"f31-initial-sdk", "f31-later-sdk"} <= retained
        assert "f31-unused-sdk" not in retained
        assert (
            "f31_initial_sdk" in sys.modules and "f31_later_sdk" in sys.modules
        )
        assert not loader_host.registry.runtime_owners.leases()
    finally:
        if loader_host.get_loaded_plugin("ordinary") is not None:
            await loader_host.unload_plugin("ordinary")
        for name in ("f31_initial_sdk", "f31_later_sdk", "f31_unused_sdk"):
            sys.modules.pop(name, None)


@pytest.mark.asyncio
async def test_ordinary_description_pins_requirements_before_loading(
    usage_api,
    loader_host,
    tmp_path,
    monkeypatch,
):
    usage = public_usage(usage_api, loader_host.registry)
    site = tmp_path / "pinned-sdk-site"
    install_metadata(site, "f31-pinned-sdk")
    monkeypatch.syspath_prepend(str(site))
    source = loader_host.plugin_dirs[0] / "pinned"
    manifest = python_source(
        source,
        plugin="pinned",
        body=(
            "class Definition:\n"
            "    def register(self, api): pass\n"
            "plugin = Definition()\n"
        ),
    )
    (source / "requirements.txt").write_text("f31-pinned-sdk==1.0\n")
    binding = loader_host.backend_resolver.resolve(source, manifest)
    (source / "requirements.txt").write_text("f31-mutated-sdk==9.0\n")
    try:
        record = await loader_host.load_plugin(
            manifest,
            source,
            backend_binding=binding,
            prepared=True,
        )
        assert record.status == "active", record.diagnostics
        declared = rows(usage, "declaration")
        assert len(declared) == 1
        assert declared[0].requirements == ("f31-pinned-sdk==1.0",)
    finally:
        await loader_host.unload_plugin("pinned")
    assert not rows(usage, "declaration")


@pytest.mark.asyncio
async def test_failed_python_candidate_restores_exact_old_declaration(
    usage_api,
    loader_host,
    tmp_path,
    monkeypatch,
):
    usage = public_usage(usage_api, loader_host.registry)
    site = tmp_path / "site"
    install_metadata(site, "f31-rollback-sdk")
    monkeypatch.syspath_prepend(str(site))
    source = loader_host.plugin_dirs[0] / "rollback"
    parsed = python_source(
        source,
        plugin="rollback",
        body=(
            "class Definition:\n"
            "    def register(self, api): pass\n"
            "plugin = Definition()\n"
        ),
    )
    (source / "requirements.txt").write_text("f31-rollback-sdk==1.0\n")
    candidate = tmp_path / "candidate"
    python_source(
        candidate,
        plugin="rollback",
        body=(
            "class Definition:\n"
            "    def register(self, api):\n"
            "        raise RuntimeError('F31_CANDIDATE_REJECTED')\n"
            "plugin = Definition()\n"
        ),
    )
    (candidate / "requirements.txt").write_text("f31-rollback-sdk>=1.0\n")
    try:
        assert (
            await loader_host.load_plugin(parsed, source)
        ).status == "active"
        old = rows(usage, "declaration")[0]
        report = await loader_host.lifecycle.reload(
            "rollback",
            new_source=candidate,
        )
        assert not report.ok and not report.needs_restart, report.errors
        assert loader_host.get_loaded_plugin("rollback").status == "active"
        assert (
            source / "requirements.txt"
        ).read_text() == "f31-rollback-sdk==1.0\n"
        restored = rows(usage, "declaration")
        assert len(restored) == 1
        assert restored[0].source_revision == old.source_revision
        assert restored[0].requirements == ("f31-rollback-sdk==1.0",)
    finally:
        await loader_host.unload_plugin("rollback")
    assert not rows(usage, "declaration")


@pytest.mark.asyncio
async def test_host_registered_non_channel_admission_uses_same_registry(
    usage_api,
    loader_host,
    tmp_path,
):
    from qwenpaw.plugins.architecture import PluginManifest, PluginType
    from qwenpaw.plugins.execution_backend import (
        DefinitionResult,
        PluginDescription,
    )

    usage = public_usage(usage_api, loader_host.registry)
    source = loader_host.plugin_dirs[0] / "non-channel"
    python_source(
        source,
        plugin="non-channel",
        body="raise AssertionError('Python fallback imported')\n",
    )
    (source / "requirements.txt").write_text("f31-custom-component-sdk==1.0\n")
    (source / "definition.json").write_text("{}")
    raw = json.loads((source / "plugin.json").read_text())
    raw["entry"] = {"descriptor": "definition.json"}
    (source / "plugin.json").write_text(json.dumps(raw))
    site = tmp_path / "custom-sdk-site"
    install_metadata(site, "f31-custom-component-sdk")
    install_metadata(site, "f31-child-sdk")
    actual = await audit_child(
        tmp_path,
        sys.executable,
        ROOT / "src",
        paths=(site,),
        label="custom-evidence",
    )
    audits = 0

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
            return actual

        async def audit_dependencies(self, description):
            nonlocal audits
            audits += 1
            return await audit_child(
                tmp_path,
                sys.executable,
                ROOT / "src",
                paths=(site,),
                label=f"custom-final-evidence-{audits}",
            )

        async def load_definition(
            self,
            description,
            config,
            *,
            saved_definition=None,
        ):
            pending = rows(usage, "declaration")
            assert len(pending) == 1 and pending[0].plugin_id == "non-channel"
            assert pending[0].requirements == (
                "f31-custom-component-sdk==1.0",
            )
            return DefinitionResult(SimpleNamespace(register=lambda api: None))

        async def before_activate(self, description):
            pass

        def validate_update(self, old, candidate, *, in_place):
            pass

        def capture_restore_state(self, record):
            return None

        def restore_state(self, state):
            pass

    loader_host.backend_resolver.register_descriptor(
        PluginType.GENERAL,
        TrustedAdapter(),
    )
    try:
        record = await loader_host.load_plugin(
            PluginManifest.from_dict(raw),
            source,
        )
        assert record.status == "active", record.diagnostics
        assert len(rows(usage, "declaration")) == 1
        assert not rows(usage, "host")
    finally:
        await loader_host.unload_plugin("non-channel")
    assert not rows(usage)


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["channel", "python"])
@pytest.mark.parametrize(
    "stop_fails",
    [False, True],
    ids=["stopped", "retained"],
)
async def test_observation_failure_cannot_skip_owned_preparation_stop(
    usage_api,
    loader_host,
    tmp_path,
    monkeypatch,
    backend,
    stop_fails,
):
    """The evidence observer fails only in finally, after evidence is saved."""
    from qwenpaw.plugins.execution.process import InspectionResult, StopResult

    usage = public_usage(usage_api, loader_host.registry)
    owners = loader_host.registry.runtime_owners
    site = tmp_path / "audit-site"
    site.mkdir()
    observed = evidence(site, dependency_sites=(str(site),))
    source = tmp_path / "preparation-source"
    source.mkdir()
    requirements = source / "requirements.txt"
    requirements.write_text("fixture-sdk==1.0\n")
    events = []
    processes = []
    native_observe = usage.observe

    def observe_then_fail(lease, snapshot):
        events.append("observe")
        assert lease in owners.leases()
        if processes[-1].finalizing:
            events.append("finally-observer-failure")
            raise RuntimeError("F31_FINALLY_OBSERVER_FAILURE")
        native_observe(lease, snapshot)

    monkeypatch.setattr(usage, "observe", observe_then_fail)

    class PreparationProcess:
        def __init__(self):
            self._snapshot = None
            self.finalizing = False
            self.stop_fails = stop_fails
            processes.append(self)

        @property
        def dependency_snapshot(self):
            self.finalizing = True
            return self._snapshot

        @dependency_snapshot.setter
        def dependency_snapshot(self, snapshot):
            self._snapshot = snapshot

        async def audit(self, spec):
            events.append("audit")
            self.dependency_snapshot = observed
            if backend == "channel":
                self.dependency_observer(observed)
            return InspectionResult(observed, None, StopResult(True, 0, False))

        async def stop(self):
            events.append("stop")
            return StopResult(
                not self.stop_fails,
                None if self.stop_fails else 0,
                False,
                ("controlled-child",) if self.stop_fails else (),
            )

    if backend == "channel":
        from qwenpaw.plugins.architecture import PluginManifest
        from qwenpaw.plugins.channel_adapter import ChannelRuntimeSettings

        raw = json.loads(
            (ROOT / "plugins/channel/feishu/plugin.json").read_text(),
        )
        raw.pop("qwenpaw_version", None)
        raw["dependencies"] = ["fixture-sdk==1.0"]
        (source / "plugin.json").write_text(json.dumps(raw))
        shutil.copyfile(
            ROOT / "plugins/channel/feishu/channel.json",
            source / "channel.json",
        )
        monkeypatch.setattr(
            "qwenpaw.app.channels.process_supervisor.ChannelProcess",
            PreparationProcess,
        )
        loader_host.registry.configure_channel_runtime(
            ChannelRuntimeSettings(
                python_executable=sys.executable,
                support_root=ROOT / "src",
                qwenpaw_version="2.2.2b4",
                selected_channels=frozenset({"feishu"}),
            ),
        )
        binding = loader_host.backend_resolver.resolve(
            source,
            PluginManifest.from_dict(raw),
        )
        plugin_id = "feishu"
        operation = loader_host._prepare_channel_candidate(
            binding.description.payload,
            probe=False,
        )
    else:
        monkeypatch.setattr(
            "qwenpaw.plugins.execution.PluginProcess",
            PreparationProcess,
        )
        plugin_id = "ordinary-preparation"
        operation = loader_host._prepare_python_dependencies(
            requirements,
            plugin_id,
        )
    try:
        with pytest.raises(RuntimeError):
            await operation
        assert events.count("finally-observer-failure") == 1, events
        assert events.index("finally-observer-failure") < events.index(
            "stop",
        ), events
        assert (
            events.count("stop") == 1
        ), "observer failure skipped the actual attached stop adapter"
        assert not rows(usage, "declaration")
        held = owners.leases(plugin_id)
        runtime = rows(usage, "runtime")
        if stop_fails:
            assert len(held) == 1 and len(runtime) == 1
            assert runtime[0].instance_id == held[0].instance_id
            assert runtime[0].requirements == ("fixture-sdk==1.0",)
            assert runtime[0].snapshot.versions == {"fixture-sdk": "1.0"}
        else:
            assert not held and not runtime
    finally:
        for process in processes:
            process.stop_fails = False
        await owners.stop_all(plugin_id)


@pytest.mark.parametrize("module_kind", ["flat", "namespace"])
@pytest.mark.parametrize(
    "unrelated_other_drive",
    [False, True],
    ids=["same_drive", "other_drive"],
)
def test_record_without_top_level_identifies_actual_import_only(
    usage_api,
    fresh_registry,
    tmp_path,
    monkeypatch,
    module_kind,
    unrelated_other_drive,
):
    from qwenpaw.plugins.python_backend import PythonBackend

    usage = public_usage(usage_api, fresh_registry)
    site = tmp_path / "record-site"
    site.mkdir()
    if module_kind == "flat":
        imported_name = "f31_record_actual"
        actual_file, unused_file = (
            "f31_record_actual.py",
            "f31_record_unused.py",
        )
    else:
        imported_name = "f31_record_namespace.actual"
        actual_file = "f31_record_namespace/actual.py"
        unused_file = "f31_record_namespace/unused.py"
        (site / "f31_record_namespace").mkdir()
    for dist, filename in (
        ("f31-record-owner", actual_file),
        ("f31-record-control", unused_file),
    ):
        (site / filename).write_text("VALUE = 'actual-local-sdk'\n")
        info = site / (dist.replace("-", "_") + "-1.0.dist-info")
        info.mkdir()
        (info / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {dist}\nVersion: 1.0\n",
        )
        # Both valid distributions intentionally omit top_level.txt.
        (info / "RECORD").write_text(
            f"{filename},,\n{info.name}/METADATA,,\n{info.name}/RECORD,,\n",
        )
    monkeypatch.syspath_prepend(str(site))
    token = usage.declare(
        declaration(
            usage_api,
            "record-host",
            None,
            requirements=("f31-record-owner==1.0", "f31-record-control==1.0"),
        ),
    )
    try:
        module = importlib.import_module(imported_name)
        assert (
            Path(module.__file__).resolve() == (site / actual_file).resolve()
        )
        with monkeypatch.context() as patch:
            if unrelated_other_drive:
                unrelated = tmp_path / "other-drive"
                unrelated.mkdir()
                (unrelated / "f31_unrelated_drive_module.py").write_text(
                    "VALUE = 'unrelated'\n",
                )
                patch.syspath_prepend(str(unrelated))
                other = importlib.import_module("f31_unrelated_drive_module")
                other_origin = Path(other.__file__).resolve()
                native_relpath = os.path.relpath

                def different_drive_relpath(path, start=os.curdir):
                    if Path(path).resolve() == other_origin:
                        # Models ntpath.relpath's different-drive ValueError.
                        raise ValueError(
                            "path is on mount 'C:', start on mount 'D:'",
                        )
                    return native_relpath(path, start)

                patch.setattr(os.path, "relpath", different_drive_relpath)
            PythonBackend.observe_host_dependencies(
                SimpleNamespace(source_path=tmp_path / "plugin"),
                usage,
                token,
            )
        usage.withdraw(token)
        assert not rows(usage, "declaration")
        hosts = rows(usage, "host")
        captured = {
            name
            for use in hosts
            if use.snapshot
            for name in use.snapshot.distributions
        }
        assert "f31-record-owner" in captured
        assert "f31-record-control" not in captured
        owner = next(
            use
            for use in hosts
            if use.snapshot
            and "f31-record-owner" in use.snapshot.distributions
        )
        assert (
            owner.source_revision == "old" and owner.plugin_id == "record-host"
        )
        assert owner.snapshot.versions["f31-record-owner"] == "1.0"
        assert owner.instance_id is None and owner.generation is None
        assert not fresh_registry.runtime_owners.leases()
    finally:
        usage.withdraw(token)
        for name in (
            imported_name,
            "f31_record_namespace",
            "f31_unrelated_drive_module",
        ):
            sys.modules.pop(name, None)


@pytest.mark.asyncio
async def test_failed_host_refresh_retains_versions_with_unknown_environment(
    usage_api,
    loader_host,
    tmp_path,
    monkeypatch,
):
    from qwenpaw.plugins.execution import dependencies

    usage = public_usage(usage_api, loader_host.registry)
    initial, later = tmp_path / "initial-site", tmp_path / "later-site"
    install_metadata(initial, "f31-refresh-initial-sdk", version="1.7")
    install_metadata(later, "f31-refresh-later-sdk", version="3.2")
    monkeypatch.syspath_prepend(str(initial))
    source = loader_host.plugin_dirs[0] / "refresh-host"
    manifest = python_source(
        source,
        plugin="refresh-host",
        body=(
            "import f31_refresh_initial_sdk\n"
            "class Definition:\n"
            "    def register(self, api): pass\n"
            "    def import_later(self):\n"
            "        import f31_refresh_later_sdk\n"
            "plugin = Definition()\n"
        ),
    )
    (source / "requirements.txt").write_text("f31-refresh-initial-sdk==1.7\n")
    failures = []

    def unavailable_inventory(packet):
        failures.append(packet["code_root"])
        raise ValueError("F31_CONTROLLED_HOST_REFRESH_FAILURE")

    try:
        record = await loader_host.load_plugin(manifest, source)
        assert record.status == "active", record.diagnostics
        before = rows(usage, "host")[0]
        assert before.environment is not None
        assert str(initial) in before.environment.sites
        assert str(later) not in before.environment.sites
        assert before.snapshot.versions["f31-refresh-initial-sdk"] == "1.7"
        monkeypatch.syspath_prepend(str(later))
        record.instance.import_later()
        assert "f31_refresh_later_sdk" in sys.modules
        with monkeypatch.context() as patch:
            patch.setattr(
                dependencies,
                "observe_dependencies",
                unavailable_inventory,
            )
            report = await loader_host.lifecycle.set_enabled(
                "refresh-host",
                False,
            )
        assert report.quiescent and failures == [str(source)]
        assert not rows(usage, "declaration")
        retained = rows(usage, "host")[0]
        assert retained.snapshot.versions["f31-refresh-initial-sdk"] == "1.7"
        assert retained.source_revision == before.source_revision
        assert retained.requirements == ("f31-refresh-initial-sdk==1.7",)
        assert (
            retained.environment is None
        ), "failed collection cannot attest complete old roots"
        included = rows(usage, "host", environment(usage_api, later))
        assert len(included) == 1 and included[0].plugin_id == "refresh-host"
        assert (
            included[0].snapshot.versions["f31-refresh-initial-sdk"] == "1.7"
        )
        assert (
            included[0].instance_id is None and included[0].generation is None
        )
        assert (
            before.environment is not None
        )  # Earlier snapshot stays detached.
        assert not loader_host.registry.runtime_owners.leases()
    finally:
        if loader_host.get_loaded_plugin("refresh-host") is not None:
            await loader_host.unload_plugin("refresh-host")
        for name in ("f31_refresh_initial_sdk", "f31_refresh_later_sdk"):
            sys.modules.pop(name, None)
