# -*- coding: utf-8 -*-
"""Authorized local output through the real isolated Telegram worker."""

import base64
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest

from telegram_support import (
    runtime,
    telegram_sdk,
    fault_runtime,
    telegram,
    rows,
)

__all__ = ["runtime", "telegram_sdk", "fault_runtime"]


@pytest.mark.asyncio
async def test_authorized_project_file_reaches_real_telegram_worker(
    runtime,
    telegram_sdk,
    tmp_path,
    monkeypatch,
):
    from qwenpaw.agents.tools.send_file import send_file_to_user
    from qwenpaw.config.context import (
        set_current_project_dir,
        set_current_workspace_dir,
    )
    from qwenpaw.app.channels.renderer import MessageRenderer
    from qwenpaw.schemas import Message, MessageType, DataContent

    rt = await telegram(runtime, telegram_sdk)
    project = tmp_path / "external-authorized-project"
    project.mkdir()
    source = project / "季度 report.pdf"
    payload = b"%PDF-outbound-media-regression\x00\xff"
    source.write_bytes(payload)
    # Inject already-authorized turn context, not a governance decision.
    set_current_project_dir(project)
    set_current_workspace_dir(rt.ws.workspace_dir)
    try:
        output = await send_file_to_user(source.name)
        message = Message(
            type=MessageType.FUNCTION_CALL_OUTPUT,
            content=[
                DataContent(
                    data={
                        "name": "SendFileToUser",
                        "output": output.content,
                    }
                )
            ],
        )
        parts = MessageRenderer().message_to_parts(message)
        part = next(p for p in parts if p.type.value == "file")
        # The success expectation must exercise the actual worker, even on RED.
        await rt.channel.send_media("12345", part, {})
        sent = rows(telegram_sdk.work, "sendDocument")[-1]["files"]["document"]
        assert base64.b64decode(sent["bytes_b64"]) == payload
        assert sent["filename"] == source.name
        assert sent["mime"] == "application/pdf"
        snapshot = Path(unquote(urlparse(part.file_url).path))
        assert snapshot.is_relative_to(rt.ws.workspace_dir / "media")
        assert snapshot.is_file() and not snapshot.is_symlink()
        assert snapshot.stat().st_ino != source.stat().st_ino
        source.write_bytes(b"changed after tool completion")
        assert snapshot.read_bytes() == payload
        source.unlink()
        await rt.channel.send_media("12345", part, {})
        resent = rows(telegram_sdk.work, "sendDocument")[-1]["files"][
            "document"
        ]
        assert base64.b64decode(resent["bytes_b64"]) == payload
        assert part.file_url == snapshot.as_uri()
        from qwenpaw.utils import outbound_media as store

        future = store.time.time() + store.OUTBOUND_MEDIA_TTL_SECONDS * 2
        monkeypatch.setattr(store.time, "time", lambda: future)
        await store.cleanup_outbound_media(rt.ws.workspace_dir)
        assert (
            not snapshot.exists()
        ), "successful platform ACK must release lifecycle pin"
    finally:
        set_current_project_dir(None)
        set_current_workspace_dir(None)


@pytest.mark.asyncio
async def test_worker_rejects_raw_outside_cross_workspace_and_symlink_urls(
    runtime,
    telegram_sdk,
    tmp_path,
):
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError

    rt = await telegram(runtime, telegram_sdk)
    outside = tmp_path / "arbitrary-secret.pdf"
    outside.write_bytes(b"not an authorized tool output")
    other_workspace = tmp_path / "another-workspace" / "media"
    other_workspace.mkdir(parents=True)
    cross_workspace = other_workspace / "private.pdf"
    cross_workspace.write_bytes(b"another workspace")
    media = rt.ws.workspace_dir / "media"
    media.mkdir(exist_ok=True)
    link = media / "outside-link.pdf"
    link.symlink_to(outside)
    for source in (outside, cross_workspace, link):
        with pytest.raises(
            ChannelDeliveryError, match="MEDIA_PATH_UNAUTHORIZED"
        ):
            await rt.channel.send_media(
                "12345",
                {"type": "file", "file_url": source.as_uri()},
                {},
            )
    assert rows(telegram_sdk.work, "sendDocument") == []


