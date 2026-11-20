# -*- coding: utf-8 -*-
"""Console static serving and startup route priority."""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap


def _run_with_console(tmp_path, script):
    env = {
        **os.environ,
        "QWENPAW_CONSOLE_STATIC_DIR": str(tmp_path / "console"),
        "QWENPAW_WORKING_DIR": str(tmp_path / "work"),
        "QWENPAW_SECRET_DIR": str(tmp_path / "secrets"),
        "QWENPAW_AUTH_ENABLED": "false",
        "QWENPAW_TELEMETRY_DISABLED": "1",
    }
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


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

    _run_with_console(
        tmp_path,
        """
        from pathlib import Path
        from qwenpaw.app import _app

        endpoint = next(
            route.endpoint for route in _app.app.routes
            if getattr(route, "name", None) == "qwenpaw_console_spa_catchall"
        )
        root = Path(_app._CONSOLE_STATIC_DIR)
        for name in ("logo.svg", "public-link.svg"):
            assert Path(endpoint(name).path).resolve() == root / "logo.svg"
        assert Path(endpoint("private-link.svg").path) == root / "index.html"
        for name in ("../auth.json", "missing.svg", "directory", "loop.svg"):
            assert Path(endpoint(name).path) == root / "index.html"
        """,
    )


def test_startup_routes_skip_general_api_matching(tmp_path):
    console = tmp_path / "console"
    assets = console / "assets"
    assets.mkdir(parents=True)
    (assets / "entry.js").write_text("console.log('entry');")

    _run_with_console(
        tmp_path,
        """
        from unittest.mock import patch

        from fastapi.testclient import TestClient
        from starlette.routing import NoMatchFound

        from qwenpaw.app._app import app

        for route in app.routes:
            try:
                route.url_path_for("auth_status")
            except NoMatchFound:
                continue
            break
        else:
            raise AssertionError("Expected the auth status route")

        client = TestClient(app)
        with patch.object(
            route,
            "matches",
            side_effect=AssertionError("Startup routes should match first"),
        ):
            response = client.get("/assets/entry.js")
            assert response.status_code == 200
            assert response.text == "console.log('entry');"

            response = client.get("/api/healthz")
            assert response.status_code == 503
            assert response.json()["status"] == "starting"
        """,
    )
