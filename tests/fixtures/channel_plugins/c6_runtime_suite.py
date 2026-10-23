# -*- coding: utf-8 -*-
"""Finite runtime manifest and fresh managed-site acc
eptance, actual A/child."""

# pylint: disable=protected-access,redefined-outer-name,unused-argument
import hashlib
import json
from dataclasses import replace
from pathlib import Path
import platform
import subprocess
import sys
from types import SimpleNamespace as NS

import pytest
from starlette.requests import Request

from c5_support import KEY, wheelhouse

pytest_plugins = ["c5_support"]


def configure_runtime(transaction, monkeypatch, runtime):
    """Retain Loader's environment custody when replacing fixture settings."""
    from qwenpaw.plugins.dependency_maintenance import lease_environment

    lease_environment(runtime.dependency_paths)
    monkeypatch.setattr(transaction.registry, "channel_runtime", None)
    transaction.registry.configure_channel_runtime(runtime)


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    from qwenpaw.__version__ import __version__

    root = tmp_path / "resources"
    executable = root / "python/bin/python3"
    executable.parent.mkdir(parents=True)
    executable.write_text("fixture runtime executable")
    support = root / "site"
    worker = support / "qwenpaw/channel_protocol/shared_worker.py"
    worker.parent.mkdir(parents=True)
    worker.write_text("fixture support")
    index = support / "qwenpaw/official_channels/index.json"
    index.parent.mkdir()
    index.write_text("fixture index")
    identity = {
        "version": [3, 11],
        "implementation": "cpython",
        "cache_tag": "cpython-311",
        "sys_platform": "win32",
        "system": "Windows",
        "machine": "AMD64",
        "supported_tags": ["cp311-cp311-win_amd64", "py3-none-any"],
    }
    data = {
        "schema_version": 1,
        "host_version": __version__,
        "preset": "channels-full",
        "python_executable": "python/bin/python3",
        "support_root": "site",
        "dependency_paths": ["site"],
        "python": identity,
        "python_runtime_release": "local-verification",
        "host_wheel_sha256": "a" * 64,
        "official_index_sha256": hashlib.sha256(
            index.read_bytes(),
        ).hexdigest(),
    }
    manifest = root / "runtime.json"
    manifest.write_text(json.dumps(data))
    env = {
        "QWENPAW_TAURI_RESOURCE_DIR": str(root),
        "QWENPAW_CHANNEL_RUNTIME_MANIFEST": str(manifest),
        "QWENPAW_DESKTOP_PY_RUNTIME": str(executable),
        "QWENPAW_CHANNEL_SUPPORT_ROOT": str(support),
        "QWENPAW_CHANNEL_DEPENDENCY_PATHS": json.dumps([str(support)]),
        "QWENPAW_CHANNEL_PRESET": "channels-full",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_config_path",
        lambda: tmp_path / "host/config.json",
    )
    return NS(
        root=root,
        executable=executable,
        support=support,
        manifest=manifest,
        data=data,
        index=index,
    )


def test_frozen_runtime_uses_child_abi_and_site_support_without_probe(frozen):
    from qwenpaw.plugins.channel_bootstrap import (
        resolve_default_channel_runtime,
    )

    runtime = resolve_default_channel_runtime()
    assert runtime.python_executable == str(frozen.executable)
    assert runtime.support_root == frozen.support
    assert runtime.runtime_identity == frozen.data["python"]
    assert (
        runtime.dependency_install_target.parent.name == "py3.11-windows-amd64"
    )
    assert runtime.dependency_paths == (
        frozen.support,
        runtime.dependency_install_target,
    )
    assert not list(runtime.dependency_install_target.iterdir())


@pytest.mark.parametrize(
    "fault",
    ["env", "support", "python", "index", "path"],
)
def test_frozen_runtime_fails_closed_without_fallback(
    frozen,
    monkeypatch,
    fault,
):
    from qwenpaw.plugins.channel_bootstrap import (
        resolve_default_channel_runtime,
    )

    if fault == "env":
        monkeypatch.setenv("QWENPAW_CHANNEL_DEPENDENCY_PATHS", "[]")
    elif fault == "support":
        (frozen.support / "qwenpaw/channel_protocol/shared_worker.py").unlink()
    elif fault == "python":
        frozen.executable.unlink()
    elif fault == "index":
        frozen.index.write_text("corrupted")
    else:
        frozen.data["support_root"] = "../untrusted"
        frozen.manifest.write_text(json.dumps(frozen.data))
    with pytest.raises((ValueError, FileNotFoundError)):
        resolve_default_channel_runtime()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["install", "repair"])
