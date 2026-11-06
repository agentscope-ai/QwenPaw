# -*- coding: utf-8 -*-
"""Load the optional Data task adapter without installing a plugin."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_data_task_bridge():
    name = "qpd_task_bridge_under_test"
    if name not in sys.modules:
        directory = (
            Path(__file__).resolve().parents[1]
            / "plugins/apps/qwenpaw-data/backend/task_bridge"
        )
        spec = importlib.util.spec_from_file_location(
            name,
            directory / "__init__.py",
            submodule_search_locations=[str(directory)],
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]
