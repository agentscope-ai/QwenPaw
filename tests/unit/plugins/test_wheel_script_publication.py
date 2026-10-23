# -*- coding: utf-8 -*-
"""Wheel script relocation stays inside the audited additive target."""

import base64
import csv
from dataclasses import replace
import hashlib
from io import StringIO
from pathlib import Path
import stat
import subprocess
import sys
from textwrap import dedent
from types import ModuleType
import zipfile

import pytest

from qwenpaw.plugins import dependency_gate as gate
from qwenpaw.plugins.execution.dependencies import (
    check_import_origins,
    observe_dependencies,
    repair_marker,
)
from qwenpaw.plugins.execution.errors import ProtocolValidationError

from .test_generic_dependency_gate import inputs, wheel


def script_wheel(
    tmp_path,
    marker,
    *,
    name="jmespath",
    script="jp.py",
    extra=None,
    forged=False,
    shebang=b"#!python\n",
    body=None,
):
    addition = wheel(tmp_path, name=name, version="0.10.0")
    package = name.replace("-", "_")
    with zipfile.ZipFile(addition.path) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    script_path = f"{package}-0.10.0.data/scripts/{script}"
    body = (
        body
        if body is not None
        else (
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).write_text('script executed')\n"
        )
    )
    files[script_path] = shebang + (
        body.encode() if isinstance(body, str) else body
    )
    files.update(extra or {})
    record = f"{package}-0.10.0.dist-info/RECORD"
    rows = StringIO(newline="")
    writer = csv.writer(rows, lineterminator="\n")
    for path, content in files.items():
        if path != record:
            digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest())
            writer.writerow(
                (
                    path,
                    "sha256=" + digest.decode().rstrip("="),
                    str(len(content)),
                ),
            )
    writer.writerow((record, "", ""))
    files[record] = rows.getvalue().encode()
    if forged:
        files[script_path] += b"# altered after source RECORD\n"
    with zipfile.ZipFile(addition.path, "w") as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return gate.WheelAddition(
        addition.path,
        hashlib.sha256(addition.path.read_bytes()).hexdigest(),
    )


async def publish(values, additions):
    site, reqs, process, usage, spec = values
    return await gate.prepare_shared_dependencies(
        process,
        spec,
        plugin_id="creator",
        requirements_file=reqs,
        usage_registry=usage,
        install_target=site,
        wheels=tuple(additions),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "os_name,platform_system,directory,shebang",
    [
        ("posix", "Linux", "bin", b"#!python\n"),
        ("nt", "Windows", "Scripts", b"#!pythonw\n"),
    ],
)
async def test_standard_script_relocates_with_audited_shebang_and_record(
    tmp_path,
    os_name,
    platform_system,
    directory,
    shebang,
):
    values = inputs(tmp_path, "jmespath==0.10.0\n")
    site, _, process, _, _ = values
    process.snapshot = replace(
        process.snapshot,
        marker_environment={
            **process.snapshot.marker_environment,
            "os_name": os_name,
            "platform_system": platform_system,
        },
    )
    marker = tmp_path / "script-executed"
    addition = script_wheel(tmp_path, marker, shebang=shebang)
    external = tmp_path / "bin" / "host-tool"
    external.parent.mkdir()
    external.write_bytes(b"host script outside publication target\n")

    observed = await publish(values, (addition,))

    script = site / directory / "jp.py"
    assert (
        script.read_bytes().splitlines()[0]
        == ("#!" + process.snapshot.executable).encode()
    )
    assert observed.distributions["jmespath"]["version"] == "0.10.0"
    assert not (site / "jmespath-0.10.0.data").exists()
    if os_name == "posix":
        assert stat.S_IMODE(script.stat().st_mode) & 0o111 == 0o111
    record = site / "jmespath-0.10.0.dist-info/RECORD"
    rows = list(csv.reader(StringIO(record.read_text())))
    assert {row[0] for row in rows} == {
        "jmespath.py",
        "jmespath-0.10.0.dist-info/METADATA",
        "jmespath-0.10.0.dist-info/WHEEL",
        "jmespath-0.10.0.dist-info/top_level.txt",
        "jmespath-0.10.0.dist-info/RECORD",
        f"{directory}/jp.py",
    }
    for relative, digest, size in rows:
        if relative.endswith("/RECORD"):
            assert (digest, size) == ("", "")
        else:
            content = (site / relative).read_bytes()
            expected = base64.urlsafe_b64encode(
                hashlib.sha256(content).digest(),
            )
            assert digest == "sha256=" + expected.decode().rstrip("=")
            assert size == str(len(content))
    assert external.read_bytes() == b"host script outside publication target\n"
    assert sorted(path.name for path in external.parent.iterdir()) == [
        "host-tool",
    ]
    assert not marker.exists()
    assert not repair_marker(site).exists()


