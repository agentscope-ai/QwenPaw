# -*- coding: utf-8 -*-
"""Execute install.sh offline through real venvs, wheels and channel preparation.

Only uv's command boundary is adapted to stdlib venv and actual pip. Unrelated
host libraries are borrowed from the test interpreter; paho and QwenPaw are
excluded so neither can conceal a missing post-rebuild preparation step.
"""

import ast
import json
from pathlib import Path
import runpy
import subprocess
import sys
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[3]
SUPPORT_PATH = ROOT / "tests/fixtures/channel_plugins/wheel_upgrade_support.py"
SUPPORT = runpy.run_path(str(SUPPORT_PATH))

UV_ADAPTER = r'''
import json, os, pathlib, runpy, shutil, subprocess, sys

support = runpy.run_path(os.environ["INSTALLER_TEST_SUPPORT"])
args = sys.argv[1:]
target = pathlib.Path(os.environ["QWENPAW_HOME"]) / "venv"
if args[0] == "venv":
    assert pathlib.Path(args[1]) == target
    assert os.environ["UV_VENV_CLEAR"] == "1"
    existed = (target / "old-environment").is_file()
    shutil.rmtree(target, ignore_errors=True)
    support["create_environment"](target, with_pip="--seed" in args)
    pathlib.Path(os.environ["INSTALLER_TEST_CLEARED"]).write_text(str(existed))
elif args[:2] == ["pip", "install"]:
    python = args[args.index("--python") + 1]
    assert pathlib.Path(python) == target / "bin/python"
    assert args[2].split("==")[0] == "qwenpaw"
    subprocess.run([
        sys.executable, "-m", "pip", "--python", python, "install",
        "--no-index", "--quiet", os.environ["INSTALLER_TEST_WHEEL"],
    ], check=True)
    result = subprocess.run([python, "-I", "-c", """
import importlib.util, json, pathlib, qwenpaw
print(json.dumps({"host": qwenpaw.__file__,
                  "sdk_present": importlib.util.find_spec("paho") is not None}))
"""], check=True, text=True, capture_output=True)
    pathlib.Path(os.environ["INSTALLER_TEST_BASE"]).write_text(result.stdout)
else:
    raise AssertionError("Unexpected uv invocation: " + repr(args))
'''


@pytest.fixture(scope="module")
def installer_artifacts(tmp_path_factory):
    root = tmp_path_factory.mktemp("installer-wheels")
    return {
        "candidate": SUPPORT["build_candidate"](root),
        "legacy": SUPPORT["legacy_host_wheel"](root / "legacy"),
        "sdk": SUPPORT["installed_sdk_wheel"](root / "sdk"),
    }


@pytest.fixture
def installer_script():
    return ROOT / "scripts/install.sh"


def _case(root, artifacts, *, selected=True, sdk_available=True):
    env = SUPPORT["clean_environment"](root)
    install_home = root / "installation"
    python = SUPPORT["create_environment"](install_home / "venv")
    SUPPORT["run"](
        [
            python,
            "-I",
            "-m",
            "pip",
            "install",
            "--no-index",
            "--quiet",
            "--find-links",
            artifacts["sdk"].parent,
            artifacts["legacy"],
        ],
        env=env,
        cwd=root,
    )
    # This old installation really owns a working SDK before it is removed.
    SUPPORT["run"](
        [
            python,
            "-I",
            "-c",
            "from paho.mqtt.client import Client; "
            "client = Client(client_id='before-rebuild'); "
            "assert client.is_connected() is False",
        ],
        env=env,
        cwd=root,
    )
    (python.parent.parent / "old-environment").write_text("must be removed")
    state = Path(env["QWENPAW_WORKING_DIR"])
    state.mkdir()
    (state / "config.json").write_text(
        json.dumps(
            {
                "channels": {
                    "mqtt": {
                        "enabled": selected,
                        "host": "127.0.0.1",
                        "port": 1883,
                        "subscribe_topic": "qwenpaw/in/+",
                        "publish_topic": "qwenpaw/out/{client_id}",
                    },
                },
            },
        ),
    )
    tools = root / "tools"
    tools.mkdir()
    (tools / "uv").write_text(f"#!{sys.executable}\n" + UV_ADAPTER)
    (tools / "uv").chmod(0o755)
    # Installer mirror probing cannot leave the machine or bootstrap uv.
    (tools / "curl").write_text("#!/bin/sh\nexit 1\n")
    (tools / "curl").chmod(0o755)
    empty = root / "empty-index"
    empty.mkdir()
    env.update(
        PATH=str(tools) + ":" + env["PATH"],
        QWENPAW_HOME=str(install_home),
        INSTALLER_TEST_SUPPORT=str(SUPPORT_PATH),
        INSTALLER_TEST_WHEEL=str(artifacts["candidate"]),
        INSTALLER_TEST_CLEARED=str(root / "cleared.txt"),
        INSTALLER_TEST_BASE=str(root / "base.json"),
        PIP_FIND_LINKS=str(
            artifacts["sdk"].parent if sdk_available else empty,
        ),
    )
    return env, python


def _install(script, root, env, *args):
    return subprocess.run(
        ["bash", str(script), *args],
        env=env,
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )


