# -*- coding: utf-8 -*-
"""Trusted active roots, separate consumer inventories and bounded workers."""

import asyncio
import importlib
from importlib import metadata
import importlib.util
import json
import os
from pathlib import Path
import shutil
import site
import statistics
import subprocess
import sys
import sysconfig
from types import SimpleNamespace
import venv

import psutil
import pytest

from qwenpaw.plugins import dependency_gate as gate
from qwenpaw.plugins.channel_bootstrap import resolve_default_channel_runtime
from qwenpaw.plugins.dependency_usage import (
    DependencyDeclaration,
    DependencyUsageRegistry,
)
from qwenpaw.plugins.execution import PluginLaunchSpec, PluginProcess
from qwenpaw.plugins.execution.bootstrap import _hash_code_root
from qwenpaw.plugins.execution.dependencies import observe_dependencies
from qwenpaw.plugins.ownership import RuntimeOwners
from qwenpaw.plugins.python_backend import PythonBackend

ROOT = Path(__file__).resolve().parents[3]
WORKER = Path(__file__).with_name("worker.py")


def install(root, name, version="1.0", requires=(), module=None, body=None):
    root.mkdir(parents=True, exist_ok=True)
    module = module or name.replace("-", "_")
    (root / f"{module}.py").write_text(body or "VALUE = 'user-site-sdk'\n")
    info = root / f"{name.replace('-', '_')}-{version}.dist-info"
    info.mkdir(exist_ok=True)
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
        + "".join(f"Requires-Dist: {value}\n" for value in requires),
    )
    (info / "top_level.txt").write_text(module + "\n")
    (info / "RECORD").write_text(f"{module}.py,,\n{info.name}/METADATA,,\n")
    return info


@pytest.fixture(name="user_site")
def user_site_fixture(tmp_path, monkeypatch):
    root = tmp_path / "user-site"
    install(root, "shared-fixture-sdk")
    monkeypatch.setattr(site, "ENABLE_USER_SITE", True)
    monkeypatch.setattr(site, "getusersitepackages", lambda: str(root))
    monkeypatch.setattr(sys, "path", [*sys.path, str(root)])
    return root


def launch(tmp_path, *, paths=(), requirements="", label="worker"):
    code = tmp_path / label
    code.mkdir()
    shutil.copyfile(WORKER, code / "worker.py")
    reqs = code / "requirements.txt"
    reqs.write_text(requirements)
    return PluginLaunchSpec(
        python_executable=sys.executable,
        support_root=ROOT / "src",
        code_root=code,
        source_revision=_hash_code_root(code),
        plugin_id="shared-fixture",
        instance_id=label,
        generation=1,
        entrypoint="worker:Worker",
        config={},
        requirements_path=reqs,
        dependency_paths=tuple(paths),
        startup_timeout=3,
        shutdown_timeout=0.4,
    )


async def report(process, **params):
    return await process.call("fixture.report", params, timeout=3)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "retained",
        "top-level",
        "non-wheel",
        "wrong-name",
        "wrong-version",
        "missing-child",
        "child-closure",
    ],
)
async def test_actual_worker_retained_wheel_url_checks_identity_and_closure(
    tmp_path, case
):
    from qwenpaw.plugins.execution.process import ProcessError

    target = tmp_path / "site"
    install(target, "url-leaf")
    if case != "missing-child":
        install(
            target,
            "url-child",
            requires=(
                "url-leaf>=2" if case == "child-closure" else "url-leaf==1",
            ),
        )
    filename = {
        "non-wheel": "url_child-1.0.tar.gz",
        "wrong-name": "url_leaf-1.0-py3-none-any.whl",
        "wrong-version": "url_child-2.0-py3-none-any.whl",
    }.get(case, "url_child-1.0-py3-none-any.whl")
    edge = "url-child @ " + (tmp_path / filename).as_uri()
    install(target, "url-parent", requires=(edge,))
    spec = launch(
        tmp_path,
        paths=(target,),
        requirements=(edge if case == "top-level" else "url-parent==1") + "\n",
    )
    before = {
        str(path.relative_to(target)): path.read_bytes()
        for path in target.rglob("*")
        if path.is_file()
    }
    process = PluginProcess()
    try:
        if case == "retained":
            assert (await process.start(spec))["state"] == "ready"
            actual = await report(process)
            assert actual["versions"] == {
                "url-parent": "1.0",
                "url-child": "1.0",
                "url-leaf": "1.0",
            }
            assert actual["blocked"] == []
        else:
            with pytest.raises(ProcessError) as caught:
                await process.start(spec)
            # Top-level URLs are refused before the dependency handshake.
            expected = (
                "WORKER_START_FAILED"
                if case == "top-level"
                else "DEPENDENCY_UNSATISFIED"
            )
            assert caught.value.reason_code == expected
    finally:
        receipt = await process.stop()
        assert receipt.exited and not receipt.residual
    after = {
        str(path.relative_to(target)): path.read_bytes()
        for path in target.rglob("*")
        if path.is_file()
    }
    assert after == before


