"""Unmodified bundled Matrix ZIP through native nio and the real Core Agent."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

import psutil
import pytest

from extension_process_suite import eventually, runtime
from extension_sample import ROOT
from g2_actual_agent_suite import assert_host_and_reload, worker_identity
from matrix_formal_support import (
    BOT,
    ROOM,
    SENDER,
    hs,
    matrix_host_guard,
    sync_payload,
    text_event,
)
from real_host_runtime import bind_real_runtime

__all__ = ["runtime", "hs", "matrix_host_guard"]


def formal_source(directory, key, **_kwargs):
    from qwenpaw.plugins.official_channels import bundled_channel_source

    assert key == "matrix"
    with bundled_channel_source(key) as extracted:
        destination = Path(directory) / key
        shutil.copytree(extracted, destination)
    return destination


def assert_original_archive(rt):
    resources = ROOT / "src/qwenpaw/official_channels"
    index = json.loads((resources / "index.json").read_text())
    row = next(row for row in index["plugins"] if row["plugin_id"] == "matrix")
    artifact = resources / row["filename"]
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == row["sha256"]
    members = {}
    with zipfile.ZipFile(artifact) as archive:
        for item in archive.infolist():
            if item.is_dir():
                continue
            relative = Path(item.filename).relative_to("matrix")
            data = archive.read(item)
            assert (rt.source / relative).read_bytes() == data
            assert (
                ROOT / "plugins/channel/matrix" / relative
            ).read_bytes() == data
            members[str(relative)] = hashlib.sha256(data).hexdigest()
    return {"sha256": row["sha256"], "members": members}


@pytest.mark.asyncio
async def test_official_matrix_zip_native_sync_real_agent_and_cleanup(
    runtime, hs, monkeypatch, tmp_path
):
    rt = await runtime(
        "matrix",
        source_factory=formal_source,
        homeserver=hs.url,
        user_id=BOT,
        access_token="formal-matrix-token",
        streaming_enabled=False,
        access_control_dm=True,
    )
    assert rt.record.manifest.id == rt.key == "matrix"
    archive = assert_original_archive(rt)
    old_pid = rt.process.health_snapshot()["pid"]
    host = await bind_real_runtime(rt, monkeypatch)
    assert not psutil.pid_exists(old_pid)
    await eventually(
        lambda: rt.process.health_snapshot()["platform_state"] == "connected"
    )
    initial_syncs = len(hs.calls("/sync"))
    hs.sync.put_nowait((sync_payload("formal-catchup"), 200))
    await eventually(lambda: len(hs.calls("/sync")) > initial_syncs)
    identity = worker_identity(rt, int(hs.url.rsplit(":", 1)[1]))
    rt.channel._get_acl_store().add_to_whitelist("matrix", SENDER)
    native = "Matrix native actual agent"
    hs.sync.put_nowait(
        (
            sync_payload(
                "formal-live", [text_event(native, "$formal-message")]
            ),
            200,
        )
    )
    await eventually(lambda: len(hs.sent) == 1 and len(host.calls) == 1)
    sent = hs.sent[0]
    assert sent["method"] == "PUT"
    assert f"/rooms/{ROOM}/send/m.room.message/" in sent["path"]
    assert sent["body"]["msgtype"] == "m.text"
    assert sent["body"]["body"] == "actual agent answer"
    assert sent["headers"]["Authorization"] == "Bearer formal-matrix-token"
    evidence = await assert_host_and_reload(
        rt, host, native, "matrix:" + ROOM, ROOM
    )
    assert rt.channel._get_acl_store().get_all_pending() == []
    assert rt.ws.requests[0].channel_meta["sender_id"] == SENDER
    assert_original_archive(rt)
    receipt = await rt.manager.stop_one("matrix")
    assert receipt.stopped and receipt.exited and not receipt.residual
    assert not psutil.pid_exists(identity["pid"])
    assert not rt.loader.registry.runtime_owners.leases("matrix")
    evidence.update(worker=identity, artifact=archive, actor=SENDER)
    (tmp_path / "matrix-formal-evidence.json").write_text(
        json.dumps(evidence, indent=2)
    )


@pytest.mark.asyncio
async def test_native_send_refusal_preserves_actual_agent_completion(
    runtime, hs, monkeypatch
):
    """Legacy ordinary send logged failures without ending Agent consumption."""
    rt = await runtime(
        "matrix",
        source_factory=formal_source,
        homeserver=hs.url,
        user_id=BOT,
        access_token="formal-matrix-token",
        streaming_enabled=False,
    )
    assert_original_archive(rt)
    host = await bind_real_runtime(rt, monkeypatch)
    await eventually(
        lambda: rt.process.health_snapshot()["platform_state"] == "connected"
    )
    hs.send.append(
        ({"errcode": "M_FORBIDDEN", "error": "synthetic refusal"}, 403)
    )
    payload = {
        "sender_id": SENDER,
        "session_id": "matrix:" + ROOM,
        "user_id": ROOM,
        "content_parts": [{"type": "text", "text": "refused reply question"}],
        "meta": {"room_id": ROOM, "sender_id": SENDER},
    }
    streamed, errors = [], []
    try:
        async for row in rt.channel._stream_with_tracker(payload):
            streamed.append(json.loads(row.removeprefix("data: ")))
    except Exception as exc:
        errors.append(repr(exc))
    assert len(host.calls) == len(host.builds) == 1
    assert host.builds[0]["agent"] == "QwenPawAgent"
    assert len(hs.sent) == 1
    assert hs.sent[0]["body"]["body"] == "actual agent answer"
    assert any(
        row.get("object") == "message" and row.get("status") == "completed"
        for row in host.events
    )
    assert any(
        row.get("object") == "response" and row.get("status") == "completed"
        for row in host.events
    ), (host.events, errors)
    assert any(
        row.get("object") == "response" and row.get("status") == "completed"
        for row in streamed
    ), (streamed, errors)
    assert errors == []
