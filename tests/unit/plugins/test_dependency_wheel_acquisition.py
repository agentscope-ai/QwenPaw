# -*- coding: utf-8 -*-
"""Offline acquisition exercises pip and the real shared publication gate."""

import base64
from io import BytesIO
import os
import sys
import tarfile
from types import SimpleNamespace
import zipfile

import pytest

from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.plugins.execution.dependencies import repair_marker
from qwenpaw.plugins.dependency_gate import SharedDependencyError

from .test_generic_dependency_gate import (
    Audit,
    declare,
    evidence,
    materialize_host_metadata,
    wheel,
)


def source_distribution(index, payload, *, broken=False):
    """A real zero-build-dependency PEP 517 package, available only as source."""
    backend = (
        "import base64\nfrom pathlib import Path\n"
        "def build_wheel(wheel_directory, config_settings=None, "
        "metadata_directory=None):\n"
        + (
            "    raise RuntimeError('deliberate offline build failure')\n"
            if broken
            else (
                f"    name = {payload.path.name!r}\n"
                f"    data = {base64.b64encode(payload.path.read_bytes())!r}\n"
                "    Path(wheel_directory, name).write_bytes(base64.b64decode(data))\n"
                "    return name\n"
            )
        )
    )
    files = {
        "pyproject.toml": (
            '[build-system]\nrequires = []\nbuild-backend = "backend"\n'
            'backend-path = ["."]\n'
        ),
        "backend.py": backend,
        "PKG-INFO": "Metadata-Version: 2.1\nName: f32-sdk\nVersion: 2.0\n",
    }
    archive = index / "f32_sdk-2.0.tar.gz"
    with tarfile.open(archive, "w:gz") as package:
        for name, contents in files.items():
            data = contents.encode()
            member = tarfile.TarInfo("f32_sdk-2.0/" + name)
            member.size = len(data)
            package.addfile(member, BytesIO(data))
    return archive


@pytest.fixture
def acquisition(tmp_path, monkeypatch, fresh_registry):
    index = tmp_path / "index"
    index.mkdir()
    site = tmp_path / "site"
    site.mkdir()
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("f32-sdk==2.0\n")
    snapshot = evidence(site)
    process = Audit(snapshot)
    spec = SimpleNamespace(
        identity="opaque-generic-spec",
        python_executable=sys.executable,
        code_root=tmp_path,
    )
    loader = PluginLoader([tmp_path / "plugins"])
    monkeypatch.setenv("PIP_NO_INDEX", "1")
    monkeypatch.setenv("PIP_FIND_LINKS", str(index))
    monkeypatch.setenv("PIP_NO_CACHE_DIR", "1")
    monkeypatch.setenv("PIP_CONFIG_FILE", os.devnull)
    monkeypatch.delenv("QWENPAW_RUNTIME_PROVISIONER", raising=False)

    async def acquire(observed=snapshot):
        await loader._acquire_dependency_wheels(
            process,
            spec,
            observed,
            site,
            "creator",
            requirements,
        )

    return SimpleNamespace(
        index=index,
        site=site,
        requirements=requirements,
        acquire=acquire,
        process=process,
        usage=fresh_registry.dependency_usage,
    )


@pytest.mark.asyncio
async def test_sdist_only_dependency_builds_then_publishes_validated_wheel(
    tmp_path,
    acquisition,
):
    source_distribution(
        acquisition.index,
        wheel(tmp_path, requires=("f32-addon==1.0",)),
    )
    wheel(acquisition.index, name="f32-addon", version="1.0")

    await acquisition.acquire()

    assert (acquisition.site / "f32_sdk.py").read_text() == (
        "VALUE = 'safe-local-addition'\n"
    )
    observed = await acquisition.process.audit(
        SimpleNamespace(identity="opaque-generic-spec"),
    )
    assert observed.snapshot.distributions["f32-sdk"]["version"] == "2.0"
    assert observed.snapshot.distributions["f32-addon"]["version"] == "1.0"
    assert (acquisition.site / "f32_addon.py").is_file()
    assert not repair_marker(acquisition.site).exists()


@pytest.mark.asyncio
async def test_binary_dependency_still_publishes_without_source_build(
    acquisition,
):
    wheel(acquisition.index)

    await acquisition.acquire()

    assert (acquisition.site / "f32_sdk.py").read_text() == (
        "VALUE = 'safe-local-addition'\n"
    )
    assert not repair_marker(acquisition.site).exists()


