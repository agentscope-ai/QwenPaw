# -*- coding: utf-8 -*-
"""Internal persistence receipts; never serialized into user messages."""

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReplayReceipt:
    """A committed message and its durable replay reader."""

    store: Any
    session_id: str
    user_id: str
    channel: str
    turn_id: str
    message_id: str
    ordinal: int
    sequence: int
    committed: bool = True

    def read_page(self, through: int, after: int) -> list[tuple[int, str]]:
        return self.store.read_replay_page(
            session_id=self.session_id,
            user_id=self.user_id,
            channel=self.channel,
            turn_id=self.turn_id,
            through=through,
            after=after,
        )


replay_receipt: ContextVar[ReplayReceipt | None] = ContextVar(
    "replay_receipt",
    default=None,
)


class ReplayEvent(str):
    """An unchanged wire event with a compact internal replay projection."""

    def __new__(cls, wire: str, replay: str):
        instance = super().__new__(cls, wire)
        instance.replay = replay
        return instance
