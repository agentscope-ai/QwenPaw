# -*- coding: utf-8 -*-
"""Both dependency declarations participate in real plugin transactions."""

# pylint: disable=protected-access
import json
from importlib.metadata import version

import pytest

from qwenpaw.plugins import SDKError, SDKRestartRequiredError
from qwenpaw.plugins import dependency_gate
from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.plugins.testing import PluginTestHost

from .sdk_author_fixture import make_plugin
from .sdk_dependency_fixture import dependency_python

pytestmark = pytest.mark.p1


def package(tmp_path, dependencies=(), requirements=None, *, sdk=True):
    """An executable plugin with no imports that could hide a missed gate."""
    root = make_plugin(
        tmp_path,
        "class Plugin:\n    def register(self, ctx): pass\n"
        "plugin = Plugin()\n",
        [],
    )
    path = root / "plugin.json"
    manifest = json.loads(path.read_text())
    manifest["dependencies"] = list(dependencies)
    if not sdk:
        manifest.pop("sdk")
    path.write_text(json.dumps(manifest))
    if requirements is not None:
        (root / "requirements.txt").write_text(requirements)
    return root


@pytest.fixture(name="installer")
def fake_installer(monkeypatch):
    """Observe the real install boundary; never change the test environment."""
    installed = {}
    calls = []
    original = dependency_gate._dist_version

    def distribution(name):
        return installed[name] if name in installed else original(name)

    def install(_loader, requirements, _plugin_id, **_kwargs):
        text = requirements.read_text()
        calls.append(text)
        for req in dependency_gate.parse_requirement_lines(requirements):
            if req.name.startswith("b01-probe-"):
                installed[req.name] = "1.0"

    monkeypatch.setattr(dependency_gate, "_dist_version", distribution)
    monkeypatch.setattr(PluginLoader, "_install_requirements", install)
    return calls


@pytest.mark.parametrize(
    ("dependencies", "requirements", "expected", "sdk"),
    [
        (["b01-probe-manifest==1.0"], None, {"b01-probe-manifest"}, True),
        ([], "b01-probe-file==1.0\n", {"b01-probe-file"}, False),
        (
            ["b01-probe-manifest==1.0"],
            "b01-probe-file==1.0\n",
            {"b01-probe-manifest", "b01-probe-file"},
            True,
        ),
    ],
)
async def test_install_includes_every_declared_dependency(
    tmp_path,
    installer,
    dependencies,
    requirements,
    expected,
    sdk,
):
    source = package(tmp_path, dependencies, requirements, sdk=sdk)
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    async with PluginTestHost(tmp_path / "host") as host:
        assert (await host.install(source)).ok
    assert len(installer) == 1
    for name in expected:
        assert name in installer[0]
    assert {p.name: p.read_bytes() for p in source.iterdir()} == before


async def test_satisfied_and_marker_excluded_manifest_does_not_install(
    tmp_path,
    installer,
):
    source = package(
        tmp_path,
        [
            f"packaging=={version('packaging')}",
            "b01-probe-never; python_version<'2'",
        ],
    )
    async with PluginTestHost(tmp_path / "host") as host:
        assert (await host.install(source)).ok
    assert installer == []


@pytest.mark.parametrize("dependency", ["httpx==0.0.1", "Pillow==0.0.1"])
@pytest.mark.parametrize("origin", ["manifest", "requirements"])
async def test_manifest_cannot_replace_host_or_sdk_distribution(
    tmp_path,
    installer,
    dependency,
    origin,
):
    source = package(
        tmp_path,
        [dependency] if origin == "manifest" else [],
        dependency if origin == "requirements" else None,
    )
    async with PluginTestHost(tmp_path / "host") as host:
        with pytest.raises(SDKRestartRequiredError):
            await host.install(source)
        corrected = tmp_path / "corrected"
        corrected.mkdir()
        assert (await host.install(package(corrected), replace=True)).ok
    assert installer == []