async def test_default_fresh_site_supports_existing_HTTP_local_wheel_pipeline(
    transaction,
    monkeypatch,
    tmp_path,
    operation,
):
    from qwenpaw.plugins.channel_bootstrap import (
        resolve_default_channel_runtime,
    )
    from qwenpaw.app.routers.plugins import (
        install_plugin_source,
        repair_plugin_dependencies,
    )

    runtime = resolve_default_channel_runtime()
    configure_runtime(transaction, monkeypatch, runtime)
    assert runtime.dependency_install_target.exists()
    assert not list(runtime.dependency_install_target.iterdir())
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_plugins_dir",
        lambda: transaction.installed.parent,
    )
    local = wheelhouse(tmp_path / "wheelhouse")
    source = transaction.artifact()
    (source / "requirements.txt").write_text("c5-transaction-sdk==1.0\n")
    driver = source / KEY / "c5_driver.py"
    driver.write_text(driver.read_text() + "\nimport c5_transaction_sdk\n")

    def build_wheels(command, *, timeout, plugin_id):
        assert plugin_id == KEY
        assert command[1:5] == ["-I", "-m", "pip", "wheel"]
        assert not {"download", "install", "--dest", "--target"}.intersection(
            command
        )
        staging = Path(command[command.index("--wheel-dir") + 1])
        assert staging.is_dir()
        assert not staging.is_relative_to(runtime.dependency_install_target)
        assert Path(command[command.index("--constraint") + 1]).is_file()
        assert Path(command[command.index("-r") + 1]).read_text() == (
            "c5-transaction-sdk==1.0\n"
        )
        return subprocess.run(
            [*command, "--no-index", "--find-links", str(local)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    monkeypatch.setattr(
        transaction.loader,
        "_run_subprocess_with_streaming_log",
        build_wheels,
    )
    app = NS(state=NS(plugin_loader=transaction.loader))
    record = await install_plugin_source(
        str(source),
        app=app,
        reload_agents=False,
    )
    assert "channel_validation_passed" in record.diagnostics
    if operation == "repair":
        record.status = "failed"
        transaction.loader.lifecycle.get_instance(KEY).mark_failed(
            "fixture failed",
        )
        request = Request({"type": "http", "app": app})
        result = await repair_plugin_dependencies(KEY, request)
        assert result["status"] in {"active", "inactive"}
        assert "channel_validation_passed" in result["diagnostics"]
    assert (
        runtime.dependency_install_target / "c5_transaction_sdk.py"
    ).read_text() == "VALUE = 'offline-c5-sdk'\n"
    assert (
        runtime.dependency_install_target
        / "c5_transaction_sdk-1.0.dist-info/RECORD"
    ).is_file()


@pytest.mark.asyncio
async def test_actual_child_identity_mismatch_blocks_before_dependency_write(
    transaction,
    monkeypatch,
):
    from qwenpaw.plugins.channel_bootstrap import (
        resolve_default_channel_runtime,
    )

    identity = {
        "version": [99, 1],
        "implementation": "cpython",
        "cache_tag": "cpython-991",
        "sys_platform": sys.platform,
        "system": platform.system(),
        "machine": platform.machine(),
        "supported_tags": ["py3-none-any"],
    }
    runtime = resolve_default_channel_runtime()
    configure_runtime(
        transaction,
        monkeypatch,
        replace(runtime, runtime_identity=identity),
    )
    source = transaction.artifact()
    writes = []

    async def forbidden(*args, **kwargs):
        writes.append(True)
        raise AssertionError("Mismatch crossed dependency-write boundary")

    monkeypatch.setattr(
        transaction.loader,
        "_ensure_dependencies_installed",
        forbidden,
    )
    with pytest.raises(Exception, match="CHANNEL_RUNTIME_IDENTITY_MISMATCH"):
        await transaction.loader.load_plugin_from_path(source)
    assert not writes and not list(runtime.dependency_install_target.iterdir())
    assert transaction.loader.get_loaded_plugin(KEY) is None


def _offline_cli_case(transaction, monkeypatch):
    """Seed the real offline CLI with managed runtime and preserved config."""
    from click.testing import CliRunner
    from qwenpaw.cli import plugin_commands as cli
    from qwenpaw.config.utils import load_config, save_config
    from qwenpaw.plugins.channel_bootstrap import (
        resolve_default_channel_runtime,
    )

    configure_runtime(
        transaction,
        monkeypatch,
        resolve_default_channel_runtime(),
    )
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_plugins_dir",
        lambda: transaction.installed.parent,
    )
    monkeypatch.setattr(cli, "_is_running", lambda: False)
    monkeypatch.delenv("QWENPAW_RUNTIME_ID", raising=False)
    root = load_config()
    root.plugins[KEY] = {"enabled": False, "custom": "preserve-offline"}
    root.channel_plugin_state.version = 1
    root.channel_plugin_state.preset = "channels-full"
    save_config(root)
    return CliRunner(), cli


def test_offline_CLI_A_uninstall_tombstone_and_explicit_reinstall_commit(
    transaction,
    monkeypatch,
):
    from qwenpaw.config.utils import load_config

    runner, cli = _offline_cli_case(transaction, monkeypatch)
    source = transaction.artifact()
    installed = runner.invoke(cli.plugin, ["install", str(source)])
    assert installed.exit_code == 0, installed.output
    assert transaction.installed.is_dir()
    assert load_config().plugins[KEY] == {
        "enabled": False,
        "custom": "preserve-offline",
    }
    deleted = runner.invoke(cli.plugin, ["uninstall", KEY], input="y\n")
    assert deleted.exit_code == 0, deleted.output
    assert not transaction.installed.exists()
    assert KEY in load_config().channel_plugin_state.uninstalled
    assert KEY not in load_config().plugins
    broken = transaction.artifact("2.0.0", broken=True)
    descriptor = json.loads((broken / "channel.json").read_text())
    descriptor["schema_version"] = 3
    (broken / "channel.json").write_text(json.dumps(descriptor))
    failed = runner.invoke(cli.plugin, ["install", str(broken)])
    assert failed.exit_code != 0, failed.output
    assert "schema_version must be integer 2" in failed.output
    assert KEY in load_config().channel_plugin_state.uninstalled
    assert not transaction.installed.exists()
    reinstalled = runner.invoke(cli.plugin, ["install", str(source)])
    assert reinstalled.exit_code == 0, reinstalled.output
    assert transaction.installed.is_dir()
    assert KEY not in load_config().channel_plugin_state.uninstalled
    persisted = load_config().model_dump()
    committed = {
        path.relative_to(transaction.installed): path.read_bytes()
        for path in transaction.installed.rglob("*")
        if path.is_file()
    }
    failed_force = runner.invoke(
        cli.plugin,
        ["install", str(broken), "--force"],
    )
    assert failed_force.exit_code != 0, failed_force.output
    assert "schema_version must be integer 2" in failed_force.output
    assert {
        path.relative_to(transaction.installed): path.read_bytes()
        for path in transaction.installed.rglob("*")
        if path.is_file()
    } == committed
    assert KEY not in load_config().channel_plugin_state.uninstalled
    assert load_config().model_dump() == persisted


def test_offline_CLI_force_installs_without_importing_driver(
    transaction,
    monkeypatch,
):
    """Commit a valid static Driver without executing its failing body."""
    from qwenpaw.config.utils import load_config

    runner, cli = _offline_cli_case(transaction, monkeypatch)
    source = transaction.artifact()
    installed = runner.invoke(cli.plugin, ["install", str(source)])
    assert installed.exit_code == 0, installed.output
    assert transaction.installed.is_dir()
    persisted = load_config().model_dump()
    raises_on_import = transaction.artifact("2.1.0", broken=True)
    driver = raises_on_import / KEY / "c5_driver.py"
    imported = raises_on_import.parent / "driver-imported"
    driver.write_text(
        "from pathlib import Path as _OfflinePath\n"
        f"_OfflinePath({str(imported)!r}).write_text('imported')\n"
        + driver.read_text(),
    )
    offline = runner.invoke(
        cli.plugin,
        ["install", str(raises_on_import), "--force"],
    )
    assert offline.exit_code == 0, offline.output
    assert not imported.exists() and not transaction.network.exists()
    assert (transaction.installed / KEY / "c5_driver.py").read_bytes() == (
        driver.read_bytes()
    )
    assert (
        json.loads((transaction.installed / "plugin.json").read_text())[
            "version"
        ]
        == "2.1.0"
    )
    assert load_config().model_dump() == persisted
    assert KEY not in load_config().channel_plugin_state.uninstalled


@pytest.mark.parametrize("operation", ["install", "uninstall"])
def test_live_CLI_API_failure_never_falls_back_to_offline_writer(
    transaction,
    monkeypatch,
    operation,
):
    from click.testing import CliRunner
    from qwenpaw.cli import plugin_commands as cli

    source = transaction.artifact()
    monkeypatch.setattr(cli, "_is_running", lambda: True)
    monkeypatch.setattr(cli, "_api_install_plugin", lambda *_a, **_k: False)
    monkeypatch.setattr(cli, "_api_uninstall_plugin", lambda *_a, **_k: False)

    def forbidden(*_args, **_kwargs):
        pytest.fail("Live API failure attempted local mutation")

    monkeypatch.setattr(cli, "_offline_channel_transaction", forbidden)
    before = source.joinpath("plugin.json").read_bytes()
    result = CliRunner().invoke(
        cli.plugin,
        [operation, str(source) if operation == "install" else KEY],
        input="y\n",
    )
    assert result.exit_code == 0, result.output
    assert not transaction.installed.exists()
    assert source.joinpath("plugin.json").read_bytes() == before
