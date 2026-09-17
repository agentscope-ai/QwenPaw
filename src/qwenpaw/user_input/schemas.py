# -*- coding: utf-8 -*-
"""Schemas for structured user input requests."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

QuestionKind = Literal["single_choice", "free_text", "choice_with_custom"]
RequestStatus = Literal["pending", "answered", "ignored", "timeout", "cancelled"]
AnswerAction = Literal["submit", "ignore", "cancel"]


class UserInputOption(BaseModel):
    """One selectable option for a structured question."""

    label: str
    value: str
    description: str | None = None
    recommended: bool = False


class UserInputQuestion(BaseModel):
    """One question shown to the user."""

    id: str
    question: str
    kind: QuestionKind = "choice_with_custom"
    options: list[UserInputOption] = Field(default_factory=list)
    placeholder: str | None = None
    required: bool = True
    default_value: str | None = None

    @field_validator("id", "question")
    @classmethod
    def _not_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class UserInputRequest(BaseModel):
    """Serializable pending request sent to the frontend."""

    request_id: str
    agent_id: str
    session_id: str
    root_session_id: str
    user_id: str
    channel: str
    title: str | None = None
    questions: list[UserInputQuestion]
    question_index: int = 0
    total_questions: int = 1
    status: RequestStatus = "pending"
    created_at: float
    timeout_seconds: float


class UserInputAnswer(BaseModel):
    """Frontend answer payload."""

    answers: dict[str, Any] = Field(default_factory=dict)
    action: AnswerAction = "submit"


class UserInputResult(BaseModel):
    """Result returned to the waiting tool call."""

    request_id: str
    status: RequestStatus
    answers: dict[str, Any] = Field(default_factory=dict)