@pytest.mark.asyncio
async def test_two_wheels_share_script_directory_preserving_existing_siblings(
    tmp_path,
):
    values = inputs(tmp_path, "jmespath==0.10.0\nother-sdk==0.10.0\n")
    site, _, process, _, _ = values
    process.snapshot = replace(
        process.snapshot,
        marker_environment={
            **process.snapshot.marker_environment,
            "os_name": "posix",
            "platform_system": "Linux",
        },
    )
    scripts = site / "bin"
    scripts.mkdir()
    sibling = scripts / "host-tool"
    sibling.write_bytes(b"preserve existing sibling script\n")
    marker = tmp_path / "script-executed"
    additions = (
        script_wheel(tmp_path, marker),
        script_wheel(tmp_path, marker, name="other-sdk", script="other-tool"),
    )

    observed = await publish(values, additions)

    assert observed.distributions["jmespath"]["version"] == "0.10.0"
    assert observed.distributions["other-sdk"]["version"] == "0.10.0"
    assert {path.name for path in scripts.iterdir()} == {
        "jp.py",
        "other-tool",
        "host-tool",
    }
    assert sibling.read_bytes() == b"preserve existing sibling script\n"
    assert not marker.exists()
    assert not repair_marker(site).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    [
        "existing-exact",
        "existing-casefold",
        "staged-exact",
        "staged-casefold",
        "script-directory-symlink",
        "unsupported-scheme",
        "foreign-data-root",
        "nonflat-script",
        "forged-source-record",
        "module-collision",
        "existing-script-package",
    ],
)
async def test_invalid_script_plan_rejects_before_any_runtime_write(
    tmp_path,
    kind,
):
    requirements = "jmespath==0.10.0\n"
    if kind.startswith("staged-"):
        requirements += "other-sdk==0.10.0\n"
    values = inputs(tmp_path, requirements)
    site, _, process, _, _ = values
    process.snapshot = replace(
        process.snapshot,
        marker_environment={
            **process.snapshot.marker_environment,
            "os_name": "posix",
            "platform_system": "Linux",
        },
    )
    marker = tmp_path / "script-executed"
    outside = tmp_path / "outside-scripts"
    outside.mkdir()
    external = outside / "host-tool"
    external.write_bytes(b"outside script untouched\n")
    sentinel = site / "host-owned.txt"
    sentinel.write_bytes(b"existing runtime bytes\n")
    extra = {
        "unsupported-scheme": {
            "jmespath-0.10.0.data/purelib/other.py": b"unsupported data\n",
        },
        "foreign-data-root": {
            "foreign-0.10.0.data/scripts/foreign-tool": b"foreign data\n",
        },
    }.get(kind, {})
    additions = [
        script_wheel(
            tmp_path,
            marker,
            extra=extra,
            script="nested/jp.py" if kind == "nonflat-script" else "jp.py",
            forged=kind == "forged-source-record",
        ),
    ]
    if kind in {"existing-exact", "existing-casefold"}:
        scripts = site / "bin"
        scripts.mkdir()
        filename = "jp.py" if kind == "existing-exact" else "JP.PY"
        (scripts / filename).write_bytes(b"existing script untouched\n")
    elif kind.startswith("staged-"):
        additions.append(
            script_wheel(
                tmp_path,
                marker,
                name="other-sdk",
                script="jp.py" if kind == "staged-exact" else "JP.PY",
            ),
        )
    elif kind == "script-directory-symlink":
        (site / "bin").symlink_to(outside, target_is_directory=True)
    elif kind == "module-collision":
        (site / "jmespath.py").write_bytes(b"existing module untouched\n")
    elif kind == "existing-script-package":
        (site / "bin").mkdir()
        (site / "bin/__init__.py").write_bytes(b"existing import package\n")
    before = {
        str(path.relative_to(site)): path.read_bytes()
        for path in site.rglob("*")
        if path.is_file()
    }

    with pytest.raises(gate.SharedDependencyError) as error:
        await publish(values, additions)

    assert error.value.reason_code in {
        "DEPENDENCY_PLAN_UNVERIFIED",
        "DEPENDENCY_RESTART_REQUIRED",
    }
    assert {
        str(path.relative_to(site)): path.read_bytes()
        for path in site.rglob("*")
        if path.is_file()
    } == before
    assert external.read_bytes() == b"outside script untouched\n"
    assert list(outside.iterdir()) == [external]
    if kind == "script-directory-symlink":
        assert (site / "bin").is_symlink()
    assert not marker.exists()
    assert not repair_marker(site).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "script",
    ["__init__.py", "__init__.pyc", "__init__.pyd"],
)
async def test_script_cannot_turn_directory_into_shadowing_import_package(
    tmp_path,
    script,
):
    values = inputs(tmp_path, "jmespath==0.10.0\n")
    site, _, process, _, _ = values
    process.snapshot = replace(
        process.snapshot,
        marker_environment={
            **process.snapshot.marker_environment,
            "os_name": "posix",
            "platform_system": "Linux",
        },
    )
    original = site / "bin.py"
    original.write_bytes(b"VALUE = 'host bin import module'\n")
    marker = tmp_path / "script-executed"

    with pytest.raises(gate.SharedDependencyError):
        await publish(values, (script_wheel(tmp_path, marker, script=script),))

    assert list(site.iterdir()) == [original]
    assert original.read_bytes() == b"VALUE = 'host bin import module'\n"
    assert not marker.exists()
    assert not repair_marker(site).exists()


