# -*- coding: utf-8 -*-
"""In-memory service for structured user input requests."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

from ..identity.runtime import is_multi_user_enabled

from .broadcast import broadcast_user_input_update
from .schemas import (
    UserInputAnswer,
    UserInputQuestion,
    UserInputRequest,
    UserInputResult,
)

logger = logging.getLogger(__name__)

_GC_PENDING_MAX_AGE_SECONDS = 1800.0
_GC_MAX_PENDING = 200


@dataclass
class PendingUserInput:
    """Runtime pending input request with its waiting future."""

    request: UserInputRequest
    future: asyncio.Future[UserInputResult]
    all_questions: list[UserInputQuestion]
    answers: dict[str, Any]
    question_index: int = 0


class UserInputService:
    """Process-wide pending structured input store."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._pending: dict[str, PendingUserInput] = {}

    async def create_pending(
        self,
        *,
        session_id: str,
        root_session_id: str,
        user_id: str,
        channel: str,
        agent_id: str,
        title: str | None,
        questions: list[UserInputQuestion],
        timeout_seconds: float = 300.0,
        recipient_user_id: str | None = None,
    ) -> UserInputRequest:
        """Create a pending request and broadcast it."""
        if is_multi_user_enabled():
            if not recipient_user_id:
                raise ValueError("User input requires a trusted user identity")
            user_id = recipient_user_id
        request_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        request = UserInputRequest(
            request_id=request_id,
            agent_id=agent_id,
            session_id=session_id,
            root_session_id=root_session_id,
            user_id=user_id,
            channel=channel,
            title=title,
            questions=[questions[0]],
            question_index=0,
            total_questions=len(questions),
            created_at=time.time(),
            timeout_seconds=timeout_seconds,
        )
        pending = PendingUserInput(
            request=request,
            future=loop.create_future(),
            all_questions=questions,
            answers={},
        )

        async with self._lock:
            self._pending[request_id] = pending
            self._gc_pending_locked()

        logger.info(
            "User input pending created: request_id=%s agent_id=%s "
            "session=%s root=%s questions=%d",
            request_id[:8],
            agent_id,
            session_id[:8],
            root_session_id[:8],
            len(questions),
        )
        self._broadcast("user_input_request", request)
        return request

    async def get_pending(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str | None = None,
    ) -> UserInputRequest | None:
        """Return the oldest pending request for the session/root session."""
        async with self._lock:
            matches = [
                pending.request
                for pending in self._pending.values()
                if pending.request.agent_id == agent_id
                and (
                    not is_multi_user_enabled()
                    or (user_id and pending.request.user_id == user_id)
                )
                and pending.request.status == "pending"
                and (
                    pending.request.session_id == session_id
                    or pending.request.root_session_id == session_id
                )
            ]
        if not matches:
            return None
        return sorted(matches, key=lambda item: item.created_at)[0]

    async def answer_request(
        self,
        request_id: str,
        answer: UserInputAnswer,
        *,
        agent_id: str | None = None,
        user_id: str | None = None,
    ) -> UserInputRequest | None:
        """Resolve or advance a pending request from a frontend answer."""
        async with self._lock:
            pending = self._pending.get(request_id)
            if pending is None:
                return None
            if is_multi_user_enabled() and (
                not user_id
                or pending.request.user_id != user_id
                or pending.request.agent_id != agent_id
            ):
                return None

            if answer.action == "submit":
                pending.answers.update(dict(answer.answers or {}))
                if pending.question_index < len(pending.all_questions) - 1:
                    pending.question_index += 1
                    pending.request.question_index = pending.question_index
                    pending.request.questions = [
                        pending.all_questions[pending.question_index],
                    ]
                    next_request = pending.request
                    result = None
                else:
                    self._pending.pop(request_id, None)
                    pending.request.status = "answered"
                    next_request = pending.request
                    result = UserInputResult(
                        request_id=request_id,
                        status="answered",
                        answers=dict(pending.answers),
                    )
            else:
                self._pending.pop(request_id, None)
                status = {
                    "ignore": "ignored",
                    "cancel": "cancelled",
                }[answer.action]
                pending.request.status = status  # type: ignore[assignment]
                next_request = pending.request
                result = UserInputResult(
                    request_id=request_id,
                    status=status,  # type: ignore[arg-type]
                    answers=dict(pending.answers),
                )

        if result is None:
            self._broadcast("user_input_request", next_request)
            return next_request

        if not pending.future.done():
            pending.future.set_result(result)
        self._broadcast("user_input_update", next_request, result)
        return next_request

    async def wait_for_result(
        self,
        request_id: str,
        timeout_seconds: float,
    ) -> UserInputResult:
        """Wait for the answer or resolve as timeout."""
        async with self._lock:
            pending = self._pending.get(request_id)
        if pending is None:
            raise ValueError(f"User input request {request_id} not found")

        try:
            return await asyncio.wait_for(
                pending.future,
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            return await self._timeout_request(request_id)

    async def cancel_all_pending_by_root_session(
        self,
        root_session_id: str,
        *,
        agent_id: str | None = None,
        user_id: str | None = None,
    ) -> int:
        """Cancel all pending requests for a root session."""
        cancelled = 0
        async with self._lock:
            items = [
                (key, pending)
                for key, pending in self._pending.items()
                if pending.request.root_session_id == root_session_id
                and (
                    not is_multi_user_enabled()
                    or (
                        user_id
                        and pending.request.user_id == user_id
                        and pending.request.agent_id == agent_id
                    )
                )
                and pending.request.status == "pending"
            ]
            for key, pending in items:
                self._pending.pop(key, None)
                pending.request.status = "cancelled"
                result = UserInputResult(
                    request_id=key,
                    status="cancelled",
                    answers={},
                )
                if not pending.future.done():
                    pending.future.set_result(result)
                self._broadcast("user_input_update", pending.request, result)
                cancelled += 1
        return cancelled

    async def _timeout_request(self, request_id: str) -> UserInputResult:
        async with self._lock:
            pending = self._pending.pop(request_id, None)
        result = UserInputResult(
            request_id=request_id,
            status="timeout",
            answers={},
        )
        if pending is None:
            return result
        pending.request.status = "timeout"
        if not pending.future.done():
            pending.future.set_result(result)
        self._broadcast("user_input_update", pending.request, result)
        return result

    def _broadcast(
        self,
        event_type: str,
        request: UserInputRequest,
        result: UserInputResult | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "type": event_type,
            "request": request.model_dump(),
            "session_id": request.session_id,
            "root_session_id": request.root_session_id,
        }
        if result is not None:
            payload["result"] = result.model_dump()
        broadcast_user_input_update(request.agent_id, payload, user_id=request.user_id)

    def _gc_pending_locked(self) -> None:
        now = time.time()
        expired = [
            key
            for key, pending in self._pending.items()
            if now - pending.request.created_at > _GC_PENDING_MAX_AGE_SECONDS
        ]
        for key in expired:
            pending = self._pending.pop(key)
            pending.request.status = "timeout"
            result = UserInputResult(
                request_id=key,
                status="timeout",
                answers={},
            )
            if not pending.future.done():
                pending.future.set_result(result)
            self._broadcast("user_input_update", pending.request, result)

        overflow = len(self._pending) - _GC_MAX_PENDING
        if overflow <= 0:
            return
        ordered = sorted(
            self._pending.items(),
            key=lambda item: item[1].request.created_at,
        )
        for key, pending in ordered[:overflow]:
            self._pending.pop(key, None)
            pending.request.status = "timeout"
            result = UserInputResult(
                request_id=key,
                status="timeout",
                answers={},
            )
            if not pending.future.done():
                pending.future.set_result(result)
            self._broadcast("user_input_update", pending.request, result)


_service: UserInputService | None = None


def get_user_input_service() -> UserInputService:
    """Return the process-wide user input service singleton."""
    global _service
    if _service is None:
        _service = UserInputService()
    return _service
