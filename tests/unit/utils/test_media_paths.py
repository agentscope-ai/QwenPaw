# -*- coding: utf-8 -*-
"""File name extraction preserves POSIX names and explicit Windows paths."""

from types import SimpleNamespace

import pytest

from qwenpaw.utils import media_paths


@pytest.mark.parametrize("host", ["posix", "nt"])
@pytest.mark.parametrize(
    "path, expected",
    [
        (r"/tmp/invoice\real.png", r"invoice\real.png"),
        (r"C:\files\real.png", "real.png"),
        (r"\\server\share\real.png", "real.png"),
        (r".\dir\real.png", "real.png"),
        (r"..\dir\real.png", "real.png"),
        (r"file://C:\files\real.png", "real.png"),
        (r"file://\\server\share\real.png", "real.png"),
        ("file:///C:/files/real.png", "real.png"),
        ("file://server/share/real.png", "real.png"),
        ("file:///tmp/invoice%5Creal.png", r"invoice\real.png"),
    ],
)
def test_explicit_path_flavors_are_host_independent(
    monkeypatch,
    host,
    path,
    expected,
):
    monkeypatch.setattr(media_paths, "os", SimpleNamespace(name=host))
    assert media_paths.media_basename(path) == expected


@pytest.mark.parametrize(
    "host, expected",
    [("posix", r"invoice\real.png"), ("nt", "real.png")],
)
def test_ambiguous_relative_path_follows_host(monkeypatch, host, expected):
    monkeypatch.setattr(media_paths, "os", SimpleNamespace(name=host))
    assert media_paths.media_basename(r"invoice\real.png") == expected
