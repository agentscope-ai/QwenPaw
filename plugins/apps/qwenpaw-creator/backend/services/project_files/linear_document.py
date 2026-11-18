# -*- coding: utf-8 -*-
"""The common wire form for a linear project and its historical empty extensions."""

from collections.abc import Mapping
from typing import Any

# This is also the frozen field order used to verify earlier interactive
# builds' transaction and Project hashes, independent of JSON object order.
EMPTY_PRESENTATION = {
    "design_prompt": "",
    "screens": {},
    "motion": None,
    "cover_file_id": None,
    "cover_checksum": None,
    "cover_fingerprint": "",
}


def without_empty_extensions(document: dict[str, Any]) -> dict[str, Any]:
    """Omit only the two provably inert fields. Preserve every unknown value."""
    if (
        "narrative_edges" not in document
        and "interactive_presentation" not in document
    ):
        return document
    if document.get("narrative_edges", []) != []:
        return document
    presentation = document.get("interactive_presentation", {})
    if not isinstance(presentation, Mapping) or any(
        key not in EMPTY_PRESENTATION or value != EMPTY_PRESENTATION[key]
        for key, value in presentation.items()
    ):
        return document
    return {
        k: v
        for k, v in document.items()
        if k not in ("narrative_edges", "interactive_presentation")
    }
