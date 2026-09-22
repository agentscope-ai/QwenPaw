# -*- coding: utf-8 -*-
"""Best-effort transcript recording for normalized chat envelopes."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import TYPE_CHECKING, Any

from ...constant import QWENPAW_CLIENT_MESSAGE_ID_KEY
from ...runtime.console_turn_state import REGENERATE_FROM
from ...schemas import (
    AgentResponse,
    DataContent,
    Message,
    RunStatus,
    TextContent,
)
from .transcript import TranscriptStore, TurnStatus

if TYPE_CHECKING:
    from .transcript_catalog import TranscriptCatalog

logger = logging.getLogger(__name__)

TRANSCRIPT_TURN_ID_CONTEXT_KEY = "_qwenpaw_transcript_turn_id"
_CHECKPOINT_INTERVAL_SECONDS = 1.0
_CHECKPOINT_MAX_BYTES = 64 * 1024

_TERMINAL_STATUS: dict[RunStatus, TurnStatus] = {
    RunStatus.Completed: "completed",
    RunStatus.Failed: "failed",
    RunStatus.Cancelled: "cancelled",
}


class TranscriptRecorder:
    """Persist one request turn without affecting response delivery."""

    def __init__(
        self,
        *,
        store: TranscriptStore | TranscriptCatalog | None,
        request: Any,
        source: str,
    ) -> None:
        self._store = store
        self._request = request
        self._source = source
        self._session_id = str(
            getattr(request, "session_id", "") or uuid.uuid4().hex,
        )
        self._user_id = str(
            getattr(request, "user_id", "") or self._session_id,
        )
        self._channel = str(
            getattr(request, "channel", "") or "console",
        )
        self._turn_id = self._resolve_turn_id(request)
        request_context = getattr(request, "request_context", None)
        if not isinstance(request_context, dict):
            request_context = {}
            request.request_context = request_context
        request_context[TRANSCRIPT_TURN_ID_CONTEXT_KEY] = self._turn_id
        self._ordinals: dict[str, int] = {}
        self._snapshots: dict[str, Message] = {}
        self._dirty_message_ids: set[str] = set()
        self._finished_at: dict[str, str] = {}
        self._pending_bytes = 0
        self._last_checkpoint = time.monotonic()
        self._next_ordinal = 0
        self._started = False
        self._finished = False
        self._degraded = False

    @property
    def degraded(self) -> bool:
        """Return whether recording was disabled after a write failure."""
        return self._degraded

    @property
    def turn_id(self) -> str:
        """Return the stable identifier selected for this turn."""
        return self._turn_id

    async def start(self) -> None:
        """Create the turn and persist its incoming display messages."""
        if self._store is None or self._started or self._degraded:
            return
        self._started = True
        replaces_turn_id = await self._replacement_turn_id()
        if self._degraded:
            return
        await self._write(
            self._store.start_turn,
            session_id=self._session_id,
            user_id=self._user_id,
            channel=self._channel,
            turn_id=self._turn_id,
            source=self._source,
            replaces_turn_id=replaces_turn_id,
        )
        if self._degraded:
            return
        for message in getattr(self._request, "input", None) or []:
            if isinstance(message, Message):
                await self._record_message(message, force=True)

    async def observe(self, value: Any) -> None:
        """Record normalized message snapshots and terminal responses."""
        if not self._started or self._degraded:
            return
        if isinstance(value, Message):
            await self._record_message(
                value,
                force=value.status != RunStatus.InProgress,
            )
            return
        if getattr(value, "object", None) == "content":
            await self._record_content(value)
            return
        if not isinstance(value, AgentResponse):
            return
        for message in value.output:
            await self._record_message(
                message,
                finished_at=value.completed_at,
                force=True,
            )
        terminal = _TERMINAL_STATUS.get(value.status)
        if terminal is not None:
            await self.finish(
                terminal,
                error=self._normalized_error(
                    getattr(value, "error", None),
                ),
                finished_at=value.completed_at,
            )

    async def finish(
        self,
        status: TurnStatus,
        *,
        error: dict[str, Any] | None = None,
        finished_at: str | None = None,
    ) -> None:
        """Persist a terminal turn state idempotently."""
        if (
            not self._started
            or self._finished
            or self._store is None
            or self._degraded
        ):
            return
        await self._flush_dirty()
        if self._degraded:
            return
        await self._write(
            self._store.finish_turn,
            session_id=self._session_id,
            turn_id=self._turn_id,
            status=status,
            error=error,
            finished_at=finished_at,
        )
        if not self._degraded:
            await self._write(
                self._store.purge_if_due,
                session_id=self._session_id,
            )
        if not self._degraded:
            self._finished = True

    async def _record_message(
        self,
        message: Message,
        *,
        finished_at: str | None = None,
        force: bool = False,
        pending_bytes: int = 0,
    ) -> None:
        if self._store is None or self._degraded:
            return
        previous = self._snapshots.get(message.id)
        if previous is not None and previous.content and not message.content:
            message = message.model_copy(
                update={"content": previous.content},
                deep=True,
            )
        else:
            message = message.model_copy(deep=True)
        self._snapshots[message.id] = message
        ordinal = self._ordinals.get(message.id)
        if ordinal is None:
            ordinal = self._next_ordinal
            self._ordinals[message.id] = ordinal
            self._next_ordinal += 1
        self._dirty_message_ids.add(message.id)
        if finished_at is not None:
            self._finished_at[message.id] = finished_at
        self._pending_bytes += pending_bytes
        if force or previous is None or self._checkpoint_due():
            await self._flush_dirty()

    async def _record_content(self, content: Any) -> None:
        """Merge one streaming content event into its message snapshot."""
        message_id = str(getattr(content, "msg_id", "") or "")
        snapshot = self._snapshots.get(message_id)
        if snapshot is None:
            return

        incoming = content.model_copy(
            update={"delta": False},
            deep=True,
        )
        parts = list(snapshot.content)
        index = getattr(content, "index", None)
        if not isinstance(index, int) or index < 0:
            index = len(parts)

        if index < len(parts):
            incoming = self._merge_content(parts[index], incoming, content)
            parts[index] = incoming
        else:
            parts.append(incoming)

        await self._record_message(
            snapshot.model_copy(update={"content": parts}, deep=True),
            pending_bytes=self._content_size(content),
        )

    def _checkpoint_due(self) -> bool:
        return (
            self._pending_bytes >= _CHECKPOINT_MAX_BYTES
            or time.monotonic() - self._last_checkpoint
            >= _CHECKPOINT_INTERVAL_SECONDS
        )

    async def _flush_dirty(self) -> None:
        """Persist accumulated message snapshots in display order."""
        if self._store is None or not self._dirty_message_ids:
            return
        message_ids = sorted(
            self._dirty_message_ids,
            key=self._ordinals.__getitem__,
        )
        for message_id in message_ids:
            await self._write(
                self._store.upsert_message,
                session_id=self._session_id,
                turn_id=self._turn_id,
                message=self._snapshots[message_id],
                ordinal=self._ordinals[message_id],
                finished_at=self._finished_at.get(message_id),
            )
            if self._degraded:
                return
            self._dirty_message_ids.discard(message_id)
            self._finished_at.pop(message_id, None)
        self._pending_bytes = 0
        self._last_checkpoint = time.monotonic()

    @staticmethod
    def _content_size(content: Any) -> int:
        """Estimate pending serialized bytes without retaining each chunk."""
        try:
            return len(content.model_dump_json().encode("utf-8"))
        except (AttributeError, TypeError, ValueError):
            return 0

    @staticmethod
    def _merge_content(
        previous: Any,
        incoming: Any,
        source: Any,
    ) -> Any:
        """Merge incremental text/data fields; replace cumulative events."""
        if not getattr(source, "delta", False):
            return incoming
        if isinstance(previous, TextContent) and isinstance(
            incoming,
            TextContent,
        ):
            return incoming.model_copy(
                update={"text": previous.text + incoming.text},
            )
        if isinstance(previous, DataContent) and isinstance(
            incoming,
            DataContent,
        ):
            old_data = previous.data
            new_data = incoming.data
            if isinstance(old_data, dict) and isinstance(new_data, dict):
                merged = {**old_data, **new_data}
                for key in ("arguments", "output"):
                    old_value = old_data.get(key)
                    new_value = new_data.get(key)
                    if isinstance(old_value, str) and isinstance(
                        new_value,
                        str,
                    ):
                        merged[key] = old_value + new_value
                return incoming.model_copy(update={"data": merged})
        return incoming

    async def _replacement_turn_id(self) -> str | None:
        if self._store is None:
            return None
        request_context = getattr(self._request, "request_context", None) or {}
        target = request_context.get(REGENERATE_FROM)
        if not target:
            return None
        message_id = None
        client_message_id = None
        if isinstance(target, dict):
            message_id = str(target.get("message_id") or "") or None
            client_message_id = (
                str(target.get("client_message_id") or "") or None
            )
        else:
            client_message_id = str(target)
        return await self._write(
            self._store.find_turn_for_message,
            session_id=self._session_id,
            message_id=message_id,
            client_message_id=client_message_id,
        )

    async def _write(self, method: Any, **kwargs: Any) -> Any:
        task = asyncio.create_task(asyncio.to_thread(method, **kwargs))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise
        except Exception:
            self._degraded = True
            logger.warning(
                "Transcript recording degraded for session %s",
                self._session_id,
                exc_info=True,
            )
        return None

    @staticmethod
    def _resolve_turn_id(request: Any) -> str:
        request_context = getattr(request, "request_context", None) or {}
        for key in ("delivery_id", "turn_id"):
            candidate = request_context.get(key)
            if candidate:
                return f"{key}:{candidate}"
        regeneration_target = request_context.get(REGENERATE_FROM)
        for message in getattr(request, "input", None) or []:
            metadata = getattr(message, "metadata", None) or {}
            client_id = metadata.get(QWENPAW_CLIENT_MESSAGE_ID_KEY)
            if client_id:
                if regeneration_target:
                    return f"regenerate:{client_id}"
                return f"client:{client_id}"
        if regeneration_target:
            if isinstance(regeneration_target, dict):
                target_id = regeneration_target.get("message_id")
            else:
                target_id = regeneration_target
            return f"regenerate:{target_id or uuid.uuid4().hex}"
        return f"turn:{uuid.uuid4().hex}"

    @staticmethod
    def _normalized_error(value: Any) -> dict[str, Any] | None:
        if not value:
            return None
        if isinstance(value, dict):
            return {
                "code": str(value.get("code") or "error"),
                "message": "",
            }
        return {"code": type(value).__name__, "message": ""}


__all__ = [
    "TRANSCRIPT_TURN_ID_CONTEXT_KEY",
    "TranscriptRecorder",
]
