# -*- coding: utf-8 -*-
"""Tests for the plugin manifest's declared QwenPaw compatibility range."""

import json
from pathlib import Path

from qwenpaw._version_compat import check_plugin_version_compat
from qwenpaw.plugins.architecture import PluginManifest

_MANIFEST = (
    Path(__file__).resolve().parents[4]
    / "plugins"
    / "bundle"
    / "computer-use"
    / "plugin.json"
)
_FRONTEND_BUNDLE = _MANIFEST.parent / "dist" / "index.js"


def _manifest() -> PluginManifest:
    # The real manifest is the subject: a test fixture would pass while the
    # shipped file stays wrong.
    return PluginManifest(**json.loads(_MANIFEST.read_text(encoding="utf-8")))


def test_built_frontend_embeds_the_manifest_version():
    version = json.loads(_MANIFEST.read_text(encoding="utf-8"))["version"]
    bundle = _FRONTEND_BUNDLE.read_text(encoding="utf-8")

    assert f'"{version}"' in bundle, (
        f"frontend bundle does not embed manifest version {version}; "
        "rebuild it with `npm run build`"
    )


def test_the_running_qwenpaw_is_inside_the_declared_range():
    # The loader disables a plugin whose range excludes the running version, so
    # this failing means the plugin ships dead on the current tree.
    compatible, message = check_plugin_version_compat(_manifest())
    assert compatible, message