@pytest.mark.asyncio
async def test_default_runtime_finds_active_user_site_in_actual_worker(
    tmp_path,
    user_site,
):
    runtime = resolve_default_channel_runtime()
    assert user_site.resolve() in runtime.dependency_paths
    assert runtime.dependency_install_target != user_site.resolve()
    spec = launch(
        tmp_path,
        paths=runtime.dependency_paths,
        requirements="shared-fixture-sdk==1.0\n",
    )
    process = PluginProcess()
    try:
        result = await process.start(spec)
        assert result["state"] == "ready", result
        actual = await report(process, sdk=True)
        assert actual["sdk"] == "user-site-sdk" and actual["isolated"] == 1
        assert actual["blocked"] == []
        assert "shared_fixture_sdk" not in sys.modules
    finally:
        assert (await process.stop()).exited


@pytest.mark.asyncio
async def test_ordinary_python_preparation_reads_active_user_site(
    tmp_path,
    user_site,
    monkeypatch,
):
    from qwenpaw.plugins.loader import PluginLoader

    code = tmp_path / "ordinary"
    code.mkdir()
    reqs = code / "requirements.txt"
    reqs.write_text("shared-fixture-sdk==1.0\n")
    loader = PluginLoader([code])
    environment = tmp_path / "python-environment"
    await asyncio.to_thread(
        venv.EnvBuilder(system_site_packages=True, with_pip=False).create,
        environment,
    )
    monkeypatch.setattr(sys, "executable", str(environment / "bin/python"))
    targets = []
    native_prepare = gate.prepare_shared_dependencies

    async def capture_target(
        *args,
        plugin_id,
        requirements_file,
        usage_registry,
        **kwargs,
    ):
        targets.append(kwargs["install_target"])
        return await native_prepare(
            *args,
            plugin_id=plugin_id,
            requirements_file=requirements_file,
            usage_registry=usage_registry,
            **kwargs,
        )

    async def no_acquisition(*args):
        raise AssertionError(
            "Satisfied user-site dependency attempted acquisition",
        )

    monkeypatch.setattr(loader, "_acquire_dependency_wheels", no_acquisition)
    monkeypatch.setattr(gate, "prepare_shared_dependencies", capture_target)
    # This regression drives the existing preparation consumer directly.
    # pylint: disable-next=protected-access
    decision = await loader._prepare_python_dependencies(reqs, "ordinary")
    assert decision.already_satisfied
    assert not loader.registry.runtime_owners.leases()
    assert "shared_fixture_sdk" not in sys.modules
    assert targets and all(
        target is not None
        and target.is_relative_to(environment)
        and target != user_site
        for target in targets
    ), targets


def shared_paths():
    spec = importlib.util.find_spec("qwenpaw.plugins.execution.environment")
    assert spec is not None, "Common trusted environment resolver is missing"
    return importlib.import_module(spec.name).shared_dependency_paths()


