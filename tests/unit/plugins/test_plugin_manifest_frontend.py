# -*- coding: utf-8 -*-
"""Tests for frontend plugin host-module declarations."""

from qwenpaw.plugins.architecture import PluginManifest


def test_manifest_preserves_frontend_host_modules() -> None:
    """Frontend host modules should survive manifest validation."""
    manifest = PluginManifest.from_dict(
        {
            "id": "frontend-plugin",
            "version": "1.0.0",
            "entry": {
                "frontend": "dist/index.js",
                "host_modules": ["Chat/OptionsPanel/defaultConfig"],
            },
        },
    )

    assert manifest.entry.host_modules == [
        "Chat/OptionsPanel/defaultConfig",
    ]
