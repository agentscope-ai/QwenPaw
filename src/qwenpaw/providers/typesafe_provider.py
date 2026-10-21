# -*- coding: utf-8 -*-
"""TypeSafe account configuration and decision model evaluation."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, List, Mapping

from agentscope.classifier import (
    BinaryQuestion,
    ClassifierQuestion,
    ClassifierResponse,
    JevClassifierModel,
    RefusalAnswer,
)
from agentscope.credential import TypeSafeCredential

from .provider import ModelConnectionResult, ModelInfo, Provider

# Answer type produced by AgentScope for each supported question type.
_ANSWER_TYPES = {
    "binary": "binary_answer",
    "choice": "choice_answer",
    "score": "score_answer",
}


class TypeSafeEvaluationError(RuntimeError):
    """Configuration, transport, or response-shape failure."""

    def __init__(self, message: str, http_status: int | None = None) -> None:
        super().__init__(message)
        self.http_status = http_status


def _from_sdk_error(exc: Exception) -> TypeSafeEvaluationError | None:
    """Translate a ``typesafe_sdk`` failure, or return None for others."""
    try:
        from typesafe_sdk import TypeSafeError
    except ImportError:
        return None
    if not isinstance(exc, TypeSafeError):
        return None
    # API errors carry the HTTP status as ``status``.
    status = getattr(exc, "status", None)
    return TypeSafeEvaluationError(
        f"{type(exc).__name__}: {exc}",
        http_status=status if isinstance(status, int) else None,
    )


class TypeSafeProvider(Provider):
    """Manage TypeSafe models using the standard provider lifecycle."""

    chat_model: str = ""

    @asynccontextmanager
    async def _classifier(
        self,
        model: str,
        timeout: float,
    ) -> AsyncIterator[JevClassifierModel]:
        """Build a Jev classifier and release its HTTP client afterwards.

        SDK failures raised while building or using the classifier are
        normalized to :class:`TypeSafeEvaluationError`.
        """
        key = self.api_key.strip()
        if not key:
            raise TypeSafeEvaluationError("TypeSafe API key is not configured")
        try:
            classifier = JevClassifierModel(
                credential=TypeSafeCredential(
                    api_key=key,
                    base_url=self.base_url.strip() or None,
                ),
                model=model,
                timeout=timeout,
                # Approval decisions are latency-sensitive; fail fast and let
                # the caller fall back to asking the user.
                max_retries=0,
            )
        except ImportError as exc:
            raise TypeSafeEvaluationError(
                "typesafe-sdk is not installed",
            ) from exc
        except Exception as exc:
            error = _from_sdk_error(exc)
            if error is None:
                raise
            raise error from exc
        try:
            yield classifier
        except Exception as exc:
            error = _from_sdk_error(exc)
            if error is None:
                raise
            raise error from exc
        finally:
            await classifier.client.aclose()

    def _call_options(self) -> dict[str, Any]:
        return (
            {"extra_headers": dict(self.custom_headers)}
            if self.custom_headers
            else {}
        )

    async def evaluate(
        self,
        *,
        state: str | dict[str, Any],
        questions: Mapping[str, ClassifierQuestion],
        model: str = "jev-latest",
        timeout: float = 4.0,
    ) -> ClassifierResponse:
        """Submit typed questions and validate the classifier response."""
        if (
            not questions
            or not model.strip()
            or not isinstance(state, (str, dict))
            or timeout <= 0
        ):
            raise ValueError(
                "model, state, questions, and timeout are required",
            )
        for name, question in questions.items():
            if not name or getattr(question, "type", None) not in (
                _ANSWER_TYPES
            ):
                raise ValueError(f"invalid question: {name}")
        async with self._classifier(model, timeout) as classifier:
            response = await classifier(
                state,
                questions,
                **self._call_options(),
            )
        for name, question in questions.items():
            answer = response.content.get(name)
            if isinstance(answer, RefusalAnswer):
                raise TypeSafeEvaluationError(f"Question refused: {name}")
            if getattr(answer, "type", None) != _ANSWER_TYPES[question.type]:
                raise TypeSafeEvaluationError("Invalid response envelope")
        return response

    async def fetch_models(self, timeout: float = 5) -> List[ModelInfo]:
        async with self._classifier("jev-latest", timeout) as classifier:
            response = await classifier.client.models.list(
                **self._call_options(),
            )
        return [
            ModelInfo(
                id=row.name,
                name=row.name,
                model_type="decision",
            )
            for row in response.models
        ]

    async def check_connection(self, timeout: float = 5) -> tuple[bool, str]:
        try:
            await self.fetch_models(timeout)
        except TypeSafeEvaluationError as exc:
            return False, self.connection_error_message(exc)
        return True, ""

    async def check_model_connection(
        self,
        model_id: str,
        timeout: float = 5,
    ) -> ModelConnectionResult:
        try:
            await self.evaluate(
                state="Hello",
                questions={
                    "greeting": BinaryQuestion(
                        instructions="Is the state a greeting?",
                    ),
                },
                model=model_id,
                timeout=timeout,
            )
        except TypeSafeEvaluationError as exc:
            return ModelConnectionResult(
                success=False,
                message=self.connection_error_message(exc),
                http_status=exc.http_status,
            )
        return ModelConnectionResult(success=True)

    @classmethod
    def connection_error_message(cls, exc: Exception) -> str:
        status = getattr(exc, "http_status", None)
        detail = cls.sanitize_connection_message(
            str(exc) or exc.__class__.__name__,
        )
        return f"status={status}: {detail}" if status is not None else detail
