# -*- coding: utf-8 -*-
"""Shared helpers for pawapp tests: load the QPD bridge package by path.

The plugin backend is not an installed package; the bridge subpackage
uses relative imports, so it must be registered as a real package for
its modules to import each other.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
BRIDGE_DIR = (
    REPOSITORY_ROOT
    / "plugins"
    / "apps"
    / "qwenpaw-data"
    / "backend"
    / "bridge"
)
_PKG = "qpd_bridge_under_test"


def load_bridge_module(name: str = ""):
    if _PKG not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            _PKG,
            BRIDGE_DIR / "__init__.py",
            submodule_search_locations=[str(BRIDGE_DIR)],
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[_PKG] = module
        spec.loader.exec_module(module)
    if not name:
        return sys.modules[_PKG]
    return importlib.import_module(f"{_PKG}.{name}")


@pytest.fixture(scope="session")
def bridge():
    return load_bridge_module()


@pytest.fixture(scope="session")
def bridge_events():
    return load_bridge_module("events")


@pytest.fixture(scope="session")
def bridge_engine_client():
    return load_bridge_module("engine_client")


@pytest.fixture(scope="session")
def bridge_middleware():
    return load_bridge_module("middleware")


@pytest.fixture(scope="session")
def bridge_commands():
    return load_bridge_module("commands")


@pytest.fixture(scope="session")
def bridge_session_store():
    return load_bridge_module("session_store")
