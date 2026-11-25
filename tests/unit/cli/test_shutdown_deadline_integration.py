# -*- coding: utf-8 -*-
"""Process-level coverage for the composed CLI and Uvicorn shutdown budget."""

# pylint: disable=protected-access

import os
import signal
import socket
import subprocess
import sys
import textwrap
import threading
import time
from functools import partial
from pathlib import Path

import psutil
import pytest
from click.testing import CliRunner

from qwenpaw.cli import shutdown_cmd
from qwenpaw.plugins.channel_workers import ChannelDefinition
from tests.channel_support.process import alive
from tests.channel_support.sdk import make_channel


def test_app_lifespan_waits_for_channel_worker(tmp_path):
    key = "slow-shutdown"
    source = tmp_path / key
    marker = tmp_path / "worker.pid"
    make_channel(
        source,
        textwrap.dedent(
            """
            import os
            import threading
            import time
            from pathlib import Path
            from qwenpaw.plugins.channel_workers import ChannelDriver

            class Driver(ChannelDriver):
                async def start(self, ch):
                    marker = Path(ch.config["marker"])
                    marker.write_text(str(os.getpid()))
                    for index in range(3):
                        stop = threading.Event()
                        def run(stop=stop, index=index):
                            stop.wait()
                            time.sleep(4.25)
                            marker.with_suffix(f".{index}.exited").touch()
                        ch.resources.child().thread(run, stop=stop)
                    await ch.report_status("connected")

                async def send(self, ch, response):
                    raise AssertionError("Unexpected delivery during shutdown")
            """,
        ),
        ChannelDefinition(
            key,
            {"en": "Slow shutdown", "zh": "延时退出"},
            "driver:Driver",
            {"type": "object", "properties": {"marker": {"type": "string"}}},
            ("marker",),
            ("channel.generic.v1",),
        ),
        capabilities=["channels", "resources"],
    )
    script = textwrap.dedent(
        """
        import asyncio
        import sys
        from pathlib import Path
        from qwenpaw.app._app import app
        from qwenpaw.config.config import load_agent_config, save_agent_config

        async def run():
            source, marker = map(Path, sys.argv[1:])
            async with app.router.lifespan_context(app):
                await app.state.startup_ready.wait()
                ws = await app.state.multi_agent_manager.get_agent("default")
                config = load_agent_config("default")
                setattr(config.channels, source.name, {
                    "enabled": True, "marker": str(marker),
                })
                save_agent_config("default", config)
                ws._config = config
                await app.state.plugin_loader.load_plugin_from_path(source)
                await ws.channel_manager.start_one(source.name, config)
                assert marker.exists()
                channel = await ws.channel_manager.get_channel(source.name)
            assert channel.last_stop_result.acknowledged is True
            assert not channel.last_stop_result.forced

        asyncio.run(run())
        """,
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(source), str(marker)],
        env={
            **os.environ,
            "QWENPAW_WORKING_DIR": str(tmp_path / "app"),
            "QWENPAW_SECRET_DIR": str(tmp_path / "secrets"),
            "QWENPAW_BACKUP_DIR": str(tmp_path / "backups"),
            "QWENPAW_RUNNING_IN_CONTAINER": "true",
            "QWENPAW_TELEMETRY_DISABLED": "true",
        },
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert not alive(int(marker.read_text()))
    assert sorted(p.name for p in tmp_path.glob("*.exited")) == [
        "worker.0.exited",
        "worker.1.exited",
        "worker.2.exited",
    ]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal behavior")
