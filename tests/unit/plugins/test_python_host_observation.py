# -*- coding: utf-8 -*-
"""Fresh installed metadata must attest actual loaded host dependencies."""

import csv
import importlib.util
from importlib.metadata import PathDistribution
import io
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from qwenpaw.plugins.dependency_usage import DependencyDeclaration
from qwenpaw.plugins.python_backend import PythonBackend


def _record(*rows):
    output = io.StringIO()
    csv.writer(output).writerows(rows)
    return output.getvalue()


@pytest.fixture(name="host")
def host_fixture(tmp_path, monkeypatch, fresh_registry):
    """Bound actual metadata discovery while publishing real usage evidence."""
    site = tmp_path / "site"
    site.mkdir()
    # Use a real, bounded installed environment; no inventory result is mocked.
    monkeypatch.setattr(sys, "path", [str(site)])
    usage = fresh_registry.dependency_usage
    observations = []

    def metadata(name="observer-owner", *, record=None, top="observer_module"):
        info = site / (name.replace("-", "_") + "-1.0.dist-info")
        info.mkdir(exist_ok=True)
        (info / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n",
        )
        (info / "top_level.txt").write_text(top + "\n")
        if record is not None:
            (info / "RECORD").write_text(record)
        return info

    def load(path, name="observer_module"):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        assert Path(module.__file__).absolute() == Path(path).absolute()
        return module

    def observe():
        plugin = f"observer-{len(observations)}"
        token = usage.declare(DependencyDeclaration(plugin, "fresh", (), None))
        observations.append(token)
        try:
            PythonBackend.observe_host_dependencies(
                SimpleNamespace(source_path=tmp_path / "plugin"),
                usage,
                token,
            )
        finally:
            usage.withdraw(token)
        return tuple(
            use
            for use in usage.snapshot(None).uses
            if use.origin == "host" and use.plugin_id == plugin
        )

    return SimpleNamespace(
        site=site,
        metadata=metadata,
        load=load,
        observe=observe,
    )


def _versions(observed):
    return {
        name: row["version"]
        for use in observed
        if use.snapshot is not None
        for name, row in use.snapshot.distributions.items()
    }


@pytest.fixture(name="public_inventory")
def public_inventory_fixture():
    """Use the supported interpreter's public inventory as a small oracle."""

    def listed(info, filename):
        return any(
            str(path) == filename
            for path in PathDistribution(info).files or ()
        )

    return listed


def test_host_ownership_ignores_unloaded_inventory_without_stating_it(
    host,
    monkeypatch,
):
    """Loaded ownership must avoid touching unrelated installed assets."""
    loaded = host.site / "observer_module.py"
    loaded.write_text("VALUE = 'loaded'\n")
    unrelated = [host.site / f"unused_{number}.py" for number in range(256)]
    for path in unrelated:
        path.write_text("VALUE = 'not imported'\n")
    host.metadata(
        record=_record(
            (loaded.name, "", ""),
            *((path.name, "", "") for path in unrelated),
        ),
    )
    host.load(loaded)
    native_stat = Path.stat
    visited = []
    inventory = set(unrelated)

    def count_inventory_stat(path, *args, **kwargs):
        if path in inventory:
            visited.append(path)
        return native_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", count_inventory_stat)
    assert _versions(host.observe()) == {"observer-owner": "1.0"}
    count = len(visited)
    assert (
        count <= 1
    ), f"Host ownership stated {count} unloaded inventory files"


@pytest.mark.parametrize(
    "record_name,expected",
    [
        ("alias.py", True),
        ("../outside/actual.py", True),
        ("nested/../alias.py", True),
        ("absolute", False),
    ],
)
def test_record_preserves_lexical_resolved_and_relative_origin_membership(
    host,
    tmp_path,
    public_inventory,
    record_name,
    expected,
):
    """Inventory membership must preserve both imported symlink origins."""
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "actual.py"
    target.write_text("VALUE = 'symlinked source'\n")
    link = host.site / "alias.py"
    link.symlink_to(target)
    (host.site / "nested").mkdir()
    filename = str(target) if record_name == "absolute" else record_name
    info = host.metadata(record=_record((filename, "", "")))
    host.load(link)
    assert bool(_versions(host.observe())) is expected
    if expected:
        assert _versions(host.observe()) == {"observer-owner": "1.0"}
    target.unlink()
    if expected and public_inventory(info, filename):
        assert _versions(host.observe()) == {"observer-owner": "1.0"}
    else:
        assert not host.observe(), "The public inventory excludes this origin"


@pytest.mark.parametrize("hash_value,size", [("not-a-hash", "-1"), ("", "")])
def test_record_csv_filename_and_existing_permissive_fields_keep_ownership(
    host,
    hash_value,
    size,
):
    """Quoted filenames and permissive stdlib fields retain current meaning."""
    path = host.site / "comma,name.py"
    path.write_text("VALUE = 'CSV filename'\n")
    host.metadata(record=_record((path.name, hash_value, size)))
    host.load(path)
    assert _versions(host.observe()) == {"observer-owner": "1.0"}


