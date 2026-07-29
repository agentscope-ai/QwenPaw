# -*- coding: utf-8 -*-
"""Tests for the plugin manifest's declared QwenPaw compatibility range."""

import json
from pathlib import Path

from packaging.version import Version

from qwenpaw._version_compat import check_plugin_version_compat
from qwenpaw.plugins.architecture import PluginManifest

_MANIFEST = (
    Path(__file__).resolve().parents[4]
    / "plugins"
    / "tool"
    / "computer-use"
    / "plugin.json"
)


def _manifest_range() -> tuple[str, str]:
    data = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    declared = data["qwenpaw_version"]
    return declared["min"], declared["max"]


def _manifest() -> PluginManifest:
    # The real manifest is the subject: a test fixture would pass while the
    # shipped file stays wrong.
    return PluginManifest(**json.loads(_MANIFEST.read_text(encoding="utf-8")))


def test_the_running_qwenpaw_is_inside_the_declared_range():
    # The loader disables a plugin whose range excludes the running version, so
    # this failing means the plugin ships dead on the current tree.
    compatible, message = check_plugin_version_compat(_manifest())
    assert compatible, message


def test_the_upper_bound_admits_the_release_this_lands_in():
    # The bound is exclusive and pre-releases compare as their base release, so
    # a max equal to the next minor locks the plugin out of that whole release
    # the moment its first beta is tagged -- which is how it lands on main.
    _, maximum = _manifest_range()
    from qwenpaw.__version__ import __version__ as current

    running = Version(current)
    base = (
        Version(f"{running.major}.{running.minor}.{running.micro}")
        if running.pre
        else running
    )
    assert base < Version(maximum), (
        f"max {maximum} excludes the running {current}: an exclusive bound "
        f"must sit above the release series being developed"
    )
