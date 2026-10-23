# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,too-many-locals
# pylint: disable=too-many-statements,using-constant-test
"""Independent C5 fixture, without modifying C2/C3/C4 shared fixtures."""

import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace as NS
import zipfile

import psutil
import pytest_asyncio

ROOT = Path(__file__).resolve().parents[3]
KEY = os.environ.get("QWENPAW_C5_CHANNEL", "feishu")


def wheelhouse(directory):
    """Create one complete local SDK wheel; no build tool or index access."""
    directory.mkdir()
    info = "c5_transaction_sdk-1.0.dist-info"
    files = {
        "c5_transaction_sdk.py": b"VALUE = 'offline-c5-sdk'\n",
        f"{info}/METADATA": (
            b"Metadata-Version: 2.1\nName: c5-transaction-sdk\nVersion: 1.0\n"
        ),
        f"{info}/WHEEL": (
            b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
        ),
        f"{info}/top_level.txt": b"c5_transaction_sdk\n",
    }
    entries = []
    for name, data in files.items():
        encoded = base64.urlsafe_b64encode(hashlib.sha256(data).digest())
        entries.append(
            f"{name},sha256={encoded.decode().rstrip('=')},{len(data)}\n",
        )
    files[f"{info}/RECORD"] = (
        "".join(entries) + f"{info}/RECORD,,\n"
    ).encode()
    target = directory / "c5_transaction_sdk-1.0-py3-none-any.whl"
    with zipfile.ZipFile(target, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return directory


def rows(network, kind=None, version=None):
    """Read factual connection/process evidence, never record status alone."""
    values = (
        [json.loads(line) for line in network.read_text().splitlines()]
        if network.exists()
        else []
    )
    return [
        row
        for row in values
        if (kind is None or row["kind"] == kind)
        and (version is None or row["version"] == version)
    ]


async def eventually(predicate, timeout=8):
    """Wait for observable evidence rather than a timing-dependent sleep."""
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("Timed out waiting for C5 evidence")
        await asyncio.sleep(0.01)


@pytest_asyncio.fixture
async def transaction(tmp_path, monkeypatch):
    from qwenpaw.app.channels.manager import ChannelManager
    from qwenpaw.config.config import Config
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.channel_adapter import ChannelRuntimeSettings
    from qwenpaw.plugins.loader import PluginLoader
    from qwenpaw.plugins.registry import PluginRegistry
    from qwenpaw.plugins.workspace_projector import WorkspaceProjector

    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "host")
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_config_path",
        lambda: tmp_path / "config.json",
    )
    previous = PluginRegistry._instance
    PluginRegistry._instance = None
    registry = PluginRegistry()
    installed = tmp_path / "installed"
    network = tmp_path / "network.jsonl"
    (tmp_path / "shared-site").mkdir()
    workspaces = []
    loader = PluginLoader(
        [installed],
        channel_runtime=ChannelRuntimeSettings(
            python_executable=sys.executable,
            support_root=ROOT / "src",
            qwenpaw_version="2.2.2b4",
            selected_channels=frozenset({KEY}),
            startup_timeout=5,
            shutdown_timeout=0.25,
            admission_timeout=2,
            dependency_paths=(tmp_path / "shared-site",),
            dependency_install_target=tmp_path / "shared-site",
        ),
    )
    loader.registry = registry
    registry.projector = WorkspaceProjector(live_workspaces=lambda: workspaces)

    def artifact(version="1.0.0", *, installed_source=False, broken=False):
        source = (
            installed / KEY
            if installed_source
            else tmp_path / ("incoming-" + version) / KEY
        )
        shutil.copytree(ROOT / "plugins/channel" / KEY, source)
        manifest = json.loads((source / "plugin.json").read_text())
        manifest["version"] = version
        manifest.pop("dependencies", None)
        (source / "plugin.json").write_text(json.dumps(manifest))
        (source / "requirements.txt").write_text("")
        descriptor = json.loads((source / "channel.json").read_text())
        descriptor["entrypoint"] = {
            "scope": "runner",
            "module": KEY + ".c5_driver",
            "qualname": "Driver",
        }
        (source / "channel.json").write_text(json.dumps(descriptor))
        body = Path(__file__).with_name("c5_driver.py").read_text()
        if broken:
            body += "\nraise RuntimeError('invalid candidate before stop')\n"
        (source / KEY / "c5_driver.py").write_text(
            f"NETWORK = {str(network)!r}\nVERSION = {version!r}\n" + body,
        )
        return source

    async def workspace(name, *, fail_new=False):
        directory = tmp_path / name
        directory.mkdir()
        credentials = (
            {
                "app_id": "fail-new" if fail_new else name,
                "app_secret": "workspace-secret",
            }
            if KEY == "feishu"
            else {
                "client_id": "fail-new" if fail_new else name,
                "client_secret": "workspace-secret",
            }
        )
        config = Config.model_validate(
            {"channels": {KEY: {"enabled": True, **credentials}}},
        )

        async def agent(_request):
            if False:
                yield None

        ws = NS(
            agent_id=name,
            workspace_dir=directory,
            _config=config,
            stream_query=agent,
        )
        ws.channel_manager = ChannelManager.from_config(
            agent,
            config,
            workspace_dir=directory,
        )
        ws.channel_manager.set_workspace(ws)
        workspaces.append(ws)
        await ws.channel_manager.start_all()
        return ws

    async def seed(*, enabled=True, config=None):
        source = artifact(installed_source=True)
        manifest = PluginManifest.from_dict(
            json.loads((source / "plugin.json").read_text()),
        )
        record = await loader.load_plugin(
            manifest,
            source,
            {**(config or {}), "enabled": enabled},
            activate=False,
        )
        await loader.activate_plugin_unlocked(KEY)
        return record

    async def identity(ws):
        channel = await ws.channel_manager.get_channel(KEY)
        assert channel is not None
        value = await channel.channel_process.call("fixture.identity", {})
        return channel, value

    case = NS(
        loader=loader,
        registry=registry,
        installed=installed / KEY,
        network=network,
        artifact=artifact,
        workspace=workspace,
        seed=seed,
        identity=identity,
        workspaces=workspaces,
        site=tmp_path / "shared-site",
        config_path=tmp_path / "config.json",
    )
    yield case
    try:
        if loader.get_loaded_plugin(KEY) is not None:
            await loader.unload_plugin(KEY)
        for ws in workspaces:
            await ws.channel_manager.stop_all()
        for row in rows(network, "connected"):
            assert not psutil.pid_exists(
                row["pid"],
            ), "C5 fixture leaked a worker"
    finally:
        PluginRegistry._instance = previous
