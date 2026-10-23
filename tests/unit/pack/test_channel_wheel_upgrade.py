# -*- coding: utf-8 -*-
"""Real pip/venv upgrades execute released host and SDK code offline."""

import email
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures/channel_plugins"
spec = importlib.util.spec_from_file_location(
    "channel_wheel_upgrade_support",
    FIXTURES / "wheel_upgrade_support.py",
)
assert spec is not None and spec.loader is not None
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)


@pytest.fixture(scope="module")
def wheels(tmp_path_factory):
    root = tmp_path_factory.mktemp("channel-wheel-upgrade")
    warehouse = root / "warehouse"
    sdk = support.installed_sdk_wheel(warehouse)
    old = support.legacy_host_wheel(warehouse)
    candidate = support.build_candidate(root)
    return warehouse, sdk, old, candidate


def saved_channel(root):
    host = root / "host"
    host.mkdir()
    values = {
        "enabled": True,
        "host": "historic-broker",
        "subscribe_topic": "qwenpaw/in/+",
        "publish_topic": "qwenpaw/out/{client_id}",
        "bot_prefix": "keep-me",
    }
    path = host / "config.json"
    path.write_text(json.dumps({"channels": {"mqtt": values}}))
    return path, values


def assert_saved(path, values):
    saved = json.loads(path.read_text())["channels"]["mqtt"]
    assert all(saved[key] == value for key, value in values.items())