@pytest.mark.parametrize("explicit_script_tops", [False, True])
def test_dependency_audit_excludes_script_record_dirs_unless_declared(
    tmp_path,
    explicit_script_tops,
):
    site, reqs, _, _, _ = inputs(tmp_path, "jmespath==0.10.0\n")
    info = site / "jmespath-0.10.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: jmespath\nVersion: 0.10.0\n",
    )
    (info / "top_level.txt").write_text(
        "jmespath\nbin\nScripts\n" if explicit_script_tops else "jmespath\n",
    )
    (info / "RECORD").write_text(
        "jmespath.py,,\nbin/jp.py,,\nScripts/jp.py,,\n",
    )

    observed = observe_dependencies(
        {
            "code_root": str(tmp_path / "plugin"),
            "_audit_sites": [str(site)],
            "requirements_path": str(reqs),
            "dependency_paths": [str(site)],
        },
    )

    assert set(observed.distributions["jmespath"]["top_level"]) == (
        {"jmespath", "bin", "Scripts"}
        if explicit_script_tops
        else {"jmespath"}
    )


@pytest.mark.parametrize("package", ["bin", "Scripts"])
def test_inferred_script_named_package_keeps_plugin_origin_fence(
    tmp_path,
    monkeypatch,
    package,
):
    site, reqs, _, _, _ = inputs(tmp_path, "other-sdk==0.10.0\n")
    info = site / "other_sdk-0.10.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: other-sdk\nVersion: 0.10.0\n",
    )
    # No top_level.txt: infer this legitimate package from RECORD rather than
    # treating its initializer as an ordinary relocated command-line script.
    (info / "RECORD").write_text(f"{package}/__init__.py,,\n")
    installed = site / package
    installed.mkdir()
    (installed / "__init__.py").write_text("VALUE = 'installed SDK'\n")
    code_root = tmp_path / "plugin"
    shadow = code_root / package
    shadow.mkdir(parents=True)
    initializer = shadow / "__init__.py"
    initializer.write_text("VALUE = 'plugin-local shadow'\n")
    module = ModuleType(package)
    module.__file__ = str(initializer)
    module.__path__ = [str(shadow)]
    monkeypatch.setitem(sys.modules, package, module)

    observed = observe_dependencies(
        {
            "code_root": str(code_root),
            "_audit_sites": [str(site)],
            "requirements_path": str(reqs),
            "dependency_paths": [str(site)],
        },
    )

    with pytest.raises(
        ProtocolValidationError,
        match="DEPENDENCY_ORIGIN_INVALID",
    ):
        check_import_origins(observed, code_root, {"other-sdk"})
    assert package in observed.distributions["other-sdk"]["top_level"]


