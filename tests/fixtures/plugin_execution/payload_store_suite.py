"""Actual private files, closed refs and disk ownership; no IPC substitutes."""

import asyncio
import hashlib
import json
import os
import stat

import pytest
import pytest_asyncio


def deadline():
    return asyncio.get_running_loop().time() + 2


@pytest_asyncio.fixture
async def stores():
    from qwenpaw.plugins.execution.payloads import PayloadStore

    owned = []

    def make(limits=None):
        host = PayloadStore.create(limits)
        worker = PayloadStore.attach(host.launch_context())
        owned.append((host, worker))
        return host, worker

    yield make
    for host, worker in owned:
        assert await worker.cleanup(deadline=deadline())
        assert await host.cleanup(deadline=deadline())
        assert not host.root.exists()


async def stage(store, text=None):
    text = text or json.dumps({"text": "原文" * 100}, ensure_ascii=False)
    wire, token = await store.stage(text, max_frame_bytes=64, deadline=deadline())
    return text, wire, token


@pytest.mark.asyncio
async def test_reference_closed_shape_readonly_atomic_file_and_plain_wire(stores):
    host, worker = stores()
    small = '{"text":" 小 "}'
    assert await host.stage(small, max_frame_bytes=1024, deadline=deadline()) == (small, None)
    text, wire, token = await stage(host)
    ref = json.loads(wire)
    assert set(ref) == {"$qwenpaw_payload", "run_id", "direction", "id", "byte_length", "sha256"}
    assert ref == {
        "$qwenpaw_payload": 1, "run_id": host.run_id, "direction": "h2w", "id": token,
        "byte_length": len(text.encode()), "sha256": hashlib.sha256(text.encode()).hexdigest(),
    }
    assert len(token) == 32 and all(c in "0123456789abcdef" for c in token)
    assert str(host.root) not in wire
    path = host.root / "h2w" / (token + ".json")
    assert path.read_bytes() == text.encode()
    assert stat.S_IMODE(path.stat().st_mode) == 0o400
    assert not list(host.root.rglob("*.part"))
    assert await worker.read(wire, deadline=deadline()) == text
    assert not path.exists()
    assert host.pending_snapshot()["pending_files"] == host.pending_snapshot()["pending_bytes"] == 0


@pytest.mark.parametrize("mutation", ["extra_path", "run", "direction", "id", "length", "digest", "bool_marker", "duplicate"])
@pytest.mark.asyncio
async def test_forged_reference_rejected_without_consuming_valid_payload(stores, mutation):
    from qwenpaw.plugins.execution.errors import FrameProtocolError

    host, worker = stores()
    text, wire, token = await stage(host)
    ref = json.loads(wire)
    if mutation == "extra_path": ref["path"] = "/etc/passwd"
    elif mutation == "run": ref["run_id"] = "0" * 32
    elif mutation == "direction": ref["direction"] = "w2h"
    elif mutation == "id": ref["id"] = "../outside"
    elif mutation == "length": ref["byte_length"] += 1
    elif mutation == "digest": ref["sha256"] = "0" * 64
    elif mutation == "bool_marker": ref["$qwenpaw_payload"] = True
    bad = json.dumps(ref)
    if mutation == "duplicate": bad = bad[:-1] + ',"id":"' + token + '"}'
    with pytest.raises(FrameProtocolError):
        await worker.read(bad, deadline=deadline())
    assert (host.root / "h2w" / (token + ".json")).exists()
    assert await worker.read(wire, deadline=deadline()) == text


@pytest.mark.parametrize("body", [b'"\xff"', b'{"number":NaN}'])
@pytest.mark.asyncio
async def test_digest_valid_but_invalid_utf8_or_strict_json_rejected(stores, body):
    from qwenpaw.plugins.execution.errors import FrameProtocolError

    host, worker = stores()
    _, wire, token = await stage(host)
    path = host.root / "h2w" / (token + ".json")
    path.chmod(0o600); path.write_bytes(body); path.chmod(0o400)
    ref = json.loads(wire)
    ref.update(byte_length=len(body), sha256=hashlib.sha256(body).hexdigest())
    with pytest.raises(FrameProtocolError):
        await worker.read(json.dumps(ref), deadline=deadline())
    assert path.exists()


@pytest.mark.parametrize("kind", ["fifo", "hardlink", "symlink"])
@pytest.mark.asyncio
async def test_nonregular_or_aliased_payload_rejected_without_hang(stores, tmp_path, kind):
    from qwenpaw.plugins.execution.errors import FrameProtocolError

    host, worker = stores()
    text, wire, token = await stage(host)
    path = host.root / "h2w" / (token + ".json")
    outside = tmp_path / "unrelated"
    outside.write_text(text); outside.chmod(0o400)
    path.unlink()
    if kind == "fifo": os.mkfifo(path, 0o400)
    elif kind == "hardlink": os.link(outside, path)
    else: path.symlink_to(outside)
    with pytest.raises(FrameProtocolError):
        await asyncio.wait_for(worker.read(wire, deadline=deadline()), 1)
    assert outside.read_text() == text
    path.unlink()


@pytest.mark.parametrize("quota", ["bytes", "files"])
@pytest.mark.asyncio
async def test_direction_quota_released_after_consumption_and_independent(stores, quota):
    from qwenpaw.plugins.execution.errors import FrameLimitError
    from qwenpaw.plugins.execution.payloads import PayloadLimits

    text = json.dumps({"text": "x" * 100})
    size = len(text.encode())
    host, worker = stores(PayloadLimits(max_message_bytes=1024, max_pending_bytes=size if quota == "bytes" else 4096, max_pending_files=1 if quota == "files" else 4))
    _, wire, _ = await stage(host, text)
    with pytest.raises(FrameLimitError): await stage(host, text)
    assert host.pending_snapshot()["pending_files"] == 1
    assert host.pending_snapshot()["pending_bytes"] == size
    _, reverse, _ = await stage(worker, text)
    assert worker.pending_snapshot()["pending_files"] == 1
    assert await worker.read(wire, deadline=deadline()) == text
    assert await host.read(reverse, deadline=deadline()) == text
    assert host.pending_snapshot()["pending_bytes"] == worker.pending_snapshot()["pending_bytes"] == 0
    _, retry, _ = await stage(host, text)
    assert await worker.read(retry, deadline=deadline()) == text


@pytest.mark.asyncio
async def test_close_fences_new_writes_but_retains_unread_data_until_cleanup(stores):
    from qwenpaw.plugins.execution.errors import FrameClosedError

    host, worker = stores()
    text, wire, token = await stage(host)
    path = host.root / "h2w" / (token + ".json")
    host.close()
    assert path.exists()
    with pytest.raises(FrameClosedError): await stage(host)
    assert await worker.read(wire, deadline=deadline()) == text
    assert not path.exists()


@pytest.mark.asyncio
async def test_expired_deadline_has_no_published_or_partial_payload(stores):
    from qwenpaw.plugins.execution.errors import FrameTimeoutError

    host, _ = stores()
    with pytest.raises(FrameTimeoutError):
        await host.stage(json.dumps({"x": "y" * 100}), max_frame_bytes=64, deadline=asyncio.get_running_loop().time() - 1)
    # Cleanup joins the real I/O worker before making a residue claim.
    assert await host.cleanup(deadline=deadline())
    assert not host.root.exists()
