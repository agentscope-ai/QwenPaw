# -*- coding: utf-8 -*-
"""Explicit upgrades preserve live packages until a reviewed operation applies."""

import asyncio
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
import venv
import zipfile

import httpx
import pytest
from fastapi import FastAPI

from qwenpaw.plugins.channel_adapter import ChannelRuntimeSettings
from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.plugins.registry import PluginRegistry

ROOT = Path(__file__).resolve().parents[3]
# Load the real route module without the unrelated routers/__init__ fan-out,
# which eagerly loads host Agent services prohibited by this isolated suite.
_ROUTE_SPEC = importlib.util.spec_from_file_location(
    "qwenpaw.app.routers.plugins",
    ROOT / "src/qwenpaw/app/routers/plugins.py",
)
_ROUTES = importlib.util.module_from_spec(_ROUTE_SPEC)
sys.modules[_ROUTE_SPEC.name] = _ROUTES
_ROUTE_SPEC.loader.exec_module(_ROUTES)
router = _ROUTES.router


def tree_bytes(root):
    """Compare real environment content, ignoring Python's derived caches."""
    return {
        str(path.relative_to(root)): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }


def distribution(root, name, version, module=None, *, requires=()):
    """A tiny installed distribution with actual import and RECORD ownership."""
    module = module or name.replace("-", "_")
    info = f"{name.replace('-', '_')}-{version}.dist-info"
    files = {
        f"{module}.py": f"VERSION = {version!r}\n".encode(),
        f"{info}/METADATA": (
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
            + "".join(f"Requires-Dist: {value}\n" for value in requires)
        ).encode(),
        f"{info}/WHEEL": (
            b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
        ),
        f"{info}/top_level.txt": f"{module}\n".encode(),
    }
    records = []
    for relative, content in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest())
        records.append(
            f"{relative},sha256={digest.decode().rstrip('=')},{len(content)}\n",
        )
    files[f"{info}/RECORD"] = (
        "".join(records) + f"{info}/RECORD,,\n"
    ).encode()
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return files


@pytest.fixture
def isolated_loader(tmp_path, monkeypatch):
    from qwenpaw.plugins.execution import PluginProcess

    worker_logs = []

    async def capture_worker_stderr(process, child):
        while chunk := await child.stderr.read(16384):
            process._log_bytes += len(
                chunk
            )  # pylint: disable=protected-access
            worker_logs.append(chunk.decode(errors="replace")[-12000:])

    monkeypatch.setattr(PluginProcess, "_drain_logs", capture_worker_stderr)
    from qwenpaw.app.channels import registry as channel_registry

    # Built-in Console discovery imports the host Agent model stack. This
    # suite exercises installed descriptor channels only; keep their native
    # catalog/manager/projector paths while disabling unrelated discovery.
    monkeypatch.setattr(channel_registry, "_load_builtin_channels", lambda: {})
    monkeypatch.setattr(channel_registry, "_BUILTIN_CHANNEL_CACHE", None)
    previous = PluginRegistry._instance  # pylint: disable=protected-access
    PluginRegistry._instance = None  # pylint: disable=protected-access
    environment = tmp_path / "environment"
    venv.EnvBuilder(with_pip=False).create(environment)
    site = (
        environment
        / "lib"
        / (f"python{sys.version_info.major}.{sys.version_info.minor}")
        / "site-packages"
    )
    import packaging

    shutil.copytree(Path(packaging.__file__).parent, site / "packaging")
    from qwenpaw.__version__ import __version__
    import qwenpaw.config as config_package
    from qwenpaw.config import utils as config_utils
    from qwenpaw.config import config as config_model

    # Tool catalog discovery is unrelated to dependency installation and
    # would eagerly import the host Agent services this suite excludes.
    monkeypatch.setattr(config_model, "_BUILTIN_TOOLS_CACHE", {})
    monkeypatch.setattr(
        config_utils, "get_config_path", lambda: tmp_path / "host/config.json"
    )
    # Supply a real Config instance at the disk configuration boundary while
    # excluding unrelated Agent loop/catalog discovery from dependency tests.
    saved = config_model.Config.model_construct(
        tools=config_model.ToolsConfig.model_construct(builtin_tools={}),
        agents=config_model.AgentsConfig.model_construct(
            running=config_model.AgentsRunningConfig.model_construct(
                loop=config_model.LoopConfig.model_construct(),
            ),
        ),
    )
    monkeypatch.setattr(
        config_utils, "load_config", lambda *args, **kwargs: saved
    )
    monkeypatch.setattr(
        config_package, "load_config", config_utils.load_config
    )
    from qwenpaw.app.channels import base as channel_base

    monkeypatch.setattr(channel_base, "load_config", config_utils.load_config)

    destination = tmp_path / "plugins"
    destination.mkdir()
    monkeypatch.setattr(config_utils, "get_plugins_dir", lambda: destination)
    loader = PluginLoader(
        [destination],
        channel_runtime=ChannelRuntimeSettings(
            python_executable=str(environment / "bin/python"),
            support_root=ROOT / "src",
            qwenpaw_version=__version__,
            selected_channels=None,
            dependency_paths=(site,),
            dependency_install_target=site,
            startup_timeout=4,
            shutdown_timeout=0.5,
        ),
    )

    def local_wheel_solver(command, **kwargs):
        del kwargs
        assert "wheel" in command and "install" not in command, command
        destination = Path(command[command.index("--wheel-dir") + 1])
        requirements = Path(command[command.index("-r") + 1])
        from packaging.requirements import Requirement
        from importlib import metadata

        versions = {
            "markdown-it-py": ("3.0.0", "markdown_it"),
            "websocket-client": ("1.9.0", "websocket"),
            "matrix-nio": ("0.25.0", "nio"),
            "httpx": ("0.27.0", "httpx"),
            "linkify-it-py": ("2.0.0", "linkify_it"),
            "cryptography": ("43.0.0", "cryptography"),
            "upgrade-sdk": ("2.0", "upgrade_sdk"),
            "agentscope": ("2.0.10", "agentscope_fixture"),
            "python-lsp-server": ("1.13.1", "pylsp_fixture"),
        }
        for line in requirements.read_text().splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            requirement = Requirement(line)
            if requirement.marker and not requirement.marker.evaluate():
                continue
            version, module = versions[requirement.name]
            assert requirement.specifier.contains(version), requirement
            scratch = tmp_path / ("wheel-" + requirement.name)
            installed = {
                item.metadata["Name"]: item
                for item in metadata.distributions(path=[str(site)])
            }
            observed = installed.get(requirement.name)
            files = distribution(
                scratch,
                requirement.name,
                version,
                module,
                requires=(observed.requires or ()) if observed else (),
            )
            name = requirement.name.replace("-", "_")
            destination.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(
                destination / f"{name}-{version}-py3-none-any.whl", "w"
            ) as archive:
                for relative, content in files.items():
                    archive.writestr(relative, content)
        return subprocess.CompletedProcess(
            command, 0, stdout="Local fixture wheels resolved", stderr=""
        )

    monkeypatch.setattr(
        loader, "_run_subprocess_with_streaming_log", local_wheel_solver
    )
    app = FastAPI()
    app.state.plugin_loader = loader
    app.include_router(router)
    try:
        yield loader, app, site, destination
    finally:
        if worker_logs:
            print("Worker stderr:\n" + "\n".join(worker_logs))
        PluginRegistry._instance = previous  # pylint: disable=protected-access


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "channel,name,old,module,other",
    [
        (
            "matrix",
            "markdown-it-py",
            "2.2.0",
            "markdown_it",
            (
                ("matrix-nio", "0.25.0"),
                ("httpx", "0.27.0"),
                ("linkify-it-py", "2.0.0"),
            ),
        ),
        (
            "qq",
            "websocket-client",
            "1.8.0",
            "websocket",
            (("httpx", "0.27.0"), ("cryptography", "43.0.0")),
        ),
    ],
)
async def test_install_old_unconsumed_package_returns_reviewable_upgrade(
    isolated_loader,
    tmp_path,
    channel,
    name,
    old,
    module,
    other,
):
    # Removing structured upgrade staging recreates the user's actual install
    # failure even though there is no running consumer to stop.
    loader, app, site, destination = isolated_loader
    for package, version in other:
        distribution(site, package, version)
    distribution(site, name, old, module)
    source = tmp_path / "incoming"
    shutil.copytree(ROOT / "plugins/channel" / channel, source)
    before = tree_bytes(site)
    assert not loader.registry.runtime_owners.leases()
    assert not loader.registry.dependency_usage.snapshot().uses
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://fixture.test",
    ) as client:
        response = await client.post(
            "/plugins/install", json={"source": str(source)}
        )
    assert tree_bytes(site) == before
    assert not (destination / channel).exists()
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, dict), detail
    assert detail["code"] == "DEPENDENCY_UPGRADE_REQUIRED", detail
    operation = detail["operation"]
    assert operation["id"]
    assert operation["status"] == "needs_confirmation", operation
    assert operation["plugin_id"] == channel