def _assert_rebuilt(root, python):
    assert (root / "cleared.txt").read_text() == "True"
    assert not (python.parent.parent / "old-environment").exists()
    base = json.loads((root / "base.json").read_text())
    assert Path(base["host"]).is_relative_to(python.parent.parent)
    assert base["sdk_present"] is False


@pytest.mark.skipif(sys.platform == "win32", reason="Unix installer")
def test_installer_recovers_enabled_sdk_after_clearing_environment(
    tmp_path,
    installer_artifacts,
    installer_script,
):
    """Omitting the installer preparation hook loses the old enabled SDK."""
    env, python = _case(tmp_path, installer_artifacts)
    result = _install(installer_script, tmp_path, env)
    assert result.returncode == 0, result.stdout + result.stderr
    _assert_rebuilt(tmp_path, python)
    # No manual prepare/repair: this checks the installer's resulting state,
    # then sends with the real SDK through a real child, including restart.
    result = SUPPORT["run"](
        [python, "-I", "-B", SUPPORT["PROBE"]],
        env=env,
        cwd=tmp_path,
    )
    assert json.loads(result.stdout)["sent"] == [
        ["qwenpaw/out/client17", "upgraded-1"],
        ["qwenpaw/out/client17", "upgraded-2"],
    ]


@pytest.mark.skipif(sys.platform == "win32", reason="Unix installer")
def test_installer_without_enabled_channels_does_not_install_sdk(
    tmp_path,
    installer_artifacts,
    installer_script,
):
    """Eagerly installing all channel dependencies would fail on an empty index."""
    env, python = _case(
        tmp_path,
        installer_artifacts,
        selected=False,
        sdk_available=False,
    )
    result = _install(installer_script, tmp_path, env)
    assert result.returncode == 0, result.stdout + result.stderr
    _assert_rebuilt(tmp_path, python)
    SUPPORT["run"](
        [
            python,
            "-I",
            "-c",
            "from qwenpaw.plugins.channel_bootstrap import "
            "resolve_default_channel_runtime; import importlib.metadata as m; "
            "runtime=resolve_default_channel_runtime(); "
            "assert not list(m.distributions(path=[runtime.dependency_install_target])); "
            "assert not any(d.metadata['Name'].lower() == 'paho-mqtt' "
            "for d in m.distributions(path=runtime.dependency_paths))",
        ],
        env=env,
        cwd=tmp_path,
    )


@pytest.mark.skipif(sys.platform == "win32", reason="Unix installer")
def test_installer_fails_when_enabled_channel_cannot_be_prepared(
    tmp_path,
    installer_artifacts,
    installer_script,
):
    """Ignoring a failed real preparation command must not report success."""
    env, python = _case(tmp_path, installer_artifacts, sdk_available=False)
    result = _install(installer_script, tmp_path, env)
    _assert_rebuilt(tmp_path, python)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "Enabled channel preparation failed" in result.stderr
    assert "QwenPaw installed successfully" not in result.stdout


@pytest.mark.skipif(sys.platform == "win32", reason="Unix installer")
@pytest.mark.parametrize(
    "capability",
    ["no-prepare-command", "no-plugins-group"],
)
def test_installer_accepts_version_with_older_plugins_cli(
    tmp_path,
    installer_artifacts,
    installer_script,
    capability,
):
    """A successful older CLI help response may lack the new capability."""
    # Model the previous Click API using the actual candidate CLI with only
    # the new command removed. All other wheel bytes remain the same.
    with zipfile.ZipFile(installer_artifacts["candidate"]) as wheel:
        files = {
            name: wheel.read(name)
            for name in wheel.namelist()
            if not name.endswith(".dist-info/RECORD")
        }
    module = "qwenpaw/cli/plugin_commands.py"
    source = files[module].decode()
    command = next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == "prepare_upgrade"
    )
    lines = source.splitlines(keepends=True)
    del lines[
        min(node.lineno for node in command.decorator_list)
        - 1 : command.end_lineno
    ]
    files[module] = "".join(lines).encode()
    if capability == "no-plugins-group":
        main = "qwenpaw/cli/main.py"
        tree = ast.parse(files[main])
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                pairs = [
                    (key, value)
                    for key, value in zip(node.keys, node.values)
                    if not (
                        isinstance(key, ast.Constant)
                        and key.value in {"plugin", "plugins"}
                    )
                ]
                node.keys = [key for key, _ in pairs]
                node.values = [value for _, value in pairs]
        files[main] = (ast.unparse(tree) + "\n").encode()
    info = next(name for name in files if name.endswith(".dist-info/METADATA"))
    version = next(
        line.removeprefix("Version: ")
        for line in files[info].decode().splitlines()
        if line.startswith("Version: ")
    )
    wheel = SUPPORT["_write_wheel"](
        tmp_path / "older-api",
        "qwenpaw",
        version,
        files,
    )
    env, python = _case(
        tmp_path,
        {**installer_artifacts, "candidate": wheel},
        selected=False,
    )
    result = _install(installer_script, tmp_path, env, "--version", version)
    assert result.returncode == 0, result.stdout + result.stderr
    _assert_rebuilt(tmp_path, python)
