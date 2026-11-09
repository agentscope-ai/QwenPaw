# -*- coding: utf-8 -*-
"""Both dependency declarations participate in real plugin transactions."""

# pylint: disable=protected-access
import json
import logging
from importlib.metadata import version
from pathlib import Path

import pytest

from qwenpaw.plugins import SDKError
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
        (root / "requirements.txt").write_text(requirements, encoding="utf-8")
    return root


@pytest.fixture(name="installer")
def observe_installer(monkeypatch):
    """Fail if a check-only or rejected transaction reaches preparation."""
    calls = []

    async def install(_loader, requirements, _plugin_id, **_kwargs):
        calls.append(requirements.read_text())
        raise AssertionError(
            "Read-only dependency check attempted installation",
        )

    monkeypatch.setattr(PluginLoader, "_prepare_python_dependencies", install)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation",
    ["read", "install", "immutable", "immutable-known", "immutable-read"],
)
async def test_unknown_version_respects_operation_and_environment(
    tmp_path,
    monkeypatch,
    operation,
    caplog,
):
    import importlib
    import sys
    from importlib.metadata import PackageNotFoundError

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    source = package(
        tmp_path,
        requirements="unknown-dependency>=1\n",
        sdk=False,
    )
    module = bundle / "unknown_dependency.py"
    module.write_text("VALUE = 1\n")
    monkeypatch.syspath_prepend(str(bundle))
    importlib.invalidate_caches()
    installed = False
    calls = []
    probes = []

    def version_of(name):
        if installed:
            return "1.0"
        raise PackageNotFoundError(name)

    async def install(_self, _requirements, _plugin_id, **_kwargs):
        nonlocal installed
        calls.append(_requirements.read_text())
        installed = True

    async def probe(plugin_id, *_args):
        probes.append(plugin_id)

    monkeypatch.setattr("qwenpaw.plugins.loader._probe_incoming", probe)

    monkeypatch.setattr(dependency_gate, "_dist_version", version_of)
    monkeypatch.setattr(dependency_gate, "_dist_requires", lambda name: ())
    monkeypatch.setattr(PluginLoader, "_prepare_python_dependencies", install)
    monkeypatch.setattr(
        sys,
        "frozen",
        operation.startswith("immutable"),
        raising=False,
    )
    loader = PluginLoader([])
    from qwenpaw.plugins.dependency_context import DependencyEnvironmentContext

    context = DependencyEnvironmentContext(
        sys.executable,
        source,
        (bundle,),
        None,
        (bundle,),
    )
    monkeypatch.setattr(loader, "_dependency_environment", lambda: context)
    if operation == "immutable-known":
        info = bundle / "unknown_dependency-1.0.dist-info"
        info.mkdir()
        (info / "METADATA").write_text(
            "Name: unknown-dependency\nVersion: 1.0\n",
        )
    from qwenpaw.plugins.architecture import PluginManifest

    description = loader._python_backend.describe(
        source,
        PluginManifest.model_validate_json(
            (source / "plugin.json").read_text(),
        ),
    )
    preparation = loader._python_backend.prepare(
        description,
        allow_install=operation not in {"read", "immutable-read"},
        probe=True,
    )
    if operation == "immutable":
        with pytest.raises(dependency_gate.SharedDependencyError) as error:
            await preparation
        assert error.value.reason_code == "DEPENDENCY_ENVIRONMENT_PROTECTED"
        assert not error.value.decision.require_restart
        assert not calls and not probes
        return

    await preparation
    assert probes == [description.manifest.id]
    if operation == "install":
        assert len(calls) == 1
    else:
        assert not calls
    if operation in {"read", "immutable-read"}:
        assert "installed version unknown; attempting load" in caplog.text


