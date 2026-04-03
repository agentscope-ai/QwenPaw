# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from copaw.utils import command_runner
from copaw.utils.command_runner import (
    CommandExecutionError,
    ManagedProcess,
    ProcessLaunchError,
    run_command,
    run_command_async,
    shutdown_process,
    shutdown_process_sync,
    start_multiprocessing_process,
    start_command_async,
)


def test_run_command_returns_combined_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: dict[str, object] = {}

    def fake_run(*args, **kwargs) -> subprocess.CompletedProcess[str]:
        recorded["command"] = args[0]
        recorded["cwd"] = kwargs["cwd"]
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="stdout line\n",
            stderr="stderr line\n",
        )

    monkeypatch.setattr(command_runner.subprocess, "run", fake_run)

    result = run_command(["demo", "--flag"], cwd=Path("/tmp/demo"))

    assert result.command == ["demo", "--flag"]
    assert result.combined_output == "stdout line\nstderr line"
    assert recorded == {
        "command": ["demo", "--flag"],
        "cwd": "/tmp/demo",
    }


def test_run_command_raises_for_non_zero_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(
        command: list[str],
        **_kwargs,
    ) -> subprocess.CompletedProcess[str]:
        del _kwargs
        return subprocess.CompletedProcess(
            args=command,
            returncode=2,
            stdout="",
            stderr="failure",
        )

    monkeypatch.setattr(command_runner.subprocess, "run", fake_run)

    with pytest.raises(CommandExecutionError, match="failure") as exc_info:
        run_command(["demo"], check=True)

    assert exc_info.value.returncode == 2
    assert exc_info.value.command == ["demo"]


def test_run_command_raises_for_missing_executable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*args, **kwargs) -> subprocess.CompletedProcess[str]:
        del args, kwargs
        raise FileNotFoundError

    monkeypatch.setattr(command_runner.subprocess, "run", fake_run)

    with pytest.raises(
        CommandExecutionError,
        match="Command executable not found",
    ):
        run_command(["missing-binary"])


@pytest.mark.asyncio
async def test_run_command_async_uses_sync_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run_command(command: list[str], **_kwargs):
        del command, _kwargs
        return command_runner.CommandResult(
            command=["demo"],
            returncode=0,
            stdout="ok",
            stderr="",
        )

    monkeypatch.setattr(command_runner, "run_command", fake_run_command)

    result = await run_command_async(["demo"])

    assert result.combined_output == "ok"


