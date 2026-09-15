"""Chat-owned input context, independent of task admission and playback."""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class _Input:
    identity: str
    order: int
    text: str
    target: str
    context_only: bool


class ChatInputContext:
    """Preserve committed input until its owning Chat is released.

    Registration and capture are synchronous on the Chat event loop. A capture
    has an explicit cutoff: later inputs belong to the next model request.
    Nothing here starts, drains, cancels or acknowledges a task.
    """

    def __init__(self) -> None:
        self._inputs: dict[str, _Input] = {}
        self._sources: dict[str, str] = {}

    def register(
        self,
        identity: str,
        text: str,
        *,
        target: str = "",
        context_only: bool = False,
    ) -> None:
        if not identity or not text.strip():
            raise ValueError("Input identity and text are required")
        # Replayed source identities cannot replace original words or order.
        self._inputs.setdefault(
            identity,
            _Input(
                identity,
                len(self._inputs) + 1,
                text,
                target,
                context_only,
            ),
        )

    def bind(self, input_id: str, source_id: str) -> None:
        if source_id not in self._inputs:
            raise ValueError("Cannot bind an unregistered input")
        previous = self._sources.setdefault(input_id, source_id)
        if previous != source_id:
            raise ValueError("An execution input already has a source")

    def register_execution(self, input_id: str, text: str) -> None:
        if input_id not in self._sources and text.strip():
            self.register(input_id, text)
            self.bind(input_id, input_id)

    def _group(self, identity: str) -> str:
        seen: set[str] = set()
        while identity and identity not in seen:
            seen.add(identity)
            source = self._sources.get(identity, identity)
            item = self._inputs.get(source)
            if item is None or not item.target:
                return source
            identity = item.target
        return ""

    def capture(self, input_ids: tuple[str, ...]) -> str:
        sources = {self._sources.get(i, i) for i in input_ids}
        active = [
            self._inputs[i]
            for i in sources
            if i in self._inputs and not self._inputs[i].context_only
        ]
        if not active:
            return ""
        groups = {self._group(item.identity) for item in active}
        starts = [self._inputs[g].order for g in groups if g in self._inputs]
        floor = min(starts or [item.order for item in active])
        related = [
            item
            for item in self._inputs.values()
            if item.identity not in sources
            and item.order >= floor
            and (
                (item.context_only and not item.target)
                or self._group(item.target or item.identity) in groups
            )
        ]
        if not related:
            return ""
        rows = sorted([*active, *related], key=lambda item: item.order)
        return json.dumps(
            {
                "through_order": max(item.order for item in rows),
                "active_input_ids": list(input_ids),
                "inputs": [
                    {
                        "source_id": item.identity,
                        "order": item.order,
                        "kind": (
                            "user_update"
                            if item.context_only
                            else "active_input"
                            if item.identity in sources
                            else "related_input"
                        ),
                        "text": item.text,
                    }
                    for item in rows
                ],
            },
            ensure_ascii=False,
        )


INPUT_CONTEXT_INSTRUCTION = (
    "Current Chat input snapshot, in original user order. active_input is "
    "already admitted work, not a second request. user_update contains the "
    "user's original follow-on words, including questions, corrections and "
    "constraints; apply relevant constraints when deciding what to do next. "
    "related_input is another input for the same task; it may be queued or "
    "already processed, and is NOT work released for this model request. "
    "Read its corrections and constraints too, but execute work only for "
    "active_input, never merely because it appears in related_input. "
    "Reading an update does NOT admit additional work, authorize a rerun, "
    "or prove that an already-issued tool was cancelled. Other queued work "
    "is not released by this snapshot. Report actual execution results, not "
    "corrected or intended values. This snapshot supplements the conversation; "
    "it is not an execution result or a new user message.\n"
)