def test_shared_roots_follow_active_order_and_canonical_aliases(
    tmp_path,
    monkeypatch,
):
    user, first, second, cwd, plugin = (
        tmp_path / name
        for name in ("user", "first", "second", "cwd", "plugin")
    )
    for root in (user, first, second, cwd, plugin):
        root.mkdir()
    user_alias, second_alias = (
        tmp_path / "user-alias",
        tmp_path / "second-alias",
    )
    user_alias.symlink_to(user, target_is_directory=True)
    second_alias.symlink_to(second, target_is_directory=True)
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(site, "ENABLE_USER_SITE", True)
    monkeypatch.setattr(site, "getusersitepackages", lambda: str(user))
    monkeypatch.setattr(
        site,
        "getsitepackages",
        lambda: [str(first), str(second)],
    )
    native_get_path = sysconfig.get_path
    monkeypatch.setattr(
        sysconfig,
        "get_path",
        lambda name, *args, **kwargs: (
            str(first if name == "purelib" else second)
            if name in {"purelib", "platlib"}
            else native_get_path(name, *args, **kwargs)
        ),
    )
    monkeypatch.setattr(
        sys,
        "path",
        [
            "",
            str(cwd),
            str(plugin),
            str(user_alias),
            str(second_alias),
            str(first),
            str(user),
            str(second),
            str(tmp_path / "missing"),
        ],
    )
    assert shared_paths() == (
        user.resolve(),
        second.resolve(),
        first.resolve(),
    )


@pytest.mark.parametrize(
    "enabled,active",
    [(False, True), (None, True), (True, False)],
)
def test_default_runtime_excludes_disabled_or_inactive_user_site(
    user_site,
    monkeypatch,
    enabled,
    active,
):
    monkeypatch.setattr(site, "ENABLE_USER_SITE", enabled)
    if not active:
        monkeypatch.setattr(
            sys,
            "path",
            [path for path in sys.path if path != str(user_site)],
        )
    runtime = resolve_default_channel_runtime()
    assert user_site.resolve() not in runtime.dependency_paths
    assert user_site.resolve() not in shared_paths()