@pytest.mark.asyncio
async def test_missing_binary_is_added_alongside_existing_source_only_dependency(
    tmp_path,
    acquisition,
):
    source_distribution(acquisition.index, wheel(tmp_path))
    wheel(acquisition.index, name="f32-addon", version="1.0")
    acquisition.requirements.write_text("f32-sdk==2.0\nf32-addon==1.0\n")
    snapshot = evidence(acquisition.site, versions={"f32-sdk": "2.0"})
    materialize_host_metadata(snapshot)
    acquisition.process.snapshot = snapshot
    existing = acquisition.site / "f32_sdk.py"
    existing.write_bytes(b"VALUE = 'already installed source-only SDK'\n")
    before = {
        str(path.relative_to(acquisition.site)): path.read_bytes()
        for path in acquisition.site.rglob("*")
        if path.is_file()
    }

    await acquisition.acquire(snapshot)

    assert (acquisition.site / "f32_addon.py").read_text() == (
        "VALUE = 'safe-local-addition'\n"
    )
    for relative_path, contents in before.items():
        assert (acquisition.site / relative_path).read_bytes() == contents
    assert not repair_marker(acquisition.site).exists()


@pytest.mark.asyncio
async def test_failed_source_build_leaves_runtime_untouched(
    tmp_path,
    acquisition,
):
    source_distribution(acquisition.index, wheel(tmp_path), broken=True)
    sentinel = acquisition.site / "host-owned.txt"
    sentinel.write_bytes(b"existing host bytes")

    with pytest.raises(RuntimeError, match="DEPENDENCY_PLAN_UNVERIFIED"):
        await acquisition.acquire()

    assert list(acquisition.site.iterdir()) == [sentinel]
    assert sentinel.read_bytes() == b"existing host bytes"
    assert not repair_marker(acquisition.site).exists()


@pytest.mark.asyncio
async def test_source_built_wheel_with_invalid_record_cannot_publish(
    tmp_path,
    acquisition,
):
    payload = wheel(tmp_path)
    with zipfile.ZipFile(payload.path) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    files["f32_sdk.py"] = b"VALUE = 'tampered after RECORD was written'\n"
    with zipfile.ZipFile(payload.path, "w") as archive:
        for name, contents in files.items():
            archive.writestr(name, contents)
    source_distribution(acquisition.index, payload)

    with pytest.raises(SharedDependencyError) as error:
        await acquisition.acquire()

    assert error.value.reason_code == "DEPENDENCY_PLAN_UNVERIFIED"
    assert not list(acquisition.site.iterdir())
    assert not repair_marker(acquisition.site).exists()


@pytest.mark.asyncio
async def test_source_built_dependency_conflicting_with_consumer_cannot_publish(
    tmp_path,
    acquisition,
):
    source_distribution(acquisition.index, wheel(tmp_path))
    declare(
        acquisition.usage,
        "running-consumer",
        evidence(acquisition.site),
        ("f32-sdk<2",),
    )

    with pytest.raises(SharedDependencyError) as error:
        await acquisition.acquire()

    assert error.value.reason_code == "DEPENDENCY_RESTART_REQUIRED"
    assert not list(acquisition.site.iterdir())
    assert not repair_marker(acquisition.site).exists()


@pytest.mark.asyncio
async def test_acquisition_respects_existing_distribution_version_constraints(
    tmp_path,
    acquisition,
):
    source_distribution(
        acquisition.index,
        wheel(tmp_path, requires=("f32-host>=1",)),
    )
    # Only version 2 is downloadable. The audited version 1 must constrain pip;
    # silently resolving 2 and filtering it out would hide an incomplete plan.
    wheel(acquisition.index, name="f32-host", version="2.0")
    snapshot = evidence(acquisition.site, versions={"f32-host": "1.0"})
    materialize_host_metadata(snapshot)
    acquisition.process.snapshot = snapshot
    before = {
        str(path.relative_to(acquisition.site)): path.read_bytes()
        for path in acquisition.site.rglob("*")
        if path.is_file()
    }

    with pytest.raises(SharedDependencyError) as error:
        await acquisition.acquire(snapshot)

    assert error.value.reason_code == "DEPENDENCY_RESTART_REQUIRED"
    assert error.value.decision.require_restart
    assert {
        str(path.relative_to(acquisition.site)): path.read_bytes()
        for path in acquisition.site.rglob("*")
        if path.is_file()
    } == before
    assert not repair_marker(acquisition.site).exists()