@pytest.mark.parametrize(
    "inventory,expected",
    [
        ("absent", True),
        ("empty", True),
        ("missing-record", False),
        ("sources", True),
        ("missing-sources", False),
        ("installed-files", True),
    ],
)
def test_absent_and_empty_existing_inventory_keep_distinct_fallbacks(
    host,
    inventory,
    expected,
):
    """Absent inventory may infer ownership from a top-level module origin."""
    path = host.site / "observer_module.py"
    path.write_text("VALUE = 'legacy source'\n")
    record = {
        "empty": "",
        "missing-record": _record(("missing.py", "", "")),
    }.get(inventory)
    info = host.metadata(record=record)
    if inventory in {"sources", "missing-sources"}:
        filename = path.name if inventory == "sources" else "missing.py"
        (info / "SOURCES.txt").write_text(filename + "\n")
    if inventory == "installed-files":
        (info / "installed-files.txt").write_text("../" + path.name + "\n")
    host.load(path)
    assert bool(_versions(host.observe())) is expected


@pytest.mark.parametrize(
    "bad_row",
    [
        ("unused.py", "", "not-an-integer"),
        ("unused.py", "", "", "extra-column"),
    ],
)
@pytest.mark.parametrize("bad_distribution", [False, True])
def test_later_malformed_record_row_cannot_publish_clean_host_evidence(
    host,
    bad_row,
    bad_distribution,
):
    """A matched early row cannot hide malformed later inventory evidence."""
    path = host.site / "observer_module.py"
    path.write_text("VALUE = 'matched before malformed row'\n")
    first = (path.name, "", "")
    record = _record(first) if bad_distribution else _record(first, bad_row)
    host.metadata(record=record)
    if bad_distribution:
        host.metadata(
            "unrelated-broken",
            record=_record(bad_row),
            top="unused",
        )
    host.load(path)
    (unknown,) = host.observe()
    assert unknown.environment is None
    assert unknown.snapshot is None


@pytest.mark.parametrize(
    "denied",
    ["unloaded", "loaded", "record-read-error", "record-permission"],
)
def test_only_unloaded_asset_stat_errors_are_irrelevant_to_host_ownership(
    host,
    monkeypatch,
    public_inventory,
    denied,
):
    """Actual origin and unsuppressed read failures must remain unknown."""
    loaded, unused = host.site / "observer_module.py", host.site / "unused.py"
    loaded.write_text("VALUE = 'loaded'\n")
    unused.write_text("VALUE = 'unloaded'\n")
    info = host.metadata(
        record=_record((loaded.name, "", ""), (unused.name, "", "")),
    )
    host.load(loaded)
    native_stat, native_open = Path.stat, Path.open

    def guarded_stat(path, *args, **kwargs):
        target = unused if denied == "unloaded" else loaded
        if denied in {"unloaded", "loaded"} and path == target:
            raise PermissionError("controlled installed-file access failure")
        return native_stat(path, *args, **kwargs)

    def guarded_open(path, *args, **kwargs):
        if path == info / "RECORD":
            if denied == "record-read-error":
                raise OSError("controlled inventory I/O failure")
            if denied == "record-permission":
                # PathDistribution.read_text treats this as absent metadata.
                raise PermissionError("controlled inventory read permission")
        return native_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", guarded_stat)
    monkeypatch.setattr(Path, "open", guarded_open)
    expected = (
        "owner" if denied in {"unloaded", "record-permission"} else "unknown"
    )
    if denied == "loaded":
        try:
            expected = (
                "owner" if public_inventory(info, loaded.name) else "no-owner"
            )
        except PermissionError:
            expected = "unknown"
    observed = host.observe()
    if expected == "owner":
        versions = _versions(observed)
        assert versions == {"observer-owner": "1.0"}
    elif expected == "no-owner":
        assert not observed
    else:
        (unknown,) = observed
        assert unknown.environment is None
        assert unknown.snapshot is None


def test_host_observation_refreshes_record_metadata_and_loaded_origins(
    host,
    monkeypatch,
    public_inventory,
):
    """Inventory, versions, imports and file existence are fresh each time."""
    first, later = host.site / "observer_module.py", host.site / "later.py"
    first.write_text("VALUE = 'first'\n")
    later.write_text("VALUE = 'later'\n")
    info = host.metadata(record=_record((first.name, "", "")))
    host.load(first)
    assert _versions(host.observe()) == {"observer-owner": "1.0"}
    (info / "RECORD").write_text(_record((later.name, "", "")))
    assert not host.observe(), "Fresh RECORD must exclude the former filename"
    host.load(later, "observer_later")
    (info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: observer-owner\nVersion: 2.0\n",
    )
    assert _versions(host.observe()) == {"observer-owner": "2.0"}
    monkeypatch.delitem(sys.modules, "observer_later")
    assert not host.observe(), "An unimported module cannot keep ownership"
    host.load(later, "observer_later")
    later.unlink()
    if public_inventory(info, later.name):
        assert _versions(host.observe()) == {"observer-owner": "2.0"}
    else:
        assert not host.observe(), "The public inventory excludes this origin"
