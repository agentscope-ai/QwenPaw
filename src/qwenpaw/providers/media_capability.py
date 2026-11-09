# -*- coding: utf-8 -*-
"""Shared media capability policy for agent runtime consumers."""

from typing import NamedTuple


class MediaDecision(NamedTuple):
    """Describe media support without conflating denial and uncertainty."""

    supported: bool | None
    explicit: bool


def get_media_decision(model_info, media_type="image", allow_generic=True):
    """Resolve one media type using explicit overrides before discovery."""
    overrides = getattr(model_info, "config_overrides", [])
    capability = f"supports_{media_type}"
    if capability in overrides:
        return MediaDecision(getattr(model_info, capability) is True, True)
    if (
        "supports_multimodal" in overrides
        and model_info.supports_multimodal is False
    ):
        return MediaDecision(False, True)

    specific = getattr(model_info, capability)
    if specific is not None:
        return MediaDecision(specific, False)
    if allow_generic and model_info.supports_multimodal is True:
        return MediaDecision(True, False)
    if model_info.supports_multimodal is not False:
        return MediaDecision(None, False)
    return MediaDecision(False, False)


__all__ = ["MediaDecision", "get_media_decision"]
