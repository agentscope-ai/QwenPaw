"""Real file/transport/process lifetimes with releasable OS boundaries."""

import asyncio
import errno
import json
import os
from pathlib import Path
import stat
import threading

import pytest

from payload_publication_suite import BoundaryWriter
from payload_store_suite import deadline, stage
from process_suite import alive, eventually

pytest_plugins = ["payload_store_suite", "process_suite", "payload_support"]


@pytest.mark.asyncio
async def test_read_frame_deadline_is_not_reset_when_hydration_io_starts(stores, monkeypatch):
    from qwenpaw.plugins.execution import payloads
    from qwenpaw.plugins.execution.errors import FrameTimeoutError
    from qwenpaw.plugins.execution.framing import FramedTransport, FramingLimits, encode_frame

    host, worker = stores()
    _, ref, token = await stage(host)
    frame = encode_frame(ref)
    header, body = frame.split(b"\r\n\r\n", 1)
    reader = asyncio.StreamReader()
    transport = FramedTransport(reader, BoundaryWriter("normal"), limits=FramingLimits(read_timeout=0.3), payloads=worker)
    entered, release, exited = threading.Event(), threading.Event(), threading.Event()
    original_open = payloads.os.open

    def blocked_open(path, flags, *args, **kwargs):
        if path != token + ".json" or kwargs.get("dir_fd") != worker._directories["h2w"]:
            return original_open(path, flags, *args, **kwargs)
        entered.set()
        try:
            if not release.wait(2):
                raise TimeoutError("test failed to release OS open")
            return original_open(path, flags, *args, **kwargs)
        finally:
            exited.set()

    pending = None
    timers = []
    try:
        with monkeypatch.context() as patch:
            patch.setattr(payloads.os, "open", blocked_open)
            reader.feed_data(header + b"\r\n\r\n")
            pending = asyncio.create_task(transport.receive())
            await eventually(lambda: transport._reader.message_deadline is not None)
            original_deadline = transport._reader.message_deadline
            loop = asyncio.get_running_loop()
            # Body arrival consumes most of the original frame budget. A
            # reset at hydration would let the later successful open through.
            timers.append(loop.call_at(original_deadline - 0.1, reader.feed_data, body))
            timers.append(loop.call_at(original_deadline + 0.05, release.set))
            with pytest.raises(FrameTimeoutError):
                await asyncio.wait_for(pending, 1)
            assert entered.is_set(), "Hydration boundary must actually be reached"
            assert not release.is_set(), "Timeout must precede the successful OS release"
            assert transport._reader.message_deadline == original_deadline
            assert (host.root / "h2w" / (token + ".json")).exists()
            assert worker.pending_snapshot()["io_pending"] == 1
    finally:
        release.set()
        for timer in timers: timer.cancel()
        if pending is not None:
            if not pending.done(): pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await transport.aclose()
        assert await worker.cleanup(deadline=deadline())
        assert exited.is_set() and worker.pending_snapshot()["io_pending"] == 0


