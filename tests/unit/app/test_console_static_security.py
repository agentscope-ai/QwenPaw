# -*- coding: utf-8 -*-
"""Console static serving enforces resolved filesystem containment."""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap


def test_console_static_symlinks_stay_within_build(tmp_path):
    console = tmp_path / "console"
    console.mkdir()
    (console / "index.html").write_text("console index")
    public = console / "logo.svg"
    public.write_text("public logo")
    private = tmp_path / "auth.json"
    private.write_text("private credentials")
    (console / "public-link.svg").symlink_to(public)
    (console / "private-link.svg").symlink_to(private)
    (console / "directory").mkdir()
    (console / "loop.svg").symlink_to("loop.svg")
    env = {
        **os.environ,
        "QWENPAW_CONSOLE_STATIC_DIR": str(console),
        "QWENPAW_WORKING_DIR": str(tmp_path / "work"),
        "QWENPAW_SECRET_DIR": str(tmp_path / "secrets"),
        "QWENPAW_TELEMETRY_DISABLED": "1",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                """
                from pathlib import Path
                from qwenpaw.app import _app

                endpoint = next(
                    route.endpoint for route in _app.app.routes
                    if getattr(route, "name", None)
                    == "qwenpaw_console_spa_catchall"
                )
                root = Path(_app._CONSOLE_STATIC_DIR)
                for name in ("logo.svg", "public-link.svg"):
                    assert Path(endpoint(name).path).resolve() == root / "logo.svg"
                assert Path(endpoint("private-link.svg").path) == root / "index.html"
                for name in ("../auth.json", "missing.svg", "directory", "loop.svg"):
                    assert Path(endpoint(name).path) == root / "index.html"

                """,
            ),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
