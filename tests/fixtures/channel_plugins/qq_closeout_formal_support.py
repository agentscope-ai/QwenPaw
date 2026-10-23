"""Authentic QQ bundle and original external Gateway/REST boundary."""

import importlib.abc
from pathlib import Path
import shutil
import sys

import pytest

pytest.register_assert_rewrite("qq_native_support")
from qq_native_support import external  # noqa: E402
from extension_process_suite import runtime  # noqa: E402

__all__ = ["external", "runtime", "qq_host_import_guard"]


@pytest.fixture(autouse=True)
def qq_host_import_guard(monkeypatch):
    prefixes = ("qwenpaw_channel_qq", "qwenpaw.app.channels.qq")

    def implementation(name):
        return any(name == p or name.startswith(p + ".") for p in prefixes)

    assert not any(implementation(name) for name in sys.modules)
    attempts = []

    class Guard(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if implementation(fullname):
                attempts.append(fullname)
                raise AssertionError("QQ implementation in host: " + fullname)

    monkeypatch.setattr(sys, "meta_path", [Guard(), *sys.meta_path])
    yield
    assert not attempts
    assert not any(implementation(name) for name in sys.modules)


def official_qq_zip(directory, key, **_ignored):
    from qwenpaw.plugins.official_channels import bundled_channel_source

    assert key == "qq"
    with bundled_channel_source("qq") as source:
        destination = Path(directory) / key
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination)
        assert {
            p.relative_to(source): p.read_bytes()
            for p in source.rglob("*")
            if p.is_file()
        } == {
            p.relative_to(destination): p.read_bytes()
            for p in destination.rglob("*")
            if p.is_file()
        }
    return destination
