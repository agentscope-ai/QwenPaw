# -*- coding: utf-8 -*-
"""TypeSafe account configuration and decision model evaluation."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator, Mapping
from typing import Any, List

import httpx2
from agentscope.classifier import (
    BinaryAnswer,
    BinaryQuestion,
    ClassifierModelBase,
    ClassifierQuestion,
    ClassifierResponse,
    JevClassifierModel,
)
from agentscope.credential import TypeSafeCredential
from pydantic import Field
from typesafe_sdk import (
    AsyncTypeSafeClient,
    RetryPolicy,
    SystemOneResponse,
    TypeSafeError,
    Usage,
)

from ..exceptions import ProviderError
from ..config.utils import get_config_path
from ..drivers.credentials.store import AsyncCredentialStore
from .provider import ModelConnectionResult, ModelInfo, Provider


class _SystemOneResponse(SystemOneResponse):
    """Allow omitted usage metadata while retaining SDK answer validation."""

    usage: Usage = Field(default_factory=Usage)


class _ConfiguredJevClassifier(JevClassifierModel):
    """Use the provider's SDK client with AgentScope's typed conversion."""

    def __init__(
        self,
        credential: TypeSafeCredential,
        model: str,
        client: AsyncTypeSafeClient,
    ) -> None:
        # JevClassifierModel does not support client injection. Initialize the
        # shared model state without constructing a second, unused SDK client.
        ClassifierModelBase.__init__(self, credential=credential, model=model)
        self.client = client

    async def __call__(
        self,
        state: str | dict,
        questions: Mapping[str, ClassifierQuestion],
        **kwargs: Any,
    ) -> ClassifierResponse:
        kwargs.setdefault("response_model", _SystemOneResponse)
        return await super().__call__(
            state=state,
            questions=questions,
            **kwargs,
        )


class TypeSafeProvider(Provider):
    """Manage TypeSafe models using the standard provider lifecycle."""

    chat_model: str = ""

    async def _resolve_api_key(self) -> str | None:
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
    async def _open_client(
        self,
        *,
        timeout: float,
        max_retries: int,
    ) -> AsyncIterator[tuple[TypeSafeCredential, AsyncTypeSafeClient]]:
        """Share SDK configuration and lifetime across all TypeSafe calls."""
        if timeout <= 0 or max_retries < 0:
            raise ValueError("invalid request budget")
        key = await self._resolve_api_key()
        if not key:
            raise ProviderError(
                "TypeSafe API key is not configured",
                details={"error_type": "not_configured"},
            )
        credential = TypeSafeCredential(
            api_key=key,
            base_url=self.base_url.rstrip("/"),
        )

        async def use_provider_endpoint(request: httpx2.Request) -> None:
            # Both SDK endpoints append /v1. Saved provider URLs already
            # include the API prefix, which may be a custom proxy path.
            resource = request.url.path.rsplit("/", 1)[-1]
            request.url = httpx2.URL(f"{credential.base_url}/{resource}")

        try:
            # Own the HTTP client even if SDK configuration fails on entry.
            async with httpx2.AsyncClient(
                event_hooks={"request": [use_provider_endpoint]},
            ) as http_client:
                async with AsyncTypeSafeClient(
                    api_key=key,
                    base_url=credential.base_url,
                    timeout=timeout,
                    retry=RetryPolicy(max_retries=max_retries),
                    headers=self.custom_headers,
                    http_client=http_client,
                ) as client:
                    yield credential, client
        except TypeSafeError as exc:
            raise ProviderError(type(exc).__name__) from exc

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
        if not model_id.strip():
            raise ValueError("invalid classifier model")
        async with self._open_client(
            timeout=timeout,
            max_retries=max_retries,
        ) as (credential, client):
            yield _ConfiguredJevClassifier(
                credential=credential,
                model=model_id,
                client=client,
            )

    async def fetch_models(self, timeout: float = 5) -> List[ModelInfo]:
        async with self._open_client(
            timeout=timeout,
            max_retries=0,
        ) as (_, client):
            response = await client.models.list()
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
