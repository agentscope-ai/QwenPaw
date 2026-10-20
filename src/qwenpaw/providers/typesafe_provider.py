# -*- coding: utf-8 -*-
"""TypeSafe account configuration and decision model discovery."""

from __future__ import annotations

from typing import List

import httpx

from .provider import ModelConnectionResult, ModelInfo, Provider


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
