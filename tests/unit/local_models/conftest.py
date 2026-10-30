# -*- coding: utf-8 -*-
"""Run the existing component tests against the shipped plugin source."""
# Load the standalone source under a stable name for component tests.
# pylint: disable=wrong-import-position,wrong-import-order,protected-access
import sys
import importlib.util
import atexit
from pathlib import Path

import pytest

source = (
    Path(__file__).resolve().parents[3] / "plugins/provider/local-llamacpp"
)
spec = importlib.util.spec_from_file_location(
    "llamacpp",
    source / "__init__.py",
    submodule_search_locations=[str(source)],
)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

from llamacpp.llamacpp import LlamaCppBackend  # noqa: E402
from llamacpp.model_manager import ModelManager  # noqa: E402


@pytest.fixture(autouse=True)
def local_data(monkeypatch, tmp_path):
    backends = []
    for component in (LlamaCppBackend, ModelManager):
        original = component.__init__

        def initialize(self, _original=original, **kwargs):
            kwargs.setdefault("data_dir", tmp_path)
            _original(self, **kwargs)
            if isinstance(self, LlamaCppBackend):
                backends.append(self)

        monkeypatch.setattr(component, "__init__", initialize)
    yield
    for backend in backends:
        atexit.unregister(backend._shutdown_server_at_exit)
