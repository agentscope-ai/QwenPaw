# -*- coding: utf-8 -*-
"""Shutting down must stop dependency installers before workspace teardown."""

# pylint: disable=protected-access,consider-using-with,too-many-statements
import asyncio
import json
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import psutil
import pytest

from qwenpaw.app import _app
from qwenpaw.plugins import install_lock, local_transcription
from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.plugins.testing import PluginTestHost

from .test_manifest_dependencies import package


def environment_lock_path():
    return install_lock.environment_install_lock_path(
        Path(sysconfig.get_path("purelib")),
    )


@pytest.mark.parametrize(
    "outcome",
    ["ok", "job_error", "resume_error", "cancel"],
)
def test_windows_installer_owns_job_before_resuming(monkeypatch, outcome):
    """Check Windows launch ordering and startup cleanup without OS workers."""
    import io
    from qwenpaw.plugins import dependency_process as installer

    events = []
    cancel = threading.Event()

    class Process:
        pid = 123
        returncode = None
        stdout = io.StringIO("installer output\n")

        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.stdout.close()

        def poll(self):
            return self.returncode

        def wait(self, **_kwargs):
            self.returncode = 0
            return self.returncode

        def children(self, **_kwargs):
            return []

        def terminate(self):
            events.append("terminate")
            self.returncode = -1

        kill = terminate

        def resume(self):
            assert events == ["spawn_suspended", "job"]
            if outcome == "resume_error":
                raise OSError("resume failed")
            events.append("resume")

    process = Process()

    def spawn(_cmd, **kwargs):
        assert kwargs["creationflags"] & installer._CREATE_SUSPENDED
        events.append("spawn_suspended")
        return process

    class Job:
        running = True

        def __init__(self, pid):
            assert pid == process.pid
            if outcome == "job_error":
                raise OSError("job unavailable")
            events.append("job")
            if outcome == "cancel":
                cancel.set()

        def signal(self, *, force):
            assert force
            events.append("stop_job")
            self.running = False

        def alive(self):
            return self.running

        def close(self):
            assert not self.running
            events.append("close_job")

    monkeypatch.setattr(installer, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(
        installer,
        "subprocess",
        SimpleNamespace(
            Popen=spawn,
            PIPE=subprocess.PIPE,
            STDOUT=subprocess.STDOUT,
            TimeoutExpired=subprocess.TimeoutExpired,
            CompletedProcess=subprocess.CompletedProcess,
        ),
    )
    monkeypatch.setattr(
        installer,
        "psutil",
        SimpleNamespace(
            Process=lambda _: process,
            wait_procs=lambda *args, **kwargs: ([], []),
            NoSuchProcess=psutil.NoSuchProcess,
            AccessDenied=psutil.AccessDenied,
        ),
    )
    monkeypatch.setattr(
        "qwenpaw.plugins.execution.process_tree.ProcessTree",
        Job,
    )
    if outcome == "ok":
        result = installer.run_install_command(
            ["python", "-m", "pip"],
            timeout=1,
            plugin_id="test",
            cancel=cancel,
        )
        assert result.stdout == "installer output"
    else:
        expected = asyncio.CancelledError if outcome == "cancel" else OSError
        with pytest.raises(expected):
            installer.run_install_command(
                ["python", "-m", "pip"],
                timeout=1,
                plugin_id="test",
                cancel=cancel,
            )
    if outcome == "job_error":
        assert "resume" not in events
        assert "terminate" in events
    else:
        assert events[-2:] == ["stop_job", "close_job"]
        assert ("resume" in events) == (outcome == "ok")


@pytest.mark.parametrize("kind", ["sdk", "legacy", "whisper"])
@pytest.mark.parametrize("stage", ["installing", "waiting_lock"])
@pytest.mark.parametrize("operation", ["install", "repair"])
async def test_shutdown_cancels_dependency_install(
    tmp_path,
    monkeypatch,
    kind,
    stage,
    operation,
):
    source = package(tmp_path, ["shutdown-probe==1.0"], sdk=kind != "legacy")
    plugin_id = "extension-contract"
    if kind == "whisper":
        source = tmp_path / "whisper"
        shutil.copytree(local_transcription.SOURCE, source)
        manifest_path = source / "plugin.json"
        manifest = json.loads(manifest_path.read_text())
        # Force an actual install even when this host already has Whisper.
        manifest["dependencies"].append("shutdown-probe==1.0")
        manifest_path.write_text(json.dumps(manifest))
        monkeypatch.setattr(local_transcription, "SOURCE", source)
        plugin_id = local_transcription.PLUGIN_ID

    monkeypatch.setenv("PIP_NO_INDEX", "1")
    entered = threading.Event()
    spawned = []
    popen = subprocess.Popen

    runner = PluginLoader._run_subprocess_with_streaming_log

    def slow_install(_cmd, **kwargs):
        def observe(*args, **values):
            proc = popen(*args, **values)
            spawned.append(proc)
            entered.set()
            return proc

        # Observe only the installer, not main's separate audit processes.
        with patch("subprocess.Popen", observe):
            return runner(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                **kwargs,
            )

    monkeypatch.setattr(
        PluginLoader,
        "_run_subprocess_with_streaming_log",
        staticmethod(slow_install),
    )
    exit_requested = threading.Event()
    monkeypatch.setattr(_app.os, "_exit", lambda _code: exit_requested.set())

    async with PluginTestHost(tmp_path / "host") as host:
        loader = host._loader
        if operation == "repair":
            from qwenpaw.plugins import SDKError

            installed_source = host.root / "plugins" / plugin_id
            shutil.copytree(source, installed_source)
            with pytest.raises(SDKError, match="shutdown-probe"):
                await host.load(installed_source)
        service = (
            local_transcription.LocalTranscriptionService(
                loader,
                host.root / "migration.json",
            )
            if kind == "whisper"
            else None
        )
        app = SimpleNamespace(
            state=SimpleNamespace(
                plugin_loader=loader,
                local_transcription=service,
                multi_agent_manager=SimpleNamespace(stop_all=AsyncMock()),
            ),
        )
        lock = None
        if stage == "waiting_lock":
            lock = install_lock.plugin_install_lock(
                environment_lock_path(),
            )
            assert lock.__enter__()
            acquire = install_lock._acquire_os_lock

            def observe_lock(fd):
                acquired = acquire(fd)
                if not acquired:
                    entered.set()
                return acquired

            monkeypatch.setattr(install_lock, "_acquire_os_lock", observe_lock)
        if service:
            service.request()
            install = service.task
        elif operation == "repair":
            install = asyncio.create_task(
                loader.repair_dependencies(plugin_id),
            )
        else:
            install = asyncio.create_task(host.install(source))
        shutdown = None
        try:
            assert await asyncio.to_thread(entered.wait, 20)
            shutdown = asyncio.create_task(
                _app._stop_workspaces_after_dependents(
                    app,
                    SimpleNamespace(shutdown=AsyncMock(return_value=True)),
                ),
            )
            done, _ = await asyncio.wait({shutdown}, timeout=12.5)
            assert (
                shutdown in done
            ), "Shutdown blocked on dependency installation"
            await shutdown
            assert (
                not exit_requested.is_set()
            ), "Shutdown hit the 12-second watchdog"
            app.state.multi_agent_manager.stop_all.assert_awaited_once()
            with pytest.raises(RuntimeError, match="shutting down"):
                await loader._ensure_dependencies_installed(
                    source,
                    plugin_id,
                    allow_install=True,
                )
            assert install.done()
            assert install.cancelled()
            assert all(proc.poll() is not None for proc in spawned)
            if stage == "waiting_lock":
                assert (
                    not spawned
                ), "Cancelled lock waiter still started an installer"
                with pytest.raises(install_lock.InstallLockError):
                    with install_lock.plugin_install_lock(
                        environment_lock_path(),
                        timeout=0,
                    ):
                        pytest.fail("Cancellation released the peer's lock")
        finally:
            # Bounded cleanup also works against the unfixed implementation.
            if lock:
                lock.__exit__(None, None, None)
            for proc in spawned:
                if proc.poll() is None:
                    proc.kill()
            install.cancel()
            await asyncio.gather(install, return_exceptions=True)
            if shutdown:
                await shutdown
            if service:
                await service.close()

        # A fresh backend can explicitly retry; no OS lock remains held.
        with install_lock.plugin_install_lock(
            environment_lock_path(),
            timeout=0,
        ) as acquired:
            assert acquired
        restarted = PluginLoader([host.root / "plugins"])
        async with restarted._dependency_install_scope(source):
            assert not restarted._closing


@pytest.mark.parametrize("stop", ["cancel", "timeout"])
@pytest.mark.parametrize(
    "enumeration_error",
    [None, "permission", "access_denied"],
)
async def test_installer_reaps_stubborn_child_after_parent_exits(
    tmp_path,
    monkeypatch,
    stop,
    enumeration_error,
):
    """Stop the installer tree, including TERM-resistant POSIX helpers."""
    import os
    import signal

    from qwenpaw.plugins.dependency_process import run_install_command

    if enumeration_error:
        if os.name == "nt":
            pytest.skip("Process-group fallback requires POSIX")

        def deny_children(_process, **_kwargs):
            if enumeration_error == "access_denied":
                raise psutil.AccessDenied()
            raise PermissionError("Process enumeration denied")

        monkeypatch.setattr(psutil.Process, "children", deny_children)

    child_pid = tmp_path / "child.pid"
    parent_pid = tmp_path / "parent.pid"
    child_code = (
        "import os, signal, time\n"
        "from pathlib import Path\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"Path({str(child_pid)!r}).write_text(str(os.getpid()))\n"
        "while True: time.sleep(1)\n"
    )
    parent_code = (
        "import os, signal, subprocess, sys, time\n"
        "from pathlib import Path\n"
        "signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))\n"
        f"Path({str(parent_pid)!r}).write_text(str(os.getpid()))\n"
        f"subprocess.Popen([sys.executable, '-c', {child_code!r}])\n"
    )
    if enumeration_error:
        parent_code += "while True: time.sleep(1)\n"
    spawned = []
    popen = subprocess.Popen

    def observe(*args, **kwargs):
        proc = popen(*args, **kwargs)
        spawned.append(proc)
        return proc

    monkeypatch.setattr(subprocess, "Popen", observe)
    cancel = threading.Event()
    worker = asyncio.create_task(
        asyncio.to_thread(
            run_install_command,
            [sys.executable, "-c", parent_code],
            timeout=2 if stop == "timeout" else 30,
            plugin_id="tree-probe",
            cancel=cancel,
        ),
    )
    try:
        async with asyncio.timeout(5):
            while not child_pid.exists():
                await asyncio.sleep(0.01)
            if not enumeration_error:
                while not spawned or spawned[0].poll() is None:
                    await asyncio.sleep(0.01)
        child = psutil.Process(int(child_pid.read_text()))
        if stop == "cancel":
            cancel.set()
        expected = (
            asyncio.CancelledError
            if stop == "cancel"
            else subprocess.TimeoutExpired
        )
        with pytest.raises(expected):
            await asyncio.wait_for(asyncio.shield(worker), timeout=6)
        assert not child.is_running() or child.status() == psutil.STATUS_ZOMBIE
        assert spawned[0].poll() is not None
    finally:
        # Kill only this test's processes if an assertion/regression fails.
        if os.name == "nt":
            for path in (child_pid, parent_pid):
                if path.exists():
                    try:
                        psutil.Process(int(path.read_text())).kill()
                    except psutil.NoSuchProcess:
                        pass
        elif parent_pid.exists():
            try:
                os.killpg(int(parent_pid.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass
        await asyncio.gather(worker, return_exceptions=True)


@pytest.mark.parametrize(
    "enumeration_error",
    [None, PermissionError, psutil.AccessDenied],
)
async def test_request_cancellation_stops_installer_without_shutdown(
    tmp_path,
    monkeypatch,
    enumeration_error,
):
    """HTTP task cancellation must signal the worker before awaiting it."""
    if enumeration_error:
        monkeypatch.setattr(
            psutil.Process,
            "children",
            Mock(side_effect=enumeration_error()),
        )
    source = package(tmp_path, ["shutdown-probe==1.0"])
    started = threading.Event()
    spawned = []
    popen = subprocess.Popen

    runner = PluginLoader._run_subprocess_with_streaming_log

    def slow_install(_cmd, **kwargs):
        def observe(*args, **values):
            proc = popen(*args, **values)
            spawned.append(proc)
            started.set()
            return proc

        with patch("subprocess.Popen", observe):
            return runner(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                **kwargs,
            )

    monkeypatch.setenv("PIP_NO_INDEX", "1")
    monkeypatch.setattr(
        PluginLoader,
        "_run_subprocess_with_streaming_log",
        staticmethod(slow_install),
    )
    async with PluginTestHost(tmp_path / "host") as host:
        task = asyncio.create_task(host.install(source))
        try:
            assert await asyncio.to_thread(started.wait, 20)
            task.cancel()
            # Repeated cancellation must not release the lock early either.
            await asyncio.sleep(0)
            task.cancel()
            done, _ = await asyncio.wait({task}, timeout=5)
            assert task in done
            assert task.cancelled()
            assert all(proc.poll() is not None for proc in spawned)
            assert not host._loader._dependency_installs
            with install_lock.plugin_install_lock(
                environment_lock_path(),
                timeout=0,
            ) as acquired:
                assert acquired
        finally:
            for proc in spawned:
                if proc.poll() is None:
                    proc.kill()
            await asyncio.gather(task, return_exceptions=True)
