# -*- coding: utf-8 -*-
"""Terminal shutdown receipts through real process and lifecycle boundaries."""

import json
import os
import subprocess
import sys
import textwrap
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import psutil
import pytest
from click.testing import CliRunner

from qwenpaw import process_ownership as ownership
from qwenpaw.cli import shutdown_cmd
from qwenpaw.cli.shutdown_cmd import ShutdownOutcome, _terminate_pid
from qwenpaw.plugins.channel_workers import ChannelDefinition
from tests.channel_support.sdk import make_channel

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX receipts")


@pytest.mark.parametrize("timeout", [False, True])
def test_final_receipt_seals_and_drains_launches(monkeypatch, timeout):
    backend = ownership.backend_instance()
    backend.__enter__()
    root = psutil.Process()
    gate = ownership._directory() / ownership._instance(root)
    admitted = threading.Event()
    release = threading.Event()
    options = {"start_new_session": True}
    if timeout:
        monkeypatch.setattr(ownership, "SERVER_EXIT_SECONDS", 0.1)

    def launch():
        with ownership.managed_launch(options) as started:
            admitted.set()
            assert release.wait(5)
            with subprocess.Popen(
                [sys.executable, "-c", "pass"],
                **options,
            ) as child:
                started(child.pid)

    with ownership.observe_backend(
        root,
    ) as observer, ThreadPoolExecutor() as pool:
        worker = pool.submit(launch)
        try:
            assert admitted.wait(5)
            monkeypatch.setenv(
                ownership._OWNER,
                options["env"][ownership._OWNER],
            )
            closing = pool.submit(backend.__exit__, None, None, None)
            deadline = time.monotonic() + 5
            while gate.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert not gate.exists()
            assert observer.members(set()) == (set(), False)
            assert not observer.closed
            if timeout:
                closing.result(timeout=2)
            else:
                assert not closing.done()
            with pytest.raises(FileNotFoundError):
                with ownership.managed_launch({"start_new_session": True}):
                    pytest.fail(
                        "A new launch passed the sealed admission gate",
                    )
        finally:
            release.set()
        worker.result(timeout=5)
        closing.result(timeout=5)
        assert observer.members(set()) == (set(), True)
        assert observer.closed is (not timeout)
        with pytest.raises(FileNotFoundError):
            with ownership.managed_launch({"start_new_session": True}):
                pytest.fail("Inherited ownership reopened the ended backend")


def test_live_registered_process_prevents_final_receipt():
    root = psutil.Process()
    backend = ownership.backend_instance()
    backend.__enter__()
    options = {"start_new_session": True}
    with ownership.observe_backend(root) as receipt:
        with ownership.managed_launch(options) as started:
            child = subprocess.Popen(
                [sys.executable, "-c", "import sys; sys.stdin.read()"],
                stdin=subprocess.PIPE,
                **options,
            )
            started(child.pid)
        try:
            backend.__exit__(None, None, None)
            assert receipt.members(set()) == (
                {psutil.Process(child.pid)},
                True,
            )
            assert not receipt.closed
        finally:
            child.communicate(input=b"")