def write_wheel(
    wheels,
    name,
    body="ANSWER = 'installed from manifest'\n",
    *,
    info=None,
    metadata_headers="",
    wheel_headers="",
    payload=None,
    executable=(),
):
    import base64
    import hashlib
    import zipfile

    module = name.replace("-", "_")
    info = info or f"{module}-1.0.dist-info"
    files = {
        f"{module}/__init__.py": body,
        f"{info}/METADATA": (
            f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n"
            + metadata_headers
        ),
        f"{info}/WHEEL": (
            "Wheel-Version: 1.0\nGenerator: b01-test\n"
            "Root-Is-Purelib: true\nTag: py3-none-any\n" + wheel_headers
        ),
    }
    files.update(payload or {})
    records = []
    for key, value in files.items():
        data = value.encode() if isinstance(value, str) else value
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest())
        records.append(
            f"{key},sha256={digest.decode().rstrip('=')},{len(data)}\n",
        )
    files[f"{info}/RECORD"] = "".join(records) + f"{info}/RECORD,,\n"
    wheel = wheels / f"{module}-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, body in files.items():
            entry = zipfile.ZipInfo(name)
            entry.external_attr = (
                0o100755 if name in executable else 0o100644
            ) << 16
            archive.writestr(entry, body)
    return wheel


def test_wheel_preserves_package_executable_modes(tmp_path):
    import hashlib
    import os
    import sys

    from packaging.markers import default_environment
    from qwenpaw.plugins.execution.dependencies import DependencySnapshot
    from qwenpaw.plugins.wheel_additions import (
        WheelAddition,
        validate_additions,
    )

    binary = "b01_probe/binaries/probe"
    wheel = write_wheel(
        tmp_path,
        "b01-probe",
        payload={binary: b"probe"},
        executable=(binary,),
    )
    target = tmp_path / "site"
    target.mkdir()
    snapshot = DependencySnapshot(
        sys.executable,
        sys.prefix,
        (str(target),),
        default_environment(),
        ("py3-none-any",),
        {},
    )
    files, _ = validate_additions(
        (
            WheelAddition(
                wheel,
                hashlib.sha256(wheel.read_bytes()).hexdigest(),
            ),
        ),
        snapshot,
        target,
    )
    assert files.executable_paths == {binary}
    dependency_gate._write_additions(target, files)
    assert (target / binary).read_bytes() == b"probe"
    if os.name != "nt":
        assert (target / binary).stat().st_mode & 0o111 == 0o111
        assert not (target / "b01_probe/__init__.py").stat().st_mode & 0o111


@pytest.mark.parametrize("over_budget", [False, True])
def test_wheel_unpacked_size_budget(tmp_path, monkeypatch, over_budget):
    import hashlib
    import zipfile
    from qwenpaw.plugins import wheel_additions
    from qwenpaw.plugins.execution.errors import ProtocolValidationError

    wheel = write_wheel(tmp_path, "b01-probe")
    with zipfile.ZipFile(wheel) as archive:
        expanded = sum(info.file_size for info in archive.infolist())
    monkeypatch.setattr(
        wheel_additions,
        "_MAX_WHEEL_UNPACKED_BYTES",
        expanded - int(over_budget),
    )
    addition = wheel_additions.WheelAddition(
        wheel,
        hashlib.sha256(wheel.read_bytes()).hexdigest(),
    )
    if over_budget:
        with pytest.raises(
            ProtocolValidationError,
            match="DEPENDENCY_PLAN_UNVERIFIED",
        ):
            wheel_additions._members(addition)
    else:
        assert wheel_additions._members(addition)
    assert not (tmp_path / "site").exists()