def prepare_with_process_trace(python, env, root):
    trace = root / "processes.jsonl"
    script = r"""
import json, pathlib, sys
trace = pathlib.Path(sys.argv[1])
def observe(event, arguments):
    if event == "subprocess.Popen":
        with trace.open("a") as stream:
            stream.write(json.dumps(arguments[1]) + "\n")
sys.addaudithook(observe)
from qwenpaw.cli.main import cli
cli(["plugins", "prepare-upgrade"], prog_name="qwenpaw")
"""
    result = subprocess.run(
        [str(python), "-I", "-c", script, str(trace)],
        env=env,
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    commands = [json.loads(line) for line in trace.read_text().splitlines()]
    return result, commands


def test_real_wheel_upgrade_keeps_enabled_sdk_and_runs_after_restart(
    tmp_path,
    wheels,
):
    warehouse, _, old, candidate = wheels
    python = support.create_environment(tmp_path / "venv")
    env = support.clean_environment(tmp_path)
    env["PIP_FIND_LINKS"] = str(warehouse)
    config, values = saved_channel(tmp_path)
    # Keep a user-maintained source across the actual pip replacement.
    with zipfile.ZipFile(candidate) as host:
        index = json.loads(host.read("qwenpaw/official_channels/index.json"))
        mqtt = next(
            row for row in index["plugins"] if row["plugin_id"] == "mqtt"
        )
        payload = host.read("qwenpaw/official_channels/" + mqtt["filename"])
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            archive.extractall(config.parent / "plugins")
    source = config.parent / "plugins/mqtt"
    (source / "README.md").write_text("preserve my installed customization\n")
    original = {
        path.relative_to(source): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }
    support.run(
        [python, "-I", "-m", "pip", "install", old],
        env=env,
        cwd=tmp_path,
    )
    support.run(
        [
            python,
            "-I",
            "-c",
            "import paho.mqtt.client as mqtt; "
            "from importlib.metadata import version; "
            "assert version('qwenpaw') == '0.0.0'; "
            "assert not mqtt.Client(callback_api_version="
            "mqtt.CallbackAPIVersion.VERSION2).is_connected()",
        ],
        env=env,
        cwd=tmp_path,
    )
    marker = python.parent / "old-environment"
    marker.write_text("same interpreter environment")
    support.run(
        [python, "-I", "-m", "pip", "install", "--upgrade", candidate],
        env=env,
        cwd=tmp_path,
    )
    assert marker.read_text() == "same interpreter environment"
    with zipfile.ZipFile(candidate) as archive:
        name = next(
            item
            for item in archive.namelist()
            if item.endswith(".dist-info/METADATA")
        )
        expected = email.message_from_bytes(archive.read(name))["Version"]
    observed = support.run(
        [
            python,
            "-I",
            "-c",
            "from importlib.metadata import version; print(version('qwenpaw'))",
        ],
        env=env,
        cwd=tmp_path,
    )
    assert observed.stdout.strip() == expected != "0.0.0"
    # The SDK survives pip's host replacement; normal boot uses only checks.
    # No upgrade/repair command is invoked in this path.
    for _ in range(2):
        result = support.run(
            [python, "-I", "-B", support.PROBE],
            env=env,
            cwd=tmp_path,
        )
        observation = json.loads(result.stdout.splitlines()[-1])
        assert Path(observation["sdk_origin"]).is_relative_to(
            tmp_path / "venv",
        )
        assert_saved(config, values)
        assert {
            path.relative_to(source): path.read_bytes()
            for path in source.rglob("*")
            if path.is_file()
        } == original
    assert not list((tmp_path / "host/plugin_runtime").rglob("*.dist-info"))


def test_explicit_upgrade_bootstraps_pipless_venv_and_real_sdk(
    tmp_path,
    wheels,
):
    warehouse, _, _, candidate = wheels
    python = support.create_environment(tmp_path / "venv", with_pip=False)
    env = support.clean_environment(tmp_path)
    env["PIP_FIND_LINKS"] = str(warehouse)
    config, values = saved_channel(tmp_path)
    # pip's supported --python mode installs into a genuinely pipless target.
    support.run(
        [
            sys.executable,
            "-I",
            "-m",
            "pip",
            "--python",
            python,
            "install",
            candidate,
        ],
        env=env,
        cwd=tmp_path,
    )
    absent = subprocess.run(
        [str(python), "-I", "-m", "pip", "--version"],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert absent.returncode != 0 and "No module named pip" in absent.stderr
    result, commands = prepare_with_process_trace(python, env, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert sum("ensurepip" in command for command in commands) == 1
    assert (
        sum("pip" in command and "wheel" in command for command in commands)
        == 2
    )
    support.run(
        [python, "-I", "-m", "pip", "--version"],
        env=env,
        cwd=tmp_path,
    )
    for _ in range(2):
        result = support.run(
            [python, "-I", "-B", support.PROBE],
            env=env,
            cwd=tmp_path,
        )
        origin = json.loads(result.stdout.splitlines()[-1])["sdk_origin"]
        assert Path(origin).is_relative_to(tmp_path / "host/plugin_runtime")
        assert_saved(config, values)


def test_missing_sdk_wheel_fails_explicit_upgrade_without_ensurepip_retry(
    tmp_path,
    wheels,
):
    _, _, _, candidate = wheels
    python = support.create_environment(tmp_path / "venv")
    env = support.clean_environment(tmp_path)
    config, values = saved_channel(tmp_path)
    support.run(
        [python, "-I", "-m", "pip", "install", candidate],
        env=env,
        cwd=tmp_path,
    )
    result, commands = prepare_with_process_trace(python, env, tmp_path)
    assert result.returncode != 0
    assert "DEPENDENCY_PLAN_UNVERIFIED" in result.stderr
    assert not any("ensurepip" in command for command in commands)
    wheel_commands = [
        command
        for command in commands
        if "pip" in command and "wheel" in command
    ]
    assert len(wheel_commands) == 2
    planned, control = wheel_commands
    assert "--constraint" in planned
    assert "--constraint" not in control
    staging = Path(planned[planned.index("--wheel-dir") + 1])
    assert Path(planned[planned.index("--constraint") + 1]).parent == staging
    assert Path(control[control.index("--wheel-dir") + 1]) != staging
    for command in wheel_commands:
        assert command[:5] == [str(python), "-I", "-m", "pip", "wheel"]
        assert command[command.index("-r") + 1] == str(
            config.parent / "plugins/mqtt/requirements.txt",
        )
    assert not list((tmp_path / "host/plugin_runtime").rglob("*.dist-info"))
    assert_saved(config, values)
