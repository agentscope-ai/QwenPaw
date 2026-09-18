# -*- coding: utf-8 -*-
"""Durable mailbox-scoped consent and limits for automatic mail work."""

from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from ...utils.io_utils import write_json_atomic

BATCH_CONFIRM_THRESHOLD = 50
CONSECUTIVE_FAILURE_LIMIT = 3


class _StateModel(BaseModel):
    model_config = ConfigDict(strict=True)


class _Batch(_StateModel):
    uidvalidity: Optional[int]
    uids: list[int]


class _Pause(_StateModel):
    pause_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    reason: Literal["batch", "failures", "state_error"]
    count: int = Field(ge=0)
    notified: bool = False
    source: str = ""
    batch: Optional[_Batch] = None


class _GuardState(_StateModel):
    mailbox_fingerprint: str
    failures: int = Field(default=0, ge=0)
    approved: dict[str, _Batch] = Field(default_factory=dict)
    pause: Optional[_Pause] = None


class MailProcessingGuard:
    """One owner for guard state shared by the monitor and approval replay.

    The monitor owns one instance. Short synchronous transactions use a lock;
    event-loop callers must offload each complete method with run_sync_io.
    This file is separate from the worker-owned discovery watermark so neither
    approval APIs nor wake completions can overwrite mail delivery progress.
    """

    def __init__(self, path: Path, mailbox_fingerprint: str) -> None:
        self._path = path
        self._fingerprint = mailbox_fingerprint
        self._lock = threading.RLock()
        self._state: Optional[_GuardState] = None

    def _load(self) -> _GuardState:
        if self._state is not None:
            return self._state
        state = _GuardState(mailbox_fingerprint=self._fingerprint)
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("mail guard state must be an object")
            if raw.get("mailbox_fingerprint") == self._fingerprint:
                if not {"failures", "approved", "pause"}.issubset(raw):
                    raise ValueError("mail guard state is incomplete")
                state = _GuardState.model_validate(raw)
            elif not isinstance(raw.get("mailbox_fingerprint"), str):
                raise ValueError("mail guard state has no mailbox identity")
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            # Corruption must not silently reopen automatic processing. An
            # explicit user resume can replace the unreadable state safely.
            state.pause = _Pause(reason="state_error", count=0)
        self._state = state
        return state

    def _persist(self, candidate: _GuardState) -> None:
        try:
            write_json_atomic(self._path, candidate.model_dump())
        except OSError:
            state = self._load()
            if state.pause is None:
                state.pause = _Pause(reason="state_error", count=0)
            raise
        self._state = candidate

    def get_pause(self) -> Optional[dict]:
        """Return public state without UID lists or mailbox identifiers."""
        with self._lock:
            pause = self._load().pause
            if pause is None:
                return None
            return pause.model_dump(
                include={"pause_id", "reason", "count", "notified"},
            )

    def check_batch(
        self,
        source: str,
        uids: list[int],
        uidvalidity: Optional[int],
    ) -> bool:
        """Pause an oversized, unconfirmed snapshot before executing work."""
        with self._lock:
            state = self._load()
            if state.pause is not None:
                return False
            current = set(uids)
            batch = state.approved.get(source)
            approved = (
                current.intersection(batch.uids)
                if batch is not None and batch.uidvalidity == uidvalidity
                else set()
            )
            unapproved = sorted(current - approved)
            candidate = state.model_copy(deep=True)
            if approved:
                candidate.approved[source] = _Batch(
                    uidvalidity=uidvalidity,
                    uids=sorted(approved),
                )
            else:
                candidate.approved.pop(source, None)
            if len(unapproved) > BATCH_CONFIRM_THRESHOLD:
                candidate.pause = _Pause(
                    reason="batch",
                    count=len(unapproved),
                    source=source,
                    batch=_Batch(uidvalidity=uidvalidity, uids=unapproved),
                )
            if candidate != state:
                self._persist(candidate)
            return candidate.pause is None

    def record_result(self, succeeded: bool) -> None:
        """Count consecutive wake failures across both delivery paths."""
        with self._lock:
            state = self._load()
            candidate = state.model_copy(deep=True)
            candidate.failures = 0 if succeeded else state.failures + 1
            if (
                candidate.failures >= CONSECUTIVE_FAILURE_LIMIT
                and candidate.pause is None
            ):
                candidate.pause = _Pause(
                    reason="failures",
                    count=candidate.failures,
                )
            if candidate != state:
                self._persist(candidate)

    def resume(self, pause_id: str) -> bool:
        """Durably grant only the shown batch, or reset a failure pause."""
        with self._lock:
            state = self._load()
            pause = state.pause
            if pause is None or pause.pause_id != pause_id:
                return False
            candidate = state.model_copy(deep=True)
            if pause.reason == "batch" and pause.batch is not None:
                previous = state.approved.get(pause.source)
                uids = set(pause.batch.uids)
                if (
                    previous is not None
                    and previous.uidvalidity == pause.batch.uidvalidity
                ):
                    uids.update(previous.uids)
                candidate.approved[pause.source] = _Batch(
                    uidvalidity=pause.batch.uidvalidity,
                    uids=sorted(uids),
                )
            if pause.reason != "batch":
                candidate.failures = 0
            candidate.pause = None
            self._persist(candidate)
            return True

    def mark_notified(self, pause_id: str) -> None:
        """Ack a durable notification without modifying a newer pause."""
        with self._lock:
            state = self._load()
            pause = state.pause
            if pause is None or pause.pause_id != pause_id or pause.notified:
                return
            candidate = state.model_copy(deep=True)
            candidate.pause.notified = True
            self._persist(candidate)