@pytest.mark.parametrize(
    "declaration",
    [
        "--extra-index-url https://invalid.invalid",
        "pkg[extra]",
        "pkg @ https://invalid.invalid/pkg.whl",
        "pkg\nother",
    ],
)
async def test_manifest_unsupported_syntax_is_not_silently_ignored(
    tmp_path,
    installer,
    declaration,
):
    source = package(tmp_path, [declaration])
    async with PluginTestHost(tmp_path / "host") as host:
        with pytest.raises(SDKError):
            await host.install(source)
    assert installer == []


async def test_both_constraints_apply_when_same_package_is_declared_twice(
    tmp_path,
    installer,
):
    source = package(
        tmp_path,
        ["packaging==0.0.1"],
        f"packaging=={version('packaging')}\n",
    )
    async with PluginTestHost(tmp_path / "host") as host:
        with pytest.raises(SDKRestartRequiredError):
            await host.install(source)
    assert installer == []


async def test_boot_checks_manifest_without_installing_or_mutating_source(
    tmp_path,
    installer,
):
    source = package(tmp_path, ["b01-probe-missing==1.0"])
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    source.chmod(0o555)
    try:
        async with PluginTestHost(tmp_path / "host") as host:
            with pytest.raises(SDKError, match="b01-probe-missing"):
                await host.load(source)
        assert installer == []
        assert {p.name: p.read_bytes() for p in source.iterdir()} == before
    finally:
        source.chmod(0o755)


async def test_upgrade_rejection_keeps_old_tool_callable(tmp_path, installer):
    from .test_sdk_install_transaction import package as tool_package
    from .test_sdk_install_transaction import text_result

    one = tool_package(tmp_path, "1.0.0")
    two = tool_package(tmp_path, "2.0.0")
    path = two / "plugin.json"
    manifest = json.loads(path.read_text())
    manifest["dependencies"] = ["Pillow==0.0.1"]
    path.write_text(json.dumps(manifest))
    async with PluginTestHost(tmp_path / "host") as host:
        assert (await host.install(one)).ok
        with pytest.raises(SDKRestartRequiredError):
            await host.install(two, replace=True)
        assert await text_result(host) == "1.0.0::1"
        assert (await host.reload("extension-contract")).ok
        assert await text_result(host) == "1.0.0::2"
    assert installer == []


async def test_repair_installs_manifest_dependency_after_boot_failure(
    tmp_path,
    installer,
):
    source = package(tmp_path, ["b01-probe-repair==1.0"])
    async with PluginTestHost(tmp_path / "host") as host:
        with pytest.raises(SDKError, match="b01-probe-repair"):
            await host.load(source)
        assert installer == []
        repaired = await host._loader.repair_dependencies("extension-contract")
        assert repaired.status == "active"
        assert len(installer) == 1 and "b01-probe-repair" in installer[0]


