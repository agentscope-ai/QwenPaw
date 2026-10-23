"""Real framing/store with controlled OS-writer acceptance, not Process E2E."""

import asyncio
import json

import pytest

from payload_store_suite import deadline
from process_suite import eventually

pytest_plugins = ["payload_store_suite", "process_suite", "payload_support"]


class BoundaryWriter:
    """Only stream acceptance/drain are controlled; transport remains real."""

    def __init__(self, mode):
        self.mode = mode
        self.frames = []
        self.accepted = asyncio.get_running_loop().create_future()

    def write(self, data):
        if self.mode == "write_failure":
            raise BrokenPipeError("controlled OS boundary")
        self.frames.append(data)

    def wait_write_accepted(self):
        return self.accepted if self.mode == "deferred" else None

    async def drain(self):
        if self.mode == "drain_failure":
            raise BrokenPipeError("controlled post-acceptance drain")

    def close(self):
        pass

    async def wait_closed(self):
        pass


def callbacks(events, text):
    def prepare():
        events.append("prepared")
        return text

    return {
        "prepare_write": prepare,
        "on_write_succeeded": lambda: events.append("published"),
        "on_write_failed": lambda: events.append("failed"),
        "on_write_deferred": lambda: events.append("deferred"),
    }


@pytest.mark.parametrize("visible", [False, True])
@pytest.mark.asyncio
async def test_payload_publication_preserves_before_and_after_visibility_failure(stores, visible):
    from qwenpaw.plugins.execution.errors import FrameWriteError
    from qwenpaw.plugins.execution.framing import FramedTransport, FramingLimits

    host, worker = stores()
    writer = BoundaryWriter("drain_failure" if visible else "write_failure")
    transport = FramedTransport(asyncio.StreamReader(), writer, limits=FramingLimits(max_frame_bytes=512), payloads=host)
    text = json.dumps({"text": "x" * 1000})
    events = []
    try:
        with pytest.raises(FrameWriteError) as caught:
            await transport.send("{}", **callbacks(events, text))
        assert bool(getattr(caught.value, "side_effect_possible", False)) is visible
        assert events == ["prepared", "published" if visible else "failed"]
        assert len(writer.frames) == int(visible)
        assert host.pending_snapshot()["pending_files"] == int(visible)
        if visible:
            ref = writer.frames[0].split(b"\r\n\r\n", 1)[1].decode()
            assert await worker.read(ref, deadline=deadline()) == text
    finally:
        await transport.aclose()


@pytest.mark.parametrize("accepted", [False, True])
@pytest.mark.asyncio
async def test_deferred_timeout_keeps_file_until_actual_acceptance_settles(stores, accepted):
    from qwenpaw.plugins.execution.errors import FrameTimeoutError
    from qwenpaw.plugins.execution.framing import FramedTransport, FramingLimits

    host, worker = stores()
    writer = BoundaryWriter("deferred")
    transport = FramedTransport(asyncio.StreamReader(), writer, limits=FramingLimits(max_frame_bytes=512, write_timeout=0.1), payloads=host)
    text = json.dumps({"text": "x" * 1000})
    events = []
    try:
        with pytest.raises(FrameTimeoutError) as caught:
            await transport.send("{}", **callbacks(events, text))
        assert caught.value.side_effect_possible is True
        assert events == ["prepared", "deferred"]
        assert host.pending_snapshot()["pending_files"] == 1
        if accepted: writer.accepted.set_result(None)
        else: writer.accepted.set_exception(BrokenPipeError("controlled eventual refusal"))
        await eventually(lambda: len(events) == 3)
        assert events == ["prepared", "deferred", "published" if accepted else "failed"]
        assert host.pending_snapshot()["pending_files"] == int(accepted)
        if accepted:
            ref = writer.frames[0].split(b"\r\n\r\n", 1)[1].decode()
            assert await worker.read(ref, deadline=deadline()) == text
        assert len(writer.frames) == 1
    finally:
        if not writer.accepted.done(): writer.accepted.set_exception(BrokenPipeError("test cleanup"))
        await transport.aclose()


@pytest.mark.asyncio
async def test_cancel_during_prepare_never_publishes_or_leaves_payload(stores):
    from qwenpaw.plugins.execution.framing import FramedTransport, FramingLimits

    host, _ = stores()
    writer = BoundaryWriter("normal")
    transport = FramedTransport(asyncio.StreamReader(), writer, limits=FramingLimits(max_frame_bytes=512), payloads=host)
    entered = asyncio.Event()
    events = []

    async def prepare():
        entered.set()
        await asyncio.Event().wait()

    args = callbacks(events, "")
    args["prepare_write"] = prepare
    pending = asyncio.create_task(transport.send("{}", **args))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError): await pending
        assert writer.frames == [] and events == ["failed"]
        assert host.pending_snapshot()["pending_files"] == 0
    finally:
        if not pending.done(): pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        await transport.aclose()


@pytest.mark.asyncio
async def test_actual_process_cleanup_residual_retains_store_then_retries(payload_launch, payload_processes):
    from process_suite import alive

    spec, _ = payload_launch()
    process = payload_processes()
    await process.start(spec)
    pid = process.health_snapshot()["pid"]
    store = process._payloads
    obstructing = store.root / "h2w" / "unexpected-directory"
    obstructing.mkdir()
    try:
        result = await process.stop()
        assert not result.exited and result.residual == ("PAYLOAD_STORE_REMAINING",)
        assert not alive(pid)
        assert process._payloads is store and store.root.exists()
    finally:
        obstructing.rmdir()
    result = await process.stop()
    assert result.exited and not result.residual
    assert process._payloads is None and not store.root.exists()
