# -*- coding: utf-8 -*-
"""Entry point declarations are inert metadata during additive publication."""

import base64
from dataclasses import replace
import hashlib
import zipfile

import pytest

from qwenpaw.plugins import dependency_gate as gate
from qwenpaw.plugins.execution.dependencies import repair_marker

from .test_generic_dependency_gate import inputs, wheel


def entry_point_wheel(tmp_path, marker, *, extra=None, corrupt=False):
    """Build a complete wheel with an entry point that must never execute."""
    addition = wheel(tmp_path, name="tabulate", version="0.10.0")
    with zipfile.ZipFile(addition.path) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    files["tabulate.py"] = (
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('imported')\n"
        "def main():\n"
        f"    Path({str(marker)!r}).write_text('executed')\n"
    ).encode()
    files[
        "tabulate-0.10.0.dist-info/entry_points.txt"
    ] = b"[console_scripts]\ntabulate = tabulate:main\n"
    files.update(extra or {})
    record = "tabulate-0.10.0.dist-info/RECORD"
    files[record] = (
        "".join(
            f"{name},sha256="
            + base64.urlsafe_b64encode(hashlib.sha256(data).digest())
            .decode()
            .rstrip("=")
            + f",{len(data)}\n"
            for name, data in files.items()
            if name != record
        )
        + f"{record},,\n"
    ).encode()
    if corrupt:
        files[
            "tabulate-0.10.0.dist-info/entry_points.txt"
        ] += b"# changed after RECORD\n"
    with zipfile.ZipFile(addition.path, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return gate.WheelAddition(
        addition.path,
        hashlib.sha256(addition.path.read_bytes()).hexdigest(),
    )


@pytest.mark.asyncio
async def test_console_entry_point_metadata_publishes_without_running_or_scripts(
    tmp_path,
):
    site, reqs, process, usage, spec = inputs(
        tmp_path,
        "tabulate==0.10.0\n",
    )
    marker = tmp_path / "entry-point-executed"
    addition = entry_point_wheel(tmp_path, marker)

    observed = await gate.prepare_shared_dependencies(
        process,
        spec,
        plugin_id="creator",
        requirements_file=reqs,
        usage_registry=usage,
        install_target=site,
        wheels=(addition,),
    )

    assert observed.distributions["tabulate"]["version"] == "0.10.0"
    assert (
        site / "tabulate-0.10.0.dist-info/entry_points.txt"
    ).read_bytes() == b"[console_scripts]\ntabulate = tabulate:main\n"
    assert {
        str(path.relative_to(site))
        for path in site.rglob("*")
        if path.is_file()
    } == {
        "tabulate.py",
        "tabulate-0.10.0.dist-info/METADATA",
        "tabulate-0.10.0.dist-info/WHEEL",
        "tabulate-0.10.0.dist-info/RECORD",
        "tabulate-0.10.0.dist-info/top_level.txt",
        "tabulate-0.10.0.dist-info/entry_points.txt",
    }
    assert not marker.exists()
    assert not (tmp_path / "bin").exists()
    assert not (tmp_path / "Scripts").exists()
    assert not repair_marker(site).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,reason",
    [
        ("pth", "DEPENDENCY_PLAN_UNVERIFIED"),
        ("unsupported-data-scheme", "DEPENDENCY_PLAN_UNVERIFIED"),
        ("metadata-record-tampered", "DEPENDENCY_PLAN_UNVERIFIED"),
        ("incompatible-tag", "DEPENDENCY_PLAN_UNVERIFIED"),
        ("collision", "DEPENDENCY_RESTART_REQUIRED"),
    ],
)
async def test_entry_point_metadata_keeps_rejection_gate_intact(
    tmp_path,
    kind,
    reason,
):
    site, reqs, process, usage, spec = inputs(
        tmp_path,
        "tabulate==0.10.0\n",
    )
    marker = tmp_path / "entry-point-executed"
    extra = {
        "pth": {"startup.pth": b"import tabulate\n"},
        "unsupported-data-scheme": {
            "tabulate-0.10.0.data/headers/tabulate.h": b"unsupported scheme\n",
        },
    }.get(kind, {})
    addition = entry_point_wheel(
        tmp_path,
        marker,
        extra=extra,
        corrupt=kind == "metadata-record-tampered",
    )
    if kind == "incompatible-tag":
        process.snapshot = replace(
            process.snapshot,
            supported_tags=("cp999-none-any",),
        )
    if kind == "collision":
        (site / "tabulate.py").write_bytes(b"existing host module bytes\n")
    before = {
        str(path.relative_to(site)): path.read_bytes()
        for path in site.rglob("*")
        if path.is_file()
    }

    with pytest.raises(gate.SharedDependencyError) as error:
        await gate.prepare_shared_dependencies(
            process,
            spec,
            plugin_id="creator",
            requirements_file=reqs,
            usage_registry=usage,
            install_target=site,
            wheels=(addition,),
        )

    assert error.value.reason_code == reason
    assert {
        str(path.relative_to(site)): path.read_bytes()
        for path in site.rglob("*")
        if path.is_file()
    } == before
    assert not marker.exists()
    assert not (tmp_path / "bin").exists()
    assert not (tmp_path / "Scripts").exists()
    assert not repair_marker(site).exists()
