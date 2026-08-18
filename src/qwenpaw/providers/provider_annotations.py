# -*- coding: utf-8 -*-
"""Provider model annotation service."""

from __future__ import annotations

from collections.abc import Iterable

from .capability_baseline import ExpectedCapabilityRegistry
from .provider import Provider


class ProviderAnnotationService:
    """Apply documentation-derived capabilities to provider models."""

    def __init__(self, registry: ExpectedCapabilityRegistry) -> None:
        self._registry = registry

    def apply(
        self,
        providers: Iterable[Provider],
        *,
        refresh: bool = False,
    ) -> None:
        """Apply expected capabilities without overwriting probe results."""
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
                        expected = self._registry.get_expected(
                            provider.id,
                            model.id,
                        )
                        if expected:
                            model.supports_image = expected.expected_image
                            model.supports_video = expected.expected_video
                    model.supports_multimodal = bool(
                        model.supports_image or model.supports_video,
                    )
                    continue
                expected = self._registry.get_expected(
                    provider.id,
                    model.id,
                )
                if expected:
                    model.supports_image = expected.expected_image
                    model.supports_video = expected.expected_video
                    model.supports_multimodal = bool(
                        expected.expected_image or expected.expected_video,
                    )
                    model.probe_source = "documentation"
