# -*- coding: utf-8 -*-
"""Lifecycle tests for the EventStream application orchestrator."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from record_replay.errors import RecordingProtocolError
from record_replay.event_stream_recorder import EventStreamDesktopRecorder
from record_replay.models import RecordingEvent, RecordingState
from record_replay.session_store import RecordingStore
from record_replay.service import DesktopRecordingService


class _FakeClient:
    def __init__(self, root: Path) -> None:
        """Create a deterministic in-memory EventStream peer."""
        self.artifact_root = root.resolve()
        self.calls: list[str] = []
        self.fail_method: str | None = None
        self.fail_status = False
        self.native_state = "idle"
        self.closed = False

    async def available(self) -> bool:
        """Advertise the test contract."""
        return True

    async def status(
        self,
        *,
        recording_id: str | None = None,
    ) -> dict[str, Any]:
        """Return the minimum native status shape."""
        del recording_id
        if self.fail_status:
            raise RecordingProtocolError("failed:event_stream.status")
        return {
            "available": True,
            "state": self.native_state,
            "permissions": {},
        }

    async def request(
        self,
        method: str,
        params: dict[str, str] | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        """Record one typed request and return a contract-shaped result."""
        self.calls.append(method)
        if method == self.fail_method:
            raise RecordingProtocolError(f"failed:{method}")
        params = params or {}
        recording_id = params.get("recording_id", "")
        if method == "event_stream.start":
            self.native_state = "recording"
            return {"recording_id": recording_id, "state": "recording"}
        if method == "event_stream.pause":
            self.native_state = "paused"
            return {"recording_id": recording_id, "state": "paused"}
        if method == "event_stream.resume":
            self.native_state = "recording"
            return {"recording_id": recording_id, "state": "recording"}
        if method == "event_stream.stop":
            self.native_state = "idle"
            return {
                "recording_id": recording_id,
                "events_ref": f"{recording_id}/events.jsonl",
                "metadata_ref": f"{recording_id}/metadata.json",
                "event_count": 1,
                "dropped_event_count": 0,
                "last_seq": 0,
                "sha256": "0" * 64,
            }
        return {"ok": True}

    async def close(self) -> None:
        """Record connection closure."""
        self.closed = True


class _FakeIngestor:  # pylint: disable=too-few-public-methods
    def import_artifact(self, store: Any, artifact: Any) -> Any:
        """Commit one normalized event without reading staged files."""
        event = RecordingEvent(
            seq=0,
            t_monotonic_ms=1,
            type="scroll",
            input={"delta_y": 1},
        )
        return store.import_events_atomic(
            artifact.recording_id,
            [event],
            dropped_event_count=0,
        )


async def _start(
    recorder: EventStreamDesktopRecorder,
    workspace: Path,
) -> Any:
    return await recorder.start(
        workspace_dir=str(workspace),
        workspace_id="agent",
        user_id="user",
        agent_id="agent",
    )


@pytest.mark.asyncio
async def test_successful_lifecycle_commits_before_release(
    tmp_path: Path,
) -> None:
    """The new runtime preserves the durable product lifecycle."""
    client = _FakeClient(tmp_path / "staging")
    recorder = EventStreamDesktopRecorder(
        client,  # type: ignore[arg-type]
        ingestor=_FakeIngestor(),  # type: ignore[arg-type]
    )

    started = await _start(recorder, tmp_path / "workspace")
    assert started.state is RecordingState.RECORDING
    assert (await recorder.pause()).state is RecordingState.PAUSED
    assert (await recorder.resume()).state is RecordingState.RECORDING
    completed = await recorder.stop()

    assert completed.state is RecordingState.COMPLETED
    assert completed.event_count == 1
    assert client.calls == [
        "event_stream.start",
        "event_stream.pause",
        "event_stream.resume",
        "event_stream.stop",
        "event_stream.release",
    ]


@pytest.mark.asyncio
async def test_pause_protocol_failure_is_fail_closed(tmp_path: Path) -> None:
    """An uncertain pause cannot leave an invisible native recording alive."""
    client = _FakeClient(tmp_path / "staging")
    recorder = EventStreamDesktopRecorder(client)  # type: ignore[arg-type]
    await _start(recorder, tmp_path / "workspace")
    client.fail_method = "event_stream.pause"

    with pytest.raises(RecordingProtocolError):
        await recorder.pause()

    snapshot = await recorder.snapshot()
    assert snapshot.active is None
    assert snapshot.last is not None
    assert snapshot.last.state is RecordingState.FAILED
    assert snapshot.last.failure_code == "event_stream_pause_failed"
    assert client.calls[-1] == "event_stream.cancel"


@pytest.mark.asyncio
async def test_close_cancels_and_marks_interrupted(tmp_path: Path) -> None:
    """Backend shutdown preserves crash semantics and releases ownership."""
    client = _FakeClient(tmp_path / "staging")
    recorder = EventStreamDesktopRecorder(client)  # type: ignore[arg-type]
    await _start(recorder, tmp_path / "workspace")

    await recorder.close()

    snapshot = await recorder.snapshot()
    assert snapshot.active is None
    assert snapshot.last is not None
    assert snapshot.last.state is RecordingState.INTERRUPTED
    assert snapshot.last.failure_code == "backend_shutdown"
    assert client.calls[-1] == "event_stream.cancel"
    assert client.closed is True


@pytest.mark.asyncio
async def test_status_reconciles_native_emergency_stop(tmp_path: Path) -> None:
    """Polling observes the Helper's local Stop action without reverse RPC."""
    client = _FakeClient(tmp_path / "staging")
    recorder = EventStreamDesktopRecorder(client)  # type: ignore[arg-type]
    await _start(recorder, tmp_path / "workspace")
    client.native_state = "idle"

    await recorder.runtime_status()

    snapshot = await recorder.snapshot()
    assert snapshot.active is None
    assert snapshot.last is not None
    assert snapshot.last.state is RecordingState.INTERRUPTED
    assert snapshot.last.failure_code == "native_session_stopped"


