"""Real missing target plus narrow OS-open fault classification controls."""

import errno
import json

import pytest

from payload_store_suite import deadline, stage

pytest_plugins = ["payload_store_suite"]


@pytest.mark.asyncio
async def test_missing_reference_target_is_protocol_failure(stores):
    from qwenpaw.plugins.execution.errors import FrameProtocolError

    host, worker = stores()
    _, wire, token = await stage(host)
    (host.root / "h2w" / (token + ".json")).unlink()
    with pytest.raises(FrameProtocolError):
        await worker.read(wire, deadline=deadline())


@pytest.mark.parametrize("failure", [errno.ENOTDIR, errno.EIO, errno.EACCES])
@pytest.mark.asyncio
async def test_read_open_invalid_path_is_distinct_from_real_io_failure(stores, monkeypatch, failure):
    from qwenpaw.plugins.execution import payloads
    from qwenpaw.plugins.execution.errors import FrameProtocolError, FrameWriteError

    host, worker = stores()
    _, wire, token = await stage(host)
    original = payloads.os.open

    def fail_selected(path, flags, *args, **kwargs):
        if path == token + ".json" and kwargs.get("dir_fd") == worker._directories["h2w"]:
            raise OSError(failure, "controlled OS open failure")
        return original(path, flags, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(payloads.os, "open", fail_selected)
        expected = FrameProtocolError if failure == errno.ENOTDIR else FrameWriteError
        with pytest.raises(expected):
            await worker.read(wire, deadline=deadline())
    assert (host.root / "h2w" / (token + ".json")).exists()


@pytest.mark.parametrize("failure", [errno.ELOOP, errno.ENOSPC])
@pytest.mark.asyncio
async def test_stage_open_errors_remain_io_failures_without_pending_allocation(stores, monkeypatch, failure):
    from qwenpaw.plugins.execution import payloads
    from qwenpaw.plugins.execution.errors import FrameWriteError

    host, _ = stores()
    original = payloads.os.open

    def fail_selected(path, flags, *args, **kwargs):
        if str(path).endswith(".part") and kwargs.get("dir_fd") == host._directories["h2w"]:
            raise OSError(failure, "controlled stage OS failure")
        return original(path, flags, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(payloads.os, "open", fail_selected)
        with pytest.raises(FrameWriteError):
            await host.stage(json.dumps({"x": "y" * 100}), max_frame_bytes=64, deadline=deadline())
    assert host.pending_snapshot()["pending_files"] == 0
    assert host.pending_snapshot()["pending_bytes"] == 0
    assert not list(host.root.rglob("*.part")) and not list(host.root.rglob("*.json"))