@pytest.mark.asyncio
async def test_existing_internal_remote_and_data_media_remain_compatible(
    runtime,
    telegram_sdk,
):
    rt = await telegram(runtime, telegram_sdk)
    media = rt.ws.workspace_dir / "media"
    media.mkdir(exist_ok=True)
    internal = media / "existing.pdf"
    internal.write_bytes(b"existing internal file")
    await rt.channel.send_media(
        "12345",
        {"type": "file", "file_url": internal.as_uri()},
        {},
    )
    sent = rows(telegram_sdk.work, "sendDocument")[-1]["files"]["document"]
    assert base64.b64decode(sent["bytes_b64"]) == internal.read_bytes()
    remote = "https://example.test/original.pdf"
    await rt.channel.send_media(
        "12345",
        {"type": "file", "file_url": remote},
        {},
    )
    assert (
        rows(telegram_sdk.work, "sendDocument")[-1]["arguments"]["document"]
        == remote
    )
    await rt.channel.send_media(
        "12345",
        {"type": "file", "file_url": "data:application/pdf;base64,cGRm"},
        {},
    )
    sent = rows(telegram_sdk.work, "sendDocument")[-1]["files"]["document"]
    assert base64.b64decode(sent["bytes_b64"]) == b"pdf"


@pytest.mark.asyncio
async def test_real_governance_deny_does_not_stage_file(tmp_path):
    from agentscope.permission import PermissionBehavior
    from qwenpaw.agents.tools.send_file import send_file_to_user
    from qwenpaw.config.context import (
        set_current_project_dir,
        set_current_workspace_dir,
    )
    from qwenpaw.governance import PolicyGuardedTool, ResourceGovernor
    from qwenpaw.governance.policy import (
        GovernanceAction,
        GovernancePolicy,
        GovernanceRule,
    )

    workspace = tmp_path / "workspace"
    project = tmp_path / "project"
    workspace.mkdir()
    project.mkdir()
    source = project / "denied.pdf"
    source.write_bytes(b"denied data")
    governor = ResourceGovernor(
        str(workspace),
        governance_dir=str(tmp_path / "governance"),
        coding_project_dir=str(project),
    )
    governor._policy = GovernancePolicy(
        builtin_rules=[
            GovernanceRule(
                match=f"SendFileToUser({source.resolve()})",
                action=GovernanceAction.DENY,
            )
        ],
    )
    tool = PolicyGuardedTool(send_file_to_user, governor=governor)
    set_current_project_dir(project)
    set_current_workspace_dir(workspace)
    try:
        permission = await tool.check_permissions({"file_path": source.name})
        assert permission.behavior == PermissionBehavior.DENY
        assert tool._qp_tc_spec.tool_name == "SendFileToUser"
        assert not (workspace / "media").exists()
        assert source.read_bytes() == b"denied data"
    finally:
        set_current_project_dir(None)
        set_current_workspace_dir(None)


@pytest.fixture
def snapshot_context(tmp_path):
    from qwenpaw.config.context import set_current_workspace_dir

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = tmp_path / "report.pdf"
    source.write_bytes(b"snapshot payload")
    set_current_workspace_dir(workspace)
    try:
        yield workspace, source
    finally:
        set_current_workspace_dir(None)


@pytest.mark.asyncio
async def test_snapshot_lifetime_multiple_consumers_and_bounded_storage(
    snapshot_context,
    monkeypatch,
):
    from qwenpaw.utils import outbound_media as store

    workspace, source = snapshot_context
    clock = [1000.0]
    monkeypatch.setattr(store.time, "time", lambda: clock[0])
    snapshot = await store.stage_outbound_file(source)
    parts = [{"type": "file", "file_url": snapshot.as_uri()}]
    ordinary = workspace / "media" / "unrelated.pdf"
    ordinary.write_bytes(b"must survive cleanup")
    assert await store.stage_outbound_file(ordinary) == ordinary
    await store.update_outbound_media(
        workspace, parts, "consumer-A", pending=True
    )
    await store.update_outbound_media(
        workspace, parts, "consumer-B", pending=True
    )
    clock[0] += store.OUTBOUND_MEDIA_TTL_SECONDS + 1
    await store.cleanup_outbound_media(workspace)
    assert snapshot.read_bytes() == source.read_bytes()
    await store.update_outbound_media(
        workspace, parts, "consumer-A", pending=False
    )
    clock[0] += store.OUTBOUND_MEDIA_TTL_SECONDS + 1
    await store.cleanup_outbound_media(workspace)
    assert snapshot.exists(), "consumer B still owns unresolved delivery"
    monkeypatch.setattr(store, "OUTBOUND_MEDIA_MAX_FILES", 1)
    with pytest.raises(ValueError, match="quota"):
        await store.stage_outbound_file(source)
    assert snapshot.exists(), "quota pressure must not evict pending delivery"
    await store.update_outbound_media(
        workspace, parts, "consumer-B", pending=False
    )
    await store.cleanup_outbound_media(workspace)
    assert snapshot.exists(), "definitive settlement starts a fresh retry TTL"
    clock[0] += store.OUTBOUND_MEDIA_TTL_SECONDS + 1
    await store.cleanup_outbound_media(workspace)
    assert not snapshot.exists()
    assert ordinary.read_bytes() == b"must survive cleanup"
    monkeypatch.setattr(store, "OUTBOUND_MEDIA_MAX_BYTES", 1)
    with pytest.raises(ValueError, match="quota"):
        await store.stage_outbound_file(source)
    assert not list((workspace / "media" / "outbound").iterdir())