def channel_source(
    root, name="upgrade_fixture", requirements="upgrade-sdk>=2\n"
):
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "id": name,
                "name": "Upgrade Fixture",
                "version": "1.0",
                "type": "channel",
                "entry": {"descriptor": "channel.json"},
            }
        )
    )
    (root / "channel.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "channel_key": name,
                "label": {"en": "Upgrade Fixture", "zh": "升级测试"},
                "process_mode": "runner_process",
                "dependency_mode": "shared",
                "entrypoint": {
                    "scope": "runner",
                    "module": "driver",
                    "qualname": "Driver",
                },
                "requirements_file": "requirements.txt",
                "config_schema": {
                    "type": "object",
                    "properties": {
                        "enabled": {"type": "boolean", "default": False}
                    },
                },
                "config_fields": ["enabled"],
                "capabilities": ["channel.generic.v1"],
            }
        )
    )
    (root / "requirements.txt").write_text(requirements)
    (root / "driver.py").write_text(
        "import upgrade_sdk\n"
        "class Driver:\n"
        "    def bind(self, context): self.context = context\n"
        "    async def start(self, config): pass\n"
        "    async def stop(self): pass\n",
    )
    return root


def upgrade_manager(loader):
    from qwenpaw.plugins.dependency_upgrade import DependencyUpgradeManager

    return DependencyUpgradeManager(loader)


