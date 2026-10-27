# -*- coding: utf-8 -*-
"""TypeSafe account configuration and decision model evaluation."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, List, Mapping

from agentscope.classifier import (
    BinaryQuestion,
    ClassifierQuestion,
    ClassifierResponse,
    JevClassifierModel,
)
from agentscope.credential import TypeSafeCredential
from typesafe_sdk import TypeSafeError

from .provider import ModelConnectionResult, ModelInfo, Provider
from ..utils.io_utils import run_async_to_completion, run_sync_io


class TypeSafeEvaluationError(RuntimeError):
    """Configuration, transport, or response-shape failure."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def resolve_decision_model(slot=None, *, default_model: str | None = None):
    """Resolve an agent or global TypeSafe slot with a caller-owned default."""
    from .provider_manager import ProviderManager

    manager = ProviderManager.get_instance()
    slot = slot or manager.default_models.get("decision")
    if slot is None and default_model is None:
        raise TypeSafeEvaluationError("Configure a decision model")
    if slot is not None and slot.provider_id != "typesafe":
        raise TypeSafeEvaluationError("Decision model provider is unsupported")
    provider = manager.get_provider("typesafe")
    if not isinstance(provider, TypeSafeProvider) or not provider.enabled:
        raise TypeSafeEvaluationError("TypeSafe provider is unavailable")
    return provider, slot.model if slot is not None else default_model


class TypeSafeProvider(Provider):
    """Manage TypeSafe models using the standard provider lifecycle."""

    chat_model: str = ""

    def as_decision_model(
        self,
        model: str,
        *,
        timeout: float = 10,
        max_retries: int = 1,
    ) -> JevClassifierModel:
        """Create a host-configured AS model; the caller owns its client."""
        from .typesafe_decision_model import TypeSafeDecisionModel

        key = self.api_key.strip()
        if not key:
            raise TypeSafeEvaluationError("TypeSafe API key is not configured")
        return TypeSafeDecisionModel(
            credential=TypeSafeCredential(
                api_key=key,
                base_url=self.base_url.strip() or None,
            ),
            model=model,
            timeout=timeout,
            max_retries=max_retries,
            provider_headers=self.custom_headers,
        )

    async def as_decision_model_async(
        self,
        model: str,
        *,
        timeout: float = 10,
        max_retries: int = 1,
    ) -> JevClassifierModel:
        """Construct off-loop; close the client if creation is cancelled."""
        classifier = None

        def create():
            nonlocal classifier
            classifier = self.as_decision_model(
                model,
                timeout=timeout,
                max_retries=max_retries,
            )
            return classifier

        try:
            return await run_sync_io(create)
        except asyncio.CancelledError:
            if classifier is not None:
                await run_async_to_completion(classifier.client.aclose())
            raise

    @asynccontextmanager
    async def _classifier(
        self,
        model: str,
        timeout: float,
    ) -> AsyncIterator[JevClassifierModel]:
        """Yield a decision model, normalizing SDK failures."""
        classifier = None
        try:
            classifier = await self.as_decision_model_async(
                model,
                timeout=timeout,
                # Approval decisions are latency-sensitive; fail fast and let
                # the caller fall back to asking the user.
                max_retries=0,
            )
            yield classifier
        except (TypeSafeError, ValueError) as exc:
            # API errors carry the HTTP status as ``status``; ValueError
            # comes from answer types AgentScope cannot convert.
            status = getattr(exc, "status", None)
            raise TypeSafeEvaluationError(
                f"{type(exc).__name__}: {exc}",
                status_code=status if isinstance(status, int) else None,
            ) from exc
        finally:
            if classifier is not None:
                await run_async_to_completion(classifier.client.aclose())

    async def evaluate(
        self,
        *,
        state: str | dict[str, Any],
        questions: Mapping[str, ClassifierQuestion],
        model: str = "jev-latest",
        timeout: float = 4.0,
    ) -> ClassifierResponse:
        """Submit typed questions to the decision model.

        Interpreting (and validating) the answers is left to the caller.
        """
        if not questions or not model.strip():
            raise ValueError("model and questions are required")
        async with self._classifier(model, timeout) as classifier:
            return await classifier(state, questions)

    async def fetch_models(self, timeout: float = 5) -> List[ModelInfo]:
        async with self._classifier("jev-latest", timeout) as classifier:
            response = await classifier.client.models.list(
                extra_headers=dict(self.custom_headers) or None,
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
                http_status=exc.status_code,
            )
        return ModelConnectionResult(success=True)