@pytest.mark.asyncio
async def test_posix_script_uses_audited_interpreter_with_spaces_and_quotes(
    tmp_path,
):
    values = inputs(tmp_path, "jmespath==0.10.0\n")
    site, _, process, _, _ = values
    executable = tmp_path / "Python env's directory" / "python"
    executable.parent.mkdir()
    executable.symlink_to(sys.executable)
    process.snapshot = replace(
        process.snapshot,
        executable=str(executable),
        marker_environment={
            **process.snapshot.marker_environment,
            "os_name": "posix",
            "platform_system": "Linux",
        },
    )
    marker = tmp_path / "script-executed"
    addition = script_wheel(
        tmp_path,
        marker,
        body=(
            "import sys\nfrom pathlib import Path\n"
            f"Path({str(marker)!r}).write_text(sys.executable)\n"
        ),
    )

    await publish(values, (addition,))

    assert not marker.exists(), "publication executed an installed script"
    script = site / "bin/jp.py"
    # Execute only our generated fixture after installation. A shell trampoline
    # may vary, but it must safely reach the audited executable despite quotes.
    result = subprocess.run(
        [str(script)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert marker.read_text() == str(executable)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "executable",
    ["/python\nmalicious", "/python\x00bad"],
)
async def test_invalid_audited_interpreter_rejects_script_before_publication(
    tmp_path,
    executable,
):
    values = inputs(tmp_path, "jmespath==0.10.0\n")
    site, _, process, _, _ = values
    process.snapshot = replace(process.snapshot, executable=executable)
    marker = tmp_path / "script-executed"

    with pytest.raises(gate.SharedDependencyError):
        await publish(values, (script_wheel(tmp_path, marker),))

    assert not list(site.iterdir())
    assert not marker.exists()
    assert not repair_marker(site).exists()


@pytest.mark.asyncio
async def test_windows_script_quotes_audited_interpreter_with_spaces(tmp_path):
    values = inputs(tmp_path, "jmespath==0.10.0\n")
    site, _, process, _, _ = values
    process.snapshot = replace(
        process.snapshot,
        executable=r"C:\Program Files\Python\python.exe",
        marker_environment={
            **process.snapshot.marker_environment,
            "os_name": "nt",
            "platform_system": "Windows",
        },
    )
    marker = tmp_path / "script-executed"

    await publish(values, (script_wheel(tmp_path, marker),))

    assert (site / "Scripts/jp.py").read_bytes().splitlines()[0] == (
        b'#!"C:\\Program Files\\Python\\python.exe"'
    )
    assert not marker.exists()
    assert not repair_marker(site).exists()


@pytest.mark.asyncio
async def test_posix_trampoline_preserves_source_encoding_cookie(tmp_path):
    values = inputs(tmp_path, "jmespath==0.10.0\n")
    site, _, process, _, _ = values
    executable = tmp_path / "Python spaced directory" / "python"
    executable.parent.mkdir()
    executable.symlink_to(sys.executable)
    process.snapshot = replace(
        process.snapshot,
        executable=str(executable),
        marker_environment={
            **process.snapshot.marker_environment,
            "os_name": "posix",
            "platform_system": "Linux",
        },
    )
    marker = tmp_path / "script-executed"
    body = (
        "# coding: latin-1\nfrom pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('caf\xe9')\n"
    ).encode("latin-1")

    await publish(values, (script_wheel(tmp_path, marker, body=body),))

    assert not marker.exists(), "publication executed an installed script"
    result = subprocess.run(
        [str(site / "bin/jp.py")],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert marker.read_text() == "caf\xe9"


@pytest.mark.asyncio
@pytest.mark.parametrize("script", ["CON", "nul.exe", "COM1"])
async def test_windows_device_names_cannot_be_script_destinations(
    tmp_path,
    script,
):
    values = inputs(tmp_path, "jmespath==0.10.0\n")
    site, _, process, _, _ = values
    process.snapshot = replace(
        process.snapshot,
        marker_environment={
            **process.snapshot.marker_environment,
            "os_name": "nt",
            "platform_system": "Windows",
        },
    )
    marker = tmp_path / "script-executed"

    with pytest.raises(gate.SharedDependencyError):
        await publish(values, (script_wheel(tmp_path, marker, script=script),))

    assert not list(site.iterdir())
    assert not marker.exists()
    assert not repair_marker(site).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("module_top", ["bin", "BIN", "scripts", "Scripts"])
async def test_script_directory_cannot_merge_with_import_package(
    tmp_path,
    module_top,
):
    values = inputs(tmp_path, "jmespath==0.10.0\n")
    site, _, process, _, _ = values
    windows = module_top.lower() == "scripts"
    process.snapshot = replace(
        process.snapshot,
        marker_environment={
            **process.snapshot.marker_environment,
            "os_name": "nt" if windows else "posix",
            "platform_system": "Windows" if windows else "Linux",
        },
    )
    marker = tmp_path / "script-executed"
    addition = script_wheel(
        tmp_path,
        marker,
        extra={f"{module_top}/__init__.py": b"VALUE = 1\n"},
    )

    with pytest.raises(gate.SharedDependencyError):
        await publish(values, (addition,))

    assert not list(site.iterdir())
    assert not marker.exists()
    assert not repair_marker(site).exists()


def test_script_executable_permissions_respect_restrictive_umask(tmp_path):
    # Keep the process-wide umask confined to this isolated child.
    code = dedent(
        """\
        import asyncio
        import os
        from pathlib import Path
        import stat
        import sys
        from tests.unit.plugins.test_generic_dependency_gate import inputs
        from tests.unit.plugins.test_wheel_script_publication import (
            publish, script_wheel,
        )
        root = Path(sys.argv[1])
        os.umask(0o077)
        values = inputs(root, "jmespath==0.10.0\\n")
        marker = root / "script-executed"
        asyncio.run(publish(values, (script_wheel(root, marker),)))
        script = values[0] / "bin/jp.py"
        mode = stat.S_IMODE(script.stat().st_mode)
        assert mode == 0o700, f"expected 0700 under umask 077; got {mode:04o}"
        assert not marker.exists(), "publication executed a script"
    """,
    )

    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
