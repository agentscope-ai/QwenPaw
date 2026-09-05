# -*- coding: utf-8 -*-
"""Canonical in-prompt reference markers, rendered per provider.

Every provider that lets a prompt address individual input references spells
it differently — ``图1`` for wan3 and qwen-image, ``[Image 1]`` for
HappyHorse, ``图片1`` for Seedance, ``@image_1`` or ``<<<image_1>>>`` for
Kling, ``character1`` for wan2.6 — and some (OpenAI's gpt-image family)
document no per-image addressing at all, only array order.

Authoring against six dialects put the burden on the agent and, worse,
provider-locked the stored prompt: a ``video_prompt`` written as ``图1`` is
meaningless prose the moment the configured model changes. So prompts are
authored once in a canonical ``[Image N]`` form and rendered here at submit
time, against the provider actually being called.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


# Authored form. Case-insensitive and tolerant of internal spacing so a
# model that writes "[image 2]" or "[Image  2]" still resolves.
CANONICAL_MARKER_PATTERN = re.compile(
    r"\[\s*image\s+(\d+)\s*\]",
    re.IGNORECASE,
)


def canonical_marker(index: int) -> str:
    """The authored form for one reference index."""

    return f"[Image {index}]"


@dataclass(frozen=True, slots=True)
class ReferenceMarkerSpec:
    """One provider's documented in-prompt reference syntax.

    ``template`` carries a single ``{index}`` placeholder. ``pattern`` matches
    the provider's own form so an already-native prompt is left alone rather
    than double-rendered. ``documentation_url`` records where the syntax comes
    from, because an undocumented guess here silently misdirects references.
    """

    template: str
    pattern: re.Pattern[str]
    documentation_url: str

    def render_index(self, index: int) -> str:
        return self.template.format(index=index)


def _ordinal_prose(index: int, *, language: str) -> str:
    """Wording for providers that document no per-image addressing.

    Leaving ``[Image 1]`` in the prompt would send the model literal text it
    has no contract for. Ordinal prose keeps the author's intent legible
    without inventing a syntax the provider never defined.
    """

    if language.strip().casefold().startswith("zh"):
        return f"第{index}张参考图"
    return f"reference image {index}"


def render_reference_markers(
    prompt: str,
    spec: ReferenceMarkerSpec | None,
    *,
    language: str = "zh-CN",
) -> str:
    """Rewrite canonical ``[Image N]`` into what this provider documents.

    Idempotent for provider-native prompts: those contain no canonical
    markers, so nothing matches and the text is returned unchanged. That is
    what keeps prompts stored before this layer existed working.
    """

    if not prompt:
        return prompt

    def replace(match: re.Match[str]) -> str:
        index = int(match.group(1))
        if spec is None:
            return _ordinal_prose(index, language=language)
        return spec.render_index(index)

    return CANONICAL_MARKER_PATTERN.sub(replace, prompt)


def canonical_marker_indices(prompt: str) -> tuple[int, ...]:
    """Reference indices the prompt addresses, in order of appearance."""

    return tuple(
        int(match.group(1))
        for match in CANONICAL_MARKER_PATTERN.finditer(prompt or "")
    )


__all__ = [
    "CANONICAL_MARKER_PATTERN",
    "ReferenceMarkerSpec",
    "canonical_marker",
    "canonical_marker_indices",
    "render_reference_markers",
]
