# -*- coding: utf-8 -*-
"""SDK and legacy plugins share the real framework dependency installer."""

# pylint: disable=protected-access
from contextlib import contextmanager
import json
import os
import subprocess
import zipfile

import pytest

from qwenpaw.plugins import SDKRestartRequiredError, dependency_gate
from qwenpaw.plugins.loader import PluginLoader

from .sdk_dependency_fixture import dependency_python
from .test_manifest_dependencies import package

pytestmark = pytest.mark.p1


@pytest.mark.parametrize("sdk", [False, True])
@pytest.mark.parametrize("mode", ["pip", "uv", "desktop"])
def test_install_with_duplicate_unrelated_packages(tmp_path, sdk, mode):
    """Install/import a local wheel despite old shared-site host metadata."""
    python, _ = dependency_python(
        tmp_path / "python",
        installer="uv" if mode == "uv" else "pip",
    )
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    info = "unified_probe-1.0.dist-info"
    files = {
        "unified_probe/__init__.py": "VALUE = 'installed'\n",
        f"{info}/METADATA": (
            "Metadata-Version: 2.1\nName: unified-probe\nVersion: 1.0\n"
        ),
        f"{info}/WHEEL": (
            "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
        ),
    }
    files[f"{info}/RECORD"] = "".join(f"{key},,\n" for key in files)
    with zipfile.ZipFile(
        wheels / "unified_probe-1.0-py3-none-any.whl",
        "w",
    ) as archive:
        for key, value in files.items():
            archive.writestr(key, value)
    source = package(tmp_path, ["unified-probe==1.0"], sdk=sdk)
    entry = source / "main.py"
    entry.write_text(
        "from unified_probe import VALUE\nassert VALUE == 'installed'\n"
        + entry.read_text(),
    )
    code = r"""
import asyncio, importlib.metadata, json, subprocess, sys
from pathlib import Path
import mcp.types
from qwenpaw.plugins import dependency_gate, loader
from qwenpaw.plugins.testing import PluginTestHost

root, source = map(Path, sys.argv[1:3])
mode = sys.argv[3]
target = root / 'site'
target.mkdir(parents=True)
for name in ('uvicorn', 'certifi'):
    info = target / f'{name}-0.0.1.dist-info'
    info.mkdir()
    (info / 'METADATA').write_text(
        f'Metadata-Version: 2.1\nName: {name}\nVersion: 0.0.1\n'
    )
# Use metadata in a second site, as after a desktop upgrade. Keep actual
# host modules available; this test never replaces their files.
sys.path.append(str(target))
for name in ('uvicorn', 'certifi'):
    versions = {d.version for d in importlib.metadata.distributions()
                if d.metadata['Name'].lower() == name}
    assert len(versions) >= 2, (name, versions)
before = {p: p.read_bytes() for p in target.rglob('*') if p.is_file()}
if mode == 'desktop':
    loader._is_frozen = lambda: True
    dependency_gate._is_frozen = lambda: True
    loader._desktop_python = lambda: sys.executable
    loader._plugin_site_dir = lambda: target

commands = []
spawn = subprocess.Popen
def observe(args, *values, **kwargs):
    if 'install' in args:
        commands.append(list(args))
        assert '--dry-run' not in args, args
        assert '--constraint' not in args, args
    return spawn(args, *values, **kwargs)
subprocess.Popen = observe

async def main():
    async with PluginTestHost(root / 'host') as host:
        assert (await host.install(source)).ok
        import unified_probe
        assert unified_probe.VALUE == 'installed'
        assert importlib.metadata.version('unified-probe') == '1.0'
        if mode == 'desktop':
            assert Path(unified_probe.__file__).is_relative_to(target)
            command = commands[-1]
            assert command[command.index('--target') + 1] == str(target)
        else:
            assert '--target' not in commands[-1]
        assert len(commands) == (2 if mode == 'uv' else 1), commands
        if mode == 'uv':
            command = commands[-1]
            assert command[command.index('--python') + 1] == sys.executable
        else:
            assert commands[-1][0] == sys.executable
        # A second dependency check with installed packages must stay offline.
        decision = await host._loader._ensure_dependencies_installed(
            source, 'extension-contract', allow_install=False,
        )
        assert decision.already_satisfied
        assert len(commands) == (2 if mode == 'uv' else 1)
        assert all(p.read_bytes() == data for p, data in before.items())
    print(json.dumps({'commands': commands, 'imported': True}))
asyncio.run(main())
"""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("QWENPAW_", "COPAW_", "PYTHON"))
        and not any(
            part in key.upper()
            for part in ("TOKEN", "SECRET", "PASSWORD", "API_KEY")
        )
    }
    env.update(
        QWENPAW_WORKING_DIR=str(tmp_path / "bootstrap"),
        QWENPAW_SECRET_DIR=str(tmp_path / "secrets"),
        PIP_NO_INDEX="1",
        UV_OFFLINE="1",
        PIP_FIND_LINKS=str(wheels),
        UV_FIND_LINKS=str(wheels),
        PIP_CACHE_DIR=str(tmp_path / "pip-cache"),
        UV_CACHE_DIR=str(tmp_path / "uv-cache"),
    )
    result = subprocess.run(
        [
            str(python),
            "-I",
            "-c",
            code,
            str(tmp_path / "run"),
            str(source),
            mode,
        ],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1])["imported"]