def test_real_current_venv_resolves_only_its_active_installation_root(
    tmp_path,
):
    environment = tmp_path / "venv"
    venv.EnvBuilder(with_pip=False).create(environment)
    script = (
        "\n"
        "import importlib.util,json,sys,sysconfig\n"
        "from pathlib import Path\n"
        "spec = importlib.util.spec_from_file_location('trusted_envir"
        "onment', sys.argv[1])\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
        "assert sys.prefix != sys.base_prefix\n"
        "print(json.dumps({'paths': [str(root) for root in module.sha"
        "red_dependency_paths()],\n"
        "                  'purelib': sysconfig.get_path('purelib')})"
        ")\n"
    )
    result = subprocess.run(
        [
            str(environment / "bin/python"),
            "-I",
            "-c",
            script,
            str(ROOT / "src/qwenpaw/plugins/execution/environment.py"),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    actual = json.loads(result.stdout)
    assert actual["paths"] == [str(Path(actual["purelib"]).resolve())]
    assert all(
        Path(path).is_relative_to(environment) for path in actual["paths"]
    )


def test_frozen_default_runtime_uses_explicit_manifest_roots_only(
    tmp_path,
    user_site,
    monkeypatch,
):
    import qwenpaw.plugins.channel_bootstrap as bootstrap

    explicit = tmp_path / "frozen-manifest-site"
    explicit.mkdir()
    identity = {
        "version": list(sys.version_info[:2]),
        "system": "Darwin",
        "machine": "arm64",
    }
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        bootstrap,
        "runtime_manifest",
        lambda: (
            Path(sys.executable),
            ROOT / "src",
            (explicit,),
            identity,
            (),
        ),
    )
    runtime = resolve_default_channel_runtime()
    assert runtime.dependency_paths == (
        explicit,
        runtime.dependency_install_target,
    )
    assert runtime.runtime_identity == identity
    assert user_site not in runtime.dependency_paths


@pytest.mark.asyncio
async def test_actual_worker_preserves_stdlib_priority_without_executing_pth(
    tmp_path,
):
    root = tmp_path / "shared-site"
    install(root, "shared-fixture-sdk")
    sentinel = tmp_path / "pth-executed"
    (root / "payload.pth").write_text(
        f"import pathlib; pathlib.Path({str(sentinel)!r}).touch()\n",
    )
    (root / "colorsys.py").write_text(
        "raise AssertionError('stdlib shadow imported')\n",
    )
    spec = launch(
        tmp_path,
        paths=(root,),
        requirements="shared-fixture-sdk==1.0\n",
    )
    process = PluginProcess()
    try:
        assert (await process.start(spec))["state"] == "ready"
        actual = await report(process, sdk=True, stdlib=True)
        assert actual["sdk"] == "user-site-sdk"
        assert Path(actual["stdlib"]).is_relative_to(
            sysconfig.get_path("stdlib"),
        )
        assert not sentinel.exists()
        assert actual["blocked"] == []
    finally:
        assert (await process.stop()).exited


def test_worker_configure_keeps_explicit_sdk_ahead_of_inherited_addon(
    tmp_path,
):
    code, explicit, inherited = (
        tmp_path / name for name in ("code", "explicit", "inherited-addon")
    )
    for path in (code, explicit, inherited):
        path.mkdir()
    (explicit / "shared_priority_probe.py").write_text("VALUE = 'trusted'\n")
    (inherited / "shared_priority_probe.py").write_text("VALUE = 'wrong'\n")
    (explicit / "colorsys.py").write_text(
        "raise AssertionError('stdlib shadow')\n",
    )
    script = (
        "\n"
        "import importlib.util,json,sys\n"
        "from pathlib import Path\n"
        "support, code, explicit, inherited = map(Path, sys.argv[1:])"
        "\n"
        "spec = importlib.util.spec_from_file_location('real_executio"
        "n_worker',\n"
        "    support / 'qwenpaw/plugins/execution/worker.py')\n"
        "worker = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(worker)\n"
        "boot = worker._sibling('bootstrap')\n"
        "# Model an add-on directory already appended by global site "
        "initialization.\n"
        "sys.path.append(str(inherited))\n"
        "worker._configure(boot, {'code_root': str(code), 'support_ro"
        "ot': str(support),\n"
        "    'dependency_paths': [str(explicit)], 'startup_timeout': 3}, ())\n"
        "import shared_priority_probe,colorsys\n"
        "print(json.dumps({'sdk': shared_priority_probe.VALUE,\n"
        "    'stdlib': str(Path(colorsys.__file__).resolve()), 'isola"
        "ted': sys.flags.isolated}))\n"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            script,
            str(ROOT / "src"),
            str(code),
            str(explicit),
            str(inherited),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    actual = json.loads(result.stdout)
    assert actual["isolated"] == 1
    assert Path(actual["stdlib"]).is_relative_to(sysconfig.get_path("stdlib"))
    assert actual["sdk"] == "trusted", actual


def test_worker_configure_preserves_stdlib_when_site_packages_reports_prefix(
    tmp_path,
):
    code, explicit = tmp_path / "code", tmp_path / "explicit"
    code.mkdir()
    explicit.mkdir()
    (explicit / "colorsys.py").write_text("VALUE = 'SDK shadow'\n")
    script = """
import importlib.util,json,site,sys,sysconfig
from pathlib import Path
support, code, explicit = map(Path, sys.argv[1:])
spec = importlib.util.spec_from_file_location('real_execution_worker',
    support / 'qwenpaw/plugins/execution/worker.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)
boot = worker._sibling('bootstrap')
assert 'colorsys' not in sys.modules
prefix = Path(sys.base_prefix).resolve()
assert Path(sysconfig.get_path('stdlib')).resolve().is_relative_to(prefix)
# CPython on Windows reports the installation prefix itself as a site root.
site.getsitepackages = lambda: [str(prefix)]
worker._configure(boot, {'code_root': str(code), 'support_root': str(support),
    'dependency_paths': [str(explicit)], 'startup_timeout': 3}, ())
import colorsys
print(json.dumps({'stdlib': str(Path(colorsys.__file__).resolve()),
    'isolated': sys.flags.isolated}))
"""
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            script,
            str(ROOT / "src"),
            str(code),
            str(explicit),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    actual = json.loads(result.stdout)
    assert actual["isolated"] == 1
    assert Path(actual["stdlib"]).is_relative_to(
        sysconfig.get_path("stdlib"),
    ), actual


@pytest.mark.asyncio
async def test_raw_launch_does_not_inherit_parent_or_active_user_site(
    tmp_path,
    user_site,
    monkeypatch,
):
    arbitrary = tmp_path / "arbitrary-parent"
    install(arbitrary, "shared-parent-only")
    monkeypatch.syspath_prepend(str(arbitrary))
    spec = launch(tmp_path)
    process = PluginProcess()
    try:
        assert (await process.start(spec))["state"] == "ready"
        actual = await report(process)
        paths = {str(Path(path).resolve()) for path in actual["paths"]}
        assert str(user_site.resolve()) not in paths
        assert str(arbitrary.resolve()) not in paths
        assert (
            "shared-fixture-sdk"
            not in process.dependency_snapshot.distributions
        )
        assert (
            "shared-parent-only"
            not in process.dependency_snapshot.distributions
        )
        assert actual["versions"] == {} and actual["isolated"] == 1
    finally:
        assert (await process.stop()).exited


@pytest.mark.asyncio
async def test_actual_worker_retains_only_required_version_closure(tmp_path):
    root = tmp_path / "shared-site"
    install(root, "shared-fixture-sdk", requires=("shared-leaf==2.0",))
    install(root, "shared-leaf", "2.0")
    install(
        root,
        "shared-unused",
        body="raise AssertionError('unused imported')\n",
    )
    spec = launch(
        tmp_path,
        paths=(root,),
        requirements="shared-fixture-sdk==1.0\n",
    )
    process = PluginProcess()
    try:
        result = await process.start(spec)
        assert result["state"] == "ready", result
        actual = await report(process)
        assert actual["versions"] == {
            "shared-fixture-sdk": "1.0",
            "shared-leaf": "2.0",
        }
        assert not {
            "shared_fixture_sdk",
            "shared_leaf",
            "shared_unused",
        }.intersection(
            actual["modules"],
        )
        assert {"shared-fixture-sdk", "shared-leaf", "shared-unused"} <= set(
            process.dependency_snapshot.distributions,
        ), "Full startup audit evidence must remain available to the host"
    finally:
        assert (await process.stop()).exited


def observed_host(tmp_path, monkeypatch):
    shared, parent_user = (
        tmp_path / "shared-site",
        tmp_path / "parent-user-site",
    )
    install(shared, "shared-loaded-agent", requires=("shared-fixture-pdf>=6",))
    install(shared, "shared-fixture-sdk")
    install(parent_user, "shared-fixture-pdf", "6.1")
    usage = DependencyUsageRegistry(RuntimeOwners())
    token = usage.declare(DependencyDeclaration("host-agent", "old", (), None))
    module_spec = importlib.util.spec_from_file_location(
        "shared_loaded_agent",
        shared / "shared_loaded_agent.py",
    )
    module = importlib.util.module_from_spec(module_spec)
    monkeypatch.setitem(sys.modules, "shared_loaded_agent", module)
    module_spec.loader.exec_module(module)
    with monkeypatch.context() as patch:
        patch.setattr(sys, "path", [str(shared), str(parent_user)])
        full = observe_dependencies(
            {
                "code_root": str(tmp_path / "host-plugin"),
                "_audit_sites": sys.path,
                "dependency_paths": (),
            },
        )
        assert full.versions["shared-fixture-pdf"] == "6.1"
        PythonBackend.observe_host_dependencies(
            SimpleNamespace(source_path=tmp_path / "host-plugin"),
            usage,
            token,
        )
    return usage, token, shared, parent_user


@pytest.mark.asyncio
async def test_host_loaded_pin_uses_unimported_parent_transitive_inventory(
    tmp_path,
    monkeypatch,
):
    usage, token, shared, _parent_user = observed_host(tmp_path, monkeypatch)
    usage.withdraw(token)
    hosts = [use for use in usage.snapshot().uses if use.origin == "host"]
    assert len(hosts) == 1
    assert hosts[0].snapshot.versions == {"shared-loaded-agent": "1.0"}
    assert "shared_fixture_pdf" not in sys.modules
    spec = launch(
        tmp_path,
        paths=(shared,),
        requirements="shared-fixture-sdk==1.0\n",
    )
    process = PluginProcess()
    try:
        child = (await process.audit(spec)).snapshot
        assert "shared-fixture-pdf" not in child.distributions
        decision = gate.evaluate_shared_dependencies(
            spec.requirements_path,
            child,
            plugin_id="candidate",
            uses=hosts,
        )
        assert decision.already_satisfied, decision.reason
        assert hosts[0].snapshot.versions == {"shared-loaded-agent": "1.0"}
        assert "shared_fixture_pdf" not in sys.modules
    finally:
        assert (await process.stop()).exited


@pytest.mark.asyncio
async def test_stale_child_cannot_replace_fresh_host_requirement_metadata(
    tmp_path,
    monkeypatch,
):
    usage, token, shared, parent_user = observed_host(tmp_path, monkeypatch)
    spec = launch(
        tmp_path,
        paths=(shared, parent_user),
        requirements="shared-fixture-sdk==1.0\n",
    )
    process = PluginProcess()
    try:
        stale_child = (await process.audit(spec)).snapshot
        assert stale_child.distributions["shared-loaded-agent"][
            "requires_dist"
        ] == ("shared-fixture-pdf>=6",)
        (shared / "shared_loaded_agent-1.0.dist-info/METADATA").write_text(
            "Metadata-Version: 2.1\nName: shared-loaded-agent\nVersion: 1.0\n"
            "Requires-Dist: shared-fixture-pdf>=7\n",
        )
        usage.withdraw(token)
        hosts = [use for use in usage.snapshot().uses if use.origin == "host"]
        assert hosts[0].snapshot.versions == {"shared-loaded-agent": "1.0"}
        fresh_child = (await process.audit(spec)).snapshot
        fresh = gate.evaluate_shared_dependencies(
            spec.requirements_path,
            fresh_child,
            plugin_id="candidate",
            uses=hosts,
        )
        assert not fresh.already_satisfied
        assert fresh.reason_code == "DEPENDENCY_RESTART_REQUIRED"
        assert "shared-fixture-pdf>=7" in fresh.missing
        stale = gate.evaluate_shared_dependencies(
            spec.requirements_path,
            stale_child,
            plugin_id="candidate",
            uses=hosts,
        )
        assert not stale.already_satisfied, stale.reason
        assert stale.reason_code == fresh.reason_code
        assert "shared-fixture-pdf>=7" in stale.missing
        assert "shared_fixture_pdf" not in sys.modules
    finally:
        usage.withdraw(token)
        assert (await process.stop()).exited


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        "remove-loaded",
        "corrupt-loaded",
        "change-loaded",
        "move-loaded",
        "duplicate-pdf",
        "remove-pdf",
        "wrong-pdf-version",
        "failed-host-refresh",
    ],
)
async def test_fresh_host_audit_cannot_reuse_stale_candidate_inventory(
    tmp_path,
    monkeypatch,
    mutation,
):
    usage, token, shared, parent_user = observed_host(tmp_path, monkeypatch)
    spec = launch(
        tmp_path,
        paths=(shared, parent_user),
        requirements="shared-fixture-sdk==1.0\n",
    )
    process = PluginProcess()
    try:
        child = (await process.audit(spec)).snapshot
        assert child.versions["shared-fixture-pdf"] == "6.1"
        loaded_info = shared / "shared_loaded_agent-1.0.dist-info"
        pdf_info = parent_user / "shared_fixture_pdf-6.1.dist-info"
        if mutation == "remove-loaded":
            shutil.rmtree(loaded_info)
        elif mutation == "corrupt-loaded":
            (loaded_info / "METADATA").write_text(
                "Name: shared-loaded-agent\n",
            )
        elif mutation == "change-loaded":
            (loaded_info / "METADATA").write_text(
                "Metadata-Version: 2.1\nName: shared-loaded-agent\n"
                "Version: 1.1\n"
                "Requires-Dist: shared-fixture-pdf>=6\n",
            )
        elif mutation == "move-loaded":
            loaded_info.rename(
                shared / "shared_loaded_agent-relocated.dist-info",
            )
        elif mutation == "duplicate-pdf":
            install(parent_user, "shared-fixture-pdf", "6.2")
        elif mutation == "remove-pdf":
            shutil.rmtree(pdf_info)
        elif mutation == "wrong-pdf-version":
            (pdf_info / "METADATA").write_text(
                "Metadata-Version: 2.1\nName: shared-fixture-pdf\n"
                "Version: 5.0\n",
            )
        else:
            usage.observe_host(token, None)
        usage.withdraw(token)
        hosts = [use for use in usage.snapshot().uses if use.origin == "host"]
        assert len(hosts) == 1
        assert hosts[0].snapshot.versions == {"shared-loaded-agent": "1.0"}
        decision = gate.evaluate_shared_dependencies(
            spec.requirements_path,
            child,
            plugin_id="candidate",
            uses=hosts,
        )
        assert not decision.already_satisfied, (mutation, decision.reason)
        assert decision.reason_code in {
            "DEPENDENCY_PLAN_UNVERIFIED",
            "DEPENDENCY_RESTART_REQUIRED",
            "DEPENDENCY_UNSATISFIED",
        }
        if mutation in {"change-loaded", "move-loaded"}:
            assert decision.reason_code == "DEPENDENCY_RESTART_REQUIRED"
        if mutation == "failed-host-refresh":
            assert hosts[0].environment is None
            assert decision.reason_code == "DEPENDENCY_PLAN_UNVERIFIED"
        assert "shared_fixture_pdf" not in sys.modules
    finally:
        usage.withdraw(token)
        assert (await process.stop()).exited


