# -*- coding: utf-8 -*-
"""Lifecycle service for ``AskUserQuestion`` tool.

Manages questionnaire creation, asyncio.Future suspend/resume, timeout,
cancellation and interrupt. The single source of truth for the Future key
is ``session_id``: under the current architecture the agent invokes tools
sequentially per session, so at most one questionnaire is active per
session. ``questionnaire.id`` (UUID) is kept for log correlation only and
is not exposed to the frontend.

Override semantics: ``create_questionnaire`` releases any pending Future
for the same session before installing the new one, so a re-entrant tool
call cannot leave a stale ``pending`` state behind.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .models import (
    Question,
    QuestionAnswer,
    Questionnaire,
    QuestionnaireStatus,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 300

# Module-level singleton; replaced by DI if a test needs isolation.
_question_service: QuestionService | None = None


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class QuestionService:
    """Manages the questionnaire lifecycle.

    Responsibilities:
      * create questionnaire (passes LLM-supplied questions through as-is;
        the backend no longer injects an "Other" option or a supplementary
        question — that lives in ``AskUserQuestionCard`` to keep a single
        source of truth).
      * create asyncio.Future to suspend the agent coroutine until the
        user submits / cancels / interrupts / times out.
      * deliver the result to the suspended coroutine.

    Storage:
      * ``_active_questionnaires``: ``dict[session_id, Questionnaire]``
      * ``_futures``: ``dict[session_id, asyncio.Future[dict]]``
    """

    def __init__(
        self, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self._active_questionnaires: dict[str, Questionnaire] = {}
        self._futures: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    def _release_pending(
        self,
        session_id: str,
        status: str = "cancelled",
    ) -> None:
        """Release any pending Future for ``session_id``.

        Called from ``create_questionnaire`` to guarantee a clean slate:
        when the agent re-enters the tool while a previous questionnaire
        is still pending, the old coroutine must wake up and exit before
        the new one takes the key.

        Both bookkeeping dicts are popped here so the subsequent
        ``create_questionnaire`` write starts from a truly empty slot —
        leaving the old questionnaire record behind would let a racing
        ``_finalize`` resurrect it.

        Caller must hold ``self._lock`` (or call from a non-reentrant
        path) — the future ``set_result`` below runs **outside** the lock
        to avoid re-entrancy deadlocks.
        """
        self._active_questionnaires.pop(session_id, None)

        old_future = self._futures.pop(session_id, None)
        if old_future is not None and not old_future.done():
            old_future.set_result(
                {
                    "questionnaire_id": "",
                    "session_id": session_id,
                    "answers": [],
                    "status": status,
                },
            )

    async def _finalize(
        self,
        session_id: str,
        *,
        status: QuestionnaireStatus,
        answers: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """Atomically resolve the questionnaire lifecycle.

        Single entry point used by ``submit_answer`` / ``cancel`` /
        ``interrupt`` / ``_handle_timeout``. Centralising the path fixes
        three races present in the original implementation:

          * duplicate "change status / pop dict / set_result" blocks (DRY).
          * state mutation under the lock while ``set_result`` ran outside
            (M3).
          * silently dropping ``answers`` when the future had already been
            resolved by a concurrent path (M3).

        Returns:
            ``dict`` on the happy path; ``None`` if the questionnaire was
            already finalised by another coroutine — in that case neither
            ``_active_questionnaires`` nor the Future is touched, to avoid
            overwriting an answer that has already been delivered (M3).
            Any live orphan is left for ``_release_pending`` to clean up
            on the next ``create_questionnaire``.
        """
        async with self._lock:
            questionnaire = self._active_questionnaires.pop(session_id, None)

        if questionnaire is None:
            # Already finalised by a concurrent path (e.g. timeout / cancel /
            # interrupt beat us here). We deliberately do NOT touch the
            # Future: any live orphan is the previous winner's, and we must
            # not overwrite an already-delivered answer (M3). The next
            # ``create_questionnaire`` for this session cleans up via
            # ``_release_pending``.
            logger.debug(
                "questionnaire already gone for session %s (status=%s)",
                session_id,
                status.value,
            )
            return None

        # Lock released: writing dataclass fields and Future is safe here
        # and must not run under ``self._lock`` to avoid blocking other
        # callers while ``set_result`` schedules continuations.
        questionnaire.status = status
        questionnaire.resolved_at = time.time()
        if answers is not None:
            questionnaire.answers = [
                QuestionAnswer(
                    question_index=a["question_index"],
                    answer=a["answer"],
                    supplementary_input=a.get("supplementary_input", ""),
                )
                for a in answers
            ]

        result: dict[str, Any] = {
            "questionnaire_id": questionnaire.id,
            "session_id": session_id,
            "answers": (
                [a.to_dict() for a in questionnaire.answers]
                if answers is not None
                else []
            ),
            "status": status.value,
        }

        future = self._futures.pop(session_id, None)
        if future is not None and not future.done():
            future.set_result(result)

        logger.info(
            "Questionnaire finalized: session=%s status=%s answers=%d "
            "questionnaire=%s",
            session_id,
            status.value,
            len(result["answers"]),
            questionnaire.id,
        )
        return result

    async def create_questionnaire(
        self,
        questions: list[Question],
        timeout_seconds: float | None = None,
        session_id: str = "",
        agent_id: str = "",
        channel: str = "",
    ) -> Questionnaire:
        """Create a questionnaire and register it as active.

        Args:
            questions: Question list (used as-is; no option injection).
            timeout_seconds: Per-call override; falls back to the service
                default.
            session_id: Used as the storage key. Must match the
                ``session_id`` the frontend later resolves the Future on.
            agent_id: Owning agent id, for log correlation.
            channel: Originating channel name (e.g. ``"console"``).

        Returns:
            The created ``Questionnaire`` (without a Future attached; call
            ``create_future`` or ``create_and_wait`` to suspend).
        """
        effective_timeout = timeout_seconds or self.timeout_seconds

        async with self._lock:
            self._release_pending(session_id, status="cancelled")

            questionnaire = Questionnaire.create(
                questions=questions,
                timeout_seconds=effective_timeout,
                session_id=session_id,
                agent_id=agent_id,
                channel=channel,
            )
            self._active_questionnaires[session_id] = questionnaire

        logger.info(
            "Questionnaire created: session=%s questions=%d timeout=%ds",
            session_id,
            len(questionnaire.questions),
            effective_timeout,
        )

        return questionnaire

    async def create_and_wait(
        self,
        questions: list[Question],
        timeout_seconds: float | None = None,
        session_id: str = "",
        agent_id: str = "",
        channel: str = "",
    ) -> dict[str, Any]:
        """Create a questionnaire and block until it resolves.

        Main entry point used by the tool: chains create → Future →
        timeout task → await.

        Returns:
            ``{questionnaire_id, session_id, answers, status}`` dict. The
            ``status`` field is one of ``completed`` / ``cancelled`` /
            ``timeout`` / ``interrupted``.
        """
        questionnaire = await self.create_questionnaire(
            questions=questions,
            timeout_seconds=timeout_seconds,
            session_id=session_id,
            agent_id=agent_id,
            channel=channel,
        )

        future = await self.create_future(session_id)
        questionnaire.future = future

        timeout_task = asyncio.create_task(
            self._handle_timeout(session_id),
            name=(
                f"questionnaire-timeout-"
                f"{session_id[:8] if session_id else 'empty'}"
            ),
        )

        # The +1s slack keeps ``_handle_timeout`` (the authoritative
        # timeout path) the one that writes ``status=timeout``; the outer
        # ``wait_for`` is just a belt-and-braces against event-loop stalls.
        try:
            result = await asyncio.wait_for(
                future,
                timeout=questionnaire.timeout_seconds + 1.0,
            )
            return result
        except asyncio.TimeoutError:
            logger.warning(
                "Outer wait_for timeout fallback for session %s "
                "(questionnaire=%s)",
                session_id,
                questionnaire.id,
            )
            return {
                "questionnaire_id": questionnaire.id,
                "session_id": session_id,
                "answers": [],
                "status": "timeout",
            }
        finally:
            if not timeout_task.done():
                timeout_task.cancel()
                try:
                    await timeout_task
                except asyncio.CancelledError:
                    pass

    async def create_future(
        self, session_id: str
    ) -> asyncio.Future[dict[str, Any]]:
        """Create a Future that resolves when the questionnaire does.

        Args:
            session_id: Session id; must already have an active
                questionnaire (otherwise ``ValueError``).

        Returns:
            The newly created Future.

        Raises:
            ValueError: No active questionnaire for ``session_id``.

        Notes:
            Existence is checked **inside** ``self._lock`` so the question-
            naire cannot be popped by a concurrent ``_finalize`` between
            the check and the future registration. Without the lock a
            racing ``cancel`` could pop the questionnaire after the check
            but before the future is registered, leaving an orphan future
            that no ``_finalize`` will ever resolve.
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        async with self._lock:
            if session_id not in self._active_questionnaires:
                future.cancel()
                raise ValueError(
                    f"Questionnaire for session {session_id} not found"
                )
            self._futures[session_id] = future
        return future

    async def submit_answer(
        self,
        session_id: str,
        answers: list[dict[str, Any]],
    ) -> None:
        """Submit answers and resume the suspended Future.

        Args:
            session_id: Must match the one used in ``create_questionnaire``.
            answers: List of ``{question_index, answer, supplementary_input}``.

        Raises:
            ValueError: No active questionnaire (already submitted,
                timed out or cancelled), or the questionnaire was
                finalised by a concurrent path between the router's
                request and this call (timeout / cancel won the race).

        Notes:
            Existence is checked atomically inside ``_finalize`` rather
            than as a separate locked pre-check. The earlier check-then-act
            shape let ``_handle_timeout`` slip in between the pre-check
            and the real finalize, silently dropping the user's answers
            while the router still returned 200.
        """
        result = await self._finalize(
            session_id,
            status=QuestionnaireStatus.COMPLETED,
            answers=answers,
        )

        if result is None:
            # Either there never was an active questionnaire, or a
            # concurrent ``_handle_timeout`` / ``cancel`` / ``interrupt``
            # beat us to ``_finalize``. Surfacing this as ValueError keeps
            # the router's 404 contract honest: the caller learns their
            # answers were NOT delivered instead of a silent 200.
            logger.warning(
                "Questionnaire already finalized for session %s — "
                "answers dropped",
                session_id,
            )
            raise ValueError(
                f"No active questionnaire for session {session_id}"
            )

    async def cancel(self, session_id: str) -> None:
        """Cancel an active questionnaire.

        Args:
            session_id: Session id.

        Raises:
            ValueError: No active questionnaire for ``session_id``.
        """
        async with self._lock:
            exists = session_id in self._active_questionnaires
        if not exists:
            logger.warning(
                "No active questionnaire for session %s",
                session_id,
            )
            raise ValueError(
                f"No active questionnaire for session {session_id}"
            )

        await self._finalize(session_id, status=QuestionnaireStatus.CANCELLED)

    async def cancel_if_exists(self, session_id: str) -> None:
        """Cancel iff an active questionnaire exists; otherwise no-op.

        Used on new-message-arrival paths where raising for an unknown
        session would be incorrect.

        Args:
            session_id: Session id.
        """
        logger.debug(
            "cancel_if_exists: checking session %s",
            session_id,
        )
        async with self._lock:
            if session_id not in self._active_questionnaires:
                logger.debug(
                    "cancel_if_exists: no active questionnaire for "
                    "session %s, skipping",
                    session_id,
                )
                return

        await self.cancel(session_id)

    async def interrupt(self, session_id: str) -> dict[str, Any]:
        """Mark the questionnaire as ``interrupted``.

        Called when the user actively aborts the tool invocation, so the
        suspended coroutine can be released and return a structured
        payload.

        Args:
            session_id: Session id.

        Returns:
            A ``{questionnaire_id, session_id, answers, status}`` dict.
            Even when no questionnaire is active, a uniform ``status =
            "interrupted"`` payload is returned so callers can render a
            consistent UI state.
        """
        result = await self._finalize(
            session_id,
            status=QuestionnaireStatus.INTERRUPTED,
        )
        if result is None:
            return {
                "questionnaire_id": "",
                "session_id": session_id,
                "answers": [],
                "status": QuestionnaireStatus.INTERRUPTED.value,
            }
        return result

    def list_active(
        self,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return a snapshot of the active questionnaires.

        Args:
            session_id: Optional filter; when set, only questionnaires
                for this session are returned.

        Returns:
            List of ``Questionnaire.to_dict()`` payloads.

        Notes:
            Snapshot-only and **not safe for decision making**. The copy
            is taken without the lock, so concurrent ``_finalize`` calls
            may add or remove entries between the snapshot and the
            ``to_dict`` serialisation. Use for observability / admin UIs
            only; do not gate lifecycle decisions on this view.
        """
        snapshot = list(self._active_questionnaires.values())
        if session_id is not None:
            snapshot = [q for q in snapshot if q.session_id == session_id]
        return [q.to_dict() for q in snapshot]

    async def _handle_timeout(self, session_id: str) -> None:
        """Fire ``status=timeout`` if the questionnaire is still pending.

        ``_finalize`` is idempotent: if the user already submitted,
        cancelled or interrupted, this is a no-op and the existing
        Future result is preserved (M3 fix).

        Notes:
            ``CancelledError`` raised by ``create_and_wait``'s teardown
            (or by asyncio internals during shutdown) is swallowed —
            we are best-effort and the Future has already been resolved
            by the winning path anyway. Surfacing it here would only
            produce stack traces for a controlled teardown.
        """
        async with self._lock:
            questionnaire = self._active_questionnaires.get(session_id)
            if questionnaire is None:
                return
            timeout_seconds = questionnaire.timeout_seconds

        try:
            await asyncio.sleep(timeout_seconds)
            await self._finalize(
                session_id, status=QuestionnaireStatus.TIMEOUT
            )
        except asyncio.CancelledError:
            # Controlled teardown: the parent ``create_and_wait`` cancelled
            # us because the questionnaire already resolved through
            # ``submit_answer`` / ``cancel`` / ``interrupt``. No logging:
            # the future state is the authoritative record.
            raise


def get_question_service() -> QuestionService:
    """Return the process-wide ``QuestionService`` singleton."""
    global _question_service
    if _question_service is None:
        _question_service = QuestionService()
    return _question_service