@pytest.mark.asyncio
async def test_start_command_async_uses_asyncio_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: dict[str, object] = {}

    class _FakeAsyncProcess:
        def __init__(self) -> None:
            self.pid = 4321
            self.returncode: int | None = None
            self.stdout = None

        async def wait(self) -> int:
            self.returncode = 0
            return 0

        def terminate(self) -> None:
            self.returncode = -15

        def kill(self) -> None:
            self.returncode = -9

    fake_process = _FakeAsyncProcess()

    async def fake_create_subprocess_exec(*args, **kwargs):
        recorded["command"] = list(args)
        recorded["cwd"] = kwargs["cwd"]
        recorded["env"] = kwargs["env"]
        recorded["stdout"] = kwargs["stdout"]
        recorded["stderr"] = kwargs["stderr"]
        return fake_process

    monkeypatch.setattr(
        command_runner.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    result = await start_command_async(
        ["demo", "--serve"],
        cwd=Path("/tmp/demo"),
        env={"A": "1"},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    assert isinstance(result, ManagedProcess)
    assert result.pid == 4321
    assert result.command == ["demo", "--serve"]
    assert result.creation_mode == "asyncio"
    assert result.owns_process_group is False
    assert recorded == {
        "command": ["demo", "--serve"],
        "cwd": "/tmp/demo",
        "env": {"A": "1"},
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.STDOUT,
    }


@pytest.mark.asyncio
async def test_start_command_async_falls_back_to_threaded_popen_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    popen_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    class _FakeBlockingStdout:
        def readline(self) -> bytes:
            return b""

    class _FakePopen:
        def __init__(self) -> None:
            self.pid = 1234
            self.stdout = _FakeBlockingStdout()
            self._returncode: int | None = None

        def poll(self) -> int | None:
            return self._returncode

        def wait(self) -> int:
            self._returncode = 0
            return 0

        def terminate(self) -> None:
            self._returncode = -15

        def kill(self) -> None:
            self._returncode = -9

    async def fail_create_subprocess_exec(*args, **kwargs):
        del args, kwargs
        raise NotImplementedError

    def fake_popen_factory(*args, **kwargs):
        popen_calls.append((args, kwargs))
        return _FakePopen()

    monkeypatch.setattr(command_runner.os, "name", "nt", raising=False)
    monkeypatch.setattr(
        command_runner.asyncio,
        "create_subprocess_exec",
        fail_create_subprocess_exec,
    )
    monkeypatch.setattr(
        command_runner.subprocess,
        "Popen",
        fake_popen_factory,
    )

    result = await start_command_async(
        ["demo", "--serve"],
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    assert isinstance(result, ManagedProcess)
    assert result.pid == 1234
    assert result.creation_mode == "threaded"
    assert await result.wait() == 0
    assert popen_calls == [
        (
            (["demo", "--serve"],),
            {
                "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT,
            },
        ),
    ]


@pytest.mark.asyncio
async def test_start_command_async_raises_for_missing_executable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_create_subprocess_exec(*args, **kwargs):
        del args, kwargs
        raise FileNotFoundError

    monkeypatch.setattr(
        command_runner.asyncio,
        "create_subprocess_exec",
        fail_create_subprocess_exec,
    )

    with pytest.raises(
        ProcessLaunchError,
        match="Command executable not found",
    ):
        await start_command_async(["missing-binary"])


def test_start_multiprocessing_process_wraps_process() -> None:
    class _FakeMultiprocessingProcess:
        def __init__(self) -> None:
            self.pid = 6789
            self.exitcode: int | None = None
            self.started = False
            self.closed = False

        def start(self) -> None:
            self.started = True

        def is_alive(self) -> bool:
            return self.exitcode is None

        def join(self, timeout=None) -> None:
            del timeout
            self.exitcode = 0

        def terminate(self) -> None:
            self.exitcode = -15

        def kill(self) -> None:
            self.exitcode = -9

        def close(self) -> None:
            self.closed = True

    raw_process = _FakeMultiprocessingProcess()

    managed = start_multiprocessing_process(
        raw_process,
        command=["copaw-model-download", "demo/repo", "modelscope"],
    )

    assert isinstance(managed, ManagedProcess)
    assert managed.creation_mode == "multiprocessing"
    assert managed.command == [
        "copaw-model-download",
        "demo/repo",
        "modelscope",
    ]
    assert managed.is_alive() is True
    assert raw_process.started is True


def test_wait_for_process_exit_prefers_process_liveness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pid_checks: list[tuple[int, str]] = []

    class _FakeProcess:
        def __init__(self) -> None:
            self.pid = 2468
            self.returncode = 0
            self.stdout = None

        async def wait(self) -> int:
            return 0

        def terminate(self) -> None:
            return None

        def kill(self) -> None:
            return None

        def is_alive(self) -> bool:
            return False

        def join(self, timeout=None) -> int:
            del timeout
            return 0

    def _record_pid_check(pid: int, platform_name: str) -> bool:
        pid_checks.append((pid, platform_name))
        return True

    monkeypatch.setattr(
        command_runner,
        "_is_pid_running",
        _record_pid_check,
    )

    managed = ManagedProcess(
        _FakeProcess(),
        command=["demo"],
        owns_process_group=False,
        creation_mode="multiprocessing",
    )

    assert command_runner._wait_for_process_exit(managed, timeout=1.0) is True
    assert not pid_checks


@pytest.mark.asyncio
async def test_shutdown_process_terminates_gracefully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del monkeypatch

    class _FakeAsyncProcess:
        def __init__(self) -> None:
            self.pid = 99
            self.stdout = None
            self.returncode: int | None = None
            self.terminate_calls = 0
            self.kill_calls = 0

        async def wait(self) -> int:
            self.returncode = 0
            return 0

        def terminate(self) -> None:
            self.terminate_calls += 1

        def kill(self) -> None:
            self.kill_calls += 1

    inner = _FakeAsyncProcess()
    managed = ManagedProcess(
        inner,
        command=["demo"],
        owns_process_group=False,
        creation_mode="asyncio",
    )

    result = await shutdown_process(managed, graceful_timeout=0.1)

    assert result.exited is True
    assert result.terminated_gracefully is True
    assert result.killed is False
    assert result.returncode == 0
    assert inner.terminate_calls == 1
    assert inner.kill_calls == 0


@pytest.mark.asyncio
async def test_shutdown_process_escalates_to_kill_after_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del monkeypatch

    class _FakeAsyncProcess:
        def __init__(self) -> None:
            self.pid = 100
            self.stdout = None
            self.returncode: int | None = None
            self.terminate_calls = 0
            self.kill_calls = 0
            self._killed = False

        async def wait(self) -> int:
            if not self._killed:
                await asyncio.sleep(3600)
            self.returncode = -9
            return -9

        def terminate(self) -> None:
            self.terminate_calls += 1

        def kill(self) -> None:
            self.kill_calls += 1
            self._killed = True

    inner = _FakeAsyncProcess()
    managed = ManagedProcess(
        inner,
        command=["demo"],
        owns_process_group=False,
        creation_mode="asyncio",
    )

    result = await shutdown_process(
        managed,
        graceful_timeout=0.01,
        kill_timeout=0.1,
    )

    assert result.exited is True
    assert result.terminated_gracefully is False
    assert result.killed is True
    assert result.returncode == -9
    assert inner.terminate_calls == 1
    assert inner.kill_calls == 1


def test_shutdown_process_sync_uses_process_group_on_posix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signals: list[tuple[int, int]] = []

    class _FakeProcess:
        def __init__(self) -> None:
            self.pid = 123
            self.stdout = None
            self.returncode: int | None = None

        async def wait(self) -> int:
            self.returncode = 0
            return 0

        def terminate(self) -> None:
            raise AssertionError(
                "terminate should not be used for process groups",
            )

        def kill(self) -> None:
            raise AssertionError(
                "kill should not be used for process groups",
            )

    monkeypatch.setattr(command_runner.os, "name", "posix", raising=False)
    monkeypatch.setattr(
        command_runner.os,
        "getpgid",
        lambda pid: pid,
        raising=False,
    )
    monkeypatch.setattr(
        command_runner.os,
        "killpg",
        lambda pgid, sig: signals.append((pgid, int(sig))),
        raising=False,
    )
    monkeypatch.setattr(
        command_runner,
        "_wait_for_process_exit",
        lambda process, timeout: True,
    )

    managed = ManagedProcess(
        _FakeProcess(),
        command=["demo"],
        owns_process_group=True,
        creation_mode="asyncio",
    )
    result = shutdown_process_sync(managed, graceful_timeout=5.0)

    assert result.exited is True
    assert result.terminated_gracefully is True
    assert result.killed is False
    assert signals == [(123, int(command_runner.signal.SIGTERM))]


def test_shutdown_process_sync_escalates_to_kill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signals: list[int] = []
    wait_outcomes = iter([False, True])

    class _FakeProcess:
        def __init__(self) -> None:
            self.pid = 456
            self.stdout = None
            self.returncode: int | None = None

        async def wait(self) -> int:
            self.returncode = 0
            return 0

        def terminate(self) -> None:
            signals.append(15)

        def kill(self) -> None:
            signals.append(9)

    monkeypatch.setattr(
        command_runner,
        "_wait_for_process_exit",
        lambda process, timeout: next(wait_outcomes),
    )

    managed = ManagedProcess(
        _FakeProcess(),
        command=["demo"],
        owns_process_group=False,
        creation_mode="asyncio",
    )
    result = shutdown_process_sync(
        managed,
        graceful_timeout=5.0,
        kill_timeout=1.0,
    )

    assert result.exited is True
    assert result.terminated_gracefully is False
    assert result.killed is True
    assert signals == [15, 9]


def test_is_pid_running_uses_tasklist_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(pid: int, sig: int) -> None:
        raise AssertionError("os.kill should not be used on Windows")

    monkeypatch.setattr(command_runner.os, "kill", fail_if_called)
    monkeypatch.setattr(
        command_runner.subprocess,
        "check_output",
        lambda *args, **kwargs: (
            "Image Name                     PID Session Name        "
            "Session#    Mem Usage\n"
            "========================= ======== ================ "
            "========== ============\n"
            "llama-server.exe              4321 Console        "
            "         1     12,000 K\n"
        ),
    )

    assert command_runner._is_pid_running(4321, "nt") is True


def test_is_pid_running_uses_os_kill_on_posix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, int]] = []

    def fake_kill(pid: int, sig: int) -> None:
        calls.append((pid, sig))
        raise PermissionError()

    monkeypatch.setattr(command_runner.os, "kill", fake_kill)

    assert command_runner._is_pid_running(1234, "posix") is True
    assert calls == [(1234, 0)]
