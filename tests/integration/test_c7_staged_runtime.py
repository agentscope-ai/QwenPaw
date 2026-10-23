# -*- coding: utf-8 -*-
"""Offline Desktop support staging with a selected local child site."""

# pylint: disable=protected-access

from __future__ import annotations

import copy
import email
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
from importlib import metadata

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version
import pytest

from tests.unit.pack.test_c7_distribution import _build, _copy_release_inputs


ROOT = Path(__file__).resolve().parents[2]
STAGER = ROOT / "scripts/pack-tauri/stage_channel_runtime.py"
EXCLUSIVE = ("lark-oapi", "dingtalk-stream", "alibabacloud-dingtalk")
pytestmark = pytest.mark.slow


def _stager():
    spec = importlib.util.spec_from_file_location(
        "c7_stage_channel_runtime",
        STAGER,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _host_metadata(wheel: Path):
    with zipfile.ZipFile(wheel) as archive:
        path = next(
            name
            for name in archive.namelist()
            if name.endswith(".dist-info/METADATA")
        )
        return email.message_from_bytes(archive.read(path))


def _declared_sdk_requirement(site: Path, name: str) -> Requirement:
    directory = site / "qwenpaw/official_channels"
    index = json.loads((directory / "index.json").read_text(encoding="utf-8"))
    for row in index["plugins"]:
        with zipfile.ZipFile(directory / row["filename"]) as archive:
            lines = (
                archive.read(
                    f"{row['plugin_id']}/requirements.txt",
                )
                .decode("utf-8")
                .splitlines()
            )
        for line in lines:
            if line.strip() and not line.lstrip().startswith("#"):
                requirement = Requirement(line.strip())
                if canonicalize_name(requirement.name) == name:
                    return requirement
    raise AssertionError(f"No bundled SDK requirement: {name}")


def _required_native_distributions(wheel: Path):
    """Resolve names against existing genuine local metadata, without pip."""
    host = _host_metadata(wheel)
    environment = default_environment()
    installed = {
        canonicalize_name(dist.metadata["Name"]): dist
        for dist in metadata.distributions()
        if dist.metadata["Name"]
    }
    pending = [Requirement(f"qwenpaw[channels]=={host['Version']}")]
    seen = set()
    selected = {}
    while pending:
        requirement = pending.pop()
        name = canonicalize_name(requirement.name)
        key = (name, frozenset(requirement.extras))
        if key in seen:
            continue
        seen.add(key)
        if name == "qwenpaw":
            record = host
        else:
            dist = installed.get(name)
            assert dist is not None, f"Local child provider missing: {name}"
            assert Version(dist.version) in requirement.specifier, (
                name,
                requirement,
                dist.version,
            )
            assert dist.files is not None, f"Provider has no RECORD: {name}"
            selected[name] = dist
            record = dist.metadata
        for value in record.get_all("Requires-Dist", []):
            child = Requirement(value)
            if child.marker is None or any(
                child.marker.evaluate({**environment, "extra": extra})
                for extra in ({""} | set(requirement.extras))
            ):
                pending.append(child)
    return selected


def _copy_genuine_native_site(distributions, target: Path) -> None:
    """Copy only RECORD-listed regular library files and genuine metadata."""
    for name, dist in sorted(distributions.items()):
        origin = Path(dist.locate_file("")).resolve()
        for listed in dist.files or ():
            relative = Path(str(listed))
            source = Path(dist.locate_file(listed))
            unsafe_relative = (
                relative.is_absolute()
                or ".." in relative.parts
                or "__pycache__" in relative.parts
            )
            unsafe_source = (
                source.is_symlink()
                or not source.is_file()
                or source.suffix == ".pyc"
                or source.suffix == ".pth"
                or not source.resolve().is_relative_to(origin)
            )
            if unsafe_relative or unsafe_source:
                continue
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                assert destination.read_bytes() == source.read_bytes(), (
                    name,
                    relative,
                )
            else:
                shutil.copy2(source, destination)


def _wheel_from_installed_provider(name: str, destination: Path) -> Path:
    """Repack genuine installed RECORD files for offline wheelhouse routing."""
    dist = metadata.distribution(name)
    wheel = destination / f"coloredlogs-{dist.version}-py2.py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w", zipfile.ZIP_DEFLATED) as archive:
        for listed in dist.files or ():
            relative = Path(str(listed))
            source = Path(dist.locate_file(listed))
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or not source.is_file()
                or source.suffix == ".pyc"
                or "__pycache__" in relative.parts
            ):
                continue
            archive.write(source, relative.as_posix())
    return wheel


