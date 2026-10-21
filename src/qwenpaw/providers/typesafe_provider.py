# -*- coding: utf-8 -*-
"""TypeSafe account configuration and decision model evaluation."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from typing import List

from agentscope.classifier import (
    BinaryAnswer,
    BinaryQuestion,
    JevClassifierModel,
)
from agentscope.credential import TypeSafeCredential
from typesafe_sdk import TypeSafeError
from typesafe_sdk.constants import API_KEY_ENV, DEFAULT_MODEL

from ..exceptions import ProviderError
from .provider import ModelConnectionResult, ModelInfo, Provider


class TypeSafeProvider(Provider):
    """Manage TypeSafe models using the standard provider lifecycle."""

    chat_model: str = ""

    @asynccontextmanager
    # The decorator returns a synchronous context-manager factory.
    # pylint: disable-next=invalid-overridden-method
    async def open_classifier_model(
        self,
        model_id: str = DEFAULT_MODEL,
        *,
        timeout: float,
        max_retries: int,
    ) -> AsyncIterator[JevClassifierModel]:
        """Use AgentScope's client for classification and model discovery."""
        if not model_id.strip():
            raise ValueError("invalid classifier model")
        key = self.api_key.strip() or os.getenv(API_KEY_ENV, "").strip()
        if not key:
            raise ProviderError(
                "TypeSafe API key is not configured",
                details={"error_type": "not_configured"},
            )
        try:
            classifier = JevClassifierModel(
                credential=TypeSafeCredential(
                    api_key=key,
                    base_url=self.base_url or None,
                ),
                model=model_id,
                timeout=timeout,
                max_retries=max_retries,
            )
            async with classifier.client:
                yield classifier
        except TypeSafeError as exc:
            raise ProviderError(type(exc).__name__) from exc

    async def fetch_models(self, timeout: float = 5) -> List[ModelInfo]:
        async with self.open_classifier_model(
            timeout=timeout,
            max_retries=0,
        ) as classifier:
            response = await classifier.client.models.list(
                extra_headers=self.custom_headers,
            )
            return [
                ModelInfo(
                    id=model.name,
                    name=model.name,
                    model_type="decision",
                )
                for model in response.models
            ]

    async def check_connection(self, timeout: float = 5) -> tuple[bool, str]:
        try:
            await self.fetch_models(timeout)
        except (ProviderError, ValueError) as exc:
            return False, self.connection_error_message(
                exc.__cause__ if isinstance(exc.__cause__, Exception) else exc,
            )
        return True, ""

    async def check_model_connection(
        self,
        model_id: str,
        timeout: float = 5,
    ) -> ModelConnectionResult:
        try:
            async with self.open_classifier_model(
                model_id,
                timeout=timeout,
                max_retries=0,
            ) as classifier:
                response = await classifier(
                    state="Hello",
                    extra_headers=self.custom_headers,
                    questions={
                        "greeting": BinaryQuestion(
                            instructions="Is the state a greeting?",
                        ),
                    },
                )
                if not isinstance(
                    response.content.get("greeting"),
                    BinaryAnswer,
                ):
                    raise ValueError("Invalid greeting answer")
        except (ProviderError, ValueError) as exc:
            cause = exc.__cause__
            if not isinstance(cause, Exception):
                cause = exc
            return ModelConnectionResult(
                success=False,
                message=self.connection_error_message(cause),
                http_status=getattr(cause, "status", None),
            )
        return ModelConnectionResult(success=True)