@pytest.mark.asyncio
async def test_host_metadata_completion_avoids_unrelated_record_files(
    tmp_path,
    monkeypatch,
):
    usage, token, shared, parent_user = observed_host(tmp_path, monkeypatch)
    install(
        parent_user,
        "shared-unused-host",
        body="raise AssertionError('unused imported')\n",
    )
    usage.withdraw(token)
    hosts = [use for use in usage.snapshot().uses if use.origin == "host"]
    spec = launch(
        tmp_path,
        paths=(shared,),
        requirements="shared-fixture-sdk==1.0\n",
    )
    process = PluginProcess()
    try:
        child = (await process.audit(spec)).snapshot
        native_files = metadata.PathDistribution.files.fget

        def no_host_records(distribution):
            # Bound the real metadata origin without replacing its inventory.
            # pylint: disable-next=protected-access
            origin = Path(distribution._path).resolve()
            assert origin.parent not in {
                shared.resolve(),
                parent_user.resolve(),
            }, origin
            return native_files(distribution)

        monkeypatch.setattr(
            metadata.PathDistribution,
            "files",
            property(no_host_records),
        )
        decision = gate.evaluate_shared_dependencies(
            spec.requirements_path,
            child,
            plugin_id="candidate",
            uses=hosts,
        )
        assert decision.already_satisfied, decision.reason
        assert hosts[0].snapshot.versions == {"shared-loaded-agent": "1.0"}
        assert not {"shared_fixture_pdf", "shared_unused_host"}.intersection(
            sys.modules,
        )
    finally:
        assert (await process.stop()).exited