def test_manifest_dependency_installs_offline_wheel_in_isolated_python(
    tmp_path,
):
    """Real resolver/install/import, without touching the host environment."""
    import os
    from pathlib import Path
    import shutil
    import subprocess
    import zipfile

    import qwenpaw

    wheels = tmp_path / "wheels"
    wheels.mkdir()
    info = "b01_probe_real-1.0.dist-info"
    files = {
        "b01_probe_real/__init__.py": "ANSWER = 'installed from manifest'\n",
        f"{info}/METADATA": (
            "Metadata-Version: 2.1\nName: b01-probe-real\nVersion: 1.0\n"
        ),
        f"{info}/WHEEL": (
            "Wheel-Version: 1.0\nGenerator: b01-test\n"
            "Root-Is-Purelib: true\nTag: py3-none-any\n"
        ),
    }
    files[f"{info}/RECORD"] = "".join(f"{key},,\n" for key in files)
    wheel = wheels / "b01_probe_real-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, body in files.items():
            archive.writestr(name, body)
    source = package(tmp_path, ["b01-probe-real==1.0"])
    path = source / "plugin.json"
    manifest = json.loads(path.read_text())
    manifest["sdk"]["capabilities"] = ["tools"]
    path.write_text(json.dumps(manifest))
    (source / "main.py").write_text(
        """
from b01_probe_real import ANSWER
from qwenpaw.plugins.tools import ToolResult, ToolSpec
class Plugin:
    def register(self, ctx):
        async def answer(call, args):
            return ToolResult.text(ANSWER)
        ctx.register_tool(ToolSpec(
            "dependency_answer", "Probe", {"type": "object"},
            answer, enabled=True,
        ))
plugin = Plugin()
""",
    )
    python, _ = dependency_python(tmp_path / "python")
    # Expose current source without its unrelated editable-install metadata.
    host_source = tmp_path / "host-source"
    host_source.mkdir()
    shutil.copytree(
        Path(qwenpaw.__file__).resolve().parent,
        host_source / "qwenpaw",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    code = r"""
import asyncio, importlib.metadata, json, subprocess, sys
import mcp.types
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from qwenpaw.plugins.testing import PluginTestHost
commands = []
original = subprocess.Popen
def observe(args, *values, **kwargs):
    if 'install' in args:
        commands.append(list(args))
    return original(args, *values, **kwargs)
subprocess.Popen = observe
async def main():
    async with PluginTestHost(Path(sys.argv[3])) as host:
        assert (await host.install(Path(sys.argv[2]))).ok
        result = await host.call_tool('dependency_answer', {})
        assert result.content[0].text == 'installed from manifest'
    assert importlib.metadata.version('b01-probe-real') == '1.0'
    assert any('--dry-run' in args for args in commands), commands
    assert any('--dry-run' not in args for args in commands), commands
    assert all('--constraint' in args for args in commands), commands
    assert all(not Path(a[a.index('-r') + 1]).exists() for a in commands)
    print(json.dumps({
        'commands': commands, 'answer': 'installed from manifest'
    }))
asyncio.run(main())
"""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("QWENPAW_", "PYTHON"))
        and not any(
            part in key.upper()
            for part in ("TOKEN", "SECRET", "PASSWORD", "API_KEY")
        )
    }
    env.update(
        QWENPAW_WORKING_DIR=str(tmp_path / "bootstrap"),
        QWENPAW_SECRET_DIR=str(tmp_path / "secrets"),
        PIP_NO_INDEX="1",
        UV_NO_INDEX="1",
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
            str(host_source),
            str(source),
            str(tmp_path / "host"),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1])["answer"] == (
        "installed from manifest"
    )


@pytest.mark.parametrize("declaration", ["pkg[extra]", "pkg\nother", 123])
def test_author_checker_rejects_invalid_manifest_dependencies(
    tmp_path,
    declaration,
):
    from qwenpaw.plugins.compliance import check_plugin

    report = check_plugin(package(tmp_path, [declaration]))
    assert not report.ok
    assert any(
        item.file == "plugin.json" and "dependenc" in item.message
        for item in report.findings
    )


@pytest.mark.timeout(45)
async def test_cancelled_installer_keeps_normalized_input_until_thread_stops(
    tmp_path,
    monkeypatch,
):
    import asyncio
    import threading

    source = package(tmp_path, ["b01-probe-delayed==1.0"])
    started, release = asyncio.Event(), threading.Event()
    loop = asyncio.get_running_loop()
    inputs = []

    def install(_loader, requirements, _plugin_id, **_kwargs):
        inputs.append(requirements)
        assert "b01-probe-delayed" in requirements.read_text()
        loop.call_soon_threadsafe(started.set)
        assert release.wait(30), "Test did not release installer"
        assert requirements.is_file(), "Input deleted during installation"

    monkeypatch.setattr(PluginLoader, "_install_requirements", install)
    async with PluginTestHost(tmp_path / "host") as host:
        task = asyncio.create_task(
            host._loader._ensure_dependencies_installed(
                source,
                "extension-contract",
                allow_install=True,
            ),
        )
        startup = asyncio.create_task(started.wait())
        try:
            done, _ = await asyncio.wait(
                {startup, task},
                timeout=30,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if task in done:
                await task  # Surface dependency-audit errors immediately.
                pytest.fail("Installer completed before the release signal")
            assert startup in done, "Installer did not start within 30 seconds"
            assert inputs[0].parent != source
            for _ in range(2):
                task.cancel()
                await asyncio.sleep(0)
                assert not task.done()
                assert inputs[0].is_file()
        finally:
            release.set()
            startup.cancel()
            await asyncio.gather(startup, task, return_exceptions=True)
        assert task.cancelled()
        assert not inputs[0].exists()
        assert not (source / "requirements.txt").exists()
