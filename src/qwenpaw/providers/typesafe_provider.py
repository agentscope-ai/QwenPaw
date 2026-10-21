# -*- coding: utf-8 -*-
"""TypeSafe account configuration and decision model evaluation."""

from __future__ import annotations

import os
from dataclasses import asdict
from typing import Any, List, Mapping, cast

import httpx
from agentscope.classifier import (
    BinaryAnswer,
    BinaryQuestion,
    ChoiceAnswer,
    ChoiceQuestion,
    JevClassifierModel,
    ScoreAnswer,
    ScoreQuestion,
)
from agentscope.credential import TypeSafeCredential
from typesafe_sdk import TypeSafeAPIResponseValidationError, TypeSafeError

from ..config.utils import get_config_path
from ..drivers.credentials.store import AsyncCredentialStore
from .provider import ModelConnectionResult, ModelInfo, Provider

_QUESTION_TYPES = {
    "noul": BinaryQuestion,
    "choice": ChoiceQuestion,
    "score": ScoreQuestion,
}
_ANSWER_TYPES = {
    "noul": BinaryAnswer,
    "choice": ChoiceAnswer,
    "score": ScoreAnswer,
}


class TypeSafeEvaluationError(RuntimeError):
    """Configuration, transport, or response-shape failure."""


class TypeSafeProvider(Provider):
    """Manage TypeSafe models using the standard provider lifecycle."""

    chat_model: str = ""

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers={
                **self.custom_headers,
                "Authorization": f"Bearer {self.api_key}",
            },
            timeout=timeout,
        )

    async def _evaluation_api_key(self) -> str | None:
        """Use the provider key, then the legacy Jev key during migration."""
        if self.api_key.strip():
            return self.api_key.strip()
        try:
            store = AsyncCredentialStore(
                get_config_path().parent / "credentials.yaml",
            )
            record = await store.get("services/typesafe_jev")
            key = record.secrets.get("api_key")
            if isinstance(key, str) and key.strip():
                return key.strip()
        except Exception:
            pass
        return os.getenv("TYPESAFE_API_KEY") or None

    async def evaluate(
        self,
        *,
        state: str | dict[str, Any] | list[Any],
        questions: Mapping[str, Mapping[str, Any]],
        model: str = "jev-latest",
        timeout: float = 4.0,
    ) -> dict[str, Any]:
        """Submit typed questions and validate the response envelope."""
        if (
            not questions
            or not model.strip()
            or not isinstance(
                state,
                (str, dict, list),
            )
            or timeout <= 0
        ):
            raise ValueError(
                "model, state, questions, and timeout are required",
            )
        typed_questions = {}
        for name, question in questions.items():
            question_type = question.get("type")
            if not name or question_type not in _QUESTION_TYPES:
                raise ValueError(f"invalid question: {name}")
            if "instructions" not in question:
                raise ValueError(f"missing instructions: {name}")
            if question_type in {"choice", "score"} and not question.get(
                "criteria",
            ):
                raise ValueError(f"missing criteria: {name}")
            typed_questions[name] = _QUESTION_TYPES[question_type](
                **{k: v for k, v in question.items() if k != "type"},
            )
        key = await self._evaluation_api_key()
        if not key:
            raise TypeSafeEvaluationError("TypeSafe API key is not configured")
        try:
            classifier = JevClassifierModel(
                credential=TypeSafeCredential(
                    api_key=key,
                    # The SDK appends /v1 to its API root.
                    base_url=self.base_url.rstrip("/").removesuffix("/v1"),
                ),
                model=model,
                timeout=timeout,
                max_retries=0,
            )
            async with classifier.client:
                response = await classifier(
                    # TypeSafe accepts arrays despite AgentScope's type hint.
                    state=cast(str | dict, state),
                    questions=typed_questions,
                    extra_headers=self.custom_headers,
                )
        except TypeSafeAPIResponseValidationError as exc:
            raise TypeSafeEvaluationError("Invalid response envelope") from exc
        except (TypeSafeError, ValueError) as exc:
            raise TypeSafeEvaluationError(type(exc).__name__) from exc
        answers = {}
        for name, question in questions.items():
            answer = response.content.get(name)
            question_type = question["type"]
            if not isinstance(answer, _ANSWER_TYPES[question_type]):
                raise TypeSafeEvaluationError("Invalid response envelope")
            answers[name] = {
                **(
                    {"noul": answer.probability}
                    if isinstance(answer, BinaryAnswer)
                    else asdict(answer)
                ),
                "type": question_type,
            }
            if isinstance(answer, ScoreAnswer):
                for field in ("legend", "probabilities"):
                    answers[name][field] = {
                        str(k): v for k, v in answers[name][field].items()
                    }
        return {
            "model": response.model,
            "answers": answers,
            "usage": asdict(response.usage) if response.usage else {},
        }

    async def fetch_models(self, timeout: float = 5) -> List[ModelInfo]:
        async with self._client(timeout) as client:
            response = await client.get(
                self.base_url.rstrip("/") + "/models",
            )
            response.raise_for_status()
            return [
                ModelInfo(
                    id=row["name"],
                    name=row["name"],
                    model_type="decision",
                )
                for row in response.json()["models"]
            ]

    async def check_connection(self, timeout: float = 5) -> tuple[bool, str]:
        try:
            await self.fetch_models(timeout)
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            return False, self.connection_error_message(exc)
        return True, ""

    async def check_model_connection(
        self,
        model_id: str,
        timeout: float = 5,
    ) -> ModelConnectionResult:
        try:
            await self.evaluate(
                model=model_id,
                state="Hello",
                questions={
                    "greeting": {
                        "type": "noul",
                        "instructions": "Is the state a greeting?",
                    },
                },
                timeout=timeout,
            )
        except (TypeSafeEvaluationError, ValueError) as exc:
            cause = exc.__cause__
            if not isinstance(cause, Exception):
                cause = exc
            return ModelConnectionResult(
                success=False,
                message=self.connection_error_message(cause),
                http_status=getattr(cause, "status", None),
            )
        return ModelConnectionResult(success=True)
