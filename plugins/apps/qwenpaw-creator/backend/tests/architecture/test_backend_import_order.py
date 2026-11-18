# -*- coding: utf-8 -*-
"""The backend must import in the order the plugin loader actually uses.

pytest reaches a module through whichever test file ran first, so a
module-level import can sit inside a cycle and the whole suite still pass.
Installation walks the chain from ``backend/main.py`` instead:
``api.router`` -> ``services.project_files.facade`` -> the package ``__init__``
-> ``agent_tools`` -> ``commit``. A cycle on that path fails before the plugin
registers its routes, leaving the UI with no routes and a stuck spinner.

Observed 2026-10-28: ``commit`` -> ``transaction_gc`` reached
``services.media_files`` (package init) -> ``r2v_execution`` ->
``project_files.facade`` -> ``commit``. That edge passed 1250 tests and then
broke plugin installation. Each entrypoint is
imported in a fresh interpreter, because a cycle only shows through the order
the first import happens in.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2]

ENTRYPOINTS = (
    # The plugin's own entry, then the chains it pulls in the loader's order.
    "main",
    "api.router",
    "services.project_files.facade",
    "services.file_agent_runtime.driver",
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("entrypoint", ENTRYPOINTS)
def test_backend_entrypoint_imports_without_a_cycle(entrypoint) -> None:
    result = subprocess.run(
        [sys.executable, "-c", f"import {entrypoint}"],
        cwd=BACKEND_DIR,
        env={**os.environ, "PYTHONPATH": str(BACKEND_DIR)},
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )

    assert result.returncode == 0, result.stderr[-4000:]
