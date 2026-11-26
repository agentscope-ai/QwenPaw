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
from contextlib import contextmanager
from functools import partial
from http.client import HTTPConnection, HTTPException
from pathlib import Path

import psutil
import pytest
from click.testing import CliRunner

from qwenpaw.cli import shutdown_cmd
from qwenpaw.cli.shutdown_cmd import ShutdownOutcome
from qwenpaw.plugins.channel_workers import ChannelDefinition
from qwenpaw.process_ownership import (
    backend_instance,
    managed_launch,
    observe_backend,
)
from tests.channel_support.process import alive
from tests.channel_support.sdk import make_channel


def _make_shutdown_channel(source):
    key = source.name
    make_channel(
        source,
        textwrap.dedent(
            """
            import asyncio
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
                            due = self.stop_started + 15.5 - 4.25 * index
                            time.sleep(max(0, due - time.monotonic()))
                            marker.with_suffix(f".{index}.exited").write_text(
                                str(time.monotonic_ns()),
                            )
                        ch.resources.child().thread(run, stop=stop)
                    await ch.report_status("connected")

                async def send(self, ch, response):
                    raise AssertionError("Unexpected delivery during shutdown")

                async def stop(self, ch):
                    # Use one clock for the platform drain and ordered joins.
                    self.stop_started = time.monotonic()
                    marker = Path(ch.config["marker"])
                    marker.with_suffix(".stopping").write_text(
                        str(time.monotonic_ns()),
                    )
                    await asyncio.sleep(2.75)
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


def test_app_shutdown_drains_two_workers_after_another_crashes(tmp_path):
    sources = [tmp_path / key for key in ("crashed", "slow-one", "slow-two")]
    for source in sources:
        _make_shutdown_channel(source)
    script = textwrap.dedent(
        """
        import asyncio
        import sys
        from pathlib import Path
        from unittest.mock import AsyncMock
        import psutil
        from qwenpaw.app import _app
        from qwenpaw.app._app import app
        from qwenpaw.app.migration import ensure_default_agent_exists
        from qwenpaw.config.config import load_agent_config, save_agent_config
        from tests.channel_support.process import alive, eventually

        async def run():
            sources = list(map(Path, sys.argv[1:]))
            ensure_default_agent_exists()
            config = load_agent_config("default")
            for source in sources:
                setattr(config.channels, source.name, {
                    "enabled": True, "marker": str(source.with_suffix(".pid")),
                })
            save_agent_config("default", config)
            channels = []
            hooks = []
            async with app.router.lifespan_context(app):
                await app.state.startup_ready.wait()
                ws = await app.state.multi_agent_manager.get_agent("default")
                for source in sources:
                    await app.state.plugin_loader.load_plugin_from_path(source)
                    handle = await ws.channel_manager.start_one(
                        source.name, config,
                    )
                    channels.append(handle.channel)
                    async def before_shutdown(key=source.name):
                        for peer in sources:
                            live = await ws.channel_manager.get_channel(
                                peer.name,
                            )
                            assert live is not None
                            assert not peer.with_suffix(".stopping").exists()
                        hooks.append(key)
                    app.state.plugin_registry.register_shutdown_hook(
                        source.name, "before-stop", before_shutdown,
                    )
                pid = int(sources[0].with_suffix(".pid").read_text())
                psutil.Process(pid).kill()
                await eventually(lambda: not alive(pid))
                backups = app.state.backup_manager
                backups.shutdown = AsyncMock(wraps=backups.shutdown)
                workspaces = app.state.multi_agent_manager
                workspaces.stop_all = AsyncMock(wraps=workspaces.stop_all)
                browser_stop = AsyncMock(wraps=_app._stop_browser_runtime)
                _app._stop_browser_runtime = browser_stop
            backups.shutdown.assert_awaited_once()
            workspaces.stop_all.assert_awaited_once()
            browser_stop.assert_awaited_once_with(app)
            assert hooks == [s.name for s in sources]
            assert channels[0].last_stop_result.acknowledged is False
            for channel in channels[1:]:
                assert channel.last_stop_result.acknowledged is True
                assert not channel.last_stop_result.forced

        asyncio.run(run())
        """,
    )
    result = subprocess.run(
        [sys.executable, "-c", script, *map(str, sources)],
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
    for source in sources:
        assert not alive(int(source.with_suffix(".pid").read_text()))
    assert sorted(p.name for p in tmp_path.glob("*.exited")) == [
        f"{s.name}.{index}.exited" for s in sources[1:] for index in range(3)
    ]
    starts = [int(s.with_suffix(".stopping").read_text()) for s in sources[1:]]
    finishes = [
        int(s.with_suffix(".0.exited").read_text()) for s in sources[1:]
    ]
    assert max(starts) < min(finishes)


@contextmanager
def _orphan_backend(marker, mode, delay):
    script = Path(__file__).with_name("fixtures") / "orphan_backend.py"
    with subprocess.Popen(
        [sys.executable, script, "backend", mode, str(delay), marker],
        stdout=subprocess.PIPE,
        text=True,
    ) as backend:
        worker = None
        pid_file = marker.with_suffix(".pid")
        try:
            worker = psutil.Process(int(backend.stdout.readline()))
            yield backend, worker
        finally:
            if worker is not None and worker.is_running():
                try:
                    worker.kill()
                except psutil.NoSuchProcess:
                    pass
            if backend.poll() is None:
                backend.kill()
            if pid_file.exists() and alive(int(pid_file.read_text())):
                psutil.Process(int(pid_file.read_text())).kill()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX reparenting")
@pytest.mark.parametrize("stubborn", [False, True])
@pytest.mark.parametrize("mode", ["raw", "mixed", "sdk"])
def test_backend_exit_waits_for_orphaned_worker(
    tmp_path,
    monkeypatch,
    stubborn,
    mode,
):
    marker = tmp_path / "exited"
    with _orphan_backend(marker, mode, 60 if stubborn else 0.1) as pair:
        backend, worker = pair
        if mode == "mixed":
            terminate = psutil.Process.terminate

            def terminate_between_scans(proc):
                terminate(proc)
                # Schedule the middle worker's entire spawn-and-exit between
                # the initial snapshot and the first post-TERM CLI scan.
                if proc.pid == backend.pid:
                    deadline = time.monotonic() + 5
                    while alive(worker.pid) and time.monotonic() < deadline:
                        time.sleep(0.01)
                    assert not alive(worker.pid)

            monkeypatch.setattr(
                psutil.Process,
                "terminate",
                terminate_between_scans,
            )
        stopped = shutdown_cmd._terminate_pid(
            backend.pid,
            timeout_sec=2,
            process=backend,
            backend=True,
        )
        assert backend.returncode == -signal.SIGTERM
        assert not alive(worker.pid)
        leaf = int(marker.with_suffix(".pid").read_text())
        assert stopped is ShutdownOutcome.UNVERIFIED
        if mode == "sdk":
            assert not alive(leaf)
            assert marker.exists() == (not stubborn)
        elif mode == "mixed" and stubborn:
            assert alive(leaf)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX reparenting")
def test_shutdown_only_reaps_sessions_of_the_target_backend(tmp_path):
    with _orphan_backend(tmp_path / "other", "sdk", 0.1) as other:
        with _orphan_backend(tmp_path / "target", "sdk", 60) as target:
            backend, _ = target
            result = shutdown_cmd._terminate_pid(
                backend.pid,
                timeout_sec=1,
                process=backend,
                backend=True,
            )
            assert result is ShutdownOutcome.UNVERIFIED
            leaf = int((tmp_path / "target.pid").read_text())
            assert not alive(leaf)
        backend, worker = other
        assert backend.poll() is None
        assert alive(worker.pid)
        result = shutdown_cmd._terminate_pid(
            backend.pid,
            timeout_sec=2,
            process=backend,
            backend=True,
        )
        assert result is ShutdownOutcome.UNVERIFIED
        assert (tmp_path / "other").exists()


@pytest.mark.skipif(
    os.name == "nt" or sys.version_info < (3, 11),
    reason="POSIX Popen process_group support",
)
def test_incomplete_launch_blocks_receipt_for_an_empty_group():
    root = psutil.Process()
    with backend_instance(), observe_backend(root) as ownership:
        options = {"process_group": 0}
        with managed_launch(options) as started:
            with subprocess.Popen(
                [sys.executable, "-c", "import sys; sys.stdin.read()"],
                stdin=subprocess.PIPE,
                **options,
            ) as child:
                try:
                    started(child.pid)
                    member = psutil.Process(child.pid)
                    assert ownership.members({}) == ({member}, True)
                    # A prior generation with this PGID owns no live members.
                    stale = {child.pid: member.create_time() - 1}
                    assert ownership._live_members({}, stale, {}) == (
                        set(),
                        True,
                    )
                finally:
                    child.communicate(input=b"")
        with managed_launch({"start_new_session": True}):
            assert ownership.members({}) == (set(), False)
        assert ownership.members({}) == (set(), False)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX reload supervisor")
@pytest.mark.parametrize("crash", [False, True], ids=["graceful", "crash"])
def test_cli_shuts_down_ready_reload_server(tmp_path, monkeypatch, crash):
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    watch_dir = tmp_path / "source"
    watch_dir.mkdir()
    log = tmp_path / "server.log"
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            [
                str(Path(__file__).resolve().parents[3] / "src"),
                os.environ.get("PYTHONPATH", ""),
            ],
        ),
        "QWENPAW_WORKING_DIR": str(tmp_path / "app"),
        "QWENPAW_SECRET_DIR": str(tmp_path / "secrets"),
        "QWENPAW_BACKUP_DIR": str(tmp_path / "backups"),
        "QWENPAW_RUNNING_IN_CONTAINER": "true",
        "QWENPAW_TELEMETRY_DISABLED": "true",
    }
    # Only the listener on our reserved port belongs to this test.
    monkeypatch.setattr(shutdown_cmd, "_find_frontend_dev_pids", set)
    monkeypatch.setattr(shutdown_cmd, "_find_desktop_wrapper_pids", set)
    with log.open("wb") as output, subprocess.Popen(
        [
            sys.executable,
            "-m",
            "qwenpaw",
            "app",
            "--reload",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=watch_dir,
        env=env,
        stdout=output,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    ) as supervisor:
        try:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline and supervisor.poll() is None:
                conn = HTTPConnection("127.0.0.1", port, timeout=1)
                try:
                    conn.request("GET", "/api/healthz")
                    if conn.getresponse().status == 200:
                        break
                except (OSError, HTTPException):
                    pass
                finally:
                    conn.close()
                time.sleep(0.1)
            else:
                pytest.fail(log.read_text(errors="replace"))
            listeners = shutdown_cmd._listening_pids_for_port(port)
            assert supervisor.pid in listeners
            services = [
                psutil.Process(p) for p in listeners - {supervisor.pid}
            ]
            assert len(services) == 1
            if crash:
                terminate = psutil.Process.terminate

                def crash_at_shutdown(proc):
                    if proc.pid == supervisor.pid:
                        services[0].kill()
                    terminate(proc)

                monkeypatch.setattr(
                    psutil.Process,
                    "terminate",
                    crash_at_shutdown,
                )
            result = CliRunner().invoke(
                shutdown_cmd.shutdown_cmd,
                ["--port", str(port)],
            )
            assert result.exit_code == (3 if crash else 0), result.output
            if crash:
                assert "Unable to verify shutdown" in result.output
            assert supervisor.wait(timeout=2) == 0
            assert not services[0].is_running()
            assert shutdown_cmd._listening_pids_for_port(port) == set()
        finally:
            # The supervisor and serving child share this test-only group.
            if supervisor.poll() is None:
                try:
                    os.killpg(supervisor.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


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
        from qwenpaw.process_ownership import backend_instance, managed_launch

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
            with backend_instance():
                async with serving(app):
                    yield

        @asynccontextmanager
        async def serving(app):
            options = {"start_new_session": True}
            with managed_launch(options) as started:
                worker = await asyncio.create_subprocess_exec(
                    sys.executable, "-c", sys.argv[6], sys.argv[7],
                    stdin=asyncio.subprocess.PIPE, **options,
                )
                started(worker.pid)
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
        assert result.exit_code == (3 if stalled else 0), result.output
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
