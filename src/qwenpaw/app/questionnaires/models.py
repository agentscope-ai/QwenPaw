# -*- coding: utf-8 -*-
"""Questionnaire data models for AskUserQuestion tool.

Defines the core data structures for the questionnaire system:
- QuestionType: enum for question types (single/multi select, text input)
- QuestionnaireStatus: enum for questionnaire lifecycle states
- Question: single question definition
- QuestionAnswer: user's answer to a single question
- Questionnaire: complete questionnaire with questions and answers
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class QuestionType(StrEnum):
    """Enumeration of supported question types."""

    # Single choice: the user picks exactly one option.
    SINGLE_SELECT = "SINGLE_SELECT"
    # Multiple choice: the user picks any number of options.
    MULTI_SELECT = "MULTI_SELECT"
    # Free-form text input.
    TEXT_INPUT = "TEXT_INPUT"


class QuestionnaireStatus(StrEnum):
    """Enumeration of questionnaire lifecycle states."""

    # Waiting: the questionnaire has been created and is awaiting an answer.
    PENDING = "pending"
    # Completed: the user submitted answers.
    COMPLETED = "completed"
    # Timed out: no answer arrived within the allotted window.
    TIMEOUT = "timeout"
    # Cancelled: the user or the system cancelled the questionnaire.
    CANCELLED = "cancelled"
    # Interrupted: the user actively aborted the tool invocation.
    INTERRUPTED = "interrupted"


@dataclass
class Question:
    """A single question definition.

    Attributes:
        question_type: The kind of question (single / multi / text input).
        prompt: The human-readable question text.
        options: Choice list; only meaningful for SELECT types.
    """

    question_type: QuestionType
    prompt: str
    options: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict (for JSON transport)."""
        return {
            "question_type": self.question_type.value,
            "prompt": self.prompt,
            "options": self.options,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Question:
        """Rebuild an instance from a dict (deserialisation)."""
        return cls(
            question_type=QuestionType(data["question_type"]),
            prompt=data["prompt"],
            options=data.get("options", []),
        )


@dataclass
class QuestionAnswer:
    """The user's answer to a single question.

    Attributes:
        question_index: Zero-based index of the question in the questionnaire.
        answer: The user's answer payload.
        supplementary_input: Optional free-form supplement from the user.
    """

    question_index: int
    answer: str
    supplementary_input: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict (for JSON transport)."""
        result: dict[str, Any] = {
            "question_index": self.question_index,
            "answer": self.answer,
        }
        if self.supplementary_input:
            result["supplementary_input"] = self.supplementary_input
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QuestionAnswer:
        """Rebuild an instance from a dict (deserialisation)."""
        return cls(
            question_index=data["question_index"],
            answer=data["answer"],
            supplementary_input=data.get("supplementary_input", ""),
        )


@dataclass
class Questionnaire:
    """A complete questionnaire for a single ``AskUserQuestion`` invocation.

    Attributes:
        id: Unique questionnaire identifier (UUID).
        questions: The question list.
        answers: The user's answer list.
        status: Lifecycle status.
        timeout_seconds: Answer window in seconds.
        session_id: Owning session ID.
        agent_id: Owning agent ID.
        channel: Originating channel.
        created_at: Creation timestamp.
        resolved_at: Completion / cancellation / timeout timestamp.
        future: The ``asyncio.Future`` used to suspend the agent coroutine.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    questions: list[Question] = field(default_factory=list)
    answers: list[QuestionAnswer] = field(default_factory=list)
    status: QuestionnaireStatus = QuestionnaireStatus.PENDING
    timeout_seconds: float = 300.0  # default: 5 minutes
    session_id: str = ""
    agent_id: str = ""
    channel: str = ""
    created_at: float = 0.0
    resolved_at: float | None = None
    future: Any = None  # asyncio.Future; concrete type resolved at runtime

    @classmethod
    def create(
        cls,
        questions: list[Question],
        timeout_seconds: float = 300.0,
        session_id: str = "",
        agent_id: str = "",
        channel: str = "",
    ) -> Questionnaire:
        """Create a new questionnaire instance.

        Args:
            questions: Question list.
            timeout_seconds: Answer window in seconds.
            session_id: Session ID.
            agent_id: Agent ID.
            channel: Originating channel.

        Returns:
            The newly created ``Questionnaire``.
        """
        import time

        return cls(
            questions=questions,
            timeout_seconds=timeout_seconds,
            session_id=session_id,
            agent_id=agent_id,
            channel=channel,
            created_at=time.time(),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict (for JSON transport)."""
        return {
            "id": self.id,
            "questions": [q.to_dict() for q in self.questions],
            "answers": [a.to_dict() for a in self.answers],
            "status": self.status.value,
            "timeout_seconds": self.timeout_seconds,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "channel": self.channel,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Questionnaire:
        """Rebuild an instance from a dict (deserialisation)."""
        return cls(
            id=data["id"],
            questions=[
                Question.from_dict(q) for q in data.get("questions", [])
            ],
            answers=[
                QuestionAnswer.from_dict(a) for a in data.get("answers", [])
            ],
            status=QuestionnaireStatus(data["status"]),
            timeout_seconds=data.get("timeout_seconds", 300.0),
            session_id=data.get("session_id", ""),
            agent_id=data.get("agent_id", ""),
            channel=data.get("channel", ""),
            created_at=data.get("created_at", 0.0),
            resolved_at=data.get("resolved_at"),
        )