@pytest.mark.asyncio
async def test_status_disconnect_interrupts_active_session(
    tmp_path: Path,
) -> None:
    """A lost Helper cannot leave Python reporting active capture."""
    client = _FakeClient(tmp_path / "staging")
    recorder = EventStreamDesktopRecorder(client)  # type: ignore[arg-type]
    await _start(recorder, tmp_path / "workspace")
    client.fail_status = True

    with pytest.raises(RecordingProtocolError):
        await recorder.runtime_status()

    snapshot = await recorder.snapshot()
    assert snapshot.active is None
    assert snapshot.last is not None
    assert snapshot.last.state is RecordingState.INTERRUPTED
    assert snapshot.last.failure_code == "event_stream_disconnected"


@pytest.mark.asyncio
async def test_start_recovers_a_crash_left_session(tmp_path: Path) -> None:
    """A new session cannot strand an older workspace state as active."""
    workspace = tmp_path / "workspace"
    first_client = _FakeClient(tmp_path / "staging-1")
    first = EventStreamDesktopRecorder(first_client)  # type: ignore[arg-type]
    old = await _start(first, workspace)

    second_client = _FakeClient(tmp_path / "staging-2")
    second = EventStreamDesktopRecorder(
        second_client,  # type: ignore[arg-type]
    )
    current = await _start(second, workspace)

    recovered = RecordingStore(workspace).get(old.recording_id)
    assert recovered.state is RecordingState.INTERRUPTED
    assert recovered.failure_code == "process_interrupted"
    assert current.state is RecordingState.RECORDING


@pytest.mark.asyncio
async def test_startup_recovery_deduplicates_workspaces(
    tmp_path: Path,
) -> None:
    """Backend startup repairs each configured workspace exactly once."""
    workspace = tmp_path / "workspace"
    store = RecordingStore(workspace)
    session = store.create(
        workspace_id="agent",
        user_id="user",
        agent_id="agent",
    )
    store.transition(session.recording_id, RecordingState.RECORDING)

    count = await DesktopRecordingService.recover_workspaces(
        [workspace, workspace],
    )

    assert count == 1
    assert store.get(session.recording_id).state is RecordingState.INTERRUPTED


@pytest.mark.asyncio
async def test_native_writer_failure_must_not_remain_recording(
    tmp_path: Path,
) -> None:
    """A known failure must close capture and reach a visible failed state."""

    class FailedWriterClient(_FakeClient):
        async def status(
            self,
            *,
            recording_id: str | None = None,
        ) -> dict[str, Any]:
            return {
                **await super().status(recording_id=recording_id),
                "failure": "failed to append staged event",
            }

    client = FailedWriterClient(tmp_path / "staging")
    recorder = EventStreamDesktopRecorder(client)  # type: ignore[arg-type]
    await _start(recorder, tmp_path / "workspace")
    try:
        await recorder.runtime_status()
        snapshot = await recorder.snapshot()
        assert snapshot.active is None
        assert snapshot.last.state is RecordingState.FAILED
        assert any(call == "event_stream.cancel" for call in client.calls)
    finally:
        await recorder.close()