def imported_sdk(loader, site):
    executable = loader.registry.channel_runtime.python_executable
    result = subprocess.run(
        [
            executable,
            "-I",
            "-c",
            "import importlib.metadata as m,json,pathlib,upgrade_sdk; "
            "print(json.dumps({'version':m.version('upgrade-sdk'),'value':upgrade_sdk.VERSION,"
            "'source':str(pathlib.Path(upgrade_sdk.__file__).resolve()),"
            "'providers':[str(d._path) for d in m.distributions() if d.metadata['Name']=='upgrade-sdk']}))",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def host_extra_graph(site, package, *, bridge_requires="host-extra-leaf>=1"):
    """Install metadata with the project's exact default extra declaration."""
    from packaging.requirements import Requirement

    requirement = next(
        value
        for value in tomllib.loads((ROOT / "pyproject.toml").read_text())[
            "project"
        ]["dependencies"]
        if Requirement(value).name == package
    )
    extra = "model-ollama" if package == "agentscope" else "rope"
    version = "2.0.10" if package == "agentscope" else "1.13.1"
    distribution(
        site,
        package,
        version,
        "agentscope_fixture" if package == "agentscope" else "pylsp_fixture",
        requires=(
            f"host-extra-bridge>=1; extra == '{extra}'",
            "missing-inactive-extra>=1; extra == 'unused-extra'",
            "missing-inactive-marker>=1; python_version < '0'",
        ),
    )
    distribution(
        site,
        "host-extra-bridge",
        "1.0",
        requires=(bridge_requires,),
    )
    distribution(site, "host-extra-leaf", "1.0")
    # Deliberately differ from the running source version: ownership must use
    # the version observed inside the dependency interpreter.
    distribution(
        site,
        "qwenpaw",
        "0.0.7",
        "host_fixture",
        requires=(
            requirement,
            "missing-host-extra>=1; extra == 'unused-extra'",
            "missing-host-marker>=1; python_version < '0'",
        ),
    )
    return requirement


@pytest.mark.asyncio
@pytest.mark.parametrize("package", ["agentscope", "python-lsp-server"])
async def test_default_host_extras_stage_preflight_and_apply(
    isolated_loader,
    tmp_path,
    package,
):
    from qwenpaw.plugins.dependency_upgrade import continue_operation

    loader, _, site, destination = isolated_loader
    requirement = host_extra_graph(site, package)
    distribution(site, "upgrade-sdk", "1.0")
    before = tree_bytes(site)
    source = channel_source(tmp_path / "incoming")
    source_before = tree_bytes(source)
    manager = upgrade_manager(loader)
    operation = await manager.stage(source)
    assert operation["status"] == "needs_confirmation"
    assert operation["requires_restart"] is False
    assert tree_bytes(site) == before
    assert tree_bytes(source) == source_before
    assert not list(destination.iterdir())

    directory = manager.root / operation["id"]
    stored = json.loads((directory / "operation.json").read_text())
    (host,) = (row for row in stored["consumers"] if row["origin"] == "host")
    assert host["requirements"] == ["qwenpaw==0.0.7"]
    assert host["source_revision"] == "0.0.7"
    observed_requires = host["environment"]["distributions"]["qwenpaw"][
        "requires_dist"
    ]
    resolver_roots = (directory / "requirements.txt").read_text().splitlines()
    assert resolver_roots == ["upgrade-sdk>=2", *observed_requires]
    assert requirement in resolver_roots
    assert all(not value.startswith("qwenpaw") for value in resolver_roots)
    assert not stored["approved"]
    await continue_operation(directory, preflight=True)
    assert tree_bytes(site) == before
    assert tree_bytes(source) == source_before
    assert not list(destination.iterdir())

    applied = await manager.apply(operation["id"])
    assert applied["status"] == "succeeded", applied
    assert imported_sdk(loader, site)["value"] == "2.0"
    assert (destination / "upgrade_fixture/driver.py").read_bytes() == (
        source / "driver.py"
    ).read_bytes()
    assert tree_bytes(source) == source_before


@pytest.mark.asyncio
async def test_requested_host_extra_transitive_conflict_is_refused(
    isolated_loader,
    tmp_path,
):
    from qwenpaw.plugins.dependency_gate import SharedDependencyError

    loader, _, site, destination = isolated_loader
    host_extra_graph(site, "agentscope", bridge_requires="upgrade-sdk<2")
    distribution(site, "upgrade-sdk", "1.0")
    before = tree_bytes(site)
    manager = upgrade_manager(loader)
    # The fixture solver emits SDK 2.0, letting the real host closure reject
    # this unsafe proposal independently of the external resolver's result.
    with pytest.raises(SharedDependencyError) as refused:
        await manager.stage(channel_source(tmp_path / "incoming"))
    assert refused.value.reason_code == "DEPENDENCY_CONFLICT"
    assert "upgrade-sdk<2" in str(refused.value)
    assert tree_bytes(site) == before
    assert not list(manager.root.iterdir())
    assert not list(destination.iterdir())


@pytest.mark.asyncio
async def test_requested_host_extra_upgrade_requires_restart_before_write(
    isolated_loader,
    tmp_path,
):
    from qwenpaw.plugins.dependency_upgrade import continue_operation

    loader, _, site, destination = isolated_loader
    host_extra_graph(site, "agentscope", bridge_requires="upgrade-sdk>=1")
    distribution(site, "upgrade-sdk", "1.0")
    before = tree_bytes(site)
    manager = upgrade_manager(loader)
    operation = await manager.stage(channel_source(tmp_path / "incoming"))
    assert operation["requires_restart"] is True
    assert tree_bytes(site) == before
    assert not list(destination.iterdir())
    await continue_operation(manager.root / operation["id"], preflight=True)
    applied = await manager.apply(operation["id"])
    assert applied["status"] == "waiting_restart", applied
    assert applied["requires_restart"] is True
    assert tree_bytes(site) == before
    assert not list(destination.iterdir())


@pytest.mark.asyncio
async def test_apply_replaces_owned_files_in_original_site_and_continues_install(
    isolated_loader,
    tmp_path,
):
    loader, _, site, destination = isolated_loader
    distribution(site, "upgrade-sdk", "1.0")
    unrelated = site / "neighbor.py"
    unrelated.write_bytes(b"NEIGHBOR = 'keep exact bytes'\n")
    source = channel_source(tmp_path / "incoming")
    before = tree_bytes(site)
    manager = upgrade_manager(loader)
    operation = await manager.stage(source)
    assert operation["status"] == "needs_confirmation"
    assert operation["changes"] == [
        {
            "name": "upgrade-sdk",
            "current_version": "1.0",
            "target_version": "2.0",
        }
    ]
    assert not operation["requires_restart"]
    assert tree_bytes(site) == before
    assert imported_sdk(loader, site)["value"] == "1.0"
    applied = await manager.apply(operation["id"])
    assert applied["status"] == "succeeded", applied
    assert applied["result"]["id"] == "upgrade_fixture"
    assert manager.status(operation["id"])["status"] == "succeeded"
    assert (await manager.apply(operation["id"]))["result"] == applied[
        "result"
    ]
    actual = imported_sdk(loader, site)
    assert actual == {
        "version": "2.0",
        "value": "2.0",
        "source": str(site / "upgrade_sdk.py"),
        "providers": [str(site / "upgrade_sdk-2.0.dist-info")],
    }
    assert not (site / "upgrade_sdk-1.0.dist-info").exists()
    assert unrelated.read_bytes() == b"NEIGHBOR = 'keep exact bytes'\n"
    assert (destination / "upgrade_fixture/driver.py").read_bytes() == (
        source / "driver.py"
    ).read_bytes()
    assert "upgrade_sdk" not in sys.modules


@pytest.mark.asyncio
async def test_cancelled_candidate_cannot_modify_packages_or_continue_install(
    isolated_loader,
    tmp_path,
):
    loader, _, site, destination = isolated_loader
    distribution(site, "upgrade-sdk", "1.0")
    source = channel_source(tmp_path / "incoming")
    before = tree_bytes(site)
    manager = upgrade_manager(loader)
    operation = await manager.stage(source)
    assert manager.cancel(operation["id"])["status"] == "cancelled"
    assert manager.cancel(operation["id"])["status"] == "cancelled"
    try:
        applied = await manager.apply(operation["id"])
    except RuntimeError:
        pass
    else:
        assert applied["status"] == "cancelled", applied
    assert tree_bytes(site) == before
    assert not (destination / "upgrade_fixture").exists()
    assert manager.status(operation["id"])["status"] == "cancelled"


@pytest.mark.asyncio
async def test_upload_retains_the_reviewed_source_after_request_temp_cleanup(
    isolated_loader,
    tmp_path,
):
    loader, app, site, destination = isolated_loader
    distribution(site, "upgrade-sdk", "1.0")
    source = channel_source(tmp_path / "incoming")
    archive = tmp_path / "incoming.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        for path in source.rglob("*"):
            if path.is_file():
                zipped.write(
                    path, "retained-plugin/" + str(path.relative_to(source))
                )
    before = tree_bytes(site)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture.test"
    ) as client:
        response = await client.post(
            "/plugins/upload",
            files={
                "file": (
                    "incoming.zip",
                    archive.read_bytes(),
                    "application/zip",
                )
            },
        )
        assert response.status_code == 409, response.text
        operation = response.json()["detail"]["operation"]
        assert tree_bytes(site) == before
        shutil.rmtree(source)
        archive.unlink()
        status = await client.get(
            f"/plugins/dependency-upgrades/{operation['id']}"
        )
        assert (
            status.status_code == 200
            and status.json()["status"] == "needs_confirmation"
        )
        applied = await client.post(
            f"/plugins/dependency-upgrades/{operation['id']}/apply"
        )
        assert applied.status_code == 200, applied.text
        assert applied.json()["status"] == "succeeded", applied.text
    assert (destination / "upgrade_fixture/driver.py").is_file()
    assert imported_sdk(loader, site)["version"] == "2.0"


@pytest.mark.asyncio
async def test_environment_modified_after_confirmation_is_refused_without_writes(
    isolated_loader,
    tmp_path,
):
    loader, _, site, destination = isolated_loader
    distribution(site, "upgrade-sdk", "1.0")
    manager = upgrade_manager(loader)
    operation = await manager.stage(channel_source(tmp_path / "incoming"))
    module = site / "upgrade_sdk.py"
    module.write_text("VERSION = 'externally-modified'\n")
    changed = tree_bytes(site)
    applied = await manager.apply(operation["id"])
    assert applied["status"] == "failed", applied
    assert applied["error"]["code"] == "DEPENDENCY_PLAN_STALE", applied
    assert tree_bytes(site) == changed
    assert not (destination / "upgrade_fixture").exists()


@pytest.mark.asyncio
async def test_tampered_retained_source_cannot_be_applied(
    isolated_loader,
    tmp_path,
):
    loader, _, site, destination = isolated_loader
    distribution(site, "upgrade-sdk", "1.0")
    manager = upgrade_manager(loader)
    operation = await manager.stage(channel_source(tmp_path / "incoming"))
    from qwenpaw.config.utils import get_config_path

    retained = (
        get_config_path().parent
        / "dependency_upgrades"
        / operation["id"]
        / "source/driver.py"
    )
    retained.write_text("raise RuntimeError('changed after review')\n")
    before = tree_bytes(site)
    applied = await manager.apply(operation["id"])
    assert applied["status"] == "failed", applied
    assert applied["error"]["code"] == "DEPENDENCY_PLAN_STALE", applied
    assert tree_bytes(site) == before
    assert not (destination / "upgrade_fixture").exists()


@pytest.mark.asyncio
async def test_source_continuation_failure_rolls_back_owned_dependency_bytes_and_modes(
    isolated_loader,
    tmp_path,
):
    loader, _, site, destination = isolated_loader
    distribution(site, "upgrade-sdk", "1.0")
    module = site / "upgrade_sdk.py"
    module.chmod(0o640)
    source = channel_source(tmp_path / "incoming")
    (source / "driver.py").write_text(
        "raise RuntimeError('fixture rejects new source at probe')\n"
    )
    before, mode = tree_bytes(site), module.stat().st_mode
    manager = upgrade_manager(loader)
    operation = await manager.stage(source)
    applied = await manager.apply(operation["id"])
    assert applied["status"] == "failed", applied
    assert applied["error"], applied
    assert tree_bytes(site) == before
    assert module.stat().st_mode == mode
    assert imported_sdk(loader, site)["version"] == "1.0"
    assert not (destination / "upgrade_fixture").exists()


async def running_consumer(loader, site, root, *, stop_ok=True):
    from qwenpaw.plugins.dependency_usage import (
        DependencyDeclaration,
        DependencyEnvironment,
    )
    from qwenpaw.plugins.execution import PluginLaunchSpec, PluginProcess
    from qwenpaw.plugins.execution.bootstrap import _hash_code_root
    from qwenpaw.plugins.ownership import RuntimeKey, RuntimeStopReceipt

    root.mkdir()
    (root / "requirements.txt").write_text("upgrade-sdk>=1,<3\n")
    (root / "worker.py").write_text(
        "import upgrade_sdk\n"
        "class Worker:\n"
        "    def bind(self, context):\n"
        "        self.context=context\n"
        "        context.peer.register_method('fixture.version',self.version)\n"
        "    async def version(self,params,request): return {'version':upgrade_sdk.VERSION}\n"
        "    async def start(self,config): await self.context.set_state('ready')\n"
        "    async def stop(self): pass\n",
    )
    owners, usage = (
        loader.registry.runtime_owners,
        loader.registry.dependency_usage,
    )
    lease = owners.reserve(
        "old_consumer",
        RuntimeKey("component", "sdk", "old"),
        root,
        instance_id="old-process",
    )
    process = PluginProcess()
    spec = PluginLaunchSpec(
        python_executable=loader.registry.channel_runtime.python_executable,
        support_root=ROOT / "src",
        code_root=root,
        source_revision=_hash_code_root(root),
        plugin_id="old_consumer",
        instance_id=lease.instance_id,
        generation=lease.generation,
        entrypoint="worker:Worker",
        config={},
        requirements_path=root / "requirements.txt",
        dependency_paths=(site,),
        startup_timeout=4,
        shutdown_timeout=0.5,
    )
    snapshot = (await process.audit(spec)).snapshot
    token = usage.declare(
        DependencyDeclaration(
            "old_consumer",
            spec.source_revision,
            ("upgrade-sdk>=1,<3",),
            DependencyEnvironment.from_snapshot(snapshot),
        )
    )
    usage.bind(lease, token)
    process.dependency_observer = lambda evidence: usage.observe(
        lease, evidence
    )
    usage.observe(lease, snapshot)
    before = tree_bytes(site)
    stops = []

    async def stop():
        assert (
            tree_bytes(site) == before
        ), "Dependency bytes changed while old process was alive"
        stops.append(lease)
        if not stop_ok:
            return RuntimeStopReceipt(
                False, "fixture consumer refuses quiescence", exited=False
            )
        result = await process.stop()
        return RuntimeStopReceipt(
            result.exited and not result.residual,
            exited=result.exited,
            residual=result.residual,
        )

    owners.attach(lease, stop, resource=process)
    await process.start(spec)
    assert await process.call("fixture.version", {}, timeout=2) == {
        "version": "1.0"
    }
    return process, lease, token, stops


@pytest.mark.asyncio
@pytest.mark.parametrize("upgrade_record_created_first", [True, False])
async def test_shared_record_ownership_is_rejected_in_both_distribution_orders(
    isolated_loader,
    tmp_path,
    upgrade_record_created_first,
):
    loader, _, site, destination = isolated_loader
    packages = [
        ("upgrade-sdk", "upgrade_sdk"),
        ("neighbor-sdk", "neighbor_sdk"),
    ]
    if not upgrade_record_created_first:
        packages.reverse()
    for name, module in packages:
        distribution(site, name, "1.0", module)
    shared = site / "shared_namespace.py"
    shared.write_bytes(b"VALUE = 'owned by two distributions'\n")
    digest = (
        base64.urlsafe_b64encode(hashlib.sha256(shared.read_bytes()).digest())
        .decode()
        .rstrip("=")
    )
    for name, _ in packages:
        record = site / f"{name.replace('-', '_')}-1.0.dist-info/RECORD"
        with record.open("a") as stream:
            stream.write(
                f"shared_namespace.py,sha256={digest},{shared.stat().st_size}\n"
            )
    before = tree_bytes(site)
    from qwenpaw.plugins.dependency_gate import SharedDependencyError

    with pytest.raises(SharedDependencyError) as refused:
        await upgrade_manager(loader).stage(
            channel_source(tmp_path / "incoming")
        )
    assert refused.value.reason_code == "DEPENDENCY_PLAN_UNVERIFIED"
    assert tree_bytes(site) == before
    assert not (destination / "upgrade_fixture").exists()


@pytest.mark.asyncio
async def test_installed_consumer_true_version_conflict_is_not_an_applyable_candidate(
    isolated_loader,
    tmp_path,
    monkeypatch,
):
    loader, _, site, destination = isolated_loader
    distribution(site, "upgrade-sdk", "1.0")
    channel_source(
        destination / "old_consumer",
        name="old_consumer",
        requirements="upgrade-sdk<2\n",
    )
    source = channel_source(tmp_path / "incoming")
    before = tree_bytes(site)
    observed = []

    def incompatible_solver(command, **kwargs):
        del kwargs
        resolver = Path(command[command.index("-r") + 1]).read_text()
        observed.append(resolver)
        assert "upgrade-sdk>=2" in resolver and "upgrade-sdk<2" in resolver
        return subprocess.CompletedProcess(
            command, 1, stdout="fixture incompatible requirements", stderr=""
        )

    monkeypatch.setattr(
        loader, "_run_subprocess_with_streaming_log", incompatible_solver
    )
    from qwenpaw.plugins.dependency_gate import SharedDependencyError

    with pytest.raises(SharedDependencyError) as refused:
        await upgrade_manager(loader).stage(source)
    assert refused.value.reason_code == "DEPENDENCY_CONFLICT"
    assert observed
    assert tree_bytes(site) == before
    assert not (destination / "upgrade_fixture").exists()


@pytest.mark.asyncio
async def test_tampered_staged_wheel_cannot_be_applied(
    isolated_loader, tmp_path
):
    loader, _, site, destination = isolated_loader
    distribution(site, "upgrade-sdk", "1.0")
    manager = upgrade_manager(loader)
    operation = await manager.stage(channel_source(tmp_path / "incoming"))
    from qwenpaw.config.utils import get_config_path

    wheels = (
        get_config_path().parent
        / "dependency_upgrades"
        / operation["id"]
        / "wheels"
    )
    staged = next(wheels.glob("*.whl"))
    with staged.open("ab") as stream:
        stream.write(b"tampered after confirmation")
    before = tree_bytes(site)
    applied = await manager.apply(operation["id"])
    assert applied["status"] == "failed", applied
    assert applied["error"]["code"] == "DEPENDENCY_PLAN_STALE", applied
    assert tree_bytes(site) == before
    assert not (destination / "upgrade_fixture").exists()


@pytest.mark.asyncio
async def test_safe_missing_package_addition_stays_on_the_ordinary_install_path(
    isolated_loader,
    tmp_path,
):
    loader, app, site, destination = isolated_loader
    neighbor = site / "unrelated.py"
    neighbor.write_bytes(b"VALUE = 'existing'\n")
    source = channel_source(tmp_path / "incoming")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture.test"
    ) as client:
        response = await client.post(
            "/plugins/install", json={"source": str(source)}
        )
    assert response.status_code == 200, response.text
    assert response.json()["id"] == "upgrade_fixture"
    assert imported_sdk(loader, site)["version"] == "2.0"
    assert neighbor.read_bytes() == b"VALUE = 'existing'\n"
    assert (destination / "upgrade_fixture/driver.py").exists()


