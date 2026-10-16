# -*- coding: utf-8 -*-
"""Reusable TypeSafe Jev client backed by the standard model provider.

Callers own their questions, state projection, response interpretation, and
failure policy. This module deliberately has no security-mode semantics.
"""

from __future__ import annotations

import os
import asyncio
from dataclasses import dataclass, field
from typing import Any, Mapping

import httpx

from ..config.utils import get_config_path
from ..drivers.credentials.store import AsyncCredentialStore

_CREDENTIAL_REF = "services/typesafe_jev"
_EVALUATION_PATH = "/systemone"


class JevServiceError(RuntimeError):
    """Configuration, transport, HTTP, or response-shape failure."""


@dataclass(frozen=True)
class JevRequest:
    state: str | dict[str, Any] | list[Any]
    questions: Mapping[str, Mapping[str, Any]]
    model: str | None = None


@dataclass(frozen=True)
class JevResponse:
    model: str
    answers: dict[str, dict[str, Any]]
    usage: dict[str, Any] = field(default_factory=dict)


def _credential_store() -> AsyncCredentialStore:
    return AsyncCredentialStore(get_config_path().parent / "credentials.yaml")


def _provider_settings() -> tuple[str, str, str, dict[str, str]]:
    """Read the configured TypeSafe provider and decision model."""
    from ..providers.provider_manager import ProviderManager

    try:
        manager = ProviderManager.get_instance()
        provider = manager.get_provider("typesafe")
    except Exception as exc:
        raise JevServiceError("TypeSafe provider is unavailable") from exc
    if provider is None or not provider.enabled:
        raise JevServiceError("TypeSafe provider is unavailable")
    slot = manager.default_models.get("decision")
    model = (
        slot.model
        if slot is not None and slot.provider_id == "typesafe"
        else "jev-latest"
    )
    return provider.api_key, provider.base_url, model, provider.custom_headers


async def get_api_key() -> str | None:
    """Use the provider key, then an older Jev key during migration."""
    provider_key, _, _, _ = await asyncio.to_thread(_provider_settings)
    if provider_key.strip():
        return provider_key.strip()
    try:
        record = await _credential_store().get(_CREDENTIAL_REF)
        key = record.secrets.get("api_key")
        if isinstance(key, str) and key.strip():
            return key.strip()
    except Exception:
        pass
    return os.getenv("TYPESAFE_API_KEY") or None


class JevClient:
    """Async typed-question API for security, context, and other uses."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 4.0,
        base_url: str | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds
        self.base_url = base_url

    async def evaluate(self, request: JevRequest) -> JevResponse:
        """Submit one state with typed questions; validate envelope only."""
        if (
            not request.questions
            or (request.model is not None and not request.model.strip())
            or not isinstance(request.state, (str, dict, list))
        ):
            raise ValueError("model and questions are required")
        for name, question in request.questions.items():
            question_type = question.get("type")
            if not name or question_type not in {"noul", "choice", "score"}:
                raise ValueError(f"invalid question: {name}")
            if "instructions" not in question:
                raise ValueError(f"missing instructions: {name}")
            if question_type in {"choice", "score"} and not question.get(
                "criteria",
            ):
                raise ValueError(f"missing criteria: {name}")
        (
            _,
            provider_base_url,
            provider_model,
            custom_headers,
        ) = await asyncio.to_thread(
            _provider_settings,
        )
        key = await get_api_key()
        if not key:
            raise JevServiceError("TypeSafe API key is not configured")
        base_url = self.base_url or provider_base_url
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
            ) as client:
                response = await client.post(
                    f"{base_url.rstrip('/')}{_EVALUATION_PATH}",
                    headers={
                        **custom_headers,
                        "Authorization": f"Bearer {key}",
                    },
                    json={
                        "state": request.state,
                        "model": request.model or provider_model,
                        "questions": request.questions,
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise JevServiceError(type(exc).__name__) from exc
        if not isinstance(payload, dict):
            raise JevServiceError("Invalid response envelope")
        model = payload.get("model")
        answers = payload.get("answers")
        usage = payload.get("usage", {})
        if (
            not isinstance(model, str)
            or not isinstance(answers, dict)
            or not isinstance(usage, dict)
            or any(
                not isinstance(answers.get(name), dict)
                for name in request.questions
            )
            or any(
                answers[name].get("type") != question.get("type")
                for name, question in request.questions.items()
            )
        ):
            raise JevServiceError("Invalid response envelope")
        return JevResponse(model=model, answers=answers, usage=usage)
