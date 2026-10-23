# -*- coding: utf-8 -*-
"""Supervisor owns backend lifetime; retained workers own offline transactions."""

import asyncio
import configparser
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from types import SimpleNamespace

from click.testing import CliRunner
import pytest

from qwenpaw.cli import app_cmd as launcher
from qwenpaw.plugins import dependency_worker as worker
from qwenpaw.plugins.dependency_upgrade import (
    DependencyUpgradeManager,
    schedule_maintenance,
)

ROOT = Path(__file__).resolve().parents[3]
SUPERVISOR_KEYS = (
    "SUPERVISOR_ENABLED",
    "SUPERVISOR_PROCESS_NAME",
    "SUPERVISOR_GROUP_NAME",
)


@pytest.fixture
def launch(tmp_path, monkeypatch):
    for key in (
        *SUPERVISOR_KEYS,
        "QWENPAW_RUNTIME_PROVISIONER",
        "QWENPAW_RUNTIME_ID",
        "QWENPAW_RUNNING_IN_CONTAINER",
        "QWENPAW_RELOAD_MODE",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(launcher, "_dependency_restart", None)
    monkeypatch.setattr(
        sys,
        "orig_argv",
        [sys.executable, "-m", "qwenpaw", "app"],
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(launcher, "install_shutdown_handlers", lambda: None)
    # Keep launch configuration real while preventing the HTTP server from running.
    monkeypatch.setattr(launcher.uvicorn, "run", lambda *args, **kwargs: None)

    def invoke(*arguments):
        result = CliRunner().invoke(launcher.app_cmd, list(arguments))
        assert result.exit_code == 0, result.output + repr(result.exception)
        return launcher._dependency_restart

    return invoke


@pytest.mark.parametrize(
    "environment,arguments,automatic",
    [
        ({}, (), True),
        ({"QWENPAW_RUNNING_IN_CONTAINER": "1"}, (), True),
        ({"SUPERVISOR_ENABLED": "1"}, (), False),
        ({"SUPERVISOR_PROCESS_NAME": "app"}, (), False),
        ({"SUPERVISOR_GROUP_NAME": "app"}, (), False),
        ({}, ("--reload",), False),
    ],
    ids=[
        "standalone",
        "container-only",
        "enabled",
        "process",
        "group",
        "reload",
    ],
)
def test_repeated_launch_replaces_restart_ownership(
    launch,
    monkeypatch,
    tmp_path,
    environment,
    arguments,
    automatic,
):
    # A managed/reload invocation must clear a prior standalone invocation.
    assert launch() is not None
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    restart = launch(*arguments)
    if automatic:
        assert restart == {
            "command": [sys.executable, "-m", "qwenpaw", "app"],
            "cwd": str(tmp_path),
        }
    else:
        assert restart is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode",
    ["supervisor", "reload", "asgi", "standalone"],
)
async def test_schedule_persists_launch_selected_maintenance_without_competing_owner(
    launch,
    monkeypatch,
    tmp_path,
    mode,
):
    if mode != "asgi":
        launch()
        if mode == "supervisor":
            monkeypatch.setenv("SUPERVISOR_ENABLED", "1")
            monkeypatch.setenv("SUPERVISOR_PROCESS_NAME", "app")
        restart = launch(*(["--reload"] if mode == "reload" else []))
    else:
        restart = None  # ASGI launch has no CLI-owned restart registration.
    from qwenpaw.config import utils as config_utils

    monkeypatch.setattr(
        config_utils,
        "get_config_path",
        lambda: tmp_path / "config.json",
    )
    stopped, spawned = [], []
    manager = DependencyUpgradeManager(
        SimpleNamespace(
            dependency_upgrade_shutdown=lambda: stopped.append(
                "backend-stopped",
            ),
            dependency_upgrade_restart=restart,
        ),
    )
    directory = manager.root / ("a" * 32)
    (directory / "worker").mkdir(parents=True)
    operation = {
        "id": directory.name,
        "approved": True,
        "worker_python": sys.executable,
        "payload": {"retained": "reviewed-plan"},
    }

    def popen(command, **options):
        spawned.append((command, options))
        return SimpleNamespace(pid=12345)

    monkeypatch.setattr(subprocess, "Popen", popen)
    schedule_maintenance(manager, directory, operation)
    await asyncio.sleep(0.3)
    saved = json.loads((directory / "operation.json").read_text())
    assert saved["status"] == "waiting_restart"
    assert saved["approved"] is True
    assert saved["payload"] == {"retained": "reviewed-plan"}
    assert saved["requires_restart"] is True
    command = [
        sys.executable,
        "-I",
        "-S",
        str(directory / "worker/dependency_worker.py"),
    ]
    if mode == "standalone":
        assert saved["restart"] == restart
        assert saved["worker_pid"] == 12345
        assert saved["instructions"] == []
        assert len(spawned) == 1 and spawned[0][0] == command
        assert stopped == ["backend-stopped"]
    else:
        assert saved["restart"] is None
        assert "worker_pid" not in saved
        assert not spawned and not stopped
        instructions = "\n".join(saved["instructions"])
        assert shlex.join(command) in instructions
        assert (
            "stop" in instructions.lower()
            and "restart" in instructions.lower()
        )
        if mode == "supervisor":
            assert "supervisorctl" in instructions
            assert "stop app" in instructions and "start app" in instructions


def worker_operation(tmp_path, transaction, restart):
    """A signed retained plan changes only one owned file in a temporary site."""
    directory = tmp_path / "operations" / ("b" * 32)
    (directory / "payload").mkdir(parents=True)
    site = tmp_path / "site-packages"
    site.mkdir()
    installed = site / "fixture_sdk.py"
    installed.write_bytes(b"VERSION = '1.0'\n")
    os.chmod(installed, 0o644)
    old = installed.read_bytes()
    new = b"VERSION = '2.0'\n"
    (directory / "payload/new").write_bytes(new)
    plugin_dirs = tmp_path / "plugins"
    target = plugin_dirs / "fixture"
    target.mkdir(parents=True)
    (target / "driver.py").write_text("old plugin source")
    operation = dict.fromkeys(transaction._PLAN_FIELDS)
    operation.update(
        id=directory.name,
        plugin_id="fixture",
        capability="c" * 64,
        approved=True,
        status="waiting_restart",
        requires_restart=True,
        environment={"distributions": {}},
        plugin_dirs=[str(plugin_dirs)],
        continuation_python=sys.executable,
        support_root=str(ROOT / "src"),
        restart=restart,
        payload={
            "sites": [str(site)],
            "wheels": [],
            "old": {
                str(installed): {
                    "sha256": hashlib.sha256(old).hexdigest(),
                    "mode": 0o644,
                },
            },
            "new": {
                str(installed): {
                    "payload": "payload/new",
                    "sha256": hashlib.sha256(new).hexdigest(),
                    "mode": 0o644,
                },
            },
        },
    )
    transaction.authenticate_plan(directory, operation, seal=True)
    transaction.atomic_json(directory / "operation.json", operation)
    return directory, installed, target


@pytest.mark.parametrize(
    "automatic",
    [False, True],
    ids=["manual", "standalone"],
)
@pytest.mark.parametrize("outcome", ["success", "rollback", "repair"])
def test_worker_persists_transaction_outcome_and_respects_restart_custody(
    tmp_path,
    monkeypatch,
    automatic,
    outcome,
):
    maintenance, transaction = worker._modules()
    restart = (
        {"command": ["fixture-backend", "app"], "cwd": str(tmp_path)}
        if automatic
        else None
    )
    directory, installed, target = worker_operation(
        tmp_path,
        transaction,
        restart,
    )
    spawned = []
    monkeypatch.setenv(
        "QWENPAW_DEPENDENCY_MAINTENANCE",
        "previous-test-capability",
    )

    def continuation(command, **options):
        # Replace only the fresh child; retain real authentication, file writes,
        # journal, rollback, markers, and operation persistence in the worker.
        assert command[0] == sys.executable and command[1:3] == ["-I", "-c"]
        assert command[-2] == str(directory)
        assert options["stdin"] == subprocess.DEVNULL
        if command[-1] == "1":
            assert installed.read_bytes() == b"VERSION = '1.0'\n"
            return subprocess.CompletedProcess(command, 0)
        assert installed.read_bytes() == b"VERSION = '2.0'\n"
        (target / "driver.py").write_text("new plugin source")
        if outcome == "repair":
            # Corrupt the durable backup to force the real rollback safety check.
            (directory / "backup/0").write_bytes(b"damaged backup")
        if outcome != "success":
            return subprocess.CompletedProcess(command, 1)
        (directory / "continuation.json").write_text(
            json.dumps({"id": "fixture"}),
        )
        return subprocess.CompletedProcess(command, 0)

    def popen(command, **options):
        spawned.append((command, options))
        return SimpleNamespace(pid=12346)

    monkeypatch.setattr(worker.subprocess, "run", continuation)
    monkeypatch.setattr(worker.subprocess, "Popen", popen)
    code = worker.run(directory)
    saved = json.loads((directory / "operation.json").read_text())
    journal = json.loads((directory / "journal.json").read_text())
    assert "worker_pid" not in saved
    assert saved["restart"] == restart
    if outcome == "success":
        assert code == 0 and saved["status"] == "succeeded"
        assert saved["result"] == {"id": "fixture"}
        assert installed.read_bytes() == b"VERSION = '2.0'\n"
        assert (target / "driver.py").read_text() == "new plugin source"
        assert journal["phase"] == "committed"
    else:
        assert code == 1 and saved["status"] == "failed"
        assert saved["retryable"] is (outcome == "rollback")
        assert saved["error"]["code"] == (
            "DEPENDENCY_REPAIR_REQUIRED"
            if outcome == "repair"
            else "DEPENDENCY_CONTINUATION_FAILED"
        )
        if outcome == "rollback":
            assert installed.read_bytes() == b"VERSION = '1.0'\n"
            assert (target / "driver.py").read_text() == "old plugin source"
            assert journal["phase"] == "rolled_back"
    assert maintenance.repair_marker(installed.parent).exists() is (
        outcome == "repair"
    )
    assert maintenance.marker(installed.parent).exists() is (
        outcome == "repair"
    )
    assert len(spawned) == int(automatic and outcome != "repair")
    if spawned:
        command, options = spawned[0]
        assert command == ["fixture-backend", "app"]
        assert options["cwd"] == str(tmp_path)
        assert "QWENPAW_DEPENDENCY_MAINTENANCE" not in options["env"]


@pytest.mark.parametrize(
    "template",
    [
        "deploy/config/supervisord.conf.template",
    ],
)
def test_supervisor_template_exposes_only_restricted_local_control(template):
    config = configparser.ConfigParser(interpolation=None)
    config.read(ROOT / template)
    assert (
        config.get("unix_http_server", "file", fallback=None)
        == "/run/qwenpaw-supervisor.sock"
    )
    assert int(config.get("unix_http_server", "chmod"), 8) == 0o600
    assert (
        config.get(
            "rpcinterface:supervisor",
            "supervisor.rpcinterface_factory",
        )
        == "supervisor.rpcinterface:make_main_rpcinterface"
    )
    assert (
        config.get("supervisorctl", "serverurl")
        == "unix:///run/qwenpaw-supervisor.sock"
    )
    assert not config.has_section("inet_http_server")
    assert config.get("program:app", "autorestart") == "unexpected"
