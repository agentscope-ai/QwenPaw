"""Commit native realtime delegation signals against final transcripts."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

from .contracts import HandoffVoiceAction
from .turn_commit import CommittedSpokenTurn, PendingSpokenTurn

logger = logging.getLogger(__name__)
_EVENTS_CLOSED = object()


@dataclass(frozen=True)
class NativeDelegationRejected:
    """A native call that cannot become an authoritative Chat input."""

    source_id: str
    call_id: str
    error: str


@dataclass
class _NativeTurn:
    call_id: str = ""
    transcript: str = ""
    transcript_terminal: bool = False
    transcript_failed: bool = False


NativeTurnEvent = (
    PendingSpokenTurn | CommittedSpokenTurn | NativeDelegationRejected
)


class NativeDelegationCommitter:
    """Flush one continuous native handoff from finalized ASR fragments.

    Provider item IDs order and deduplicate transcript material; they are not
    application request boundaries.  Function-call arguments are ignored and
    calls only signal that the buffered speech belongs to ordinary Chat.
    """

    def __init__(self, *, continuation_grace_ms: int = 1200) -> None:
        if not 0 <= continuation_grace_ms <= 5000:
            raise ValueError(
                "continuation grace must be between 0 and 5000 ms"
            )
        self.on_commit: Callable[[CommittedSpokenTurn], None] | None = None
        self._continuation_grace_seconds = continuation_grace_ms / 1000
        self._turns: dict[str, _NativeTurn] = {}
        self._source_ids: list[str] = []
        self._events: asyncio.Queue[NativeTurnEvent | object] = asyncio.Queue()
        self._commit_task: asyncio.Task[None] | None = None
        self._closed = False

    def _remember(self, source_id: str) -> _NativeTurn:
        turn = self._turns.get(source_id)
        if turn is None:
            turn = _NativeTurn()
            self._turns[source_id] = turn
            self._source_ids.append(source_id)
        return turn

    def _cancel_commit(self) -> None:
        task = self._commit_task
        self._commit_task = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    async def speech_started(self, source_id: str) -> None:
        if self._closed or not source_id:
            return
        self._cancel_commit()
        self._remember(source_id)

    async def speech_stopped(self, source_id: str) -> None:
        del source_id

    async def add_segment(self, source_id: str, text: str) -> None:
        if self._closed or not source_id:
            return
        turn = self._remember(source_id)
        if turn.transcript_terminal:
            return
        turn.transcript = text.strip()
        turn.transcript_terminal = True
        self._schedule_if_ready()

    async def input_failed(self, source_id: str) -> None:
        if self._closed or not source_id:
            return
        turn = self._remember(source_id)
        turn.transcript_terminal = True
        turn.transcript_failed = True
        self._schedule_if_ready()

    async def delegation_requested(
        self,
        source_id: str,
        call_id: str,
    ) -> None:
        if self._closed or not source_id or not call_id:
            return
        turn = self._remember(source_id)
        if turn.call_id and turn.call_id != call_id:
            await self._events.put(
                NativeDelegationRejected(
                    source_id,
                    call_id,
                    "duplicate_native_delegation",
                )
            )
            return
        turn.call_id = call_id
        self._schedule_if_ready()

    def _ready(self) -> bool:
        return bool(self._turns) and any(
            turn.call_id for turn in self._turns.values()
        ) and all(turn.transcript_terminal for turn in self._turns.values())

    def _schedule_if_ready(self) -> None:
        if self._closed or not self._ready():
            return
        self._cancel_commit()
        self._commit_task = asyncio.create_task(self._commit_after_grace())

    async def _commit_after_grace(self) -> None:
        try:
            await asyncio.sleep(self._continuation_grace_seconds)
        except asyncio.CancelledError:
            return
        if self._commit_task is not asyncio.current_task():
            return
        self._commit_task = None
        self._finish()

    def _finish(self) -> bool:
        if not self._ready():
            return False
        source_ids = tuple(
            source_id
            for source_id in self._source_ids
            if source_id in self._turns
        )
        turns = [(source_id, self._turns[source_id]) for source_id in source_ids]
        self._turns.clear()
        self._source_ids.clear()

        valid_sources = tuple(
            source_id
            for source_id, turn in turns
            if turn.transcript and not turn.transcript_failed
        )
        text = "\n".join(
            turn.transcript
            for _, turn in turns
            if turn.transcript and not turn.transcript_failed
        )
        valid_calls = tuple(
            (source_id, turn.call_id)
            for source_id, turn in turns
            if turn.call_id and turn.transcript and not turn.transcript_failed
        )
        rejected_calls = tuple(
            (source_id, turn.call_id)
            for source_id, turn in turns
            if turn.call_id and (turn.transcript_failed or not turn.transcript)
        )
        for source_id, call_id in rejected_calls:
            self._events.put_nowait(
                NativeDelegationRejected(
                    source_id,
                    call_id,
                    "voice_transcription_failed",
                )
            )
        if not text or not valid_calls:
            return bool(rejected_calls)

        call_ids = tuple(call_id for _, call_id in valid_calls)
        digest = hashlib.sha256(
            "\x1e".join((*valid_sources, *call_ids)).encode()
        ).hexdigest()
        event = CommittedSpokenTurn(
            turn_id=f"spoken_{digest[:32]}",
            text=text,
            source_ids=valid_sources,
            origin="native",
            action=HandoffVoiceAction(),
            delegation_ids=call_ids,
        )
        try:
            if self.on_commit is not None:
                self.on_commit(event)
        except Exception:
            logger.exception("Could not register native voice input")
            for source_id, call_id in valid_calls:
                self._events.put_nowait(
                    NativeDelegationRejected(
                        source_id,
                        call_id,
                        "voice_input_unavailable",
                    )
                )
            return True
        self._events.put_nowait(event)
        return True

    async def commit_pending(self, origin: str = "manual") -> bool:
        del origin
        return False

    def finish_source(self, source_id: str) -> bool:
        """Release a direct conversational item outside an active handoff."""
        turn = self._turns.get(source_id)
        if turn is None:
            return True
        if turn.call_id:
            return False
        if any(item.call_id for item in self._turns.values()):
            return False
        self._turns.pop(source_id, None)
        self._source_ids = [item for item in self._source_ids if item != source_id]
        return True

    async def events(self) -> AsyncIterator[NativeTurnEvent]:
        while True:
            event = await self._events.get()
            if event is _EVENTS_CLOSED:
                return
            if isinstance(
                event,
                (
                    PendingSpokenTurn,
                    CommittedSpokenTurn,
                    NativeDelegationRejected,
                ),
            ):
                yield event

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._cancel_commit()
        self._turns.clear()
        self._source_ids.clear()
        await self._events.put(_EVENTS_CLOSED)


__all__ = ["NativeDelegationCommitter", "NativeDelegationRejected"]
