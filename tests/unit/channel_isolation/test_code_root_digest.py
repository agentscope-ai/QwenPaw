# -*- coding: utf-8 -*-
"""Source integrity remains independent of host metadata and Python caches."""

from pathlib import PureWindowsPath

import pytest

from qwenpaw.channel_protocol.artifacts import code_root_digest
from qwenpaw.channel_protocol.errors import ArtifactValidationError
from qwenpaw.plugins.execution import bootstrap


@pytest.mark.parametrize("path_order", ["native", "windows"])
def test_worker_digest_matches_host_for_case_and_nested_paths(
    tmp_path,
    monkeypatch,
    path_order,
):
    for name, content in {
        "Z.py": "upper\n",
        "a.py": "lower\n",
        "pkg.py": "module\n",
        "pkg/driver.py": "nested\n",
    }.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8"))

    if path_order == "windows":
        # Only emulate Path comparison; real traversal, relative names, and
        # file reads still run through the production hashing implementation.
        def windows_sorted(paths, *, key=None, reverse=False):
            return sorted(
                paths,
                key=key if key is not None else PureWindowsPath,
                reverse=reverse,
            )

        monkeypatch.setattr(bootstrap, "sorted", windows_sorted, raising=False)

    host_digest = code_root_digest(tmp_path)
    # Fixed canonical framing also protects the existing host digest format.
    assert host_digest == (
        "f5793dad985bd48ad1523cfc905deecfcc2dca15fee7e02204e7b8dc37531b2b"
    )
    assert bootstrap._hash_code_root(tmp_path) == host_digest


@pytest.mark.parametrize(
    "cache_name",
    ["nested/__pycache__/driver.cpython-313.pyc", "nested/driver.pyc"],
)
def test_worker_digest_ignores_python_caches_like_host(tmp_path, cache_name):
    (tmp_path / "driver.py").write_text("VALUE = 1\n", encoding="utf-8")
    initial = code_root_digest(tmp_path)
    assert bootstrap._hash_code_root(tmp_path) == initial
    cache = tmp_path / cache_name
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"compiled")

    assert code_root_digest(tmp_path) == initial
    assert bootstrap._hash_code_root(tmp_path) == initial


@pytest.mark.parametrize("change", ["content", "filename"])
def test_worker_digest_still_detects_source_changes(tmp_path, change):
    source = tmp_path / "driver.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    initial = code_root_digest(tmp_path)
    if change == "content":
        source.write_text("VALUE = 2\n", encoding="utf-8")
    else:
        source.rename(tmp_path / "renamed.py")

    changed = code_root_digest(tmp_path)
    assert changed != initial
    assert bootstrap._hash_code_root(tmp_path) == changed


def test_digest_ignores_only_requested_metadata_and_python_caches(tmp_path):
    (tmp_path / "driver.py").write_text("VALUE = 1\n")
    initial = code_root_digest(tmp_path)
    (tmp_path / ".qwenpaw-pawport.json").write_text('{"captured": true}')
    (tmp_path / "driver.pyc").write_bytes(b"compiled")
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "driver.cpython-313.pyc").write_bytes(b"cached")

    assert (
        code_root_digest(
            tmp_path,
            ignored_paths=(".qwenpaw-pawport.json",),
        )
        == initial
    )
    assert code_root_digest(tmp_path) != initial
    (tmp_path / "driver.py").write_text("VALUE = 2\n")
    assert (
        code_root_digest(
            tmp_path,
            ignored_paths=(".qwenpaw-pawport.json",),
        )
        != initial
    )


@pytest.mark.parametrize("kind", ["file", "directory", "dangling"])
def test_digest_rejects_symlinks_even_when_path_is_ignored(tmp_path, kind):
    root = tmp_path / "code"
    root.mkdir()
    target = tmp_path / "target"
    if kind == "directory":
        target.mkdir()
    elif kind == "file":
        target.write_text("outside")
    (root / "link").symlink_to(target, target_is_directory=kind == "directory")

    with pytest.raises(ArtifactValidationError, match="symlinks"):
        code_root_digest(root, ignored_paths=("link",))