@pytest.mark.parametrize(
    ("info", "metadata_headers", "wheel_headers", "accepted"),
    [
        ("b01_probe-1.0", "", "Generator: delocate\n", True),
        ("b01.probe-1.0", "", "", True),
        ("B01_Probe-1.0", "", "", True),
        ("b01_probe-1.0.0", "", "", True),
        ("other-1.0", "", "", False),
        ("b01_probe-2.0", "", "", False),
        ("b01_probe-invalid", "", "", False),
        ("b01_probe", "", "", False),
        ("b01_probe-1.0", "Name: b01-probe\n", "", False),
        ("b01_probe-1.0", "Version: 1.0\n", "", False),
        (
            "b01_probe-1.0",
            "Requires-Python: >=3\nRequires-Python: >=3\n",
            "",
            False,
        ),
        ("b01_probe-1.0", "", "Wheel-Version: 1.0\n", False),
        ("b01_probe-1.0", "", "Root-Is-Purelib: true\n", False),
        ("b01_probe-1.0", "", "Build: 1\nBuild: 1\n", False),
    ],
)
def test_wheel_identity_and_header_validation(
    tmp_path,
    caplog,
    info,
    metadata_headers,
    wheel_headers,
    accepted,
):
    import hashlib
    import sys
    import zipfile

    from packaging.markers import default_environment

    from qwenpaw.plugins.execution.dependencies import DependencySnapshot
    from qwenpaw.plugins.execution.errors import ProtocolValidationError
    from qwenpaw.plugins.wheel_additions import (
        WheelAddition,
        validate_additions,
    )

    info += ".dist-info"
    wheel = write_wheel(
        tmp_path,
        "b01-probe",
        info=info,
        metadata_headers=metadata_headers,
        wheel_headers=wheel_headers,
    )
    additions = (
        WheelAddition(wheel, hashlib.sha256(wheel.read_bytes()).hexdigest()),
    )
    target = tmp_path / "site"
    snapshot = DependencySnapshot(
        sys.executable,
        sys.prefix,
        (str(target),),
        default_environment(),
        ("py3-none-any",),
        {},
    )
    if accepted:
        files, proposed = validate_additions(additions, snapshot, target)
        with zipfile.ZipFile(wheel) as archive:
            assert files == {
                name: archive.read(name) for name in archive.namelist()
            }
        assert proposed.distributions["b01-probe"]["version"] == "1.0"
        assert proposed.distributions["b01-probe"]["metadata_path"] == str(
            target / info,
        )
    else:
        caplog.set_level(logging.INFO)
        with pytest.raises(
            ProtocolValidationError,
            match="^DEPENDENCY_PLAN_UNVERIFIED$",
        ):
            validate_additions(additions, snapshot, target)
        assert wheel.name in caplog.text
        if metadata_headers or wheel_headers:
            assert "metadata headers invalid" in caplog.text
        elif info in {"other-1.0.dist-info", "b01_probe-2.0.dist-info"}:
            assert "distribution identity mismatch" in caplog.text
    assert not target.exists()


@pytest.mark.parametrize(
    "payload",
    [
        {"b01_probe-1.0.data/data/b01_probe/__init__.py": "overwrite\n"},
        {"b01_probe-1.0.data/data/other-1.0.dist-info/METADATA": "extra\n"},
        {
            "b01_probe-1.0.data/data/other-1.0.egg-info/PKG-INFO": (
                "Metadata-Version: 2.1\nName: other\nVersion: 1.0\n"
            ),
        },
    ],
)
def test_wheel_data_cannot_overwrite_files_or_add_metadata(tmp_path, payload):
    import hashlib
    import sys

    from packaging.markers import default_environment

    from qwenpaw.plugins.execution.dependencies import DependencySnapshot
    from qwenpaw.plugins.execution.errors import ProtocolValidationError
    from qwenpaw.plugins.wheel_additions import (
        WheelAddition,
        validate_additions,
    )

    wheel = write_wheel(tmp_path, "b01-probe", payload=payload)
    target = tmp_path / "site"
    target.mkdir()
    (target / "keep.txt").write_bytes(b"unchanged\n")
    before = {path.name: path.read_bytes() for path in target.iterdir()}
    snapshot = DependencySnapshot(
        sys.executable,
        sys.prefix,
        (str(target),),
        default_environment(),
        ("py3-none-any",),
        {},
    )
    with pytest.raises(
        ProtocolValidationError,
        match="^DEPENDENCY_PLAN_UNVERIFIED$",
    ):
        validate_additions(
            (
                WheelAddition(
                    wheel,
                    hashlib.sha256(wheel.read_bytes()).hexdigest(),
                ),
            ),
            snapshot,
            target,
        )
    assert {
        path.name: path.read_bytes() for path in target.iterdir()
    } == before