@pytest.mark.asyncio
async def test_import_enospc_marks_failed_and_releases_staging(
    tmp_path: Path,
) -> None:
    """Import failure cannot be acknowledged as a completed recording."""
    import errno

    class NoSpaceIngestor:
        def import_artifact(self, *_args: Any) -> Any:
            raise OSError(errno.ENOSPC, "isolated ENOSPC fixture")

    client = _FakeClient(tmp_path / "staging")
    recorder = EventStreamDesktopRecorder(
        client,  # type: ignore[arg-type]
        ingestor=NoSpaceIngestor(),
    )
    await _start(recorder, tmp_path / "workspace")
    try:
        with pytest.raises(OSError) as error:
            await recorder.stop()
        assert error.value.errno == errno.ENOSPC
        snapshot = await recorder.snapshot()
        assert snapshot.active is None
        assert snapshot.last.state is RecordingState.FAILED
        assert client.native_state == "idle"
        assert "event_stream.release" in client.calls
    finally:
        await recorder.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_fails", [False, True])
async def test_scoped_terminal_failure_closes_owner(
    tmp_path: Path,
    cancel_fails: bool,
) -> None:
    class TerminalClient(_FakeClient):
        queried_id: str | None = None

        async def status(
            self,
            *,
            recording_id: str | None = None,
        ) -> dict[str, Any]:
            self.queried_id = recording_id
            return {
                "state": "failed",
                "recording_id": recording_id,
                "failure": "unsafe private OS error",
                "available": True,
                "permissions": {},
            }

    client = TerminalClient(tmp_path / "staging")
    recorder = EventStreamDesktopRecorder(client)  # type: ignore[arg-type]
    session = await _start(recorder, tmp_path / "workspace")
    if cancel_fails:
        client.fail_method = "event_stream.cancel"
    service = DesktopRecordingService(event_stream_recorder=recorder)
    try:
        status = await service.status()
        assert client.queried_id == str(session.recording_id)
        assert status.state == "failed" and status.recording is None
        assert (
            status.last_recording.failure_code == "event_stream_capture_failed"
        )
        assert "unsafe private" not in status.model_dump_json()
        assert client.closed is cancel_fails
    finally:
        await recorder.close()


@pytest.mark.asyncio
async def test_other_recording_failure_does_not_cancel_or_fail_this_session(
    tmp_path: Path,
) -> None:
    class OtherRecordingClient(_FakeClient):
        async def status(self, **_kwargs: Any) -> dict[str, Any]:
            return {
                "state": "recording",
                "recording_id": "other-session",
                "failure": "staging_failed",
            }

    client = OtherRecordingClient(tmp_path / "staging")
    recorder = EventStreamDesktopRecorder(client)  # type: ignore[arg-type]
    await _start(recorder, tmp_path / "workspace")
    await recorder.runtime_status()
    snapshot = await recorder.snapshot()
    assert snapshot.last.state is RecordingState.INTERRUPTED
    assert "event_stream.cancel" not in client.calls
    await recorder.close()


@pytest.mark.asyncio
async def test_old_status_poll_cannot_interrupt_a_new_session(
    tmp_path: Path,
) -> None:
    entered, release = asyncio.Event(), asyncio.Event()

    class SlowClient(_FakeClient):
        async def status(self, **_kwargs: Any) -> dict[str, Any]:
            entered.set()
            await release.wait()
            return {"state": "idle"}

    client = SlowClient(tmp_path / "staging")
    recorder = EventStreamDesktopRecorder(client)  # type: ignore[arg-type]
    poll = asyncio.create_task(recorder.runtime_status())
    await entered.wait()
    start = asyncio.create_task(_start(recorder, tmp_path / "workspace"))
    try:
        await asyncio.sleep(0)
        assert not start.done()
        release.set()
        await poll
        await start
        assert (
            await recorder.snapshot()
        ).active.state is RecordingState.RECORDING
    finally:
        release.set()
        await asyncio.gather(poll, start)
        await recorder.close()


@pytest.mark.asyncio
async def test_failed_staging_release_does_not_roll_back_workspace_commit(
    tmp_path: Path,
) -> None:
    client = _FakeClient(tmp_path / "staging")
    client.fail_method = "event_stream.release"
    recorder = EventStreamDesktopRecorder(
        client,  # type: ignore[arg-type]
        ingestor=_FakeIngestor(),
    )
    await _start(recorder, tmp_path / "workspace")
    try:
        assert (await recorder.stop()).state is RecordingState.COMPLETED
        assert (await recorder.snapshot()).active is None
    finally:
        await recorder.close()


@pytest.mark.asyncio
async def test_native_status_query_scopes_recording_id() -> None:
    from unittest.mock import AsyncMock
    from record_replay.event_stream import EventStreamClient

    client = EventStreamClient()
    client.request = AsyncMock(return_value={"state": "failed"})
    await client.status(recording_id="fixture")
    client.request.assert_awaited_once_with(
        "event_stream.status",
        {"recording_id": "fixture"},
    )