@pytest.fixture(name="c7_staged_runtime", scope="module")
def _c7_staged_runtime(tmp_path_factory):
    root = tmp_path_factory.mktemp("c7-staged-runtime")
    stage = root / "source"
    _copy_release_inputs(ROOT, stage)
    wheel = _build(stage, root / "wheel", "build_wheel")
    resource_dir = root / "resources"
    child_root = resource_dir / "binaries/python-runtime/python"
    subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "venv",
            "--copies",
            "--without-pip",
            str(child_root),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    child = child_root / "bin/python3"
    assert child.is_file() and child.resolve().is_relative_to(resource_dir)
    native_site = (
        child_root
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages"
    )
    native = _required_native_distributions(wheel)
    assert "qwenpaw" not in native
    assert set(EXCLUSIVE) <= set(native)
    _copy_genuine_native_site(native, native_site)
    stager = _stager()
    manifest_path = stager.stage_channel_runtime(
        python=child,
        wheel=wheel,
        resource_dir=resource_dir,
        python_runtime_release="local-selected-providers",
    )
    return root, wheel, resource_dir, child, manifest_path, stager


def test_c7_actual_wheel_stages_genuine_metadata_and_frozen_resources(
    c7_staged_runtime,
    monkeypatch,
) -> None:
    from qwenpaw.config import utils as config_utils
    from qwenpaw.plugins.channel_bootstrap import (
        resolve_default_channel_runtime,
    )
    from qwenpaw.plugins.official_channels import bundled_channel_source

    (
        root,
        wheel,
        resource_dir,
        child,
        manifest_path,
        _stager_module,
    ) = c7_staged_runtime
    site = manifest_path.parent / "site"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["preset"] == "light"
    assert (
        manifest["python_executable"]
        == "binaries/python-runtime/python/bin/python3"
    )
    assert manifest["support_root"] == "binaries/channel-runtime/site"
    assert manifest["dependency_paths"] == [manifest["support_root"]]
    assert (
        manifest["host_wheel_sha256"]
        == hashlib.sha256(wheel.read_bytes()).hexdigest()
    )
    index = site / "qwenpaw/official_channels/index.json"
    assert (
        manifest["official_index_sha256"]
        == hashlib.sha256(index.read_bytes()).hexdigest()
    )
    assert manifest["python"]["version"] == list(sys.version_info[:2])
    assert manifest["python"]["supported_tags"]
    with zipfile.ZipFile(wheel) as archive:
        for name in archive.namelist():
            if name.endswith(
                (
                    ".dist-info/METADATA",
                    ".dist-info/WHEEL",
                    ".dist-info/RECORD",
                ),
            ):
                assert (site / name).read_bytes() == archive.read(name)
    assert not list(site.rglob("*.pth"))
    assert (site / "qwenpaw/channel_protocol/shared_worker.py").is_file()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(config_utils, "WORKING_DIR", root / "user-working")
    monkeypatch.setenv("QWENPAW_TAURI_RESOURCE_DIR", str(resource_dir))
    monkeypatch.setenv("QWENPAW_DESKTOP_PY_RUNTIME", str(child))
    monkeypatch.setenv("QWENPAW_CHANNEL_RUNTIME_MANIFEST", str(manifest_path))
    monkeypatch.setenv("QWENPAW_CHANNEL_SUPPORT_ROOT", str(site))
    monkeypatch.setenv(
        "QWENPAW_CHANNEL_DEPENDENCY_PATHS",
        json.dumps([str(site)]),
    )
    monkeypatch.setenv("QWENPAW_CHANNEL_PRESET", "light")
    settings = resolve_default_channel_runtime()
    assert settings.python_executable == str(child)
    assert settings.support_root == site
    assert settings.dependency_install_target.is_relative_to(
        root / "user-working",
    )
    for channel in ("dingtalk", "feishu"):
        with bundled_channel_source(channel) as source:
            assert (source / channel / "driver.py").is_file()
            assert (source / "requirements.txt").is_file()


