# -*- coding: utf-8 -*-
"""An OpenRouter provider implementation."""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any, List, Optional

from agentscope.model import ChatModelBase
from openai import APIError, AsyncOpenAI

from qwenpaw.providers.provider import (
    ExtendedModelInfo,
    ModelInfo,
    Provider,
)


logger = logging.getLogger(__name__)


class OpenRouterProvider(Provider):
    """OpenRouter provider with required HTTP-Referer and X-Title headers."""

    _DEFAULT_HEADERS = {
        "HTTP-Referer": "https://qwenpaw.agentscope.io/",
        "X-Title": "QwenPaw",
    }

    def _client(self, timeout: float = 30) -> AsyncOpenAI:
        return AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=timeout,
            default_headers=self._DEFAULT_HEADERS,
        )

    @staticmethod
    def _extract_provider(model_id: str) -> str:
        """Extract provider from model ID.

        Examples:
            'openai/gpt-4o' -> 'openai'
            'anthropic/claude-3.5-sonnet' -> 'anthropic'
            'google/gemini-2.5-flash' -> 'google'
            'gpt-4o' -> 'gpt-4o' (no provider prefix)
        """
        if "/" in model_id:
            return model_id.split("/")[0]
        return ""

    @staticmethod
    def _extract_model_name(model_id: str) -> str:
        """Extract model name from model ID (part after the slash).

        Examples:
            'openai/gpt-4o' -> 'gpt-4o'
            'anthropic/claude-3.5-sonnet' -> 'claude-3.5-sonnet'
            'google/gemini-2.5-flash' -> 'gemini-2.5-flash'
            'gpt-4o' -> 'gpt-4o' (no change if no slash)
        """
        if "/" in model_id:
            return model_id.split("/")[-1]
        return model_id

    @staticmethod
    def _normalize_pricing(
        pricing: dict[str, Any] | None,
    ) -> dict[str, str]:
        """Normalize OpenRouter pricing dicts for downstream checks."""
        if not pricing:
            return {}

        return {
            str(key): "0" if value is None else str(value)
            for key, value in pricing.items()
        }

    @staticmethod
    def _is_free_model(pricing: dict[str, str]) -> bool:
        """Determine whether a model is free based on pricing fields."""
        numeric_values: list[Decimal] = []
        for value in pricing.values():
            text = str(value).strip()
            if not text:
                continue
            try:
                numeric_values.append(Decimal(text))
            except InvalidOperation:
                continue

        return bool(numeric_values) and all(
            value == 0 for value in numeric_values
        )

    @staticmethod
    def _normalize_models_payload(
        payload: Any,
        include_extended: bool = False,
    ) -> List[ModelInfo] | List[ExtendedModelInfo]:
        """Normalize the models payload from OpenRouter API.

        Args:
            payload: The raw API response payload
            include_extended: If True, return ExtendedModelInfo with metadata

        Returns:
            List of ModelInfo or ExtendedModelInfo objects
        """
        models: dict[str, ModelInfo | ExtendedModelInfo] = {}
        # payload is an OpenAI AsyncPage object with .data attribute
        rows = getattr(payload, "data", []) or []
        for row in rows:
            # row is an OpenAI Model object, use getattr for attributes
            model_id = str(getattr(row, "id", "") or "").strip()
            if not model_id:
                continue

            # Extract provider from model ID
            provider = OpenRouterProvider._extract_provider(model_id)

            # Extract model name (part after slash, or full ID if no slash)
            model_name = OpenRouterProvider._extract_model_name(model_id)

            # Use name attr if no slash in model_id
            attr_name = str(getattr(row, "name", "") or "").strip()
            if attr_name and "/" not in model_id:
                model_name = attr_name

            # Deduplication: keep first occurrence by model_id
            if model_id not in models:
                pricing_dict = OpenRouterProvider._normalize_pricing(
                    getattr(row, "pricing", None),
                )
                is_free = OpenRouterProvider._is_free_model(pricing_dict)

                if include_extended:
                    # Get architecture and pricing from the API response
                    # These are dict attributes of the Model object
                    architecture = getattr(row, "architecture", None) or {}

                    # Extract modalities from architecture dict
                    arch_input = architecture.get("input_modalities", [])
                    arch_output = architecture.get("output_modalities", [])
                    input_modalities = list(arch_input) if arch_input else []
                    output_modalities = (
                        list(arch_output) if arch_output else []
                    )
                    supports_image = "image" in input_modalities
                    supports_video = "video" in input_modalities
                    supports_multimodal = any(
                        modality != "text" for modality in input_modalities
                    )

                    models[model_id] = ExtendedModelInfo(
                        id=model_id,
                        name=model_name,
                        supports_multimodal=supports_multimodal,
                        supports_image=supports_image,
                        supports_video=supports_video,
                        probe_source="documentation",
                        is_free=is_free,
                        provider=provider,
                        input_modalities=input_modalities,
                        output_modalities=output_modalities,
                        pricing=pricing_dict,
                    )
                else:
                    models[model_id] = ModelInfo(
                        id=model_id,
                        name=model_name,
                        is_free=is_free,
                    )

        return list(models.values())

    async def check_connection(self, timeout: float = 30) -> tuple[bool, str]:
        """Check if OpenRouter provider is reachable."""
        client = self._client()
        try:
            await client.models.list(timeout=timeout)
            return True, ""
        except APIError as e:
            return False, str(e)

    async def fetch_models(
        self,
        timeout: float = 30,
        include_extended: bool = False,
    ) -> List[ModelInfo]:
        """Fetch available models.

        Args:
            timeout: Request timeout in seconds
            include_extended: If True, fetch extended model info with
                           modalities and pricing

        Returns:
            List of ModelInfo (or ExtendedModelInfo if include_extended=True)
        """
        try:
            client = self._client(timeout=timeout)
            payload = await client.models.list(timeout=timeout)
            models = self._normalize_models_payload(
                payload,
                include_extended=include_extended,
            )
            return models
        except APIError:
            return []

    async def fetch_extended_models(
        self,
        timeout: float = 30,
    ) -> List[ExtendedModelInfo]:
        """Fetch available models with extended metadata.

        This method fetches models with full information including
        provider, modalities, and pricing.

        Args:
            timeout: Request timeout in seconds

        Returns:
            List of ExtendedModelInfo objects
        """
        return await self.fetch_models(
            timeout=timeout,
            include_extended=True,
        )  # type: ignore

    def filter_models(
        self,
        models: List[ExtendedModelInfo],
        providers: Optional[List[str]] = None,
        input_modalities: Optional[List[str]] = None,
        output_modalities: Optional[List[str]] = None,
        max_prompt_price: Optional[float] = None,
    ) -> List[ExtendedModelInfo]:
        """Filter models by given criteria.

        Args:
            models: List of models to filter
            providers: Filter by provider/series (e.g., ["openai", "google"])
            input_modalities: Required input modalities (e.g., ["image"])
            output_modalities: Required output modalities (e.g., ["text"])
            max_prompt_price: Maximum prompt price per 1M tokens

        Returns:
            Filtered list of models
        """
        result = models

        # Filter by providers
        if providers:
            providers_lower = [p.lower() for p in providers]
            result = [
                m for m in result if m.provider.lower() in providers_lower
            ]

        # Filter by input modalities
        if input_modalities:
            result = [
                m
                for m in result
                if any(mod in m.input_modalities for mod in input_modalities)
            ]

        # Filter by output modalities
        if output_modalities:
            result = [
                m
                for m in result
                if any(mod in m.output_modalities for mod in output_modalities)
            ]

        # Filter by max prompt price
        if max_prompt_price is not None:
            result = [
                m
                for m in result
                if m.pricing.get("prompt")
                and float(m.pricing.get("prompt", "0")) <= max_prompt_price
            ]

        return result

    async def get_available_providers(
        self,
        timeout: float = 30,
    ) -> List[str]:
        """Get list of available providers/series from OpenRouter.

        Args:
            timeout: Request timeout in seconds

        Returns:
            List of unique provider names (e.g., ['openai', 'google'])
        """
        models = await self.fetch_extended_models(timeout=timeout)
        providers_set = set()
        for model in models:
            if model.provider:
                providers_set.add(model.provider)
        return sorted(list(providers_set))

    async def check_model_connection(
        self,
        model_id: str,
        timeout: float = 30,
    ) -> tuple[bool, str]:
        """Check if a specific model is reachable/usable"""
        try:
            client = self._client(timeout=timeout)
            res = await client.chat.completions.create(
                model=model_id,
                messages=[{"role": "user", "content": "ping"}],
                timeout=timeout,
                max_tokens=1,
                stream=True,
            )
            # consume the stream to ensure the model is actually responsive
            async for _ in res:
                break
            return True, ""
        except APIError as e:
            return False, str(e)

    def get_chat_model_instance(self, model_id: str) -> ChatModelBase:
        from .openai_chat_model_compat import OpenAIChatModelCompat

        return OpenAIChatModelCompat(
            model_name=model_id,
            stream=True,
            api_key=self.api_key,
            client_kwargs={
                "base_url": self.base_url,
                "default_headers": self._DEFAULT_HEADERS,
            },
        )
