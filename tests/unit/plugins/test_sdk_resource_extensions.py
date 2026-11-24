# -*- coding: utf-8 -*-
"""Exercise SDK custody using real blocking work and OS processes."""

import asyncio
import os
import subprocess
import sys
import threading
from contextlib import suppress

import psutil
import pytest

from qwenpaw.plugins import ResourceError
from qwenpaw.plugins.resources import ResourceOwner, ResourceScope
from .timing import WAIT_TIMEOUT


def scope():
    return ResourceScope(ResourceOwner("extensions", 1), lambda: None)


async def test_run_sync_releases_finished_work_before_scope_closes():
    resources = scope()
    async with resources:
        assert await resources.run_sync(int, "42") == 42
        with pytest.raises(ValueError, match="invalid literal"):
            await resources.run_sync(int, "invalid")
        assert resources.snapshot() == {
            "owner": resources.owner,
            "closed": False,
            "resources": (),
            "errors": (),
            "cleanup_errors": (),
        }
        assert resources._handles == []


async def test_run_sync_delivers_stop_iteration_after_thread_exits():
    async with scope() as resources:
        with pytest.raises(
            RuntimeError,
            match="run_sync.*StopIteration",
        ) as error:
            await asyncio.wait_for(resources.run_sync(next, iter(())), 3)
        assert isinstance(error.value.__cause__, StopIteration)
        assert not resources.snapshot()["resources"]


async def test_cleanup_diagnostics_retain_each_failure_until_success():
    resources = scope()
    attempts = []
    blocked = True

    async def close_first():
        attempts.append("first")
        if blocked:
            raise ValueError("first still writing")

    async def close_second():
        attempts.append("second")
        if blocked:
            raise RuntimeError("second still connected")

    first = resources.defer(close_first, "first")
    resources.defer(close_second, "second")
    try:
        with pytest.raises(ValueError, match="first still writing"):
            await first.close()
        with pytest.raises(ResourceError):
            await resources.close()
        expected = {
            "owner": resources.owner,
            "closed": False,
            "resources": ("first", "second"),
            "errors": (),
            "cleanup_errors": (
                {
                    "description": "first",
                    "error_type": "ValueError",
                    "message": "first still writing",
                },
                {
                    "description": "second",
                    "error_type": "RuntimeError",
                    "message": "second still connected",
                },
            ),
        }
        assert resources.snapshot() == expected
        detached = resources.snapshot()
        detached["cleanup_errors"][0]["message"] = "modified by caller"
        assert resources.snapshot() == expected
    finally:
        blocked = False
        await resources.close()
    assert attempts == ["first", "second", "first", "second", "first"]
    assert resources.snapshot() == {
        "owner": resources.owner,
        "closed": True,
        "resources": (),
        "errors": (),
        "cleanup_errors": (),
    }


async def test_cancelled_run_sync_releases_after_worker_exits():
    resources = scope()
    entered, release = threading.Event(), threading.Event()

    def work():
        entered.set()
        release.wait(10)
        raise ValueError("late failure")

    async with resources:
        waiting = asyncio.create_task(resources.run_sync(work))
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiting
            assert resources.snapshot()["resources"] == ("run_sync",)
        finally:
            release.set()
        async with asyncio.timeout(3):
            while resources.snapshot()["resources"]:
                await asyncio.sleep(0.01)
        assert resources._handles == []


async def test_cancelled_run_sync_keeps_lock_until_write_finishes(tmp_path):
    resources = scope()
    lock = threading.Lock()
    entered, release = threading.Event(), threading.Event()
    attempted = threading.Event()
    path = tmp_path / "state.txt"
    path.write_text("initial", encoding="utf-8")
    events = []
    acquired_early = []

    def write_locked():
        with lock:
            entered.set()
            if not release.wait(10):
                raise TimeoutError("Write was not released")
            path.write_text("completed", encoding="utf-8")
            events.append("written")

    def read_locked():
        acquired = lock.acquire(blocking=False)
        acquired_early.append(acquired)
        if acquired:
            lock.release()
        attempted.set()
        with lock:
            value = path.read_text(encoding="utf-8")
            events.append("read")
            return value

    writing = asyncio.create_task(resources.run_sync(write_locked))
    reading = None
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        writing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await writing
        reading = asyncio.create_task(resources.run_sync(read_locked))
        assert await asyncio.to_thread(attempted.wait, 3)
        assert acquired_early == [False]
        assert events == []
        assert resources.snapshot()["resources"] == (
            "run_sync",
            "run_sync",
        )
    finally:
        release.set()
        try:
            await resources.close()
        finally:
            waiters = [writing] if reading is None else [writing, reading]
            await asyncio.gather(*waiters, return_exceptions=True)

    assert reading.result() == "completed"
    assert events == ["written", "read"]
    assert resources.snapshot() == {
        "owner": resources.owner,
        "closed": True,
        "resources": (),
        "errors": (),
        "cleanup_errors": (),
    }