def test_backend_exiting_after_poll_is_reaped(tmp_path, monkeypatch):
    stopping = tmp_path / "stopping"
    script = textwrap.dedent(
        """
        import signal
        import sys
        from pathlib import Path
        from qwenpaw.process_ownership import backend_instance

        stopping = Path(sys.argv[1])
        signal.signal(signal.SIGTERM, lambda *_: stopping.touch())
        with backend_instance() as record_failure:
            print("ready", flush=True)
            sys.stdin.read()
            record_failure()
        sys.exit(1)
        """,
    )
    with subprocess.Popen(
        [sys.executable, "-c", script, str(stopping)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    ) as backend:
        assert backend.stdout.readline().strip() == "ready"
        root = psutil.Process(backend.pid)
        poll = backend.poll

        def exit_after_poll():
            code = poll()
            if code is None and stopping.exists():
                # Let the child exit just after this waitpid observation.
                backend.stdin.close()
                deadline = time.monotonic() + 5
                while root.status() != psutil.STATUS_ZOMBIE:
                    assert time.monotonic() < deadline
                    time.sleep(0.01)
            return code

        monkeypatch.setattr(backend, "poll", exit_after_poll)
        with ownership.observe_backend(root) as receipt:
            result = _terminate_pid(
                root.pid,
                process=backend,
                backend=True,
            )
            assert result is ShutdownOutcome.FAILED
            assert receipt.members(set()) == (set(), True)
            assert (receipt.failed, receipt.closed) == (True, False)
            assert backend.returncode == 1


@pytest.mark.parametrize("survivor", [False, True])
def test_corrupt_journal_does_not_skip_known_processes(monkeypatch, survivor):
    script = textwrap.dedent(
        """
        import signal
        import subprocess
        import sys
        from qwenpaw.process_ownership import backend_instance, managed_launch

        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        with backend_instance():
            options = {"start_new_session": True}
            with managed_launch(options) as started:
                child = subprocess.Popen(
                    [sys.executable, "-c", "import signal; signal.pause()"],
                    **options,
                )
                started(child.pid)
            print(child.pid, flush=True)
            while True:
                signal.pause()
        """,
    )
    with subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        text=True,
    ) as backend:
        child = None
        try:
            child = psutil.Process(int(backend.stdout.readline()))
            root = psutil.Process(backend.pid)
            path = ownership._directory() / ownership._instance(root)
            with path.open("ab") as journal:
                journal.write(b'["truncated"')
            if survivor:
                kill = psutil.Process.kill

                def deny_root(proc):
                    if proc == root:
                        raise psutil.AccessDenied(proc.pid)
                    kill(proc)

                monkeypatch.setattr(psutil.Process, "kill", deny_root)
            result = _terminate_pid(
                root.pid,
                timeout_sec=0.1,
                process=backend,
                backend=True,
            )
            assert result is (
                ShutdownOutcome.FAILED
                if survivor
                else ShutdownOutcome.UNVERIFIED
            )
            assert (backend.poll() is None) is survivor
            assert (
                not child.is_running()
                or child.status() == psutil.STATUS_ZOMBIE
            )
        finally:
            if backend.poll() is None:
                backend.kill()
                backend.wait(timeout=5)
            if child is not None and child.is_running():
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
            if child is not None:
                path.unlink(missing_ok=True)


