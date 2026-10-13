# -*- coding: utf-8 -*-
"""Plugin application state for file-backed EventStream recording."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from qwenpaw.utils.io_utils import run_sync_io
from .errors import RecordingProtocolError, RecordingStateError
from .event_stream import EventStreamClient
from .ingestor import EventStreamArtifact, RecordingIngestor
from .models import RecordingSession, RecordingState
from .session_store import RecordingStore


@dataclass
class _ActiveRecording:
    store: RecordingStore
    recording_id: UUID


@dataclass(frozen=True)
class RecorderSnapshot:
    """In-memory recording state used by the application service."""

    active: RecordingSession | None
    last: RecordingSession | None


class EventStreamDesktopRecorder:
    """Coordinate native EventStream artifacts with the Workspace store."""

    def __init__(
        self,
        client: EventStreamClient,
        *,
        ingestor: RecordingIngestor | None = None,
    ) -> None:
        self._client = client
        self._ingestor = ingestor or RecordingIngestor()
        self._lock = asyncio.Lock()
        self._active: _ActiveRecording | None = None
        self._last_session: RecordingSession | None = None

    async def available(self) -> bool:
        """Whether the host-managed Helper supports EventStream v1."""
        return await self._client.available()

    async def runtime_status(self) -> dict[str, Any]:
        """Return native state and reconcile an externally stopped session."""
        # Bind the response to this session under the lifecycle lock. A slow
        # poll for the previous session must not terminate its successor.
        async with self._lock:
            active = self._active
            try:
                native = await self._client.status(
                    recording_id=str(active.recording_id) if active else None,
                )
            except RecordingProtocolError:
                if active is not None:
                    await self._interrupt_active(
                        active,
                        "event_stream_disconnected",
                    )
                raise
            matches = active is not None and native.get("recording_id") in {
                None,
                str(active.recording_id),
            }
            if (
                active is not None
                and matches
                and (native.get("failure") or native.get("state") == "failed")
            ):
                # Older Helpers may still be capturing when they report a
                # writer failure. Cancel is idempotent with new auto-teardown.
                await self._cancel_and_fail(
                    active,
                    "event_stream_capture_failed",
                )
            elif active is not None and (
                native.get("state") == "idle" or not matches
            ):
                await self._interrupt_active(
                    active,
                    "native_session_stopped",
                )
        return native

    async def request_permissions(self) -> dict[str, Any]:
        """Request the Helper's recording permissions."""
        return await self._client.request(
            "event_stream.permission.request",
            {"operation_id": uuid4().hex},
            timeout=120.0,
        )

    async def start(
        self,
        *,
        workspace_dir: str,
        workspace_id: str,
        user_id: str,
        agent_id: str,
    ) -> RecordingSession:
        """Create the Workspace session, then start native capture."""
        async with self._lock:
            if self._active is not None:
                raise RecordingStateError("a desktop recording is active")
            store = RecordingStore(workspace_dir)
            # A hard backend crash cannot run lifespan cleanup. Repair any
            # unfinished durable session before creating its successor in the
            # same workspace.
            recovered = await run_sync_io(store.recover_unfinished)
            if recovered:
                self._last_session = recovered[-1]
            session = await run_sync_io(
                store.create,
                workspace_id=workspace_id,
                user_id=user_id,
                agent_id=agent_id,
            )
            self._last_session = session
            try:
                result = await self._client.request(
                    "event_stream.start",
                    {
                        "operation_id": uuid4().hex,
                        "recording_id": str(session.recording_id),
                    },
                    timeout=120.0,
                )
                if (
                    result.get("recording_id") != str(session.recording_id)
                    or result.get("state") != "recording"
                ):
                    raise RecordingProtocolError(
                        "EventStream start was not acknowledged",
                    )
                self._active = _ActiveRecording(store, session.recording_id)
                session = await run_sync_io(
                    store.transition,
                    session.recording_id,
                    RecordingState.RECORDING,
                )
                self._last_session = session
                return session
            except BaseException:
                try:
                    await self._client.request(
                        "event_stream.cancel",
                        self._operation_params(session.recording_id),
                    )
                except RecordingProtocolError:
                    pass
                self._last_session = await run_sync_io(
                    store.transition,
                    session.recording_id,
                    RecordingState.FAILED,
                    failure_code="event_stream_start_failed",
                )
                raise

    async def pause(self) -> RecordingSession:
        """Flush the current native segment and pause capture."""
        async with self._lock:
            active = self._require_active()
            session = await run_sync_io(active.store.get, active.recording_id)
            if session.state is not RecordingState.RECORDING:
                raise RecordingStateError("recording is not active")
            try:
                result = await self._client.request(
                    "event_stream.pause",
                    self._operation_params(active.recording_id),
                )
                if result.get("state") != "paused":
                    raise RecordingProtocolError(
                        "EventStream pause was not acknowledged",
                    )
            except BaseException:
                await self._cancel_and_fail(
                    active,
                    "event_stream_pause_failed",
                )
                raise
            session = await run_sync_io(
                active.store.transition,
                active.recording_id,
                RecordingState.PAUSED,
            )
            self._last_session = session
            return session

    async def resume(self) -> RecordingSession:
        """Resume capture into a sequence-contiguous segment."""
        async with self._lock:
            active = self._require_active()
            session = await run_sync_io(active.store.get, active.recording_id)
            if session.state is not RecordingState.PAUSED:
                raise RecordingStateError("recording is not paused")
            try:
                result = await self._client.request(
                    "event_stream.resume",
                    self._operation_params(active.recording_id),
                )
                if result.get("state") != "recording":
                    raise RecordingProtocolError(
                        "EventStream resume was not acknowledged",
                    )
            except BaseException:
                await self._cancel_and_fail(
                    active,
                    "event_stream_resume_failed",
                )
                raise
            session = await run_sync_io(
                active.store.transition,
                active.recording_id,
                RecordingState.RECORDING,
            )
            self._last_session = session
            return session

    async def stop(self) -> RecordingSession:
        """Seal, validate, import, commit, and release one recording."""
        async with self._lock:
            active = self._require_active()
            stop_result: dict[str, Any] | None = None
            try:
                stop_result = await self._client.request(
                    "event_stream.stop",
                    self._operation_params(active.recording_id),
                )
                artifact = EventStreamArtifact.from_stop_result(
                    self._client.artifact_root,
                    stop_result,
                )
                session = await run_sync_io(
                    self._ingestor.import_artifact,
                    active.store,
                    artifact,
                )
                session = await run_sync_io(
                    active.store.transition,
                    session.recording_id,
                    RecordingState.FINALIZING,
                )
                session = await run_sync_io(
                    active.store.complete,
                    session.recording_id,
                )
                # Workspace commit is the durable success boundary. A failed
                # release leaves only a TTL-managed staging copy and must not
                # roll a completed recording back to failed.
                await self._best_effort_release(artifact.events_ref)
                self._last_session = session
                self._active = None
                return session
            except BaseException:
                await self._fail_active(active, "event_stream_stop_failed")
                if stop_result is not None:
                    events_ref = stop_result.get("events_ref")
                    if isinstance(events_ref, str):
                        await self._best_effort_release(events_ref)
                raise

    async def snapshot(self) -> RecorderSnapshot:
        """Return the Python-owned active and latest durable sessions."""
        async with self._lock:
            active = self._active
            current = None
            if active is not None:
                current = await run_sync_io(
                    active.store.get,
                    active.recording_id,
                )
                self._last_session = current
            return RecorderSnapshot(active=current, last=self._last_session)

    async def close(self) -> None:
        """Cancel native capture and mark a live session interrupted."""
        async with self._lock:
            active = self._active
            if active is not None:
                try:
                    await self._client.request(
                        "event_stream.cancel",
                        self._operation_params(active.recording_id),
                    )
                except RecordingProtocolError:
                    pass
                await self._interrupt_active(active, "backend_shutdown")
            await self._client.close()

    async def _fail_active(
        self,
        active: _ActiveRecording,
        failure_code: str,
    ) -> None:
        try:
            session = await run_sync_io(active.store.get, active.recording_id)
            if session.state in {
                RecordingState.RECORDING,
                RecordingState.PAUSED,
                RecordingState.FINALIZING,
            }:
                self._last_session = await run_sync_io(
                    active.store.transition,
                    active.recording_id,
                    RecordingState.FAILED,
                    failure_code=failure_code,
                )
        finally:
            self._active = None

    async def _cancel_and_fail(
        self,
        active: _ActiveRecording,
        failure_code: str,
    ) -> None:
        try:
            await self._client.request(
                "event_stream.cancel",
                self._operation_params(active.recording_id),
            )
        except RecordingProtocolError:
            # If cancellation is uncertain, close the owning connection. This
            # releases capture even with an older Helper and cannot cancel a
            # different connection's recording.
            await self._client.close()
        await self._fail_active(active, failure_code)

    async def _interrupt_active(
        self,
        active: _ActiveRecording,
        failure_code: str,
    ) -> None:
        try:
            session = await run_sync_io(active.store.get, active.recording_id)
            if session.state in {
                RecordingState.RECORDING,
                RecordingState.PAUSED,
                RecordingState.FINALIZING,
            }:
                self._last_session = await run_sync_io(
                    active.store.transition,
                    active.recording_id,
                    RecordingState.INTERRUPTED,
                    failure_code=failure_code,
                )
        finally:
            self._active = None

    async def _best_effort_release(self, events_ref: str) -> None:
        try:
            await self._client.request(
                "event_stream.release",
                {"operation_id": uuid4().hex, "events_ref": events_ref},
            )
        except RecordingProtocolError:
            pass

    def _require_active(self) -> _ActiveRecording:
        if self._active is None:
            raise RecordingStateError("no desktop recording is active")
        return self._active

    @staticmethod
    def _operation_params(recording_id: UUID) -> dict[str, str]:
        return {
            "operation_id": uuid4().hex,
            "recording_id": str(recording_id),
        }


__all__ = ["EventStreamDesktopRecorder"]
