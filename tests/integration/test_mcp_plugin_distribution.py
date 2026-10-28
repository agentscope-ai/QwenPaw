# -*- coding: utf-8 -*-
"""Optional resource mapping must match the maintained wheel input exactly."""

import ast
from pathlib import Path, PurePosixPath, PureWindowsPath
import tomllib

import pytest

ROOT = Path(__file__).resolve().parents[2]


def resource_key(path):
    """Return a logical frozen/archive resource key."""
    return path.as_posix()


def cloned_interpreter(original_python, clone):
    """Locate the supplied venv interpreter inside its private clone."""
    return clone / original_python.relative_to(original_python.parent.parent)


def frozen_resources():
    """Evaluate data declarations without importing PyInstaller or building."""
    source = (ROOT / "scripts/pack-tauri/qwenpaw.spec").read_text()
    tree = ast.parse(source.split("# Include ReMe package data")[0])
    tree.body = [
        node
        for node in tree.body
        if not (
            isinstance(node, ast.ImportFrom)
            and node.module == "PyInstaller.utils.hooks"
        )
    ]
    namespace = {"SPECPATH": str(ROOT / "scripts/pack-tauri")}
    exec(compile(tree, "qwenpaw.spec data declarations", "exec"), namespace)
    result = {}
    for source_path, destination in namespace["datas"]:
        source_path = Path(source_path)
        if source_path.is_dir():
            for path in source_path.rglob("*"):
                if path.is_file():
                    result[
                        resource_key(
                            Path(destination) / path.relative_to(source_path),
                        )
                    ] = path
        else:
            result[
                resource_key(Path(destination) / source_path.name)
            ] = source_path
    return result


def test_frozen_optional_mcp_matches_wheel_allowlist():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    package = "qwenpaw.plugins.bundled.optional.mcp"
    source = ROOT / config["tool"]["setuptools"]["package-dir"][package]
    patterns = config["tool"]["setuptools"]["package-data"][package]
    expected = {
        resource_key(
            Path(*package.split(".")) / path.relative_to(source),
        ): path
        for pattern in patterns
        for path in source.glob(pattern)
        if path.is_file()
    }
    assert len(expected) == 13
    actual = {
        key: value
        for key, value in frozen_resources().items()
        if key.startswith("qwenpaw/plugins/bundled/optional/mcp/")
    }
    assert (
        actual == expected
    ), "Frozen offline MCP resource differs from wheel allowlist"
    assert all("node_modules" not in path for path in actual)
    assert (
        "qwenpaw/plugins/bundled/optional/mcp/frontend/dist/index.js" in actual
    )


def test_artifact_guard_rejects_actual_installed_wheel_with_wrong_bytes(
    tmp_path,
    monkeypatch,
    pytestconfig,
):
    """Mutate a private venv, preserving the positive release environment."""
    import json
    import os
    import runpy
    import shutil
    import subprocess
    import sys

    manifest = pytestconfig.getoption("--mcp-plugin-artifacts")
    if not manifest:
        pytest.skip("Pass --mcp-plugin-artifacts for built-wheel acceptance")
    artifacts = json.loads(Path(manifest).read_text())
    original_python = Path(artifacts["python"])
    clone = tmp_path / "external-venv"
    shutil.copytree(original_python.parent.parent, clone, symlinks=True)
    interpreter = cloned_interpreter(original_python, clone)
    result = subprocess.run(
        [str(interpreter), "-c", "import qwenpaw; print(qwenpaw.__file__)"],
        env={
            key: value
            for key, value in os.environ.items()
            if key != "PYTHONPATH"
        },
        capture_output=True,
        text=True,
        check=True,
    )
    package_file = Path(result.stdout.strip())
    assert package_file.is_relative_to(clone)
    package_file.write_text(
        package_file.read_text() + "\n# Controlled wrong wheel bytes\n",
    )
    actual_run = subprocess.run
    calls = []

    def observe(command, **kwargs):
        if calls:
            raise RuntimeError(
                "Guard accepted actual installed wrong wheel bytes",
            )
        calls.append(command)
        return actual_run(command, check=kwargs.pop("check", False), **kwargs)

    monkeypatch.setattr(subprocess, "run", observe)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_plugin_sdk_artifacts.py",
            "--wheel",
            artifacts["wheel"],
            "--sdist",
            artifacts["sdist"],
            "--python",
            str(interpreter),
            "--source-root",
            str(ROOT),
            "--output",
            str(tmp_path / "author-output"),
        ],
    )
    with pytest.raises(AssertionError, match="installed-import failed"):
        runpy.run_path(
            str(ROOT / "scripts/check_plugin_sdk_artifacts.py"),
            run_name="__main__",
        )
    assert len(calls) == 1
    assert (
        "wheel"
        in (tmp_path / "author-output/installed-import.log")
        .read_text()
        .lower()
    )


