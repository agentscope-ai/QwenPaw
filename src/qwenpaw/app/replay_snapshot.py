# -*- coding: utf-8 -*-
"""Serialize bounded replay state, paging evicted messages from storage."""

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from .replay_message_state import materialize_replay
from .replay_persistence import ReplayReceipt


@dataclass
class ReplayPrefix:
    """A fixed replay boundary plus a bounded in-memory message tail."""

    source: ReplayReceipt | None
    through: int
    header: dict[str, Any]
    messages: list[tuple[int, str]]
    controls: list[str]
    suffix: list[str] = field(default_factory=list)

    def append(self, event: str) -> None:
        self.suffix.append(event)

    async def __aiter__(self) -> AsyncIterator[str]:
        if self.source is None:
            raise RuntimeError("durable replay reader is unavailable")
        start = {**self.header, "status": "in_progress", "output": []}
        start.pop("error", None)
        yield f"data: {json.dumps(start)}\n\n"
        after = -1
        index = 0
        while True:
            page = await asyncio.to_thread(
                self.source.read_page,
                self.through,
                after,
            )
            if not page:
                break
            for ordinal, payload in page:
                while (
                    index < len(self.messages)
                    and self.messages[index][0] < ordinal
                ):
                    yield self.messages[index][1]
                    index += 1
                if (
                    index < len(self.messages)
                    and self.messages[index][0] == ordinal
                ):
                    yield self.messages[index][1]
                    index += 1
                else:
                    yield f"data: {payload}\n\n"
                after = ordinal
        for _, event in self.messages[index:]:
            yield event
        for event in self.controls:
            yield event
        terminal = {**self.header, "output": []}
        yield f"data: {json.dumps(terminal)}\n\n"
        for event in self.suffix:
            yield event


__all__ = ["ReplayPrefix", "materialize_replay"]