async def test_run_sync_waits_for_thread_local_cleanup():
    resources = scope()
    finishing, release = threading.Event(), threading.Event()
    local = threading.local()

    class Cleanup:
        def __del__(self):
            finishing.set()
            release.wait(10)

    def work():
        local.cleanup = Cleanup()
        return "finished"

    async with resources:
        waiting = asyncio.create_task(resources.run_sync(work))
        try:
            assert await asyncio.to_thread(finishing.wait, 3)
            await asyncio.sleep(0.02)
            assert not waiting.done()
            assert resources.snapshot()["resources"] == ("run_sync",)
        finally:
            release.set()
        assert await asyncio.wait_for(waiting, 3) == "finished"
        assert resources.snapshot()["resources"] == ()


async def test_run_sync_cancellation_retains_actual_thread(monkeypatch):
    from qwenpaw.plugins import custody

    monkeypatch.setattr(custody, "THREAD_STOP_SECONDS", 0.05)
    entered, release = threading.Event(), threading.Event()
    worker_ids = []

    def work():
        worker_ids.append(threading.get_ident())
        entered.set()
        release.wait(10)
        return "finished"

    resources = scope()
    waiting = asyncio.create_task(resources.run_sync(work))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        with pytest.raises(ResourceError, match="did not stop"):
            await resources.close()
        assert not resources.closed
        assert resources.snapshot()["resources"] == ("run_sync",)
        assert any(t.ident in worker_ids for t in threading.enumerate())
    finally:
        release.set()
        await resources.close()
    assert not any(t.ident in worker_ids for t in threading.enumerate())
    assert not resources.snapshot()["resources"]


@pytest.mark.skipif(os.name == "nt", reason="uses a POSIX nonblocking pipe")
@pytest.mark.parametrize(
    ("inherited", "text"),
    [(False, False), (True, False), (True, True)],
)
async def test_process_cleanup_reaps_child_with_full_buffered_stdin(
    tmp_path,
    inherited,
    text,
):
    resources = scope()
    release = tmp_path / "release"
    command = [sys.executable, "-c", "import time; time.sleep(60)"]
    if inherited:
        holder = (
            "import os, sys, time\n"
            "deadline = time.monotonic() + 60\n"
            "while not os.path.exists(sys.argv[1]) and time.monotonic() < deadline:\n"
            "    time.sleep(0.01)\n"
        )
        command = [
            sys.executable,
            "-c",
            "import subprocess,sys; subprocess.Popen([sys.executable,'-c',*sys.argv[1:]])",
            holder,
            str(release),
        ]
    process = resources.process(
        command,
        stdin=subprocess.PIPE,
        text=text,
    )
    closing = None
    try:
        assert process.stdin is not None
        if inherited:
            assert await asyncio.to_thread(process.wait, WAIT_TIMEOUT) == 0
        fd = process.stdin.fileno()
        os.set_blocking(fd, False)
        for chunk in (b"x" * 4096, b"x"):
            with suppress(BlockingIOError):
                while True:
                    os.write(fd, chunk)
        os.set_blocking(fd, True)
        process.stdin.write("still buffered" if text else b"still buffered")
        closing = asyncio.create_task(resources.close())
        done, _ = await asyncio.wait({closing}, timeout=WAIT_TIMEOUT)
        assert closing in done, "cleanup blocked while closing stdin"
        await closing
        assert process.poll() is not None and process.stdin.closed
    finally:
        release.touch()
        if process.poll() is None:
            process.kill()
        if closing is not None:
            await closing
        else:
            await resources.close()