@pytest.mark.asyncio
async def test_failed_copy_removes_partial_and_returns_no_attachment(
    snapshot_context,
    monkeypatch,
):
    from qwenpaw.agents.tools.send_file import send_file_to_user

    workspace, source = snapshot_context
    original_open = Path.open

    def failing_open(path, *args, **kwargs):
        if path.name == ".part":
            raise OSError("controlled disk failure")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failing_open)
    result = await send_file_to_user(str(source))
    assert not any(
        getattr(block, "type", None) == "data" for block in result.content
    )
    assert "controlled disk failure" in str(result.content)
    assert not list((workspace / "media" / "outbound").iterdir())


@pytest.mark.asyncio
async def test_cancelled_copy_waits_for_handle_close_and_removes_snapshot(
    snapshot_context,
    monkeypatch,
):
    import asyncio
    import threading
    from qwenpaw.utils import outbound_media as store

    workspace, source = snapshot_context
    entered, release = threading.Event(), threading.Event()
    closed = threading.Event()
    original_open, original_remove = Path.open, store._remove

    class DelayedTarget:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            self.handle.__enter__()
            return self

        def __exit__(self, *args):
            try:
                return self.handle.__exit__(*args)
            finally:
                closed.set()

        def write(self, data):
            result = self.handle.write(data)
            entered.set()
            assert release.wait(5)
            return result

    def delayed_open(path, *args, **kwargs):
        handle = original_open(path, *args, **kwargs)
        return DelayedTarget(handle) if path.name == ".part" else handle

    def remove_after_close(*args):
        assert (
            closed.is_set()
        ), "Windows requires copy handle closed before unlink"
        return original_remove(*args)

    monkeypatch.setattr(Path, "open", delayed_open)
    monkeypatch.setattr(store, "_remove", remove_after_close)
    task = asyncio.create_task(store.stage_outbound_file(source))
    try:
        for _ in range(200):
            if entered.is_set():
                break
            await asyncio.sleep(0.01)
        assert entered.is_set()
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not list((workspace / "media" / "outbound").iterdir())
    finally:
        release.set()
        if not task.done():
            await task


@pytest.mark.asyncio
async def test_real_worker_unknown_delivery_pins_snapshot_across_expiry(
    runtime,
    telegram_sdk,
    tmp_path,
    monkeypatch,
):
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError
    from qwenpaw.config.context import set_current_workspace_dir
    from qwenpaw.utils import outbound_media as store
    from telegram_support import set_mode

    rt = await telegram(runtime, telegram_sdk)
    source = tmp_path / "unknown.pdf"
    source.write_bytes(b"platform may already have received these bytes")
    set_current_workspace_dir(rt.ws.workspace_dir)
    try:
        snapshot = await store.stage_outbound_file(source)
    finally:
        set_current_workspace_dir(None)
    part = {
        "type": "file",
        "file_url": snapshot.as_uri(),
        "filename": source.name,
    }
    set_mode(telegram_sdk.work, "sendDocument-server")
    meta = {}
    with pytest.raises(ChannelDeliveryError) as failure:
        await rt.channel.send_media("12345", part, meta)
    assert failure.value.state == "unknown"
    assert len(rows(telegram_sdk.work, "sendDocument")) == 1
    import time

    future = time.time() + store.OUTBOUND_MEDIA_TTL_SECONDS * 2
    monkeypatch.setattr(store.time, "time", lambda: future)
    await store.cleanup_outbound_media(rt.ws.workspace_dir)
    assert snapshot.read_bytes() == source.read_bytes()
    with pytest.raises(ChannelDeliveryError):
        await rt.channel.send_media("12345", part, meta)
    assert len(rows(telegram_sdk.work, "sendDocument")) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,extension,mime",
    [
        ("video", ".mp4", "video/mp4"),
        ("audio", ".wav", None),
    ],
)
async def test_analogous_local_media_tools_snapshot_bytes_name_and_mime(
    snapshot_context,
    monkeypatch,
    kind,
    extension,
    mime,
):
    from types import SimpleNamespace
    import qwenpaw.config
    from qwenpaw.agents.tools import view_media

    workspace, original = snapshot_context
    source = original.with_suffix(extension)
    source.write_bytes(b"local media bytes")
    monkeypatch.setattr(
        view_media, "_check_multimodal_support", lambda *_: True
    )
    monkeypatch.setattr(
        qwenpaw.config,
        "load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(audio_mode="native"),
        ),
    )
    result = await getattr(view_media, f"view_{kind}")(str(source))
    block = next(block for block in result.content if block.type == "data")
    snapshot = Path(unquote(urlparse(str(block.source.url)).path))
    assert snapshot.is_relative_to(workspace / "media" / "outbound")
    assert snapshot.name == source.name
    if mime is None:
        import mimetypes

        mime = mimetypes.guess_type(source.name)[0]
        assert mime.startswith("audio/")
    assert block.source.media_type == mime
    assert snapshot.read_bytes() == source.read_bytes()
    source.unlink()
    assert snapshot.read_bytes() == b"local media bytes"


