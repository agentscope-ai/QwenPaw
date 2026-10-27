# -*- coding: utf-8 -*-
"""Dependency audits distinguish bundled tools from host conflicts."""

# pylint: disable=protected-access
import importlib
import importlib.metadata
import json
import py_compile
from pathlib import Path
import subprocess
import sys

import pytest

from qwenpaw.plugins import SDKRestartRequiredError
from qwenpaw.plugins import _sdk_dependencies as dependencies

pytestmark = pytest.mark.p1


def distribution(root, name, version):
    """Write discoverable package metadata and importable module bytes."""
    module = name.replace("-", "_")
    info = root / f"{module}-{version}.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
    )
    (root / f"{module}.py").write_text(f"VERSION = {version!r}\n")
    (info / "top_level.txt").write_text(module + "\n")
    (info / "RECORD").write_text(
        f"{module}.py,,\n{info.name}/METADATA,,\n"
        f"{info.name}/top_level.txt,,\n{info.name}/RECORD,,\n",
    )
    return info


def audit_paths(monkeypatch, *roots):
    monkeypatch.setattr(
        dependencies,
        "distributions",
        lambda: importlib.metadata.distributions(path=list(map(str, roots))),
    )


def bundled_environment(tmp_path):
    host = tmp_path / "site-packages"
    owner = distribution(host, "sdk-owner-tool", "1.0")
    vendor = host / "sdk_owner_tool" / "_vendor"
    bundled = distribution(vendor, "sdk-audit-probe", "0.9")
    with (owner / "RECORD").open("a", encoding="utf-8") as record:
        record.write(f"{bundled.relative_to(host).as_posix()}/METADATA,,\n")
        module = (vendor / "sdk_audit_probe.py").relative_to(host).as_posix()
        record.write(f"{module},,\n")
    return host, vendor


def test_owned_bundled_duplicate_does_not_block_unrelated_dependency(
    tmp_path,
    monkeypatch,
):
    host, vendor = bundled_environment(tmp_path)
    distribution(host, "sdk-audit-probe", "1.0")
    audit_paths(monkeypatch, host, vendor)
    source = tmp_path / "plugin"
    source.mkdir()
    (source / "plugin.json").write_text('{"sdk": {"version": "1.0"}}')
    assert dependencies.loaded_sdk_conflicts(source, ["sdk-new-tool==1"]) == []
    assert dependencies._installed_versions()["sdk-audit-probe"] == "1.0"


def test_bundled_only_dependency_remains_protected(tmp_path, monkeypatch):
    host, vendor = bundled_environment(tmp_path)
    audit_paths(monkeypatch, host, vendor)
    assert dependencies._installed_versions()["sdk-audit-probe"] == "0.9"


@pytest.mark.parametrize("host_name", ["host", "host\\with-backslash"])
def test_vendor_named_directory_without_owner_is_not_exempt(
    tmp_path,
    monkeypatch,
    host_name,
):
    host = tmp_path / host_name
    other = tmp_path / "not-a-tool" / "_vendor"
    distribution(host, "sdk-audit-probe", "1.0")
    distribution(other, "sdk-audit-probe", "2.0")
    audit_paths(monkeypatch, host, other)
    with pytest.raises(SDKRestartRequiredError) as caught:
        dependencies._installed_versions()
    diagnostic = str(caught.value)
    for detail in ("sdk-audit-probe", "1.0", "2.0", str(host), str(other)):
        assert detail in diagnostic


@pytest.mark.parametrize("sourceless", [False, True])
def test_bundled_copy_imported_as_public_module_cannot_be_discarded(
    tmp_path,
    monkeypatch,
    sourceless,
):
    host, vendor = bundled_environment(tmp_path)
    distribution(host, "sdk-audit-probe", "1.0")
    if sourceless:
        source = vendor / "sdk_audit_probe.py"
        py_compile.compile(
            str(source),
            cfile=str(source.with_suffix(".pyc")),
            doraise=True,
        )
        source.unlink()
        record = vendor / "sdk_audit_probe-0.9.dist-info/RECORD"
        record.write_text(
            record.read_text().replace(
                "sdk_audit_probe.py,",
                "sdk_audit_probe.pyc,",
            ),
        )
    monkeypatch.syspath_prepend(str(vendor))
    module = importlib.import_module("sdk_audit_probe")
    assert module.VERSION == "0.9"
    monkeypatch.syspath_prepend(str(host))
    audit_paths(monkeypatch, host, vendor)
    try:
        with pytest.raises(SDKRestartRequiredError):
            dependencies._installed_versions()
    finally:
        sys.modules.pop("sdk_audit_probe", None)


