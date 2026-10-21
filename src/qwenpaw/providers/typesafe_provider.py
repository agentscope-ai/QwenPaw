# -*- coding: utf-8 -*-
"""TypeSafe account configuration and decision model evaluation."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator, Mapping
from typing import Any, List

import httpx
from agentscope.classifier import (
    BinaryAnswer,
    BinaryQuestion,
    ClassifierModelBase,
    ClassifierQuestion,
    ClassifierResponse,
    JevClassifierModel,
)
from agentscope.credential import TypeSafeCredential
from typesafe_sdk import TypeSafeError

from ..exceptions import ProviderError
from ..config.utils import get_config_path
from ..drivers.credentials.store import AsyncCredentialStore
from .provider import ModelConnectionResult, ModelInfo, Provider


class _ConfiguredJevClassifier(JevClassifierModel):
    """Bind provider headers without exposing SDK options to callers."""

    def __init__(self, *, headers: Mapping[str, str], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._headers = dict(headers)

    async def __call__(
        self,
        state: str | dict,
        questions: Mapping[str, ClassifierQuestion],
        **kwargs: Any,
    ) -> ClassifierResponse:
        kwargs["extra_headers"] = {
            **self._headers,
            **kwargs.get("extra_headers", {}),
        }
        return await super().__call__(
            state=state,
            questions=questions,
            **kwargs,
        )


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

    @asynccontextmanager
    # The decorator returns a synchronous context-manager factory.
    # pylint: disable-next=invalid-overridden-method
    async def open_classifier_model(
        self,
        model_id: str,
        *,
        timeout: float,
        max_retries: int,
    ) -> AsyncIterator[ClassifierModelBase]:
        """Create a configured Jev classifier and close it on every exit."""
        if not model_id.strip() or timeout <= 0 or max_retries < 0:
            raise ValueError("invalid classifier model or request budget")
        key = await self._evaluation_api_key()
        if not key:
            raise ProviderError(
                "TypeSafe API key is not configured",
                details={"error_type": "not_configured"},
            )
        try:
            classifier = _ConfiguredJevClassifier(
                credential=TypeSafeCredential(
                    api_key=key,
                    # The SDK appends /v1 to its API root.
                    base_url=self.base_url.rstrip("/").removesuffix("/v1"),
                ),
                model=model_id,
                timeout=timeout,
                max_retries=max_retries,
                headers=self.custom_headers,
            )
            async with classifier.client:
                yield classifier
        except TypeSafeError as exc:
            raise ProviderError(type(exc).__name__) from exc

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
            async with self.open_classifier_model(
                model_id,
                timeout=timeout,
                max_retries=0,
            ) as classifier:
                response = await classifier(
                    state="Hello",
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