@pytest.mark.asyncio
async def test_ambiguous_pdf_between_host_sites_is_not_completed_from_child(
    tmp_path,
    monkeypatch,
):
    usage, token, shared, parent_user = observed_host(tmp_path, monkeypatch)
    # The host reads two real origins; the isolated candidate reads only one.
    install(shared, "shared-fixture-pdf", "6.1")
    usage.withdraw(token)
    hosts = [use for use in usage.snapshot().uses if use.origin == "host"]
    spec = launch(
        tmp_path,
        paths=(shared,),
        requirements="shared-fixture-sdk==1.0\n",
    )
    process = PluginProcess()
    try:
        child = (await process.audit(spec)).snapshot
        assert child.versions["shared-fixture-pdf"] == "6.1"
        assert (
            len(
                [
                    dist
                    for dist in metadata.distributions(
                        path=[str(shared), str(parent_user)],
                    )
                    if dist.metadata.get("Name") == "shared-fixture-pdf"
                ],
            )
            == 2
        )
        decision = gate.evaluate_shared_dependencies(
            spec.requirements_path,
            child,
            plugin_id="candidate",
            uses=hosts,
        )
        assert not decision.already_satisfied, decision.reason
        assert decision.reason_code == "DEPENDENCY_PLAN_UNVERIFIED"
        assert hosts[0].snapshot.versions == {"shared-loaded-agent": "1.0"}
    finally:
        assert (await process.stop()).exited