@pytest.mark.parametrize("sdk", [False, True])
def test_common_gate_rechecks_host_conflicts_inside_install_lock(
    tmp_path,
    monkeypatch,
    sdk,
):
    from qwenpaw.plugins import loader as module

    source = package(tmp_path, requirements="uvicorn==0.0.1\n", sdk=sdk)
    loader = PluginLoader([tmp_path])
    monkeypatch.setattr(
        module,
        "_plugin_runtime_dir",
        lambda: tmp_path / "runtime",
    )
    monkeypatch.setattr(dependency_gate, "_is_frozen", lambda: True)

    def prohibit_install(*_args, **_kwargs):
        pytest.fail("A protected host conflict reached the installer")

    monkeypatch.setattr(loader, "_install_requirements", prohibit_install)
    with pytest.raises(SDKRestartRequiredError, match="uvicorn"):
        loader._install_requirements_locked(
            source / "requirements.txt",
            "extension-contract",
        )


@pytest.mark.parametrize("sdk", [False, True])
def test_install_lock_failure_never_runs_unlocked(tmp_path, monkeypatch, sdk):
    from qwenpaw.plugins import install_lock

    source = package(tmp_path, requirements="unified-probe==1.0\n", sdk=sdk)
    loader = PluginLoader([tmp_path])

    @contextmanager
    def unavailable(*_args, **_kwargs):
        yield False

    def prohibit_install(*_args, **_kwargs):
        pytest.fail("Installer ran without the framework lock")

    monkeypatch.setattr(install_lock, "plugin_install_lock", unavailable)
    monkeypatch.setattr(loader, "_install_requirements", prohibit_install)
    with pytest.raises(RuntimeError, match="busy"):
        loader._install_requirements_locked(
            source / "requirements.txt",
            "extension-contract",
        )


@pytest.mark.parametrize("sdk", [False, True])
@pytest.mark.parametrize("frozen", [False, True])
def test_framework_preserves_large_dependency_timeout(
    tmp_path,
    monkeypatch,
    sdk,
    frozen,
):
    from qwenpaw.plugins import loader as module

    source = package(tmp_path, requirements="openai-whisper\ntorch\n", sdk=sdk)
    path = source / "plugin.json"
    manifest = json.loads(path.read_text())
    manifest["meta"] = {"dependency_install_timeout": 1800}
    path.write_text(json.dumps(manifest))
    loader = PluginLoader([tmp_path])
    monkeypatch.setattr(module, "_is_frozen", lambda: frozen)
    monkeypatch.setattr(module, "_desktop_python", lambda: "bundled-python")

    def run(args, *, timeout, plugin_id):
        assert timeout == 1800
        assert plugin_id == "extension-contract"
        raise subprocess.TimeoutExpired(args, timeout)

    monkeypatch.setattr(loader, "_run_subprocess_with_streaming_log", run)
    with pytest.raises(RuntimeError, match="1800 s limit"):
        loader._install_requirements(
            source / "requirements.txt",
            "extension-contract",
        )