async def test_async_process_interactive_io_and_close():
    resources = scope()
    process = await resources.async_process(
        [
            sys.executable,
            "-u",
            "-c",
            "import sys; print(input(), flush=True); sys.stdin.read()",
        ],
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
    )
    try:
        process.stdin.write(b"hello\n")
        await process.stdin.drain()
        line = await asyncio.wait_for(process.stdout.readline(), 3)
        assert line.splitlines() == [b"hello"]
        assert psutil.pid_exists(process.pid)
    finally:
        await resources.close()
    assert process.returncode is not None
    assert not psutil.pid_exists(process.pid)


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group contract")
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("separate_group", [False, True])
async def test_tree_closes_descendant_after_leader_exit(
    asynchronous,
    separate_group,
):
    resources = scope()
    code = (
        "import subprocess,sys; "
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(90)'], "
        f"process_group={0 if separate_group else -1}, "
        "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
        "print(p.pid,flush=True)"
    )
    args = [sys.executable, "-u", "-c", code]
    if asynchronous:
        process = await resources.async_process(
            args,
            tree=True,
            stdout=asyncio.subprocess.PIPE,
        )
        pid = int(await asyncio.wait_for(process.stdout.readline(), 3))
        await asyncio.wait_for(process.wait(), 3)
    else:
        process = resources.process(args, tree=True, stdout=subprocess.PIPE)
        pid = int(await asyncio.to_thread(process.stdout.readline))
        await asyncio.to_thread(process.wait, timeout=3)
    try:
        assert psutil.pid_exists(pid), "The descendant must outlive its leader"
        await resources.close()
        try:
            assert psutil.Process(pid).status() in {
                psutil.STATUS_ZOMBIE,
                psutil.STATUS_DEAD,
            }, "A live descendant is not cleanup success"
        except psutil.NoSuchProcess:
            pass
    finally:
        with suppress(psutil.NoSuchProcess):
            psutil.Process(pid).kill()
        if not resources.closed:
            await resources.close()


async def test_cancel_during_spawn_retains_eventual_process(monkeypatch):
    original = asyncio.create_subprocess_exec
    created, release = asyncio.Event(), asyncio.Event()
    children = []

    async def delayed(*args, **kwargs):
        child = await original(*args, **kwargs)
        children.append(child)
        created.set()
        await release.wait()
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed)
    resources = scope()
    waiting = asyncio.create_task(
        resources.async_process(
            [sys.executable, "-c", "import time; time.sleep(90)"],
        ),
    )
    try:
        await asyncio.wait_for(created.wait(), 3)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        closing = asyncio.create_task(resources.close())
        await asyncio.sleep(0)
        assert not closing.done() and psutil.pid_exists(children[0].pid)
        release.set()
        await asyncio.wait_for(closing, 3)
        assert not psutil.pid_exists(children[0].pid)
    finally:
        release.set()
        await resources.close()


async def test_process_start_failure_does_not_poison_cleanup():
    async with scope() as resources:
        with pytest.raises(FileNotFoundError):
            await resources.async_process(["/nonexistent/sdk-test-process"])
    assert resources.closed


async def test_session_visibility_failure_rejects_before_spawn(monkeypatch):
    from qwenpaw.plugins.execution.process_tree import ProcessTree

    def unavailable():
        raise PermissionError("process list unavailable")

    monkeypatch.setattr(ProcessTree, "check_session_visibility", unavailable)
    error = (
        "not yet supported on Windows"
        if os.name == "nt"
        else "process-session visibility"
    )
    async with scope() as resources:
        with pytest.raises(ResourceError, match=error):
            await resources.async_process(
                [sys.executable, "-c", "pass"],
                tree=True,
            )
        assert not resources.snapshot()["resources"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-session inspection")
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_tree_inspection_failure_retains_launched_child(
    monkeypatch,
    asynchronous,
):
    resources = scope()
    original = resources._process_tree
    pids = []

    def unavailable(pid):
        pids.append(pid)
        raise PermissionError("cannot inspect the new process yet")

    monkeypatch.setattr(resources, "_process_tree", unavailable)
    try:
        with pytest.raises(PermissionError):
            if asynchronous:
                await resources.async_process(
                    [sys.executable, "-c", "import time; time.sleep(90)"],
                    tree=True,
                )
            else:
                resources.process(
                    [sys.executable, "-c", "import time; time.sleep(90)"],
                    tree=True,
                )
        assert psutil.pid_exists(pids[0])
        with pytest.raises(ResourceError, match="cannot inspect"):
            await resources.close()
        assert not resources.closed and resources.snapshot()["resources"]
    finally:
        monkeypatch.setattr(resources, "_process_tree", original)
        await resources.close()
    assert not psutil.pid_exists(pids[0])


async def test_async_process_cleanup_with_unread_full_pipe(monkeypatch):
    from qwenpaw.plugins import custody

    monkeypatch.setattr(custody, "PROCESS_STOP_SECONDS", 0.1)
    resources = scope()
    process = await resources.async_process(
        [
            sys.executable,
            "-u",
            "-c",
            "import sys,time; sys.stdout.write('x'*1000000); time.sleep(90)",
        ],
        stdout=asyncio.subprocess.PIPE,
    )
    try:
        # Reading one byte proves the producer has reached stdout; leave the
        # remaining output unconsumed, as a disconnected terminal would.
        assert await asyncio.wait_for(process.stdout.read(1), 3) == b"x"
        await asyncio.sleep(0.1)
        await resources.close()
        assert not psutil.pid_exists(process.pid)
    finally:
        if not resources.closed:
            await process.stdout.read()
            await resources.close()
