# -*- coding: utf-8 -*-
"""REST endpoints backing the ``AskUserQuestion`` tool.

Endpoints:
  * ``POST /questionnaire/submit`` — submit answers, resume the suspended
    agent coroutine (consumed by the frontend ``AskUserQuestionCard``).
  * ``GET  /questionnaire/list``   — list active questionnaires (debug /
    admin UI only; no first-party frontend caller yet).

Active cancellation is reached via the Python ``QuestionService.cancel``
API, used by ``QuestionnaireCleanupHook``.  There is no HTTP
``/questionnaire/cancel`` endpoint.

Keying: the ``session_id`` (not the questionnaire UUID) is the public
identifier. The frontend reads it from ``window.currentSessionId`` so it
byte-for-byte matches the value the tool pulled from the agent's context
var; this is the single key under which ``QuestionService`` parks the
asyncio.Future.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..questionnaires.service import get_question_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/questionnaire", tags=["questionnaire"])


class SubmitAnswerRequest(BaseModel):
    """Payload for ``POST /questionnaire/submit``."""

    session_id: str = Field(
        ...,
        description="Session id; must match the one used by the tool.",
    )
    answers: list[dict] = Field(
        ...,
        description=(
            "Per-question answer list. Each item is "
            "{question_index, answer, supplementary_input?}."
        ),
    )


class SubmitAnswerResponse(BaseModel):
    """Response for the submit endpoint."""

    success: bool
    message: str
    session_id: str


class QuestionnaireListResponse(BaseModel):
    """Response for ``GET /questionnaire/list``."""

    questionnaires: list[dict]
    count: int


@router.post(
    "/submit",
    response_model=SubmitAnswerResponse,
    summary="Submit answers to a questionnaire",
)
async def submit_answer(
    request: Request,  # pylint: disable=unused-argument
    body: SubmitAnswerRequest,
) -> SubmitAnswerResponse:
    """Submit answers and resume the suspended agent coroutine.

    Called by the frontend after the user fills in the questionnaire
    form. A successful response means the agent will see the answers on
    its next iteration.
    """
    svc = get_question_service()

    logger.info(
        "Questionnaire submit: session=%s answers=%d",
        body.session_id[:8] if body.session_id else "<empty>",
        len(body.answers),
    )

    try:
        await svc.submit_answer(
            body.session_id,
            body.answers,
        )
    except ValueError as e:
        logger.warning("Questionnaire not found: %s", e)
        raise HTTPException(
            status_code=404,
            detail=(
                f"No active questionnaire for session: "
                f"{body.session_id[:16]}"
            ),
        ) from e
    except Exception as e:
        logger.exception("Failed to submit answer")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to submit answer: {e!s}",
        ) from e

    logger.info(
        "Questionnaire for session %s submitted successfully",
        body.session_id[:8] if body.session_id else "<empty>",
    )

    return SubmitAnswerResponse(
        success=True,
        message="Answer submitted successfully",
        session_id=body.session_id,
    )


@router.get(
    "/list",
    response_model=QuestionnaireListResponse,
    summary="List active questionnaires",
)
async def list_questionnaires(
    request: Request,  # pylint: disable=unused-argument
    session_id: Optional[str] = None,
) -> QuestionnaireListResponse:
    """List active questionnaires, optionally filtered by ``session_id``.

    Snapshot view — see ``QuestionService.list_active`` for consistency
    semantics.
    """
    svc = get_question_service()

    # M4: route goes through the public accessor rather than reaching
    # into ``svc._lock`` / ``svc._active_questionnaires``.
    items = svc.list_active(session_id=session_id)

    return QuestionnaireListResponse(
        questionnaires=items,
        count=len(items),
    )
