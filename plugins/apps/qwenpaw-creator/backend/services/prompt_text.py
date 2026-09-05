# -*- coding: utf-8 -*-
"""Shared deterministic normalization for authored prompt text."""

from __future__ import annotations

import re


# Authors and models mix punctuation widths freely in Chinese prompts
# ("，" vs ",", curly vs straight quotes). Width and quote style never
# change the spoken words, so the match key folds them before the verbatim
# containment check; letters and digits only lose their full-width forms.
_PUNCTUATION_FOLD = str.maketrans(
    {
        **{chr(code): chr(code - 0xFEE0) for code in range(0xFF01, 0xFF5F)},
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "「": '"',
        "」": '"',
        "『": '"',
        "』": '"',
        "。": ".",
        "、": ",",
        "…": "...",
        "—": "-",
        "–": "-",
    },
)


def dialogue_match_key(text: str) -> str:
    """Normalize whitespace and punctuation-width noise before matching."""

    return "".join(text.split()).translate(_PUNCTUATION_FOLD)


# Speaker prefixes ("老板娘：…" / "Regular: …") and stage directions
# ("（回头）") belong to the shot plan, not to the spoken line itself. Prompt
# prose may wrap the same spoken words in a sentence, so the contract compares
# only the dialogue that must reach the provider verbatim.
_DIALOGUE_SPEAKER_PREFIX = re.compile(r"^[^：:]{1,20}[：:]\s*")
_DIALOGUE_STAGE_DIRECTION = re.compile(r"[（(][^）)]*[）)]")


def dialogue_spoken_lines(dialogue: str) -> tuple[str, ...]:
    """Return the spoken sentences of a shot dialogue field, one per line."""

    lines: list[str] = []
    for raw in dialogue.splitlines():
        line = _DIALOGUE_SPEAKER_PREFIX.sub("", raw.strip())
        line = _DIALOGUE_STAGE_DIRECTION.sub("", line).strip()
        if line:
            lines.append(line)
    return tuple(lines)
