# -*- coding: utf-8 -*-
"""Terminal shutdown receipts through real process and lifecycle boundaries."""

import os
import subprocess
import sys
import textwrap
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import psutil
import pytest

from qwenpaw import process_ownership as ownership
from qwenpaw.cli.shutdown_cmd import ShutdownOutcome, _terminate_pid

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


def test_workspace_failure_is_reported_after_independent_services_close(
    tmp_path,
):
    ready = tmp_path / "ready"
    script = textwrap.dedent(
        """
        import asyncio
        import signal
        import sys
        from pathlib import Path
        from qwenpaw.app import _app
        from qwenpaw.plugins.lifecycle import QuiescenceError

        ready = Path(sys.argv[1])

        async def main():
            stop = asyncio.Event()
            loop = asyncio.get_running_loop()
            loop.add_signal_handler(signal.SIGTERM, stop.set)
            async with _app.lifespan(_app.app):
                await _app.app.state.startup_ready.wait()
                workspaces = _app.app.state.multi_agent_manager
                stop_all = workspaces.stop_all
                async def incomplete():
                    await stop_all()
                    raise QuiescenceError("workspace still in use")
                workspaces.stop_all = incomplete
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
        [sys.executable, "-c", script, str(ready)],
        env={
            **os.environ,
            "QWENPAW_WORKING_DIR": str(tmp_path / "app"),
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
                result = _terminate_pid(
                    backend.pid,
                    process=backend,
                    backend=True,
                )
                assert result is ShutdownOutcome.FAILED
                assert receipt.members(set()) == (set(), True)
                assert (receipt.failed, receipt.closed) == (True, False)
            assert backend.returncode == 1
            assert ready.with_suffix(".backups").exists()
            assert ready.with_suffix(".browser").exists()
        finally:
            if backend.poll() is None:
                backend.kill()