@pytest.mark.parametrize("stalled", [False, True], ids=["graceful", "forced"])
def test_cli_waits_for_request_import_and_workspace_drains(
    tmp_path,
    monkeypatch,
    stalled,
):
    ready = tmp_path / "ready"
    request_started = tmp_path / "request_started"
    workspace_stopped = tmp_path / "workspace_stopped"
    worker_stopped = tmp_path / "worker_stopped"
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]

    script = textwrap.dedent(
        """
        import asyncio
        import sys
        from contextlib import asynccontextmanager
        from pathlib import Path

        import uvicorn
        from fastapi import FastAPI

        from qwenpaw.app._app import _stop_workspaces_after_dependents

        ready = Path(sys.argv[1])
        request_started = Path(sys.argv[2])
        workspace_stopped = Path(sys.argv[3])
        port = int(sys.argv[4])

        class ImportJobs:
            async def shutdown(self):
                if sys.argv[5] == "stalled":
                    await asyncio.Event().wait()
                await asyncio.sleep(0.7)
                return True

        class WorkspaceManager:
            def __init__(self, worker):
                self.worker = worker

            async def stop_all(self):
                await asyncio.sleep(0.7)
                await self.worker.communicate(input=b"stop")
                assert self.worker.returncode == 0
                workspace_stopped.write_text("stopped", encoding="utf-8")

        @asynccontextmanager
        async def lifespan(app):
            worker = await asyncio.create_subprocess_exec(
                sys.executable, "-c", sys.argv[6], sys.argv[7],
                stdin=asyncio.subprocess.PIPE, start_new_session=True,
            )
            app.state.multi_agent_manager = WorkspaceManager(worker)
            temp = ready.with_suffix(".tmp")
            temp.write_text(str(worker.pid), encoding="utf-8")
            temp.replace(ready)
            try:
                yield
            finally:
                await _stop_workspaces_after_dependents(
                    app, ImportJobs(), deadline_sec=2.0,
                )

        app = FastAPI(lifespan=lifespan)

        @app.get("/hold")
        async def hold():
            request_started.write_text("started", encoding="utf-8")
            await asyncio.Event().wait()

        uvicorn.run(
            app,
            host="127.0.0.1",
            port=port,
            timeout_graceful_shutdown=0.7,
        )
        """,
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(Path(__file__).resolve().parents[3] / "src"),
            env.get("PYTHONPATH", ""),
        ],
    )
    proc = subprocess.Popen(  # pylint: disable=consider-using-with
        [
            sys.executable,
            "-c",
            script,
            str(ready),
            str(request_started),
            str(workspace_stopped),
            str(port),
            "stalled" if stalled else "graceful",
            textwrap.dedent(
                """
                import signal
                import sys
                from pathlib import Path

                if sys.stdin.buffer.read() == b"stop":
                    Path(sys.argv[1]).touch()
                else:
                    signal.pause()
                """,
            ),
            str(worker_stopped),
        ],
        env=env,
        start_new_session=True,
    )
    held_socket = None
    worker = None
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not ready.exists():
            if proc.poll() is not None:
                pytest.fail(f"server exited early: {proc.returncode}")
            time.sleep(0.05)
        assert ready.exists()
        worker = psutil.Process(int(ready.read_text()))

        while time.monotonic() < deadline:
            try:
                held_socket = socket.create_connection(
                    ("127.0.0.1", port),
                    timeout=0.2,
                )
                break
            except OSError:
                time.sleep(0.05)
        assert held_socket is not None
        held_socket.sendall(b"GET /hold HTTP/1.1\r\nHost: localhost\r\n\r\n")
        while time.monotonic() < deadline and not request_started.exists():
            time.sleep(0.05)
        assert request_started.exists()

        assert alive(worker.pid)
        # Scope the CLI to the test listener on this machine.
        monkeypatch.setattr(shutdown_cmd, "_find_frontend_dev_pids", set)
        monkeypatch.setattr(shutdown_cmd, "_find_desktop_wrapper_pids", set)
        if stalled:
            monkeypatch.setattr(
                shutdown_cmd,
                "_terminate_pid",
                partial(shutdown_cmd._terminate_pid, timeout_sec=0.4),
            )
        reaper = threading.Thread(target=proc.wait, daemon=True)
        reaper.start()

        result = CliRunner().invoke(
            shutdown_cmd.shutdown_cmd,
            ["--port", str(port)],
        )
        assert result.exit_code == 0, result.output
        reaper.join(timeout=1)
        assert not alive(worker.pid)
        if stalled:
            assert proc.returncode == -signal.SIGKILL
            assert not worker_stopped.exists()
            assert not workspace_stopped.exists()
        else:
            assert proc.returncode in (0, -signal.SIGTERM)
            assert worker_stopped.exists()
            assert workspace_stopped.read_text(encoding="utf-8") == "stopped"
    finally:
        if held_socket is not None:
            held_socket.close()
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        if worker is not None and worker.is_running():
            try:
                worker.kill()
            except psutil.NoSuchProcess:
                pass
