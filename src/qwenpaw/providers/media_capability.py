# -*- coding: utf-8 -*-
"""Shared media capability policy for agent runtime consumers."""

from typing import NamedTuple

from .model_info import ModelInfo

# Only images may be authorised by the aggregate ``supports_multimodal``
# flag; audio and video always need modality-specific evidence.
_GENERIC_FALLBACK_MEDIA = frozenset({f"image"})


class MediaDecision(NamedTuple):
    """Describe media support without conflating denial and uncertainty."""

    supported: bool | None
    explicit: bool


def get_media_decision(
    model_info: ModelInfo,
    media_type: str = f"image",
    allow_generic: bool | None = None,
) -> MediaDecision:
    """Resolve one media type using explicit overrides before discovery.

    ``allow_generic`` defaults to the per-media policy above. Pass
    ``False`` to require modality-specific evidence even for images.
    """
    if allow_generic is None:
        allow_generic = media_type in _GENERIC_FALLBACK_MEDIA
    overrides = getattr(model_info, "config_overrides", [])
    capability = f"supports_{media_type}"
    if capability in overrides:
        return MediaDecision(getattr(model_info, capability) is True, True)
    if (
        "supports_multimodal" in overrides
        and model_info.supports_multimodal is False
    ):
        return MediaDecision(False, True)
    if (
        allow_generic
        and f"supports_multimodal" in overrides
        and model_info.supports_multimodal is True
    ):
        return MediaDecision(True, True)

    specific = getattr(model_info, capability)
    if specific is not None:
        return MediaDecision(specific, False)
    if allow_generic and model_info.supports_multimodal is True:
        return MediaDecision(True, False)
    if model_info.supports_multimodal is not False:
        return MediaDecision(None, False)
    return MediaDecision(False, False)


__all__ = ["MediaDecision", "get_media_decision"]