def install_case(tmp_path, source, expected, *, repair=False, tool=False):
    """Run resolver, publication and admission in one disposable interpreter."""
    import os
    import subprocess
    import shutil

    import qwenpaw
    from tests.channel_support.host import local_certifi_wheel

    wheels = tmp_path / "wheels"
    wheels.mkdir()
    local_certifi_wheel(wheels)
    for name in expected:
        spelling = name.replace("-", "." if repair else "_")
        if tool:
            spelling = spelling.upper()
        write_wheel(
            wheels,
            name,
            info=f"{spelling}-1.0.dist-info",
            wheel_headers="Generator: delocate\n" if repair or tool else "",
            payload=(
                {
                    f"{spelling}-1.0.data/data/share/man/man1/probe.1": (
                        b".TH PROBE 1\nGeneric wheel data payload.\n"
                    ),
                }
                if tool
                else None
            ),
        )
    python, _ = dependency_python(tmp_path / "python")
    host_source = tmp_path / "host-source"
    host_source.mkdir()
    shutil.copytree(
        Path(qwenpaw.__file__).resolve().parent,
        host_source / "qwenpaw",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    code = r"""
import asyncio, importlib, importlib.metadata, json, subprocess, sys
import mcp.types
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from qwenpaw.plugins import SDKError
from qwenpaw.plugins.testing import PluginTestHost
from qwenpaw.utils.runtime_environment import CERTIFI_REQUIREMENT
source, root = map(Path, sys.argv[2:4])
expected = set(json.loads(sys.argv[4]))
# Unrelated stale metadata must not block a real manifest dependency install.
if sys.argv[6] == 'tool':
    duplicates = root.parent / 'duplicate-metadata'
    for version in ('1.0', '2.0'):
        info = duplicates / f'unrelated_probe-{version}.dist-info'
        info.mkdir(parents=True)
        (info / 'METADATA').write_text(
            f'Metadata-Version: 2.1\nName: unrelated-probe\nVersion: {version}\n'
        )
    sys.path.append(str(duplicates))
    assert {d.version for d in importlib.metadata.distributions()
            if d.metadata['Name'] == 'unrelated-probe'} == {'1.0', '2.0'}
commands, inputs = [], []
spawn = subprocess.Popen

def observe(args, *values, **kwargs):
    if 'install' in args:
        raise AssertionError('Dependency transaction attempted pip install')
    if 'wheel' in args and 'pip' in args:
        assert args[0] == sys.executable
        assert '--constraint' in args
        requirements = Path(args[args.index('-r') + 1])
        commands.append(list(args))
        inputs.append(requirements.read_text(encoding="utf-8-sig"))
    return spawn(args, *values, **kwargs)

subprocess.Popen = observe
before = {p.name:p.read_bytes() for p in source.iterdir()}
async def main():
    async with PluginTestHost(root) as host:
        if sys.argv[6] == 'tool':
            import shutil
            from qwenpaw.plugins.execution.dependencies import observe_dependencies
            from qwenpaw.plugins.dependency_usage import DependencyDeclaration
            candidate = root.parent / 'candidate-source'
            backend = candidate / 'backend'
            backend.mkdir(parents=True)
            (candidate / 'plugin.json').write_text(json.dumps({
                'id': 'candidate-path', 'version': '1.0',
                'entry': {'backend': 'backend/main.py'},
            }))
            (backend / 'main.py').write_text(
                'import sys\nfrom pathlib import Path\n'
                'sys.path.insert(0, str(Path(__file__).parent))\n'
                'class Plugin:\n    def register(self, api): pass\n'
                'plugin = Plugin()\n'
            )
            assert (await host.install(candidate)).ok
            usage = host._loader.registry.dependency_usage
            # Retain an observation left by the previous implementation too.
            snapshot = observe_dependencies({'code_root': root / 'unrelated',
                '_audit_sites': (*sys.path, str(backend))})
            token = usage.declare(DependencyDeclaration('legacy-path', 'old', (), None))
            from dataclasses import replace
            snapshot = replace(snapshot, distributions={})
            usage.observe_host(token, snapshot)
            usage.withdraw(token)
            shutil.rmtree(candidate)
        if sys.argv[5] == 'repair':
            try:
                await host.load(source)
            except SDKError as exc:
                assert next(iter(expected)) in str(exc)
            else:
                raise AssertionError('Boot loaded unsatisfied manifest dependency')
            assert not commands
            result = await host._loader.repair_dependencies('extension-contract')
            assert result.status == 'active'
        else:
            assert (await host.install(source)).ok
        for name in expected:
            assert importlib.metadata.version(name) == '1.0'
            assert importlib.import_module(name.replace('-', '_')).ANSWER == 'installed from manifest'
        if sys.argv[6] == 'tool':
            assert any(u.origin == 'host' and u.snapshot == snapshot
                       for u in usage.snapshot().uses)
            result = await host.call_tool('dependency_answer', {})
            assert result.content[0].text == 'installed from manifest'
            import base64, csv, hashlib, io
            distribution = importlib.metadata.distribution('b01-probe-real')
            target = Path(importlib.import_module('b01_probe_real').__file__).parent.parent
            relative = 'share/man/man1/probe.1'
            data = b'.TH PROBE 1\nGeneric wheel data payload.\n'
            assert distribution.locate_file(relative) == target / relative
            assert (target / relative).read_bytes() == data
            rows = list(csv.reader(io.StringIO(distribution.read_text('RECORD'))))
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('=')
            assert [row for row in rows if row[0] == relative] == [
                [relative, 'sha256=' + digest, str(len(data))]
            ]
            assert all('.data/' not in row[0] for row in rows)
    assert len(commands) == 1, commands
    assert all(name in inputs[0] for name in expected)
    assert all(CERTIFI_REQUIREMENT in text for text in inputs)
    assert all(not Path(a[a.index('-r') + 1]).exists() for a in commands)
    if 'requirements.txt' in before:
        original_requirements = set(filter(None, before['requirements.txt'].decode('utf-8-sig').splitlines()))
        assert original_requirements <= set(inputs[0].lstrip('\ufeff').splitlines())
        assert (source / 'requirements.txt').is_file()
        assert (source / 'requirements.txt').read_bytes() == before['requirements.txt']
    if sys.argv[5] != 'repair':
        assert {p.name:p.read_bytes() for p in source.iterdir()} == before
    print(json.dumps({'commands':commands,'installed':sorted(expected)}))
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
        QWENPAW_DEPENDENCY_STATE_DIR=str(tmp_path / "dependency-state"),
        QWENPAW_WORKING_DIR=str(tmp_path / "bootstrap"),
        QWENPAW_SECRET_DIR=str(tmp_path / "secrets"),
        QWENPAW_BACKUP_DIR=str(tmp_path / "backup"),
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
            json.dumps(sorted(expected)),
            "repair" if repair else "install",
            "tool" if tool else "module",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        set(json.loads(result.stdout.strip().splitlines()[-1])["installed"])
        == expected
    )


@pytest.mark.parametrize(
    ("dependencies", "requirements", "expected", "sdk"),
    [
        ([], "\ufeffb01-probe-file==1.0\n", {"b01-probe-file"}, False),
        (
            ["b01-probe-manifest==1.0"],
            "\ufeffb01-probe-file==1.0\n",
            {"b01-probe-manifest", "b01-probe-file"},
            True,
        ),
    ],
)
def test_install_includes_every_declared_dependency(
    tmp_path,
    dependencies,
    requirements,
    expected,
    sdk,
):
    source = package(tmp_path, dependencies, requirements, sdk=sdk)
    install_case(tmp_path, source, expected)


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


@pytest.mark.parametrize("dependency", ["httpx==0.0.1", "uvicorn==0.0.1"])
@pytest.mark.parametrize("origin", ["manifest", "requirements"])
async def test_existing_plugin_version_mismatch_is_a_load_warning(
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
        await host.load(source)
        record = host._loader.get_loaded_plugin("extension-contract")
        assert record.status == "active"
        assert any("installed" in message for message in record.diagnostics)
    assert installer == []


@pytest.mark.parametrize(
    "declaration",
    [
        "--extra-index-url https://invalid.invalid",
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


@pytest.mark.parametrize("sdk", [False, True])
async def test_both_constraints_apply_when_same_package_is_declared_twice(
    tmp_path,
    installer,
    sdk,
):
    source = package(
        tmp_path,
        ["httpx==0.0.1"],
        f"httpx=={version('httpx')}\n",
        sdk=sdk,
    )
    from qwenpaw.plugins.dependency_gate import (
        combined_requirements,
        DependencyGate,
    )

    with combined_requirements(source) as requirements:
        decision = DependencyGate().evaluate(
            requirements,
            allow_install=True,
            plugin_id="extension-contract",
        )
    assert decision.allow_install
    assert decision.missing == ["httpx==0.0.1"]
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
    manifest["dependencies"] = ["b01-probe-missing==1.0"]
    path.write_text(json.dumps(manifest))
    async with PluginTestHost(tmp_path / "host") as host:
        assert (await host.install(one)).ok
        with pytest.raises(SDKError, match="attempted installation"):
            await host.install(two, replace=True)
        assert await text_result(host) == "1.0.0::1"
        assert (await host.reload("extension-contract")).ok
        assert await text_result(host) == "1.0.0::2"
    assert len(installer) == 1


def test_repair_installs_manifest_dependency_after_boot_failure(tmp_path):
    source = package(tmp_path, ["b01-probe-repair==1.0"])
    install_case(tmp_path, source, {"b01-probe-repair"}, repair=True)


def test_manifest_dependency_installs_offline_wheel_in_isolated_python(
    tmp_path,
):
    """Real resolver/publication/import/tool call inside a disposable Python."""
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
    install_case(tmp_path, source, {"b01-probe-real"}, tool=True)


@pytest.mark.parametrize("declaration", ["pkg\nother", 123])
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


def test_requirement_readers_accept_bom_extras_and_preserve_constraints(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.plugins.execution.runtime import _requirements
    from qwenpaw.channel_protocol.shared import _read_requirements

    path = tmp_path / "requirements.txt"
    path.write_text("\ufeffsample[feature]>=1\nsample<2\n", encoding="utf-8")
    expected = {"sample[feature]>=1", "sample<2"}
    parsed = dependency_gate.parse_requirements_file(path)
    assert not parsed.unsupported
    assert {str(req) for req in parsed.requirements} == expected
    assert (
        set(_requirements(path)) == set(_read_requirements(path)) == expected
    )
    assert dependency_gate.manifest_requirements(
        {"dependencies": ["sample[feature]>=1"]},
    ) == ["sample[feature]>=1"]
    info = tmp_path / "sample-1.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(
        'Name: sample\nVersion: 1.0\nRequires-Dist: missing-extra-child>=2; extra == "feature"\n',
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    decision = dependency_gate.DependencyGate().evaluate(
        path,
        allow_install=True,
        plugin_id="extras",
    )
    assert decision.allow_install and not decision.already_satisfied
    assert len(decision.missing) == 1 and decision.missing[0].startswith(
        "missing-extra-child>=2",
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

    async def prepare(loader, requirements, plugin_id, **kwargs):
        from qwenpaw.utils.io_utils import run_sync_io

        await run_sync_io(install, loader, requirements, plugin_id, **kwargs)

    monkeypatch.setattr(PluginLoader, "_prepare_python_dependencies", prepare)
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
