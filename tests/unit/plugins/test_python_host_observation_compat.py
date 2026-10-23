# -*- coding: utf-8 -*-
"""Retain the older public inventory's loaded-source ownership semantics."""

import csv
import importlib.util
from importlib import metadata
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from qwenpaw.plugins.dependency_usage import DependencyDeclaration
from qwenpaw.plugins import python_backend


@pytest.mark.parametrize("disk_state", ["deleted", "stat-denied"])
def test_older_inventory_retains_loaded_owner_without_rechecking_disk(
    tmp_path,
    monkeypatch,
    fresh_registry,
    disk_state,
):
    """Python 3.11 RECORD inventory includes missing and inaccessible files."""
    source = tmp_path / "site" / "legacy_observer_source.py"
    source.parent.mkdir()
    source.write_text("VALUE = 'really imported before disk change'\n")
    info = source.parent / "old_inventory_owner-1.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: old-inventory-owner\nVersion: 1.0\n",
    )
    (info / "RECORD").write_text(source.name + ",,\n")
    monkeypatch.setattr(sys, "path", [str(source.parent)])
    spec = importlib.util.spec_from_file_location(
        "legacy_observer_source",
        source,
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    assert module.VALUE == "really imported before disk change"

    def older_inventory(distribution):
        # The official 3.11 public property enumerates RECORD without exists().
        # This adapter covers valid fixture rows only, not the private parser.
        files = [
            metadata.PackagePath(row[0])
            for row in csv.reader(
                distribution.read_text("RECORD").splitlines(),
            )
        ]
        for path in files:
            path.dist = distribution
        return files

    monkeypatch.setattr(
        metadata.PathDistribution,
        "files",
        property(older_inventory),
    )
    # Scope the version to this backend's interpreter view, leaving the running
    # 3.13 pytest, metadata discovery and every original 22 control untouched.
    monkeypatch.setattr(
        python_backend,
        "sys",
        SimpleNamespace(
            **{**vars(sys), "version_info": (3, 11, 0, "final", 0)},
        ),
    )
    if disk_state == "deleted":
        source.unlink()
    assert [str(path) for path in metadata.PathDistribution(info).files] == [
        source.name,
    ]
    native_stat = Path.stat
    checks = []

    def source_stat(path, *args, **kwargs):
        if path == source:
            checks.append(path)
            if disk_state == "stat-denied":
                raise PermissionError("controlled loaded-source access denial")
        return native_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", source_stat)
    usage = fresh_registry.dependency_usage
    token = usage.declare(
        DependencyDeclaration("older-host", "fresh", (), None),
    )
    try:
        python_backend.PythonBackend.observe_host_dependencies(
            SimpleNamespace(source_path=tmp_path / "plugin"),
            usage,
            token,
        )
    finally:
        usage.withdraw(token)
    versions = {
        name: row["version"]
        for owner in usage.snapshot(None).uses
        if owner.origin == "host" and owner.snapshot is not None
        for name, row in owner.snapshot.distributions.items()
    }
    assert versions == {"old-inventory-owner": "1.0"}
    assert not checks, "The older public inventory does not restat its rows"