@pytest.mark.asyncio
async def test_paired_workers_measure_readable_unused_roots_without_imports(
    tmp_path,
):
    required, extra = tmp_path / "required", tmp_path / "extra"
    install(required, "shared-fixture-sdk")
    sentinel = tmp_path / "unused-buffer-imported"
    install(
        extra,
        "shared-large-unused",
        body=(
            "from pathlib import Path\n"
            f"Path({str(sentinel)!r}).touch()\n"
            "BUFFER = bytearray(64 * 1024 * 1024)\n"
        ),
    )
    for index in range(256):
        install(extra, f"shared-unused-{index}")
    measurements = []
    for pair in range(3):
        baseline, readable = PluginProcess(), PluginProcess()
        specs = (
            launch(
                tmp_path,
                paths=(required,),
                requirements="shared-fixture-sdk==1.0\n",
                label=f"baseline-{pair}",
            ),
            launch(
                tmp_path,
                paths=(required, extra),
                requirements="shared-fixture-sdk==1.0\n",
                label=f"readable-{pair}",
            ),
        )
        try:
            health = await asyncio.gather(
                baseline.start(specs[0]),
                readable.start(specs[1]),
            )
            assert all(row["state"] == "ready" for row in health)
            async with asyncio.timeout(3):
                while any(
                    process.health_snapshot()["component_state"] != "ready"
                    for process in (baseline, readable)
                ):
                    await asyncio.sleep(0.01)
            actual = await asyncio.gather(report(baseline), report(readable))
            assert actual[0]["modules"] == actual[1]["modules"]
            assert (
                actual[0]["versions"]
                == actual[1]["versions"]
                == {
                    "shared-fixture-sdk": "1.0",
                }
            )
            assert not any(
                name.startswith("shared_unused")
                or name == "shared_large_unused"
                for row in actual
                for name in row["modules"]
            )
            assert all(
                row["blocked"] == [] and row["isolated"] == 1 for row in actual
            )
            samples = [[], []]
            for _sample in range(5):
                await asyncio.sleep(0.05)
                for index, row in enumerate(actual):
                    native = psutil.Process(row["pid"])
                    assert not native.children(recursive=True)
                    memory = native.memory_full_info()
                    samples[index].append(
                        {"rss": memory.rss, "uss": memory.uss},
                    )
            measured = {
                "pair": pair,
                "baseline": {},
                "readable": {},
                "unused_distributions": 257,
                "unused_buffer_bytes": 64 * 1024 * 1024,
            }
            for index, label in enumerate(("baseline", "readable")):
                measured[label] = {
                    **{
                        kind: int(
                            statistics.median(
                                sample[kind] for sample in samples[index]
                            ),
                        )
                        for kind in ("rss", "uss")
                    },
                    "modules": len(actual[index]["modules"]),
                    "process_count": 1,
                    "retained_versions": len(actual[index]["versions"]),
                }
            measurements.append(measured)
            assert not sentinel.exists()
        finally:
            stops = await asyncio.gather(baseline.stop(), readable.stop())
            assert all(result.exited for result in stops)
    Path("/private/tmp/qwenpaw-shared-dependencies-memory.json").write_text(
        json.dumps(measurements, indent=2) + "\n",
    )
    print("SHARED_DEPENDENCY_MEMORY=" + json.dumps(measurements))


def test_live_readers_survives_removed_candidate_and_keeps_locked_reader(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.plugins import dependency_maintenance as maintenance

    site = tmp_path / "site"
    site.mkdir()
    readers = tmp_path / ".site.dependencies-readers"
    live = readers / f"{os.getpid()}-live.lease"
    stale = readers / "999999-stale.lease"
    original_glob = Path.glob

    def enumerate_then_remove(directory, pattern):
        paths = list(original_glob(directory, pattern))
        if directory == readers and pattern == "*.lease":
            stale.unlink()
            paths.sort(key=lambda path: path != stale)
        return iter(paths)

    with maintenance.file_lock(live):
        stale.write_bytes(b"\0")
        monkeypatch.setattr(Path, "glob", enumerate_then_remove)
        assert maintenance.live_readers((site,)) == [
            {"pid": os.getpid(), "site": str(site)},
        ]
