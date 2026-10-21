# -*- coding: utf-8 -*-
"""TypeSafe account configuration and decision model evaluation."""

from __future__ import annotations

import os
from typing import Any, List, Mapping

import httpx

from ..config.utils import get_config_path
from ..drivers.credentials.store import AsyncCredentialStore
from .provider import ModelConnectionResult, ModelInfo, Provider


class TypeSafeEvaluationError(RuntimeError):
    """Configuration, transport, or response-shape failure."""


class TypeSafeProvider(Provider):
    """Manage TypeSafe models using the standard provider lifecycle."""

    chat_model: str = ""

    def _client(
        self,
        timeout: float,
        *,
        api_key: str | None = None,
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers={
                **self.custom_headers,
                "Authorization": f"Bearer {api_key or self.api_key}",
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
        for name, question in questions.items():
            question_type = question.get("type")
            if not name or question_type not in {"noul", "choice", "score"}:
                raise ValueError(f"invalid question: {name}")
            if "instructions" not in question:
                raise ValueError(f"missing instructions: {name}")
            if question_type in {"choice", "score"} and not question.get(
                "criteria",
            ):
                raise ValueError(f"missing criteria: {name}")
        key = await self._evaluation_api_key()
        if not key:
            raise TypeSafeEvaluationError("TypeSafe API key is not configured")
        try:
            async with self._client(timeout, api_key=key) as client:
                response = await client.post(
                    self.base_url.rstrip("/") + "/systemone",
                    json={
                        "state": state,
                        "model": model,
                        "questions": questions,
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TypeSafeEvaluationError(type(exc).__name__) from exc
        if not isinstance(payload, dict):
            raise TypeSafeEvaluationError("Invalid response envelope")
        answers = payload.get("answers")
        if (
            not isinstance(payload.get("model"), str)
            or not isinstance(answers, dict)
            or not isinstance(payload.get("usage", {}), dict)
            or any(
                not isinstance(answers.get(name), dict) for name in questions
            )
            or any(
                answers[name].get("type") != question.get("type")
                for name, question in questions.items()
            )
        ):
            raise TypeSafeEvaluationError("Invalid response envelope")
        return payload

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
            async with self._client(timeout) as client:
                response = await client.post(
                    self.base_url.rstrip("/") + "/systemone",
                    json={
                        "model": model_id,
                        "state": "Hello",
                        "questions": {
                            "greeting": {
                                "type": "noul",
                                "instructions": "Is the state a greeting?",
                            },
                        },
                    },
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            return ModelConnectionResult(
                success=False,
                message=self.connection_error_message(exc),
                http_status=getattr(
                    getattr(exc, "response", None),
                    "status_code",
                    None,
                ),
            )
        return ModelConnectionResult(success=True)
