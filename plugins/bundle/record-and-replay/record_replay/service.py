# -*- coding: utf-8 -*-
"""Plugin-facing orchestration for desktop recording."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from .errors import RecordingProtocolError
from .event_stream_recorder import EventStreamDesktopRecorder
from .models import RecordingDescriptor, RecordingSession, RecordingStatus
from .session_store import RecordingStore
from qwenpaw.utils.io_utils import run_sync_io


class DesktopRecordingService:
    """Stable product boundary over the shared EventStream recorder."""

    def __init__(
        self,
        *,
        event_stream_recorder: EventStreamDesktopRecorder,
    ) -> None:
        self._recorder = event_stream_recorder
        self._negotiated = False

    async def _available(self) -> bool:
        # Probe lazily before first use. Once negotiated, let the client's
        # normal reconnect/error path handle outages; do not hide active
        # session failures behind an unavailable/idle placeholder.
        if not self._negotiated:
            if await self._recorder.available():
                self._negotiated = True
        return self._negotiated

    async def status(self) -> RecordingStatus:
        """Return one low-sensitivity snapshot from the sole native subject."""
        if not await self._available():
            return RecordingStatus(
                available=False,
                state="idle",
                input_monitoring="unavailable",
                accessibility="unavailable",
            )
        native = await self._recorder.runtime_status()
        snapshot = await self._recorder.snapshot()
        current = self._describe(snapshot.active)
        last = self._describe(snapshot.last)
        permissions = native.get("permissions")
        if not isinstance(permissions, Mapping):
            permissions = {}
        return RecordingStatus(
            available=native.get("available") is True,
            input_monitoring=(
                "granted"
                if permissions.get("input_monitoring") is True
                else "required"
            ),
            accessibility=(
                "granted"
                if permissions.get("accessibility") is True
                else "required"
            ),
            state=(
                current.state.value
                if current is not None
                else (
                    "failed"
                    if last is not None and last.state.value == "failed"
                    else "idle"
                )
            ),
            recording=current,
            last_recording=last,
        )

    async def start(
        self,
        *,
        workspace_dir: str | Path,
        agent_id: str,
        user_id: str,
    ) -> RecordingStatus:
        """Start recording for a server-resolved agent workspace."""
        await self._require_available()
        await self._recorder.start(
            workspace_dir=str(workspace_dir),
            workspace_id=agent_id,
            user_id=user_id,
            agent_id=agent_id,
        )
        return await self.status()

    async def pause(self) -> RecordingStatus:
        """Pause the global recording session."""
        await self._recorder.pause()
        return await self.status()

    async def resume(self) -> RecordingStatus:
        """Resume the global recording session."""
        await self._recorder.resume()
        return await self.status()

    async def stop(self) -> RecordingStatus:
        """Stop and finalize the global recording session."""
        await self._recorder.stop()
        return await self.status()

    async def request_permissions(self) -> RecordingStatus:
        """Request recording permissions only from the shared Helper."""
        await self._require_available()
        await self._recorder.request_permissions()
        return await self.status()

    async def close(self) -> None:
        """Release recording ownership and close this plugin's connection."""
        await self._recorder.close()

    @staticmethod
    async def recover_workspaces(
        workspace_dirs: Iterable[str | Path],
    ) -> int:
        """Repair crash-left recording sessions in configured workspaces."""
        recovered = 0
        seen: set[Path] = set()
        for value in workspace_dirs:
            root = Path(value).expanduser().resolve()
            if root in seen:
                continue
            seen.add(root)
            sessions = await run_sync_io(
                RecordingStore(root).recover_unfinished,
            )
            recovered += len(sessions)
        return recovered

    async def _require_available(self) -> None:
        if not await self._available():
            raise RecordingProtocolError("desktop_runtime_unavailable")

    @staticmethod
    def _describe(
        session: RecordingSession | None,
    ) -> RecordingDescriptor | None:
        if session is None:
            return None
        return RecordingDescriptor.from_session(session)


__all__ = ["DesktopRecordingService"]
