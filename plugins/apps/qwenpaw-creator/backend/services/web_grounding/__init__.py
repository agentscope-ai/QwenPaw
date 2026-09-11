# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Public facade for Creator web grounding.

Callers should import from this package. Implementation details live in focused
modules; ``pipeline`` owns orchestration and retains compatibility helpers while
the remaining seams are extracted.
"""

from .pipeline import (
    classify_grounding_needs,
    classify_grounding_needs_llm,
    detect_grounding_needs,
    ground_prompt_context,
    search_visual_refs,
    search_web,
    stage_visual_grounding_sources,
    triage_grounding_request,
    verify_visual_grounding_groups_with_vlm,
    verify_visual_grounding_with_vlm,
)

__all__ = [
    "classify_grounding_needs",
    "classify_grounding_needs_llm",
    "detect_grounding_needs",
    "ground_prompt_context",
    "search_visual_refs",
    "search_web",
    "stage_visual_grounding_sources",
    "triage_grounding_request",
    "verify_visual_grounding_groups_with_vlm",
    "verify_visual_grounding_with_vlm",
]