@pytest.mark.parametrize("failure", ["workspace", "hook", "channel"])
def test_failure_is_reported_after_independent_services_close(
    tmp_path,
    monkeypatch,
    failure,
):
    ready = tmp_path / "ready"
    plugin = tmp_path / "checkpointer"
    if failure == "channel":
        make_channel(
            plugin,
            textwrap.dedent(
                """
                from pathlib import Path
                from qwenpaw.plugins.channel_workers import ChannelDriver

                class Driver(ChannelDriver):
                    async def start(self, ch):
                        await ch.report_status("connected")

                    async def send(self, ch, response):
                        raise AssertionError("Unexpected delivery")

                    async def stop(self, ch):
                        Path(ch.config["marker"]).touch()
                        raise OSError("checkpoint write failed")
                """,
            ),
            ChannelDefinition(
                plugin.name,
                {"en": "Checkpointer", "zh": "检查点"},
                "driver:Driver",
                {
                    "type": "object",
                    "properties": {"marker": {"type": "string"}},
                },
                ("marker",),
                ("channel.generic.v1",),
            ),
            capabilities=["channels"],
        )
    if failure == "hook":
        plugin.mkdir()
        (plugin / "plugin.json").write_text(
            json.dumps(
                {
                    "id": "checkpointer",
                    "version": "1.0.0",
                    "entry": {"backend": "main.py"},
                },
            ),
            encoding="utf-8",
        )
        (plugin / "main.py").write_text(
            textwrap.dedent(
                """
                import os
                from pathlib import Path

                class Plugin:
                    def register(self, api):
                        def flush():
                            Path(os.environ["CHECKPOINT_MARKER"]).touch()
                            raise OSError("checkpoint write failed")
                        api.register_shutdown_hook("flush-checkpoint", flush)

                plugin = Plugin()
                """,
            ),
            encoding="utf-8",
        )
    script = textwrap.dedent(
        """
        import asyncio
        import signal
        import sys
        from pathlib import Path
        from qwenpaw.app import _app
        from qwenpaw.app.migration import ensure_default_agent_exists
        from qwenpaw.config.config import load_agent_config, save_agent_config
        from qwenpaw.plugins.lifecycle import QuiescenceError

        ready = Path(sys.argv[1])
        failure = sys.argv[2]

        async def main():
            stop = asyncio.Event()
            loop = asyncio.get_running_loop()
            loop.add_signal_handler(signal.SIGTERM, stop.set)
            if failure == "channel":
                ensure_default_agent_exists()
                config = load_agent_config("default")
                config.channels.checkpointer = {
                    "enabled": True,
                    "marker": str(ready.with_suffix(".called")),
                }
                save_agent_config("default", config)
            async with _app.lifespan(_app.app):
                await _app.app.state.startup_ready.wait()
                if failure in {"channel", "hook"}:
                    loader = _app.app.state.plugin_loader
                    await loader.load_plugin_from_path(
                        ready.parent / "checkpointer",
                    )
                workspaces = _app.app.state.multi_agent_manager
                if failure == "channel":
                    ws = await workspaces.get_agent("default")
                    await ws.channel_manager.start_one("checkpointer", config)
                stop_all = workspaces.stop_all
                async def close_workspaces():
                    await stop_all()
                    ready.with_suffix(".workspaces").touch()
                    if failure == "workspace":
                        raise QuiescenceError("workspace still in use")
                workspaces.stop_all = close_workspaces
                backups = _app.app.state.backup_manager
                shutdown = backups.shutdown
                async def close_backups():
                    await shutdown()
                    ready.with_suffix(".backups").touch()
                backups.shutdown = close_backups
                browser_stop = _app._stop_browser_runtime
                async def close_browser(app):
                    await browser_stop(app)
                    ready.with_suffix(".browser").touch()
                _app._stop_browser_runtime = close_browser
                ready.touch()
                await stop.wait()

        asyncio.run(main())
        """,
    )
    log = tmp_path / "backend.log"
    with log.open("w") as output, subprocess.Popen(
        [sys.executable, "-c", script, str(ready), failure],
        env={
            **os.environ,
            "QWENPAW_WORKING_DIR": str(tmp_path / "app"),
            "CHECKPOINT_MARKER": str(ready.with_suffix(".called")),
            "QWENPAW_SECRET_DIR": str(tmp_path / "secrets"),
            "QWENPAW_BACKUP_DIR": str(tmp_path / "backups"),
            "QWENPAW_RUNNING_IN_CONTAINER": "true",
            "QWENPAW_TELEMETRY_DISABLED": "true",
        },
        stdout=output,
        stderr=subprocess.STDOUT,
    ) as backend:
        try:
            deadline = time.monotonic() + 60
            while not ready.exists() and backend.poll() is None:
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.05)
            assert ready.exists(), log.read_text(errors="replace")
            with ownership.observe_backend(
                psutil.Process(backend.pid),
            ) as receipt:
                monkeypatch.setattr(
                    shutdown_cmd,
                    "_listening_pids_for_port",
                    lambda port: {backend.pid},
                )
                monkeypatch.setattr(
                    shutdown_cmd,
                    "_find_frontend_dev_pids",
                    set,
                )
                monkeypatch.setattr(
                    shutdown_cmd,
                    "_find_desktop_wrapper_pids",
                    set,
                )
                result = CliRunner().invoke(shutdown_cmd.shutdown_cmd)
                if failure in {"channel", "hook"}:
                    assert ready.with_suffix(".called").exists()
                assert result.exit_code == 1, result.output
                assert f"Shutdown failed: {backend.pid}" in result.output
                assert receipt.members(set()) == (set(), True)
                assert (receipt.failed, receipt.closed) == (True, False)
            assert backend.wait(timeout=5) == 1
            if failure == "hook":
                error = (
                    "Plugin shutdown hooks failed: "
                    "checkpointer/flush-checkpoint"
                )
                assert error in log.read_text(encoding="utf-8")
            if failure == "channel":
                error = (
                    "Channel shutdown failed: checkpointer/checkpointer: "
                    "CHANNEL_STOP_INCOMPLETE"
                )
                assert error in log.read_text(encoding="utf-8")
            assert ready.with_suffix(".workspaces").exists()
            assert ready.with_suffix(".backups").exists()
            assert ready.with_suffix(".browser").exists()
        finally:
            if backend.poll() is None:
                backend.kill()
