# -*- coding: utf-8 -*-
# flake8: noqa: E501
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def test_dev_app_imports_in_a_cold_interpreter(tmp_path: Path) -> None:
    """A fresh process must not depend on a lucky prior import order."""

    environment = {
        **os.environ,
        "CREATOR_DATA_ROOT": str(tmp_path / "creator-data"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import dev_main; assert dev_main.app.title == 'QwenPaw-Creator Local Dev Backend'",
        ],
        cwd=Path(__file__).resolve().parents[2],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
