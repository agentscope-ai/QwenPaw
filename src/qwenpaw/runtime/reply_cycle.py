"""Run-local identity for replies produced after steerable Chat inputs."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any, Literal

InputStatus = Literal[
    "queued", "processing", "waiting", "completed", "failed", "cancelled"
]
_INPUT_TERMINAL = {"completed", "failed", "cancelled"}


@dataclass(frozen=True)
class InternalResultInput:
    """A late assistant observation, never a new user admission."""

    work_id: str
    input_ids: tuple[str, ...]
    message: Any
    attempt: int = 1
    mode: Literal["queue"] = "queue"

    @property
    def idempotency_key(self) -> str:
        return f"result:{self.work_id}:{self.attempt}"


@dataclass(frozen=True)
class InputStateEvent:
    """Execution fact for original input identities, never a UI revision."""

    run_id: str
    input_ids: tuple[str, ...]
    status: InputStatus
    resumed_from: str = ""


@dataclass(frozen=True)
class ReplyContentEvent:
    """A saved model occurrence changed; consumers read canonical Chat content."""

    run_id: str
    input_ids: tuple[str, ...]


RUN_ID_METADATA_KEY = "run_id"
TIMELINE_GROUP_ID_METADATA_KEY = "timeline_group_id"
TIMELINE_REVISION_METADATA_KEY = "timeline_revision"
TIMELINE_ORDER_METADATA_KEY = "timeline_order"
RESPONDS_TO_INPUT_IDS_METADATA_KEY = "responds_to_input_ids"

REPLY_CYCLE_METADATA_KEYS = (
    RUN_ID_METADATA_KEY,
    TIMELINE_GROUP_ID_METADATA_KEY,
    TIMELINE_REVISION_METADATA_KEY,
    TIMELINE_ORDER_METADATA_KEY,
    RESPONDS_TO_INPUT_IDS_METADATA_KEY,
)


@dataclass(frozen=True)
class ReplyCycleSnapshot:
    """Immutable owner identity for one model-response cycle."""

    run_id: str
    group_id: str
    revision: int
    responds_to_input_ids: tuple[str, ...]

    def metadata(self) -> dict[str, Any]:
        """Return stable semantic ownership for this reply cycle."""
        return {
            RUN_ID_METADATA_KEY: self.run_id,
            TIMELINE_GROUP_ID_METADATA_KEY: self.group_id,
            TIMELINE_REVISION_METADATA_KEY: self.revision,
            RESPONDS_TO_INPUT_IDS_METADATA_KEY: list(
                self.responds_to_input_ids,
            ),
        }


@dataclass(frozen=True)
class ReplyOccurrenceSnapshot(ReplyCycleSnapshot):
    """One visible output occurrence within a semantic reply cycle."""

    timeline_order: int

    def metadata(self) -> dict[str, Any]:
        metadata = super().metadata()
        metadata[TIMELINE_ORDER_METADATA_KEY] = self.timeline_order
        return metadata


class ReplyCycleContext:
    """Authoritative reply identity shared by one run's Agent and envelope.

    Input admission never mutates this object. The Agent activates a new
    snapshot only after it actually drains a mailbox batch for its next model
    request. Tool calls retain the snapshot active when the call began.
    """

    def __init__(
        self,
        run_id: str,
        initial_input_id: str,
        reserve_timeline_order: Callable[[], Awaitable[int]] | None = None,
        *,
        on_input_state: Callable[[InputStateEvent], None] | None = None,
        on_reply_content: Callable[[ReplyContentEvent, Any], None]
        | None = None,
        has_pending_work: Callable[[str], bool] | None = None,
        is_input_cancelled: Callable[[str], bool] | None = None,
    ) -> None:
        run_id = run_id.strip()
        initial_input_id = initial_input_id.strip()
        if not run_id or not initial_input_id:
            raise ValueError("run and initial input identity are required")
        self._snapshot = ReplyCycleSnapshot(
            run_id=run_id,
            group_id=initial_input_id,
            revision=1,
            responds_to_input_ids=(initial_input_id,),
        )
        self._reserve_timeline_order = reserve_timeline_order
        self._on_input_state = on_input_state
        self._on_reply_content = on_reply_content
        self._has_pending_work = has_pending_work
        self._is_input_cancelled = is_input_cancelled
        self._input_states: dict[str, InputStatus] = {
            initial_input_id: "queued"
        }
        self._active_inputs: dict[str, None] = {}
        self._occurrence: ReplyOccurrenceSnapshot | None = None
        self._call_owners: dict[
            str,
            ReplyCycleSnapshot | ReplyOccurrenceSnapshot,
        ] = {}

    @property
    def snapshot(self) -> ReplyCycleSnapshot:
        """Return the active immutable snapshot."""
        return self._snapshot

    def accept_input(self, input_id: str) -> None:
        """Register admitted work without changing the active model request."""
        if input_id not in self._input_states:
            self._input_states[input_id] = "queued"
            self._emit_input_state((input_id,), "queued")

    def reply_content_changed(self, message: Any) -> None:
        """Expose the same message object owned by the Agent, not another log."""
        if self._on_reply_content is not None:
            self._on_reply_content(
                ReplyContentEvent(
                    self.run_id, self.snapshot.responds_to_input_ids
                ),
                message,
            )

    def _emit_input_state(
        self, input_ids: tuple[str, ...], status: InputStatus
    ) -> None:
        if input_ids and self._on_input_state is not None:
            self._on_input_state(
                InputStateEvent(self.run_id, input_ids, status)
            )

    def _set_input_state(
        self, input_ids: Iterable[str], status: InputStatus
    ) -> None:
        changed = tuple(
            value
            for value in input_ids
            if self._input_states.get(value) not in _INPUT_TERMINAL | {status}
        )
        for value in changed:
            self._input_states[value] = status
        self._emit_input_state(changed, status)

    def start_inputs(self, input_ids: Iterable[str]) -> None:
        for value in input_ids:
            self.accept_input(value)
            if self._input_states[value] not in _INPUT_TERMINAL:
                self._active_inputs[value] = None
        self._set_input_state(self._active_inputs, "processing")

    def finish_reply(self, status: InputStatus) -> None:
        pending = tuple(
            i
            for i in self._active_inputs
            if status in {"completed", "failed"}
            and self._has_pending_work is not None
            and self._has_pending_work(i)
        )
        self._set_input_state(pending, "waiting")
        self._set_input_state(
            (i for i in self._active_inputs if i not in pending), status
        )
        self._active_inputs.clear()

    def waiting_inputs(self) -> list[dict[str, str]]:
        """Persist resumable ownership with the existing Agent snapshot."""
        return [
            {"input_id": value, "run_id": self.run_id}
            for value, status in self._input_states.items()
            if status == "waiting"
        ]

    def resume_inputs(self, waiting: list[dict[str, str]]) -> None:
        for item in waiting:
            input_id, run_id = item.get("input_id"), item.get("run_id")
            if not input_id or not run_id or input_id in self._input_states:
                continue
            if (
                self._is_input_cancelled is not None
                and self._is_input_cancelled(input_id)
            ):
                self._input_states[input_id] = "cancelled"
                if self._on_input_state is not None:
                    self._on_input_state(
                        InputStateEvent(
                            self.run_id, (input_id,), "cancelled", run_id
                        )
                    )
                continue
            pending = (
                self._has_pending_work is not None
                and self._has_pending_work(input_id)
            )
            self._input_states[input_id] = (
                "waiting" if pending else "processing"
            )
            if not pending:
                self._active_inputs[input_id] = None
            if self._on_input_state is not None:
                self._on_input_state(
                    InputStateEvent(
                        self.run_id,
                        (input_id,),
                        self._input_states[input_id],
                        run_id,
                    )
                )

    def pending_input_ids(self) -> tuple[str, ...]:
        return tuple(
            key
            for key, status in self._input_states.items()
            if status not in _INPUT_TERMINAL
        )

    def terminated_input_ids(self, status: str) -> tuple[str, ...]:
        """Return only inputs actually terminated with this outcome."""
        return tuple(
            i for i, state in self._input_states.items() if state == status
        )

    def settle_background_inputs(self, input_ids: Iterable[str]) -> None:
        """Settle only after the parent feedback's save is confirmed."""
        self._set_input_state(input_ids, "completed")

    def finish_run(self, status: str) -> None:
        # EOF is not a successful reply. External-tool waits remain resumable.
        if status != "cancelled" and self._has_pending_work is not None:
            self._set_input_state(
                (i for i in self._input_states if self._has_pending_work(i)),
                "waiting",
            )
        unresolved = tuple(
            value
            for value, state in self._input_states.items()
            if (status != "completed" or state != "waiting")
            and not (
                status != "cancelled"
                and state == "waiting"
                and self._has_pending_work is not None
                and self._has_pending_work(value)
            )
        )
        self._set_input_state(
            unresolved, "cancelled" if status == "cancelled" else "failed"
        )
        self._active_inputs.clear()

    @property
    def run_id(self) -> str:
        return self._snapshot.run_id

    @property
    def output_snapshot(self) -> ReplyCycleSnapshot | ReplyOccurrenceSnapshot:
        """Return the visible occurrence, or the semantic owner fallback."""
        return self._occurrence or self._snapshot

    async def start_occurrence(
        self,
    ) -> ReplyCycleSnapshot | ReplyOccurrenceSnapshot:
        """Allocate one new authoritative order at first visible output."""
        if self._reserve_timeline_order is None:
            self._occurrence = None
            return self._snapshot
        order = await self._reserve_timeline_order()
        if not isinstance(order, int) or isinstance(order, bool) or order <= 0:
            raise ValueError(
                "timeline order reserver returned an invalid order"
            )
        self._occurrence = ReplyOccurrenceSnapshot(
            run_id=self._snapshot.run_id,
            group_id=self._snapshot.group_id,
            revision=self._snapshot.revision,
            responds_to_input_ids=self._snapshot.responds_to_input_ids,
            timeline_order=order,
        )
        return self._occurrence

    async def ensure_occurrence(
        self,
    ) -> ReplyCycleSnapshot | ReplyOccurrenceSnapshot:
        """Return the current occurrence, allocating it when necessary."""
        if self._occurrence is not None:
            return self._occurrence
        return await self.start_occurrence()

    def activate(
        self,
        input_ids: Iterable[str],
    ) -> ReplyCycleSnapshot:
        """Activate one response cycle for a consumed, ordered input batch."""
        normalized = tuple(
            value.strip()
            for value in input_ids
            if isinstance(value, str) and value.strip()
        )
        if not normalized:
            raise ValueError("at least one consumed input id is required")
        self.start_inputs(normalized)
        self._snapshot = ReplyCycleSnapshot(
            run_id=self._snapshot.run_id,
            group_id=normalized[-1],
            revision=self._snapshot.revision + 1,
            responds_to_input_ids=normalized,
        )
        self._occurrence = None
        return self._snapshot

    def bind_call(
        self,
        call_id: str,
    ) -> ReplyCycleSnapshot | ReplyOccurrenceSnapshot:
        """Bind a tool call to the snapshot active at call creation."""
        call_id = call_id.strip()
        if not call_id:
            raise ValueError("tool call id is required")
        return self._call_owners.setdefault(call_id, self.output_snapshot)

    def owner_of_call(
        self,
        call_id: str,
    ) -> ReplyCycleSnapshot | ReplyOccurrenceSnapshot | None:
        """Return a tool call's stable owner, if the call was observed."""
        return self._call_owners.get(call_id)


__all__ = [
    "InputStateEvent",
    "InputStatus",
    "REPLY_CYCLE_METADATA_KEYS",
    "RESPONDS_TO_INPUT_IDS_METADATA_KEY",
    "RUN_ID_METADATA_KEY",
    "TIMELINE_GROUP_ID_METADATA_KEY",
    "TIMELINE_ORDER_METADATA_KEY",
    "TIMELINE_REVISION_METADATA_KEY",
    "ReplyCycleContext",
    "ReplyCycleSnapshot",
    "ReplyOccurrenceSnapshot",
]