def backend_python():
    """Use the real test dependency environment for the retiring backend."""
    for root in Path(pytest.__file__).resolve().parents:
        if (root / "pyvenv.cfg").is_file():
            executable = root / (
                "Scripts/python.exe" if os.name == "nt" else "bin/python"
            )
            if executable.is_file():
                return str(executable)
    return sys.executable


def retiring_backend(tmp_path):
    result = subprocess.run(
        [
            backend_python(),
            "-I",
            "-c",
            "import runpy,sys; sys.path.insert(0, sys.argv.pop(1)); "
            "runpy.run_path(sys.argv.pop(1), run_name='__main__')",
            str(Path(pytest.__file__).resolve().parents[1]),
            str(Path(__file__).with_name("upgrade_restart_host.py")),
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        timeout=40,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["candidate"]["requires_restart"]
    assert report["applied"]["status"] == "waiting_restart", report["applied"]
    assert report["applied"]["instructions"]
    assert tree_bytes(Path(report["site"])) == report["before"]
    return report


def run_absolute_worker(report, *, timeout=45):
    worker = Path(report["directory"]) / "worker/dependency_worker.py"
    assert worker.is_file()
    return subprocess.run(
        [
            report["python"],
            "-I",
            "-S",
            str(worker),
        ],
        cwd=Path(report["directory"]).parent,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def test_imported_host_package_requires_exit_then_absolute_worker_continues_install(
    tmp_path,
):
    report = retiring_backend(tmp_path)
    result = run_absolute_worker(report)
    operation = json.loads(
        (Path(report["directory"]) / "operation.json").read_text()
    )
    assert result.returncode == 0, (
        result.stdout + result.stderr + json.dumps(operation.get("error"))
    )
    assert operation["status"] == "succeeded", operation.get("error")
    assert operation["result"]["id"] == "upgrade_fixture"
    site = Path(report["site"])
    assert (site / "upgrade_sdk.py").read_bytes() == b"VERSION = '2.0'\n"
    assert not (site / "upgrade_sdk-1.0.dist-info").exists()
    assert (site / "upgrade_sdk-2.0.dist-info/METADATA").is_file()
    assert (Path(report["destination"]) / "upgrade_fixture/driver.py").exists()


def test_another_backend_reader_blocks_absolute_worker_before_any_package_write(
    tmp_path,
):
    report = retiring_backend(tmp_path)
    code = (
        "import importlib.util,pathlib,sys;"
        "spec=importlib.util.spec_from_file_location('reader',sys.argv[1]);"
        "module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module);"
        "module.lease_environment((pathlib.Path(sys.argv[2]),));"
        "print('reader-active',flush=True);input()"
    )
    reader = subprocess.Popen(
        [
            report["python"],
            "-I",
            "-S",
            "-c",
            code,
            str(ROOT / "src/qwenpaw/plugins/dependency_maintenance.py"),
            report["site"],
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert reader.stdout.readline().strip() == "reader-active"
        before = tree_bytes(Path(report["site"]))
        result = run_absolute_worker(report, timeout=15)
        assert result.returncode == 1, result.stdout + result.stderr
        operation = json.loads(
            (Path(report["directory"]) / "operation.json").read_text()
        )
        assert operation["status"] == "failed"
        assert (
            operation["error"]["code"] == "DEPENDENCY_ENVIRONMENT_BUSY"
        ), operation["error"]
        assert tree_bytes(Path(report["site"])) == before
        assert not (Path(report["destination"]) / "upgrade_fixture").exists()
    finally:
        reader.communicate("\n", timeout=5)
        assert reader.returncode == 0


@pytest.mark.asyncio
async def test_absolute_worker_cannot_bypass_unconfirmed_operation(
    isolated_loader, tmp_path
):
    loader, _, site, destination = isolated_loader
    distribution(site, "upgrade-sdk", "1.0")
    manager = upgrade_manager(loader)
    operation = await manager.stage(channel_source(tmp_path / "incoming"))
    from qwenpaw.config.utils import get_config_path

    directory = (
        get_config_path().parent / "dependency_upgrades" / operation["id"]
    )
    worker = directory / "worker"
    assert (worker / "dependency_worker.py").is_file()
    before = tree_bytes(site)
    result = run_absolute_worker(
        {"directory": str(directory), "python": sys.executable}
    )
    assert result.returncode == 1
    assert "DEPENDENCY_APPROVAL_REQUIRED" in result.stderr
    assert manager.status(operation["id"])["status"] == "needs_confirmation"
    assert tree_bytes(site) == before
    assert not (destination / "upgrade_fixture").exists()


@pytest.mark.asyncio
async def test_crash_after_durable_commit_reconciles_success_without_rewriting_packages(
    tmp_path,
    monkeypatch,
):
    crashed = subprocess.run(
        [
            backend_python(),
            "-I",
            str(Path(__file__).with_name("upgrade_restart_host.py")),
            str(tmp_path),
            "crash-after-commit",
        ],
        capture_output=True,
        text=True,
        timeout=40,
        check=False,
    )
    assert crashed.returncode == 97, crashed.stdout + crashed.stderr
    report = json.loads((tmp_path / "report.json").read_text())
    directory = Path(report["directory"])
    journal = json.loads((directory / "journal.json").read_text())
    # The crash is before the terminal operation save, after the verified
    # result is durable; recovery must finish this commit and keep new bytes.
    assert journal["phase"] == "committing"
    assert journal["result"]["id"] == "upgrade_fixture"
    site, destination = (
        Path(report["site"]),
        Path(report["destination"]) / "upgrade_fixture",
    )
    assert (site / "upgrade_sdk.py").read_bytes() == b"VERSION = '2.0'\n"
    assert (destination / "driver.py").is_file()
    committed_bytes, committed_source = tree_bytes(site), tree_bytes(
        destination
    )
    from qwenpaw.config import utils as config_utils

    monkeypatch.setattr(
        config_utils, "get_config_path", lambda: tmp_path / "host/config.json"
    )
    previous = PluginRegistry._instance  # pylint: disable=protected-access
    PluginRegistry._instance = None  # pylint: disable=protected-access
    try:
        manager = upgrade_manager(PluginLoader([Path(report["destination"])]))
        reconciled = await manager.apply(report["candidate"]["id"])
        assert reconciled["status"] == "succeeded", reconciled
        assert reconciled["result"]["id"] == "upgrade_fixture"
        assert (await manager.apply(report["candidate"]["id"])) == reconciled
        assert (
            manager.status(report["candidate"]["id"])["status"] == "succeeded"
        )
        assert tree_bytes(site) == committed_bytes
        assert tree_bytes(destination) == committed_source
        assert (
            json.loads((directory / "journal.json").read_text())["phase"]
            == "committed"
        )
    finally:
        PluginRegistry._instance = previous  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_absolute_worker_waits_for_actual_backend_exit_before_mutating(
    tmp_path,
):
    host = subprocess.Popen(
        [
            backend_python(),
            "-I",
            str(Path(__file__).with_name("upgrade_restart_host.py")),
            str(tmp_path),
            "hold-for-worker",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    worker = None
    try:
        assert host.stdout.readline().strip() == "backend-waiting"
        report = json.loads((tmp_path / "report.json").read_text())
        assert report["applied"]["status"] == "waiting_restart"
        script = Path(report["directory"]) / "worker/dependency_worker.py"
        worker = subprocess.Popen(
            [report["python"], "-I", "-S", str(script)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        await asyncio.sleep(0.3)
        assert host.poll() is None and worker.poll() is None
        assert tree_bytes(Path(report["site"])) == report["before"]
        host_stdout, host_stderr = host.communicate("\n", timeout=5)
        assert host.returncode == 0, host_stdout + host_stderr
        output, error = worker.communicate(timeout=45)
        assert worker.returncode == 0, output + error
        status = json.loads(
            (Path(report["directory"]) / "operation.json").read_text()
        )
        assert status["status"] == "succeeded", status.get("error")
        assert (
            Path(report["site"]) / "upgrade_sdk.py"
        ).read_bytes() == b"VERSION = '2.0'\n"
    finally:
        for child in (host, worker):
            if child is not None and child.poll() is None:
                child.kill()
                child.communicate(timeout=5)


def test_midwrite_backend_crash_has_absolute_recovery_that_restores_exact_old_bytes(
    tmp_path,
):
    crashed = subprocess.run(
        [
            backend_python(),
            "-I",
            str(Path(__file__).with_name("upgrade_restart_host.py")),
            str(tmp_path),
            "crash-after-first-write",
        ],
        capture_output=True,
        text=True,
        timeout=40,
        check=False,
    )
    assert crashed.returncode == 98, crashed.stdout + crashed.stderr
    report = json.loads((tmp_path / "report.json").read_text())
    site, directory = Path(report["site"]), Path(report["directory"])
    assert tree_bytes(site) != report["before"]
    assert (directory / "journal.json").is_file()
    assert (
        site.parent / ".site-packages.dependencies-repair-required"
    ).is_file()
    result = run_absolute_worker(report)
    assert result.returncode == 1, result.stdout + result.stderr
    status = json.loads((directory / "operation.json").read_text())
    assert status["status"] == "failed"
    assert status["error"]["code"] == "DEPENDENCY_INTERRUPTED", status.get(
        "error"
    )
    assert tree_bytes(site) == report["before"]
    assert not (Path(report["destination"]) / "upgrade_fixture").exists()
    assert not (
        site.parent / ".site-packages.dependencies-repair-required"
    ).exists()
    assert not (
        site.parent / ".site-packages.dependencies-maintenance"
    ).exists()
    assert (
        json.loads((directory / "journal.json").read_text())["phase"]
        == "rolled_back"
    )


def test_cli_running_backend_keeps_structured_review_without_offline_install(
    isolated_loader,
    tmp_path,
    monkeypatch,
):
    from click.testing import CliRunner
    from contextlib import contextmanager
    from qwenpaw.cli import plugin_commands as commands

    _, _, site, destination = isolated_loader
    distribution(site, "upgrade-sdk", "1.0")
    source = channel_source(tmp_path / "incoming")
    before = tree_bytes(site)
    requests = []
    operation = {
        "id": "a" * 32,
        "plugin_id": "upgrade_fixture",
        "status": "needs_confirmation",
        "changes": [
            {
                "name": "upgrade-sdk",
                "current_version": "1.0",
                "target_version": "2.0",
            }
        ],
        "message": "Review the shared change",
        "instructions": [],
    }

    def respond(request):
        requests.append(
            (request.method, request.url.path, json.loads(request.content))
        )
        return httpx.Response(
            409,
            json={
                "detail": {
                    "code": "DEPENDENCY_UPGRADE_REQUIRED",
                    "message": "Review",
                    "operation": operation,
                }
            },
        )

    @contextmanager
    def local_api(base, **kwargs):
        del kwargs
        with httpx.Client(
            base_url=base + "/", transport=httpx.MockTransport(respond)
        ) as client:
            yield client

    monkeypatch.setattr(commands, "_is_running", lambda: True)
    monkeypatch.setattr(
        commands, "_get_api_base", lambda: "http://fixture.test/api"
    )
    monkeypatch.setattr(commands, "api_client", local_api)
    invoked = CliRunner().invoke(commands.plugin, ["install", str(source)])
    assert invoked.exit_code == 0, invoked.output
    assert requests == [
        (
            "POST",
            "/api/plugins/install",
            {"source": str(source), "force": False},
        )
    ]
    assert "needs_confirmation" in invoked.output
    assert "upgrade-sdk: 1.0 -> 2.0" in invoked.output
    assert "dependency-upgrade apply " + operation["id"] in invoked.output
    assert "installed successfully" not in invoked.output
    assert tree_bytes(site) == before
    assert not (destination / "upgrade_fixture").exists()


def test_cli_apply_connection_failure_cannot_fall_back_to_offline_writes(
    isolated_loader,
    monkeypatch,
):
    from click.testing import CliRunner
    from contextlib import contextmanager
    from qwenpaw.cli import plugin_commands as commands

    _, _, site, _ = isolated_loader
    distribution(site, "upgrade-sdk", "1.0")
    before = tree_bytes(site)
    requests = []

    def disconnected(request):
        requests.append((request.method, request.url.path))
        raise httpx.ConnectError(
            "fixture backend disconnected", request=request
        )

    @contextmanager
    def local_api(base, **kwargs):
        del kwargs
        with httpx.Client(
            base_url=base + "/", transport=httpx.MockTransport(disconnected)
        ) as client:
            yield client

    monkeypatch.setattr(commands, "_is_running", lambda: True)
    monkeypatch.setattr(
        commands, "_get_api_base", lambda: "http://fixture.test/api"
    )
    monkeypatch.setattr(commands, "api_client", local_api)
    invoked = CliRunner().invoke(
        commands.plugin, ["dependency-upgrade", "apply", "a" * 32]
    )
    assert invoked.exit_code == 1, invoked.output
    assert requests == [
        ("POST", "/api/plugins/dependency-upgrades/" + "a" * 32 + "/apply")
    ]
    assert "no offline write was attempted" in invoked.output
    assert tree_bytes(site) == before


@pytest.mark.asyncio
async def test_unrestorable_active_orphan_is_preserved_without_stop_or_package_writes(
    isolated_loader, tmp_path
):
    loader, _, site, destination = isolated_loader
    distribution(site, "upgrade-sdk", "1.0")
    process, lease, token, stops = await running_consumer(
        loader, site, tmp_path / "orphan"
    )
    before = tree_bytes(site)
    try:
        manager = upgrade_manager(loader)
        operation = await manager.stage(channel_source(tmp_path / "incoming"))
        applied = await manager.apply(operation["id"])
        assert applied["status"] != "succeeded", applied
        assert stops == []
        assert tree_bytes(site) == before
        assert lease in loader.registry.runtime_owners.leases()
        assert await process.call("fixture.version", {}, timeout=2) == {
            "version": "1.0"
        }
        assert not (destination / "upgrade_fixture").exists()
    finally:
        result = await process.stop()
        from qwenpaw.plugins.ownership import RuntimeStopReceipt

        loader.registry.runtime_owners.release(
            lease, RuntimeStopReceipt(result.exited, exited=result.exited)
        )
        loader.registry.dependency_usage.withdraw(token)


def test_crash_after_dependency_rollback_finishes_old_source_restoration_without_reapply(
    tmp_path,
):
    crashed = subprocess.run(
        [
            backend_python(),
            "-I",
            str(Path(__file__).with_name("upgrade_restart_host.py")),
            str(tmp_path),
            "crash-after-dependency-rollback",
        ],
        capture_output=True,
        text=True,
        timeout=40,
        check=False,
    )
    assert crashed.returncode == 99, crashed.stdout + crashed.stderr
    report = json.loads((tmp_path / "report.json").read_text())
    site, directory = Path(report["site"]), Path(report["directory"])
    installed = Path(report["destination"]) / "upgrade_fixture"
    assert tree_bytes(site) == report["before"]
    assert tree_bytes(installed) != report["old_source"]
    assert (
        site.parent / ".site-packages.dependencies-repair-required"
    ).exists()
    result = run_absolute_worker(report)
    assert result.returncode == 1, result.stdout + result.stderr
    status = json.loads((directory / "operation.json").read_text())
    assert status["status"] == "failed"
    assert status["error"]["code"] == "DEPENDENCY_INTERRUPTED", status.get(
        "error"
    )
    assert tree_bytes(site) == report["before"]
    assert tree_bytes(installed) == report["old_source"]
    assert (
        installed / "old-only.txt"
    ).read_text() == "preserve prior installed source"
    assert not (installed / "new-only.txt").exists()
    assert not (
        site.parent / ".site-packages.dependencies-repair-required"
    ).exists()
    assert not (
        site.parent / ".site-packages.dependencies-maintenance"
    ).exists()


@pytest.mark.asyncio
async def test_host_import_after_review_requires_a_fresh_plan_before_restart_or_write(
    isolated_loader, tmp_path, monkeypatch
):
    loader, _, site, destination = isolated_loader
    distribution(site, "upgrade-sdk", "1.0")
    manager = upgrade_manager(loader)
    operation = await manager.stage(channel_source(tmp_path / "incoming"))
    assert operation["requires_restart"] is False
    monkeypatch.syspath_prepend(str(site))
    import importlib

    sdk = importlib.import_module("upgrade_sdk")
    assert sdk.VERSION == "1.0"
    before = tree_bytes(site)
    try:
        applied = await manager.apply(operation["id"])
        assert applied["status"] == "failed", applied
        assert applied["error"]["code"] == "DEPENDENCY_PLAN_STALE", applied
        assert tree_bytes(site) == before
        assert sdk.VERSION == "1.0"
        assert not (destination / "upgrade_fixture").exists()
        from qwenpaw.config.utils import get_config_path

        stored = json.loads(
            (
                get_config_path().parent
                / "dependency_upgrades"
                / operation["id"]
                / "operation.json"
            ).read_text()
        )
        assert not stored.get("worker_pid")
    finally:
        monkeypatch.delitem(sys.modules, "upgrade_sdk", raising=False)


@pytest.mark.asyncio
async def test_installed_plugin_repair_returns_reviewable_upgrade_and_preserves_config(
    isolated_loader,
):
    loader, app, site, destination = isolated_loader
    distribution(site, "upgrade-sdk", "1.0")
    installed = channel_source(destination / "upgrade_fixture")
    from qwenpaw.config.utils import get_config_path, load_config

    config = load_config()
    config.plugins = {
        "upgrade_fixture": {
            "enabled": False,
            "config": {"fixture_secret": "preserve-saved-configuration"},
        }
    }
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(config.model_dump_json())
    config_before = path.read_bytes()
    packages_before, source_before = tree_bytes(site), tree_bytes(installed)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://fixture.test",
    ) as client:
        response = await client.post(
            "/plugins/upgrade_fixture/repair-dependencies"
        )
    assert tree_bytes(site) == packages_before
    assert tree_bytes(installed) == source_before
    assert path.read_bytes() == config_before
    assert not loader.registry.runtime_owners.leases()
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, dict), detail
    assert detail["code"] == "DEPENDENCY_UPGRADE_REQUIRED", detail
    operation = detail["operation"]
    assert operation["status"] == "needs_confirmation", operation
    assert operation["plugin_id"] == "upgrade_fixture"
    assert operation["changes"] == [
        {
            "name": "upgrade-sdk",
            "current_version": "1.0",
            "target_version": "2.0",
        }
    ]
