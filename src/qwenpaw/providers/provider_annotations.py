# -*- coding: utf-8 -*-
"""Provider model annotation service."""

from __future__ import annotations

from collections.abc import Iterable

from .capability_baseline import (
    ExpectedCapability,
    ExpectedCapabilityRegistry,
)
from .provider import ModelInfo, Provider


class ProviderAnnotationService:
    """Apply documentation-derived capabilities to provider models."""

    def __init__(self, registry: ExpectedCapabilityRegistry) -> None:
        self._registry = registry

    def apply(
        self,
        providers: Iterable[Provider],
        *,
        refresh: bool = False,
        bare_name_fallback: bool = False,
    ) -> None:
        """Apply expected capabilities without overwriting probe results.

        ``bare_name_fallback`` enables a provider-agnostic model-id lookup
        for providers whose id is not part of the baseline registry
        (custom providers).
        """
        for provider in providers:
            for model in provider.all_models():
                if model.probe_source == "probed":
                    continue
                if not refresh and model.supports_multimodal is not None:
                    continue
                if (
                    model.supports_image is not None
                    or model.supports_video is not None
                ):
                    if refresh and model.probe_source == "documentation":
                        expected = self._lookup(
                            provider.id,
                            model.id,
                            bare_name_fallback,
                        )
                        if expected:
                            model.supports_image = expected.expected_image
                            model.supports_video = expected.expected_video
                    model.supports_multimodal = bool(
                        model.supports_image or model.supports_video,
                    )
                    continue
                expected = self._lookup(
                    provider.id,
                    model.id,
                    bare_name_fallback,
                )
                if expected:
                    model.supports_image = expected.expected_image
                    model.supports_video = expected.expected_video
                    model.supports_multimodal = bool(
                        expected.expected_image or expected.expected_video,
                    )
                    model.probe_source = "documentation"

    def annotate_model(
        self,
        provider: Provider,
        model: ModelInfo,
        *,
        bare_name_fallback: bool = False,
    ) -> None:
        """Apply documented capabilities to a single model record.

        Used for models added at runtime, so known models get their
        documented capabilities instead of falling back to probing.
        Probed or already-annotated models are left untouched.
        """
        if model.probe_source == "probed":
            return
        if model.supports_multimodal is not None:
            return
        expected = self._lookup(provider.id, model.id, bare_name_fallback)
        if expected:
            model.supports_image = expected.expected_image
            model.supports_video = expected.expected_video
            model.supports_multimodal = bool(
                expected.expected_image or expected.expected_video,
            )
            model.probe_source = "documentation"

    def _lookup(
        self,
        provider_id: str,
        model_id: str,
        bare_name_fallback: bool,
    ) -> ExpectedCapability | None:
        """Provider-specific lookup with optional bare model-id fallback."""
        expected = self._registry.get_expected(provider_id, model_id)
        if expected is None and bare_name_fallback:
            expected = self._registry.get_expected_by_model_id(model_id)
        return expected
