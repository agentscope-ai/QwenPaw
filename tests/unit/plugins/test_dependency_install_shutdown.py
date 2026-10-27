# -*- coding: utf-8 -*-
"""Shutting down must stop dependency installers before workspace teardown."""

# pylint: disable=protected-access,consider-using-with,too-many-statements
import asyncio
import subprocess
import sys
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import psutil
import pytest

from qwenpaw.app import _app
from qwenpaw.plugins import dependency_gate, install_lock, local_transcription
from qwenpaw.plugins.loader import PluginLoader, _install_lock_path
from qwenpaw.plugins.testing import PluginTestHost

from .test_manifest_dependencies import package


@pytest.mark.parametrize("kind", ["sdk", "legacy", "whisper"])
@pytest.mark.parametrize("stage", ["installing", "waiting_lock"])
async def test_shutdown_cancels_dependency_install(
    tmp_path,
    monkeypatch,
    kind,
    stage,
):
    source = package(tmp_path, ["shutdown-probe==1.0"], sdk=kind != "legacy")
    plugin_id = "extension-contract"
    if kind == "whisper":
        source = local_transcription.SOURCE
        plugin_id = local_transcription.PLUGIN_ID

    # Model package availability without changing the host environment.
    ready = False
    retry = False
    original_version = dependency_gate._dist_version

    def version(name):
        if name in {"shutdown-probe", "openai-whisper", "torch"}:
            if not ready:
                return None
            return "1.0" if name == "shutdown-probe" else "20990101"
        return original_version(name)

    monkeypatch.setattr(dependency_gate, "_dist_version", version)
    entered = threading.Event()
    spawned = []
    popen = subprocess.Popen

    def observe(*args, **kwargs):
        proc = popen(*args, **kwargs)
        spawned.append(proc)
        entered.set()
        return proc

    runner = PluginLoader._run_subprocess_with_streaming_log

    def slow_install(_cmd, **kwargs):
        nonlocal ready
        code = "print('installed')" if retry else "import time; time.sleep(30)"
        result = runner([sys.executable, "-c", code], **kwargs)
        if result.returncode == 0:
            ready = True
        return result

    monkeypatch.setattr(subprocess, "Popen", observe)
    monkeypatch.setattr(
        PluginLoader,
        "_run_subprocess_with_streaming_log",
        staticmethod(slow_install),
    )
    exit_requested = threading.Event()
    monkeypatch.setattr(_app.os, "_exit", lambda _code: exit_requested.set())

    async with PluginTestHost(tmp_path / "host") as host:
        loader = host._loader
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
                _install_lock_path(plugin_id),
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
        else:
            install = asyncio.create_task(host.install(source))
        shutdown = None
        try:
            assert await asyncio.to_thread(entered.wait, 5)
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
                with install_lock.plugin_install_lock(
                    _install_lock_path(plugin_id),
                    timeout=0,
                ) as acquired:
                    assert (
                        not acquired
                    ), "Cancellation released another installer's lock"
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
            _install_lock_path(plugin_id),
            timeout=0,
        ) as acquired:
            assert acquired
        retry = True
        restarted = PluginLoader([host.root / "plugins"])
        record = await restarted.repair_dependencies(plugin_id)
        assert record.status == "active"
        await restarted.unload_plugin(plugin_id)


@pytest.mark.parametrize("stop", ["cancel", "timeout"])
@pytest.mark.parametrize(
    "enumeration_error", [None, "permission", "access_denied"]
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
        "while True: time.sleep(1)\n"
    )
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
        assert not psutil.pid_exists(int(parent_pid.read_text()))
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

    def observe(*args, **kwargs):
        proc = popen(*args, **kwargs)
        spawned.append(proc)
        started.set()
        return proc

    runner = PluginLoader._run_subprocess_with_streaming_log

    def slow_install(_cmd, **kwargs):
        return runner(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            **kwargs,
        )

    monkeypatch.setattr(subprocess, "Popen", observe)
    monkeypatch.setattr(
        PluginLoader,
        "_run_subprocess_with_streaming_log",
        staticmethod(slow_install),
    )
    async with PluginTestHost(tmp_path / "host") as host:
        task = asyncio.create_task(host.install(source))
        try:
            assert await asyncio.to_thread(started.wait, 5)
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
                _install_lock_path("extension-contract"),
                timeout=0,
            ) as acquired:
                assert acquired
        finally:
            for proc in spawned:
                if proc.poll() is None:
                    proc.kill()
            await asyncio.gather(task, return_exceptions=True)
