# -*- coding: utf-8 -*-
"""Authoritative transcript recording for normalized chat envelopes."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING, Any

from ...constant import QWENPAW_CLIENT_MESSAGE_ID_KEY
from ..._session_signals import (
    TRANSCRIPT_RECORDING_READY_KEY,
    TRANSCRIPT_TURN_ID_CONTEXT_KEY,
    TURN_COMMIT_KEY,
)
from ...runtime.console_turn_state import REGENERATE_FROM
from ...schemas import (
    AgentResponse,
    Message,
    RunStatus,
)
from .transcript import TranscriptStore, TurnStatus
from ..replay_persistence import ReplayReceipt, replay_receipt

if TYPE_CHECKING:
    from .transcript_catalog import TranscriptCatalog

logger = logging.getLogger(__name__)

_TERMINAL_STATUS: dict[RunStatus, TurnStatus] = {
    RunStatus.Completed: "completed",
    RunStatus.Failed: "failed",
    RunStatus.Cancelled: "cancelled",
}


class TranscriptRecorder:
    """Persist one request turn before acknowledging its completion."""

    def __init__(
        self,
        *,
        store: TranscriptStore | TranscriptCatalog | None,
        request: Any,
        legacy_messages: list[Message] | None = None,
    ) -> None:
        self._store = store
        self._request = request
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
        self._legacy_messages = legacy_messages or []
        request_context = getattr(request, "request_context", None)
        if not isinstance(request_context, dict):
            request_context = {}
            request.request_context = request_context
        request_context[TRANSCRIPT_TURN_ID_CONTEXT_KEY] = self._turn_id
        request_context[TRANSCRIPT_RECORDING_READY_KEY] = False
        if store is not None:
            request_context[TURN_COMMIT_KEY] = {}
        self._ordinals: dict[str, int] = {}
        self._next_ordinal = 0
        self._started = False
        self._finished = False
        self._degraded = False

    async def start(self) -> None:
        """Create the turn and persist its incoming display messages."""
        if self._store is None or self._started or self._degraded:
            return
        self._started = True
        if self._legacy_messages:
            legacy_messages = self._legacy_messages
            self._legacy_messages = []
            await self._write(
                self._store.import_legacy_messages,
                session_id=self._session_id,
                user_id=self._user_id,
                channel=self._channel,
                messages=legacy_messages,
            )
            if self._degraded:
                return
        replaces_turn_id = await self._replacement_turn_id()
        if self._degraded:
            return
        await self._write(
            self._store.start_turn,
            session_id=self._session_id,
            user_id=self._user_id,
            channel=self._channel,
            turn_id=self._turn_id,
            replaces_turn_id=replaces_turn_id,
        )
        if self._degraded:
            return
        for message in getattr(self._request, "input", None) or []:
            if isinstance(message, Message):
                await self._record_message(message)
        self._request.request_context[
            TRANSCRIPT_RECORDING_READY_KEY
        ] = not self._degraded

    async def observe(self, value: Any) -> None:
        """Record normalized message snapshots and terminal responses."""
        replay_receipt.set(None)
        if not self._started or self._degraded:
            return
        if isinstance(value, Message):
            if value.id not in self._ordinals:
                self._ordinals[value.id] = self._next_ordinal
                self._next_ordinal += 1
            replay_receipt.set(
                ReplayReceipt(
                    self._store,
                    self._session_id,
                    self._user_id,
                    self._channel,
                    self._turn_id,
                    value.id,
                    self._ordinals[value.id],
                    getattr(value, "sequence_number", 0) or 0,
                    False,
                ),
            )
            if value.content and value.status != RunStatus.InProgress:
                await self._record_message(value)
            return
        if not isinstance(value, AgentResponse):
            return
        terminal = _TERMINAL_STATUS.get(value.status)
        if terminal is not None:
            messages = []
            for message in value.output:
                if not message.content:
                    continue
                if message.id not in self._ordinals:
                    self._ordinals[message.id] = self._next_ordinal
                    self._next_ordinal += 1
                messages.append((message, self._ordinals[message.id]))
            await self.finish(
                terminal,
                messages=messages,
                error=self._normalized_error(
                    getattr(value, "error", None),
                ),
                finished_at=value.completed_at,
            )
            if not self._degraded:
                for message in value.output:
                    if message.id not in self._ordinals:
                        continue
                    message.metadata = {
                        **dict(message.metadata or {}),
                        "qwenpaw_transcript_position": {
                            "turn_id": self._turn_id,
                            "ordinal": self._ordinals[message.id],
                        },
                    }

    async def finish(
        self,
        status: TurnStatus,
        *,
        error: dict[str, Any] | None = None,
        finished_at: str | None = None,
        messages: list[tuple[Message, int]] | None = None,
    ) -> None:
        """Persist a terminal turn state idempotently."""
        if (
            not self._started
            or self._finished
            or self._store is None
            or self._degraded
        ):
            return
        pending = self._request.request_context.get(TURN_COMMIT_KEY, {})
        await self._write(
            self._store.commit_turn,
            session_id=self._session_id,
            user_id=self._user_id,
            channel=self._channel,
            turn_id=self._turn_id,
            status=status,
            error=error,
            finished_at=finished_at,
            messages=messages or [],
            runtime=pending.get("runtime"),
            usage=pending.get("usage"),
        )
        if not self._degraded:
            self._finished = True

    async def _record_message(
        self,
        message: Message,
        *,
        finished_at: str | None = None,
    ) -> None:
        if self._store is None or self._degraded:
            return
        ordinal = self._ordinals.get(message.id)
        if ordinal is None:
            ordinal = self._next_ordinal
            self._ordinals[message.id] = ordinal
            self._next_ordinal += 1
        await self._write(
            self._store.upsert_message,
            session_id=self._session_id,
            user_id=self._user_id,
            channel=self._channel,
            turn_id=self._turn_id,
            message=message,
            ordinal=ordinal,
            finished_at=finished_at,
        )
        sequence = getattr(message, "sequence_number", None)
        if (
            not self._degraded
            and isinstance(sequence, int)
            and message.content
            and message.status in _TERMINAL_STATUS
        ):
            replay_receipt.set(
                ReplayReceipt(
                    self._store,
                    self._session_id,
                    self._user_id,
                    self._channel,
                    self._turn_id,
                    message.id,
                    ordinal,
                    sequence,
                ),
            )

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
            user_id=self._user_id,
            channel=self._channel,
            message_id=message_id,
            client_message_id=client_message_id,
        )

    async def _write(self, method: Any, **kwargs: Any) -> Any:
        task = asyncio.create_task(asyncio.to_thread(method, **kwargs))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                await task
            except Exception:
                self._degraded = True
                logger.warning(
                    "Transcript recording degraded during cancellation for "
                    "session %s",
                    self._session_id,
                    exc_info=True,
                )
            raise
        except Exception:
            self._degraded = True
            logger.warning(
                "Transcript recording degraded for session %s",
                self._session_id,
                exc_info=True,
            )
            raise

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
                    return f"regenerate:{client_id}:{uuid.uuid4().hex}"
                return f"client:{client_id}"
        if regeneration_target:
            if isinstance(regeneration_target, dict):
                target_id = regeneration_target.get("message_id")
            else:
                target_id = regeneration_target
            return f"regenerate:{target_id or 'turn'}:{uuid.uuid4().hex}"
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
