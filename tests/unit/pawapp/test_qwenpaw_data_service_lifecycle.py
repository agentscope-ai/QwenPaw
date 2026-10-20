# -*- coding: utf-8 -*-
"""Exercise the real supervisor and the Windows in-process module launcher."""

import sys
import textwrap
from dataclasses import replace
from pathlib import Path

import httpx
import psutil
import pytest

from qwenpaw.pawapp import PawApp

APP = Path(__file__).resolve().parents[3] / "plugins/apps/qwenpaw-data"


@pytest.mark.asyncio
@pytest.mark.parametrize("in_process", [False, True])
async def test_sidecar_retains_supervised_pid_and_stops_on_restart(
    tmp_path,
    monkeypatch,
    in_process,
):
    monkeypatch.syspath_prepend(str(APP))
    from backend import service_compat

    monkeypatch.setattr(service_compat, "APP_DATA_DIR", tmp_path)
    monkeypatch.setenv("UNGRANTED_SECRET", "host-only")
    host_modules = tmp_path / "host modules"
    host_modules.mkdir()
    monkeypatch.setenv("PYTHONPATH", str(host_modules))
    workdir = tmp_path / "service modules"
    workdir.mkdir()
    (workdir / "lifecycle_probe.py").write_text(
        textwrap.dedent(
            """\
            import json
            import os
            import sys
            from http.server import BaseHTTPRequestHandler, HTTPServer

            class Handler(BaseHTTPRequestHandler):
                def do_GET(self):
                    body = json.dumps({
                        "pid": os.getpid(),
                        "secret": os.environ.get("MODEL_SECRET"),
                        "host_secret": os.environ.get("UNGRANTED_SECRET"),
                        "paths": sys.path,
                        "args": sys.argv[1:],
                    }).encode()
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(body)

                def log_message(self, *args):
                    pass

            address = (sys.argv[1], int(sys.argv[2]))
            HTTPServer(address, Handler).serve_forever()
            """,
        ),
        encoding="utf-8",
    )
    model = {"MODEL_SECRET": "first"}
    service = service_compat.managed_service(
        PawApp(),
        "lifecycle",
        command=(
            sys.executable,
            "-m",
            "lifecycle_probe",
            "{host}",
            "{port}",
            "argument with spaces",
        ),
        cwd=workdir,
        env_factory=lambda: model,
        startup_timeout=10,
        shutdown_timeout=2,
    )
    if in_process:
        # Exercise the Windows execution path on every CI platform without
        # changing os.name or pretending this is a native Windows test.
        service.spec = replace(
            service.spec,
            command=(
                sys.executable,
                "-c",
                "import json,runpy,sys; "
                "entry=runpy.run_path(sys.argv[1]); "
                "environment=json.load(open(sys.argv[2], encoding='utf-8')); "
                "entry['run_module'](sys.argv[3:], environment)",
                *service.spec.command[1:],
            ),
        )
    async with httpx.AsyncClient(trust_env=False, timeout=2) as client:
        try:
            await service.start()
            first_url = service.base_url
            first = (await client.get(first_url)).json()
            assert first["pid"] == service.diagnostics()["pid"]
            assert first["secret"] == "first"
            assert first["host_secret"] is None
            assert str(host_modules) not in first["paths"]
            assert first["args"][-1] == "argument with spaces"
            model["MODEL_SECRET"] = "rotated"
            await service.restart()
            second_url = service.base_url
            second = (await client.get(second_url)).json()
            assert second["pid"] == service.diagnostics()["pid"]
            assert second["pid"] != first["pid"]
            assert second["secret"] == "rotated"
            assert not psutil.pid_exists(first["pid"])
            if first_url != second_url:
                with pytest.raises((httpx.ConnectError, httpx.ConnectTimeout)):
                    await client.get(first_url)
        finally:
            await service.stop()
        assert not service.is_ready
        assert not psutil.pid_exists(second["pid"])
        with pytest.raises((httpx.ConnectError, httpx.ConnectTimeout)):
            await client.get(second_url)