def test_c7_required_wheelhouse_pth_preserves_record_without_execution(
    c7_staged_runtime,
) -> None:
    """The genuine coloredlogs .pth is inert in explicit sys.path support."""
    (
        root,
        wheel,
        _resource,
        original_child,
        _manifest,
        stager,
    ) = c7_staged_runtime
    resource_dir = root / "wheelhouse-resources"
    child_root = resource_dir / "binaries/python-runtime/python"
    subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "venv",
            "--copies",
            "--without-pip",
            str(child_root),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    child = child_root / "bin/python3"
    site_relative = (
        Path("lib")
        / (f"python{sys.version_info.major}.{sys.version_info.minor}")
        / "site-packages"
    )
    native_site = child_root / site_relative
    shutil.copytree(
        original_child.parents[1] / site_relative,
        native_site,
        dirs_exist_ok=True,
        copy_function=os.link,
    )
    provider = metadata.distribution("coloredlogs")
    for listed in provider.files or ():
        relative = Path(str(listed))
        if relative.is_absolute() or ".." in relative.parts:
            continue
        path = native_site / relative
        if path.is_file():
            path.unlink()
    # importlib.metadata still discovers an empty dist-info directory.
    shutil.rmtree(native_site / Path(provider._path).name)
    wheelhouse = root / "wheelhouse"
    wheelhouse.mkdir()
    provider_wheel = _wheel_from_installed_provider("coloredlogs", wheelhouse)
    with zipfile.ZipFile(provider_wheel) as archive:
        genuine_pth = archive.read("coloredlogs.pth")
        genuine_record = next(
            archive.read(name)
            for name in archive.namelist()
            if name.endswith(".dist-info/RECORD")
        )
    manifest = stager.stage_channel_runtime(
        python=child,
        wheel=wheel,
        resource_dir=resource_dir,
        wheelhouse=wheelhouse,
    )
    site = manifest.parent / "site"
    assert (site / "coloredlogs.pth").read_bytes() == genuine_pth
    record = next(site.glob("coloredlogs-*.dist-info/RECORD"))
    assert record.read_bytes() == genuine_record
    probe = subprocess.run(
        [
            str(child),
            "-I",
            "-c",
            "import importlib.metadata as m,sys; "
            "sys.path.insert(0,sys.argv[1]); "
            "assert m.version('coloredlogs'); "
            "assert 'coloredlogs' not in sys.modules",
            str(site),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        env={**os.environ, "COLOREDLOGS_AUTO_INSTALL": "1"},
    )
    assert probe.returncode == 0, probe.stdout + probe.stderr
    snapshot = stager._snapshot(child, site)
    edited = copy.deepcopy(snapshot)
    next(
        row
        for row in edited["distributions"]
        if canonicalize_name(row["name"]) == "coloredlogs"
    )["editable"] = True
    with pytest.raises(ValueError, match="Invalid dependency provider"):
        stager._validate_closure(
            edited,
            json.loads(manifest.read_text())["host_version"],
        )


@pytest.mark.parametrize("name", EXCLUSIVE)
def test_c7_controlled_metadata_minimum_and_conflict(
    c7_staged_runtime,
    name,
) -> None:
    """These version edits model metadata only; no older SDK is executed."""
    _root, _wheel, _resource, child, manifest_path, stager = c7_staged_runtime
    site = manifest_path.parent / "site"
    snapshot = stager._snapshot(child, site)
    original = next(
        row
        for row in snapshot["distributions"]
        if canonicalize_name(row["name"]) == name
    )
    requirement = _declared_sdk_requirement(site, name)
    minimum = next(
        spec.version for spec in requirement.specifier if spec.operator == ">="
    )
    at_minimum = copy.deepcopy(snapshot)
    next(
        row
        for row in at_minimum["distributions"]
        if canonicalize_name(row["name"]) == name
    )["version"] = minimum
    stager._validate_closure(
        at_minimum,
        json.loads(manifest_path.read_text())["host_version"],
    )
    too_old = copy.deepcopy(snapshot)
    next(
        row
        for row in too_old["distributions"]
        if canonicalize_name(row["name"]) == name
    )["version"] = "0.0.1"
    with pytest.raises(ValueError, match="Invalid dependency provider"):
        stager._validate_closure(
            too_old,
            json.loads(manifest_path.read_text())["host_version"],
        )
    assert Version(original["version"]) in requirement.specifier