@pytest.mark.parametrize("cancel", [False, True])
@pytest.mark.asyncio
async def test_abandoned_file_io_retains_actual_process_owner_and_recoverable_residual(
    payload_launch, payload_processes, monkeypatch, cancel
):
    from qwenpaw.plugins.execution import payloads
    from qwenpaw.plugins.execution.errors import FrameTimeoutError

    spec, marker = payload_launch()
    process = payload_processes()
    await process.start(spec)
    pid = process.health_snapshot()["pid"]
    store = process._payloads
    entered, release, exited = threading.Event(), threading.Event(), threading.Event()
    original_link = payloads.os.link

    def blocked_link(src, dst, *args, **kwargs):
        if kwargs.get("src_dir_fd") != store._directories["h2w"]:
            return original_link(src, dst, *args, **kwargs)
        entered.set()
        try:
            if not release.wait(3):
                raise TimeoutError("test failed to release OS hardlink")
            return original_link(src, dst, *args, **kwargs)
        finally:
            exited.set()

    pending = None
    try:
        with monkeypatch.context() as patch:
            patch.setattr(payloads.os, "link", blocked_link)
            pending = asyncio.create_task(store.stage(
                json.dumps({"text": "x" * 1000}), max_frame_bytes=64,
                deadline=asyncio.get_running_loop().time() + (2 if cancel else 0.15),
            ))
            await eventually(entered.is_set)
            if cancel:
                pending.cancel()
                with pytest.raises(asyncio.CancelledError): await pending
            else:
                with pytest.raises(FrameTimeoutError): await pending
            assert store.pending_snapshot()["io_pending"] == 1
            assert store.pending_snapshot()["pending_files"] == 1
            result = await process.stop(timeout=0.2)
            assert not result.exited and result.residual
            await eventually(lambda: process._cleanup_task.done())
            assert process._cleanup_task.result().residual == ("PAYLOAD_STORE_REMAINING",)
            assert not alive(pid)
            assert process._payloads is store and store.root.exists()
            assert not marker.exists(), "No business call was published"
            release.set()
            await eventually(lambda: store.pending_snapshot()["io_pending"] == 0)
            assert exited.is_set()
        result = await process.stop()
        assert result.exited and not result.residual
        assert process._payloads is None and not store.root.exists()
    finally:
        release.set()
        if pending is not None:
            if not pending.done(): pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        result = await process.stop(timeout=2)
        assert result.exited and not result.residual
        assert exited.is_set()


@pytest.mark.parametrize("supported", [True, False])
@pytest.mark.asyncio
async def test_windows_readonly_hardlink_sequence_with_controlled_os_boundary(stores, monkeypatch, supported):
    """POSIX files emulate Windows readonly unlink; this is NOT Windows E2E."""
    from qwenpaw.plugins.execution import payloads
    from qwenpaw.plugins.execution.errors import FrameWriteError

    host, worker = stores()
    real_os = os
    original_link, original_unlink, original_chmod = os.link, os.unlink, os.chmod
    events = []

    def chmod(path, mode, *args, **kwargs):
        if str(path).startswith(str(host.root)):
            events.append(("chmod", Path(path).suffix, mode))
        return original_chmod(path, mode, *args, **kwargs)

    def unlink(path, *args, **kwargs):
        if str(path).startswith(str(host.root)):
            mode = stat.S_IMODE(Path(path).stat().st_mode)
            events.append(("unlink", Path(path).suffix, mode))
            if not mode & 0o200:
                raise PermissionError("emulated Windows readonly unlink")
        return original_unlink(path, *args, **kwargs)

    class WindowsBoundary:
        name = "nt"
        O_BINARY = 0

        def __getattr__(self, name):
            return getattr(real_os, name)

        def link(self, src, dst, **kwargs):
            events.append(("link", Path(src).suffix, stat.S_IMODE(Path(src).stat().st_mode)))
            if not supported:
                raise OSError(errno.ENOTSUP, "controlled filesystem lacks hardlinks")
            return original_link(src, dst, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(payloads, "os", WindowsBoundary())
        patch.setattr(os, "chmod", chmod)
        patch.setattr(os, "unlink", unlink)
        if supported:
            text, wire, token = await stage(host)
            path = host.root / "h2w" / (token + ".json")
            assert path.read_bytes() == text.encode()
            assert stat.S_IMODE(path.stat().st_mode) == 0o400
            assert events == [
                ("chmod", ".part", 0o400), ("link", ".part", 0o400),
                ("chmod", ".part", 0o600), ("unlink", ".part", 0o600),
                ("chmod", ".json", 0o400),
            ]
        else:
            with pytest.raises(FrameWriteError): await stage(host)
            assert not list(host.root.rglob("*.part")) and not list(host.root.rglob("*.json"))
            assert host.pending_snapshot()["pending_files"] == host.pending_snapshot()["pending_bytes"] == 0
    if supported:
        # Restore the real POSIX reader; Windows native handle APIs are not
        # faked or asserted here. This confirms final data survived staging.
        assert await worker.read(wire, deadline=deadline()) == text
