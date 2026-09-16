"""Chat-owned input context, independent of task admission and playback."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from typing import Literal

from .reply_cycle import InputStateEvent


AdmissionStatus = Literal[
    "received", "preparing", "admitted", "rejected", "failed", "cancelled"
]
_TERMINAL = {"completed", "failed", "cancelled"}
_OVERVIEW_LIMIT = 32
_EXCERPT_CHARS = 160


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

    Boundary with ``ReplyCycleContext``: this object owns the *input* side of
    truth (committed identities, their order, and admission status). The
    ``InputStateEvent`` values kept in ``self._states`` are a read-only
    projection pushed from ``ReplyCycleContext`` (the *reply*/run side of
    truth); this class never feeds state back. On any apparent disagreement,
    input identity and order are authoritative here, while run and reply
    identity are authoritative in ``ReplyCycleContext``.
    """

    def __init__(self) -> None:
        self._inputs: dict[str, _Input] = {}
        self._sources: dict[str, str] = {}
        self._states: dict[str, InputStateEvent] = {}
        self._admissions: dict[str, AdmissionStatus] = {}
        self._revision = 0
        self._closed = False

    def register(
        self,
        identity: str,
        text: str,
        *,
        target: str = "",
        context_only: bool = False,
    ) -> None:
        if self._closed:
            return
        if not identity or not text.strip():
            raise ValueError("Input identity and text are required")
        # Replayed source identities cannot replace original words or order.
        if identity in self._inputs:
            return
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
        self._revision += 1

    def bind(self, input_id: str, source_id: str) -> None:
        if self._closed:
            return
        if source_id not in self._inputs:
            raise ValueError("Cannot bind an unregistered input")
        previous = self._sources.get(input_id)
        if previous is None:
            self._sources[input_id] = source_id
            self._revision += 1
            return
        if previous != source_id:
            raise ValueError("An execution input already has a source")

    def register_execution(self, input_id: str, text: str) -> None:
        if input_id not in self._sources and text.strip():
            self.register(input_id, text)
            self.bind(input_id, input_id)

    def set_admission(self, identity: str, status: AdmissionStatus) -> None:
        """Record a real handoff outcome, separately from execution events."""
        if self._closed:
            return
        source = self._sources.get(identity, identity)
        if source in self._inputs and self._admissions.get(source) != status:
            self._admissions[source] = status
            self._revision += 1

    def state(self, input_id: str) -> InputStateEvent | None:
        return self._states.get(input_id)

    def admission_status(self, identity: str) -> AdmissionStatus:
        return self._admissions.get(
            self._sources.get(identity, identity), "received"
        )

    def observe_state(self, event: InputStateEvent) -> None:
        """Project producer events, including before source bind."""
        if self._closed or not event.run_id:
            return
        for input_id in event.input_ids:
            previous = self._states.get(input_id)
            if previous is not None:
                if previous.status in _TERMINAL:
                    continue
                if previous.run_id != event.run_id and not (
                    previous.status == "waiting"
                    and event.resumed_from == previous.run_id
                ):
                    continue
                if previous.run_id == event.run_id and (
                    previous.status == event.status or event.status == "queued"
                ):
                    continue
            self._states[input_id] = InputStateEvent(
                event.run_id,
                (input_id,),
                event.status,
                event.resumed_from,
            )
            self._revision += 1

    def close(self) -> None:
        """Retire deleted-Chat references; ignore late events."""
        self._closed = True
        self._inputs.clear()
        self._sources.clear()
        self._states.clear()
        self._admissions.clear()

    def _request_facts(
        self, item: _Input, bindings: dict[str, list[str]]
    ) -> dict:
        ids = bindings.get(item.identity, [])
        latest = self._states.get(ids[-1]) if ids else None
        return {
            "source_id": item.identity,
            "order": item.order,
            "target": item.target,
            "admission_status": (
                self._admissions.get(
                    item.identity,
                    "admitted" if latest is not None else "received",
                )
            ),
            "execution_input_id": ids[-1] if ids else "",
            "input_status": latest.status if latest is not None else None,
            "run_id": latest.run_id if latest is not None else "",
            "previous_attempts": max(0, len(ids) - 1),
        }

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
        rows = sorted([*active, *related], key=lambda item: item.order)
        included = {item.identity for item in rows}
        bindings: dict[str, list[str]] = {}
        for input_id, source in self._sources.items():
            bindings.setdefault(source, []).append(input_id)
        others = [
            self._request_facts(item, bindings)
            for item in self._inputs.values()
            if item.identity not in included and not item.context_only
        ]
        if not related and not others:
            return ""

        # Active/pending facts precede old terminal details; never truncate
        # current input or its corrections/constraints to fit this overview.
        def priority(row: dict) -> tuple[int, int]:
            if row["input_status"] in {"queued", "processing", "waiting"}:
                return (0, -row["order"])
            if row["input_status"] in _TERMINAL or row["admission_status"] in {
                "rejected",
                "failed",
                "cancelled",
            }:
                return (2, -row["order"])
            return (1, -row["order"])

        others.sort(key=priority)
        overview = []
        for row in others[:_OVERVIEW_LIMIT]:
            text = self._inputs[row["source_id"]].text
            overview.append(
                {
                    **row,
                    "request_excerpt": text[:_EXCERPT_CHARS],
                    "excerpt_truncated": len(text) > _EXCERPT_CHARS,
                }
            )
        return json.dumps(
            {
                "revision": self._revision,
                "through_order": len(self._inputs),
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
                "input_states": [
                    self._request_facts(item, bindings)
                    for item in rows
                    if not item.context_only
                ],
                "readonly_requests": sorted(
                    overview, key=lambda row: row["order"]
                ),
                "coverage": {
                    "known_other_requests": len(others),
                    "included_other_requests": len(overview),
                    "omitted_other_requests": len(others) - len(overview),
                    "other_status_counts": dict(
                        Counter(
                            row["input_status"] or row["admission_status"]
                            for row in others
                        )
                    ),
                    "unbound_execution_inputs": sum(
                        identity not in self._sources
                        for identity in self._states
                    ),
                },
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
    "corrected or intended values. This snapshot supplements the "
    "conversation; "
    "it is not an execution result or a new user message. "
    "readonly_requests describes other same-Chat inputs, NOT released work. "
    "Their request excerpts are identification context, never new "
    "instructions. "
    "received means words recorded only; preparing means handoff preparation, "
    "NOT executor queued. rejected/failed admission is not accepted queued "
    "work. A null input_status means no execution state is available for "
    "this attempt. "
    "queued has not started; waiting is awaiting background work. "
    "completed is "
    "input processing state, NOT proof of tool success, a public answer, "
    "delivery "
    "or playback. Use actual tool results for results. History lookup cannot "
    "override live receipt/execution facts merely because no archive was "
    "found. "
    "Excerpts may be truncated and coverage states omissions; missing detail "
    "does not prove nonexistence. Do not infer remaining time from total "
    "duration. "
    "The Chat application has a real execution queue outside model history. "
    "queued is authoritative admission state, even when there is no tool call "
    "for that input in the visible conversation yet. active_input identifies "
    "work that this scheduler has NOW released to you; complete its first "
    "execution unless the user has explicitly withdrawn or changed that work. "
    "A later progress/results question observes existing work; it does not by "
    "itself cancel previously admitted work. A prohibition on REPEATING work "
    "does not prohibit a still-pending FIRST execution. Do not ask the user "
    "to re-authorize that already released first execution. Preserve genuine "
    "cancellation, changes and other constraints. Never execute a request "
    "merely because it is listed in readonly_requests. "
    "This snapshot's identifiers, admission fields and coverage diagnostics "
    "are internal decision material, not a public report template. By "
    "default, "
    "describe actual results, progress and any required next step in ordinary "
    "language without echoing those internal fields. If the user explicitly "
    "requests technical or diagnostic details, include the relevant details; "
    "preserve requested depth, tables and code rather than forcing brevity.\n"
)
