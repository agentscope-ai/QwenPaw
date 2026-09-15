"""Bounded speech intents and one renderer-confirmed output credit."""

from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from dataclasses import dataclass, field, replace
from typing import Literal
from uuid import uuid4

from ...providers.realtime_voice import ProviderResponseResult


@dataclass(frozen=True)
class PresentationIntent:
    kind: Literal[
        "status", "converse", "clarify", "receipt", "rejected", "update"
    ]
    turn_id: str = ""
    user_text: str = ""
    task_ref: str = ""
    missing_information: str = ""
    completion: asyncio.Future[ProviderResponseResult] | None = None
    changed_ids: tuple[str, ...] = ()
    timeline_order: int = 0
    history_user_text: str = ""
    receipt_is_followup: bool = False

    @property
    def cost(self) -> int:
        return max(1, len(self.changed_ids))

    @property
    def automatic(self) -> bool:
        return self.kind in {"receipt", "update"}

    def cancel(self) -> None:
        if self.completion is not None and not self.completion.done():
            self.completion.cancel()


class PresentationQueue:
    """Questions are FIFO; only ungenerated automatic notices coalesce."""

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("presentation capacity must be positive")
        self.capacity = capacity
        self._direct: deque[PresentationIntent] = deque()
        self._automatic: OrderedDict[str, PresentationIntent] = OrderedDict()
        self._changed = asyncio.Event()
        self._closed = False

    def put(self, intent: PresentationIntent) -> bool:
        if self._closed:
            intent.cancel()
            return False
        key = f"{intent.kind}:{intent.task_ref}"
        previous = self._automatic.get(key) if intent.automatic else None
        if previous is not None:
            intent = replace(
                intent,
                changed_ids=tuple(
                    dict.fromkeys((*previous.changed_ids, *intent.changed_ids))
                ),
            )
        occupied = sum(
            i.cost for i in (*self._direct, *self._automatic.values())
        )
        if (
            occupied - (previous.cost if previous else 0) + intent.cost
            > self.capacity
        ):
            intent.cancel()
            return False
        if previous is not None:
            previous.cancel()
        if intent.automatic:
            self._automatic[key] = intent
        else:
            self._direct.append(intent)
        self._changed.set()
        return True

    async def get(self) -> PresentationIntent | None:
        while True:
            if self._direct:
                return self._direct.popleft()
            if self._automatic:
                return self._automatic.popitem(last=False)[1]
            if self._closed:
                return None
            self._changed.clear()
            await self._changed.wait()

    def close(self) -> None:
        self._closed = True
        for intent in (*self._direct, *self._automatic.values()):
            intent.cancel()
        self._direct.clear()
        self._automatic.clear()
        self._changed.set()


@dataclass
class OutputCredit:
    """Provider terminal AND scoped renderer feedback release the next output.

    The terminal is observed in the ordered event stream, not inferred from the
    response future. Generation/history completion never waits on this object.
    """

    output_id: str = field(default_factory=lambda: uuid4().hex)
    provider_id: str = ""
    sealed: bool = False
    playback: str = ""
    terminal: asyncio.Event = field(default_factory=asyncio.Event)
    feedback: asyncio.Event = field(default_factory=asyncio.Event)

    def seal(self) -> None:
        self.sealed = True
        self.terminal.set()

    def acknowledge(self, output_id: str, status: str) -> None:
        if output_id != self.output_id or self.playback:
            return
        if status not in {"drained", "interrupted", "failed"}:
            return
        if status == "drained" and not self.sealed:
            return
        self.playback = status
        self.feedback.set()

    async def wait(self, timeout: float) -> None:
        async with asyncio.timeout(timeout):
            await self.terminal.wait()
            await self.feedback.wait()
        if self.playback == "failed":
            raise RuntimeError("The browser could not play the speech output")