def test_wheel_and_frozen_resource_layout_cold_start(tmp_path, pytestconfig):
    """Execute wheel code and frozen resource layout, not a native binary."""
    import json
    import os
    import subprocess
    import zipfile

    manifest = pytestconfig.getoption("--mcp-plugin-artifacts")
    if not manifest:
        pytest.skip("Pass --mcp-plugin-artifacts for built-wheel acceptance")
    artifacts = json.loads(Path(manifest).read_text())
    frozen = tmp_path / "frozen-resource-layout"
    with zipfile.ZipFile(artifacts["wheel"]) as wheel:
        wheel.extractall(frozen)
        names = wheel.namelist()
    assert any(
        "bundled/optional/mcp/frontend/dist/index.js" in name for name in names
    )
    assert not any(
        "node_modules" in name or "__pycache__" in name for name in names
    )
    # Recreate optional resources from the actual frozen mapping.
    # This layout uses spec-selected bytes instead of wheel fallbacks.
    import shutil

    optional = frozen / "qwenpaw/plugins/bundled/optional/mcp"
    shutil.rmtree(optional)
    for name, source in frozen_resources().items():
        if name.startswith("qwenpaw/plugins/bundled/optional/mcp/"):
            destination = frozen / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
    probe = ROOT / "tests/fixtures/mcp/optional_runtime_probe.py"
    for layout in ("wheel", "frozen-resource-layout"):
        for mode in ("unused-v2", "legacy"):
            root = tmp_path / layout / mode
            env = {
                key: value
                for key, value in os.environ.items()
                if key not in {"PYTHONPATH", "HOME"}
            }
            env.update(
                {
                    "QWENPAW_WORKING_DIR": str(root),
                    "QWENPAW_SECRET_DIR": str(root / "secrets"),
                    "XDG_CONFIG_HOME": str(root / "xdg"),
                    "XDG_CACHE_HOME": str(root / "cache"),
                    "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
                    "PYTHONNOUSERSITE": "1",
                },
            )
            if layout != "wheel":
                env["PYTHONPATH"] = str(frozen)
            result = subprocess.run(
                [artifacts["python"], "-B", str(probe), mode, str(root)],
                env=env,
                cwd=tmp_path,
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            root.mkdir(parents=True, exist_ok=True)
            (root / "cold-start.stdout.log").write_text(result.stdout)
            (root / "cold-start.stderr.log").write_text(result.stderr)
            assert result.returncode == 0, result.stdout + result.stderr
            observations = json.loads((root / "observations.json").read_text())
            imported = Path(observations["qwenpaw_file"])
            resource = Path(observations["optional_resource"])
            assert imported.is_relative_to(
                frozen
                if layout != "wheel"
                else Path(artifacts["python"]).parent.parent,
            )
            assert resource.is_relative_to(imported.parent)
            assert (resource / "frontend/dist/index.js").is_file()
            if mode == "unused-v2":
                assert not (root / "plugins/qwenpaw-mcp").exists()
                assert observations["manager_constructions"] == 0
            else:
                assert (root / "plugins/qwenpaw-mcp/plugin.json").is_file()
                assert observations["real_rpc"]


@pytest.mark.parametrize("path_type", [PurePosixPath, PureWindowsPath])
def test_logical_resource_keys_are_posix_for_each_path_layout(path_type):
    path = path_type(
        "qwenpaw",
        "plugins",
        "bundled",
        "optional",
        "mcp",
        "plugin.json",
    )
    key = resource_key(path)
    assert key == "qwenpaw/plugins/bundled/optional/mcp/plugin.json"
    assert key.startswith("qwenpaw/plugins/bundled/optional/mcp/")


@pytest.mark.parametrize(
    "original, clone, expected",
    [
        (
            PurePosixPath("/original/venv/bin/python"),
            PurePosixPath("/private/clone"),
            PurePosixPath("/private/clone/bin/python"),
        ),
        (
            PureWindowsPath("C:/original/venv/Scripts/python.exe"),
            PureWindowsPath("D:/private/clone"),
            PureWindowsPath("D:/private/clone/Scripts/python.exe"),
        ),
    ],
)
def test_clone_preserves_supplied_venv_interpreter_layout(
    original,
    clone,
    expected,
):
    assert cloned_interpreter(original, clone) == expected
