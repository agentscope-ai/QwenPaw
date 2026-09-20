# -*- coding: utf-8 -*-
"""An OpenRouter provider implementation."""

from __future__ import annotations

from typing import ClassVar, Any, List, Optional

from agentscope.model import ChatModelBase
from openai import APIError, AsyncOpenAI
from pydantic import Field

from qwenpaw.exceptions import ProviderError
from qwenpaw.providers.provider import (
    Provider,
    ModelConnectionResult,
    ExtendedModelInfo,
    ModelInfo,
)
from .model_billing import classify_pricing, normalize_pricing
from .model_info import release_date
from ..utils.io_utils import run_sync_io
from .capping_formatter import _CappingOpenAIFormatter
from .capping_formatter import MAX_INLINE_MEDIA_BYTES
from .multimodal_prober import ProbeResult


class OpenRouterProvider(Provider):
    """OpenRouter provider with required HTTP-Referer and X-Title headers."""

    max_inline_media_bytes: int = Field(
        default=MAX_INLINE_MEDIA_BYTES,
        ge=0,
        description=(
            "Maximum size (in bytes) of a local media file inlined as "
            "base64 into the model request body. Media above this is "
            "replaced with a text placeholder to avoid oversized requests "
            "when large files (e.g. generated videos) persist in "
            "conversation history. 0 disables capping."
        ),
    )

    _OPENROUTER_CATEGORIES = "personal-agent,cli-agent"

    _DEFAULT_HEADERS = {
        "HTTP-Referer": "https://qwenpaw.agentscope.io/",
        "X-OpenRouter-Title": "QwenPaw",
        "X-OpenRouter-Categories": _OPENROUTER_CATEGORIES,
        "User-Agent": "QwenPaw/1.1",
    }

    session_header_name: ClassVar[str] = f"x-session-id"
    cache_documentation: ClassVar[str] = (
        f"https://openrouter.ai/docs/guides/best-practices/prompt-caching"
    )

    def cache_capabilities(self, model_id: str) -> frozenset[str]:
        """Use the routed model vendor's documented cache syntax."""
        if model_id.startswith((f"anthropic/", f"qwen/")):
            return frozenset({f"implicit", f"anthropic"})
        if model_id.startswith(f"openai/"):
            return frozenset({f"implicit", f"openai"})
        return frozenset({f"implicit"})

    def request_headers(self) -> dict:
        """Return provider headers for an externally owned HTTP transport."""
        return self._build_default_headers()

    def _build_default_headers(self) -> dict:
        # Required OpenRouter headers come first; user custom_headers can
        # supplement or override them.
        return {**self._DEFAULT_HEADERS, **self.custom_headers}

    def _client(self, timeout: float = 30) -> AsyncOpenAI:
        return AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=timeout,
            default_headers=self._build_default_headers(),
        )

    @staticmethod
    async def _close_client(client: AsyncOpenAI) -> None:
        """Close a temporary SDK client when it owns async resources."""
        close = getattr(client, "close", None)
        if close is not None:
            await close()

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

    @classmethod
    def parse_model_pricing(cls, row: Any) -> dict[str, Any]:
        """OpenRouter prices include request and modality charges."""
        pricing = normalize_pricing(getattr(row, f"pricing", None))
        billing = classify_pricing(pricing)
        return {
            f"pricing": pricing,
            f"billing": billing,
            f"is_free": billing == f"free",
            f"billing_source": f"api",
        }

    @staticmethod
    def _normalize_pricing(
        pricing: dict[str, Any] | None,
    ) -> dict[str, str]:
        """Normalize OpenRouter pricing dicts for downstream checks."""
        return normalize_pricing(pricing)

    @staticmethod
    def _is_free_model(pricing: dict[str, str]) -> bool:
        """Determine whether a model is free based on pricing fields."""
        return classify_pricing(pricing) == f"free"

    @classmethod
    def _normalize_models_payload(
        cls,
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
                billing = cls.parse_model_pricing(row)[f"billing"]
                # OpenRouter's /models reports authoritative context metadata.
                # Store it as auto-detected so it wins over catalog and static
                # values without becoming an explicit user override.
                window_kwargs: dict[str, Any] = {
                    f"released_at": release_date(
                        getattr(row, f"created", None)
                    ),
                }
                try:
                    context_length = int(
                        getattr(row, "context_length", 0) or 0,
                    )
                except (TypeError, ValueError):
                    context_length = 0
                if context_length >= 1000:  # ModelInfo's field lower bound
                    # Keep the legacy field populated for API compatibility;
                    # provenance still marks this as discovered metadata.
                    window_kwargs["max_input_length"] = context_length
                    window_kwargs["max_input_length_auto_detected"] = (
                        context_length
                    )

                top_provider = getattr(row, f"top_provider", None) or {}
                output_limit = top_provider.get(f"max_completion_tokens")
                if type(output_limit) is int and output_limit > 0:
                    window_kwargs[f"max_output_length"] = output_limit

                architecture = getattr(row, f"architecture", None) or {}
                input_modalities = architecture.get(f"input_modalities")
                output_modalities = architecture.get(f"output_modalities")
                capabilities: dict[str, Any] = {}
                if isinstance(input_modalities, list) and input_modalities:
                    for modality in (f"image", f"audio", f"video"):
                        capabilities[f"supports_{modality}"] = (
                            modality in input_modalities
                        )
                    capabilities[f"supports_multimodal"] = any(
                        modality in input_modalities
                        for modality in (f"image", f"audio", f"video")
                    )
                    capabilities[f"probe_source"] = f"api"
                parameters = getattr(row, f"supported_parameters", None)
                if isinstance(parameters, list):
                    capabilities[f"supports_tool_calling"] = (
                        f"tools" in parameters
                    )
                common = dict(
                    id=model_id,
                    name=model_name,
                    is_free=is_free,
                    billing=billing,
                    billing_source=f"api",
                    pricing=pricing_dict,
                    **capabilities,
                    **window_kwargs,
                )
                if include_extended:
                    models[model_id] = ExtendedModelInfo(
                        **common,
                        provider=provider,
                        input_modalities=input_modalities or [],
                        output_modalities=output_modalities or [],
                    )
                else:
                    models[model_id] = ModelInfo(**common)

        return list(models.values())

    async def check_connection(self, timeout: float = 30) -> tuple[bool, str]:
        """Check if OpenRouter provider is reachable."""
        client = self._client()
        try:
            await client.models.list(timeout=timeout)
            return True, ""
        except APIError as e:
            return False, str(e)
        finally:
            await self._close_client(client)

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
        client = await run_sync_io(self._client, timeout=timeout)
        try:
            payload = await client.models.list(timeout=timeout)
            models = self._normalize_models_payload(
                payload,
                include_extended=include_extended,
            )
            return models
        finally:
            await self._close_client(client)

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

    async def probe_model_multimodal(
        self,
        model_id: str,
        timeout: float = 10,
        image_only: bool = False,
    ) -> ProbeResult:
        """Resolve multimodal support from OpenRouter's model catalog.

        OpenRouter publishes input modalities in its ``/models`` response.
        Treat that metadata as authoritative instead of sending a paid chat
        completion.  A missing or unavailable catalog is inconclusive and
        must raise so the provider manager does not persist false capability
        flags over previously known values.
        """
        try:
            client = await run_sync_io(self._client, timeout=timeout)
            payload = await client.models.list(timeout=timeout)
        except APIError as exc:
            raise ProviderError(
                message=(
                    "Unable to read OpenRouter model metadata while probing "
                    f"'{model_id}'"
                ),
                details={"model_id": model_id},
            ) from exc

        models = self._normalize_models_payload(
            payload,
            include_extended=True,
        )
        model = next((item for item in models if item.id == model_id), None)
        if model is None:
            raise ProviderError(
                message=(
                    f"Model '{model_id}' was not found in the OpenRouter "
                    "model catalog"
                ),
                details={"model_id": model_id},
            )

        supports_image = bool(model.supports_image)
        supports_video = False if image_only else bool(model.supports_video)
        image_message = (
            "Image capability reported by OpenRouter model metadata: "
            f"{supports_image}"
        )
        video_message = (
            "Skipped: image_only=True"
            if image_only
            else (
                "Video capability reported by OpenRouter model metadata: "
                f"{supports_video}"
            )
        )
        return ProbeResult(
            supports_image=supports_image,
            supports_video=supports_video,
            image_message=image_message,
            video_message=video_message,
            probe_source="documentation",
        )

    def filter_models(
        self,
        models: List[ExtendedModelInfo],
        providers: Optional[List[str]] = None,
        input_modalities: Optional[List[str]] = None,
        output_modalities: Optional[List[str]] = None,
        max_prompt_price: Optional[float] = None,
        is_free: Optional[bool] = None,
    ) -> List[ExtendedModelInfo]:
        """Filter models by given criteria.

        Args:
            models: List of models to filter
            providers: Filter by provider/series (e.g., ["openai", "google"])
            input_modalities: Required input modalities (e.g., ["image"])
            output_modalities: Required output modalities (e.g., ["text"])
            max_prompt_price: Maximum prompt price per 1M tokens
            is_free: Whether to return only free models

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

        if is_free is True:
            result = [m for m in result if m.is_free is True]

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
    ) -> ModelConnectionResult:
        """Check a model through a basic OpenAI-compatible chat request."""
        from .openai_provider import OpenAIProvider

        return await OpenAIProvider.check_model_connection(
            self,
            model_id=model_id,
            timeout=timeout,
        )

    def get_chat_model_instance(self, model_id: str) -> ChatModelBase:
        from agentscope.credential._openai import OpenAICredential

        from .openai_chat_model_compat import OpenAIChatModelCompat

        credential = OpenAICredential(
            id=f"qwenpaw-{self.id}",
            api_key=self.api_key,
            base_url=self.base_url,
        )
        gen_kwargs = self.get_effective_generate_kwargs(model_id)
        return OpenAIChatModelCompat(
            credential=credential,
            provider_id=self.id,
            usage_guard=lambda: self.check_model_billing(model_id),
            request_policy=self.prepare_request,
            model=model_id,
            stream=True,
            extra_generate_kwargs=gen_kwargs,
            default_headers=self._build_default_headers() or None,
            context_size=self._get_context_size(model_id),
            formatter=_CappingOpenAIFormatter(
                max_bytes=self.max_inline_media_bytes,
                enable_prompt_cache_breakpoint=bool(
                    gen_kwargs.get(
                        f"enable_prompt_cache_breakpoint",
                        False,
                    )
                ),
                relay_reasoning_content=self._get_relay_reasoning(model_id),
            ),
        )
