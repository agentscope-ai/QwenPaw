# -*- coding: utf-8 -*-
"""Keep direct helper imports independent of plugin-loader module cleanup."""

import sys

import pytest

from . import _package

_MODULES = {}


def pytest_collection_finish():
    # Capture imported helper identities before earlier core test directories
    # load/unload the same real plugin and remove its source-root modules.
    _MODULES.update(
        {
            name: module
            for name, module in sys.modules.items()
            if name.startswith("mcp_plugin_under_test.")
        },
    )


@pytest.fixture(autouse=True)
def restore_transport_test_namespace():
    # Loader correctly removes source-root imports on unload. The low-level
    # suite retains its own helper objects, including monkeypatch targets;
    # restore those exact objects so lazy relative imports see the same ones.
    if not _MODULES:
        _MODULES.update(
            {
                name: module
                for name, module in sys.modules.items()
                if name.startswith("mcp_plugin_under_test.")
            },
        )
    sys.modules["mcp_plugin_under_test"] = _package
    sys.modules.update(_MODULES)
