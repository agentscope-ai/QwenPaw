# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Shared plugin test isolation."""

import pytest

from qwenpaw.plugins.registry import PluginRegistry


@pytest.fixture()
def fresh_registry():
    """Reset the singleton and restore it even if a test fails."""
    old = PluginRegistry._instance
    PluginRegistry._instance = None
    try:
        yield PluginRegistry()
    finally:
        PluginRegistry._instance = old