@pytest.mark.parametrize("change", ["version", "source"])
def test_dependency_environment_change_during_resolution_blocks_install(
    tmp_path,
    monkeypatch,
    change,
):
    host = tmp_path / "host"
    distribution(host, "sdk-audit-probe", "1.0")
    replacement = tmp_path / "replacement"
    distribution(
        replacement,
        "sdk-audit-probe",
        "2.0" if change == "version" else "1.0",
    )
    audit_paths(monkeypatch, host)
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("sdk-new-tool==1\n")
    calls = []

    def resolve(args, **_kwargs):
        calls.append(args)
        assert "--dry-run" in args, "Environment changed before a real install"
        Path(args[args.index("--report") + 1]).write_text(
            json.dumps(
                {
                    "version": "1",
                    "install": [{"metadata": {"name": "sdk-new-tool"}}],
                },
            ),
            encoding="utf-8",
        )
        audit_paths(monkeypatch, replacement)
        return subprocess.CompletedProcess(args, 0, "", "")

    with pytest.raises(SDKRestartRequiredError, match="changed"):
        dependencies.install_sdk_requirements(
            requirements,
            "environment-probe",
            python=sys.executable,
            target=None,
            run=resolve,
            find_uv=lambda: None,
        )
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("installer", "host_has_pip"),
    [("pip", True), ("pip", False), ("uv", True)],
)
def test_installer_environment_exposes_exactly_one_pip_or_none(
    tmp_path,
    monkeypatch,
    installer,
    host_has_pip,
):
    from . import sdk_dependency_fixture

    host = tmp_path / "host-site"
    host.mkdir()
    if host_has_pip:
        info = distribution(host, "pip", "99.0")
        (host / "pip.py").unlink()
        (host / "pip").mkdir()
        (host / "pip/__init__.py").write_text("__version__ = '99.0'\n")
        (info / "RECORD").write_text("pip/__init__.py,,\n")
    monkeypatch.setattr(
        sdk_dependency_fixture.site,
        "getsitepackages",
        lambda: [str(host)],
    )
    python, library = sdk_dependency_fixture.dependency_python(
        tmp_path / "venv",
        installer=installer,
    )
    if installer == "pip":
        result = subprocess.check_output(
            [
                str(python),
                "-I",
                "-c",
                "import pip; print(pip.__version__); print(pip.__file__)",
            ],
            text=True,
        ).splitlines()
        if host_has_pip:
            assert result[0] == "99.0"
        assert (
            Path(result[1]).resolve()
            == (library / "pip/__init__.py").resolve()
        )
    else:
        assert not (library / "pip").exists()


def test_same_version_editable_metadata_is_allowed(tmp_path, monkeypatch):
    installed, editable = tmp_path / "site", tmp_path / "source"
    distribution(installed, "sdk-audit-probe", "1.0")
    egg = editable / "sdk_audit_probe.egg-info"
    egg.mkdir(parents=True)
    (egg / "PKG-INFO").write_text(
        "Metadata-Version: 2.1\nName: sdk-audit-probe\nVersion: 1.0\n",
    )
    audit_paths(monkeypatch, installed, editable)
    assert dependencies._installed_versions() == {"sdk-audit-probe": "1.0"}


def test_bundled_copy_first_in_search_path_is_not_discarded(
    tmp_path,
    monkeypatch,
):
    host, vendor = bundled_environment(tmp_path)
    distribution(host, "sdk-audit-probe", "1.0")
    audit_paths(monkeypatch, vendor, host)
    with pytest.raises(SDKRestartRequiredError):
        dependencies._installed_versions()


def test_private_vendor_import_does_not_conflict_with_public_package(
    tmp_path,
    monkeypatch,
):
    host, vendor = bundled_environment(tmp_path)
    distribution(host, "sdk-audit-probe", "1.0")
    (vendor / "__init__.py").touch()
    (vendor.parent / "__init__.py").touch()
    monkeypatch.syspath_prepend(str(host))
    try:
        module = importlib.import_module(
            "sdk_owner_tool._vendor.sdk_audit_probe",
        )
        assert module.VERSION == "0.9"
        audit_paths(monkeypatch, host, vendor)
        assert dependencies._installed_versions()["sdk-audit-probe"] == "1.0"
    finally:
        for name in list(sys.modules):
            if name == "sdk_owner_tool" or name.startswith("sdk_owner_tool."):
                sys.modules.pop(name)


def test_installer_fixture_supports_filesystems_without_symlinks(
    tmp_path,
    monkeypatch,
):
    from .sdk_dependency_fixture import expose

    source = tmp_path / "source"
    source.mkdir()
    (source / "module.py").write_text("VALUE = 1\n")

    def unavailable(*_args, **_kwargs):
        raise OSError("Symlink privilege unavailable")

    monkeypatch.setattr(Path, "symlink_to", unavailable)
    destination = tmp_path / "copy"
    expose(source, destination)
    assert not destination.is_symlink()
    assert (destination / "module.py").read_text() == "VALUE = 1\n"