@pytest.mark.asyncio
async def test_invalid_and_missing_sources_never_create_attachment(
    snapshot_context,
):
    from qwenpaw.agents.tools.send_file import send_file_to_user

    workspace, source = snapshot_context
    for value in (
        str(source.with_name("missing.pdf")),
        str(source.parent),
        "bad\x00path",
    ):
        result = await send_file_to_user(value)
        assert not any(
            getattr(block, "type", None) == "data" for block in result.content
        )
    assert not (workspace / "media").exists()


@pytest.mark.asyncio
async def test_authorized_symlink_source_is_an_independent_snapshot(
    snapshot_context,
):
    from qwenpaw.utils import outbound_media as store

    workspace, source = snapshot_context
    link = source.with_name("authorized-link.pdf")
    link.symlink_to(source)
    snapshot = await store.stage_outbound_file(link)
    assert snapshot.is_relative_to(workspace / "media" / "outbound")
    assert not snapshot.is_symlink()
    assert snapshot.stat().st_ino != source.stat().st_ino
    assert snapshot.read_bytes() == source.read_bytes()
    source.unlink()
    assert snapshot.read_bytes() == b"snapshot payload"


@pytest.mark.asyncio
async def test_gc_preserves_lookalike_user_directory(snapshot_context):
    import json
    from qwenpaw.utils import outbound_media as store

    workspace, source = snapshot_context
    snapshot = await store.stage_outbound_file(source)
    assert snapshot.read_bytes() == source.read_bytes()
    user_directory = (
        workspace / "media" / "outbound" / "user-authored-directory"
    )
    user_directory.mkdir()
    user_file = user_directory / "notes.pdf"
    user_file.write_bytes(b"user-owned")
    (user_directory / ".state.json").write_text(
        json.dumps(
            {
                "name": user_file.name,
                "pending": [],
                "expires_at": 0,
            }
        )
    )
    await store.cleanup_outbound_media(workspace)
    assert user_file.read_bytes() == b"user-owned"


@pytest.mark.asyncio
async def test_ack_survives_release_state_write_failure(
    runtime,
    telegram_sdk,
    tmp_path,
    monkeypatch,
):
    import json
    from qwenpaw.config.context import set_current_workspace_dir
    from qwenpaw.utils import outbound_media as store

    rt = await telegram(runtime, telegram_sdk)
    source = tmp_path / "acknowledged.pdf"
    payload = b"platform acknowledged exactly once"
    source.write_bytes(payload)
    set_current_workspace_dir(rt.ws.workspace_dir)
    try:
        snapshot = await store.stage_outbound_file(source)
    finally:
        set_current_workspace_dir(None)
    state_path = snapshot.parent.parent / ".state.json"
    original_write = store.write_json_atomic
    rejected = []

    def reject_release(path, state, *args, **kwargs):
        if Path(path) == state_path and not state["pending"]:
            rejected.append(state)
            raise PermissionError("controlled release sidecar failure")
        return original_write(path, state, *args, **kwargs)

    monkeypatch.setattr(store, "write_json_atomic", reject_release)
    meta = {}
    await rt.channel.send_media(
        "12345",
        {"type": "file", "file_url": snapshot.as_uri()},
        meta,
    )
    assert len(rejected) == 1
    delivery_id = meta["_last_delivery_id"]
    assert delivery_id and "_pending_delivery" not in meta
    assert not meta.get("_reply_unknown")
    sent = rows(telegram_sdk.work, "sendDocument")
    assert len(sent) == 1
    document = sent[0]["files"]["document"]
    assert base64.b64decode(document["bytes_b64"]) == payload
    state = json.loads(state_path.read_text())
    assert state["pending"] == [delivery_id]
    future = store.time.time() + store.OUTBOUND_MEDIA_TTL_SECONDS * 2
    monkeypatch.setattr(store.time, "time", lambda: future)
    await store.cleanup_outbound_media(rt.ws.workspace_dir)
    assert snapshot.read_bytes() == payload
    assert json.loads(state_path.read_text())["pending"] == [delivery_id]
    assert len(rows(telegram_sdk.work, "sendDocument")) == 1
