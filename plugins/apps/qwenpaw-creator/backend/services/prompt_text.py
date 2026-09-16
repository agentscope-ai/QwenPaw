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


_QUOTED_TEXT = re.compile(
    r'“([^”\n]+)”|‘([^’\n]+)’|「([^」\n]+)」|『([^』\n]+)』|"([^"\n]+)"',
)
_SPEECH_CUE = re.compile(
    r"(?:对白|台词|旁白|画外音|独白|说(?!明|法|服)|问(?!题)|回答|喊|嘀咕|"
    r"\b(?:dialogue|narration|voice[- ]?over|says?|asks?|"
    r"replies|whispers?|shouts?)\b)"
    r'(?=[^。！？!?\n“”‘’「」『』"]{0,12}$)',
    re.IGNORECASE,
)
_NON_SPEECH_PREFIX = re.compile(
    r"(?:没(?:有)?|不(?:再|曾|会|肯|要|必|是)?|未(?:曾)?|无需|无须|禁止)"
    r"(?:\s|再|开口|出声|继续|大声){0,3}$"
    r"|\b(?:not|never|without|no(?:\s+longer)?|\w+n['’]t)"
    r"\s+(?:(?:\w+ly|ever)\s+){0,2}$"
    r"|\b(?:sign|label|caption|title|screen|notice|poster)\s*$",
    re.IGNORECASE,
)


def missing_narrative_dialogue(
    narrative: str,
    video_prompt: str,
) -> tuple[str, ...]:
    """Only explicit quoted speech is enforceable; titles/signs are not speech.

    Free-form action and unquoted prose remain semantic review concerns. This
    check neither prescribes how much dialogue a story needs nor reads shots.
    """
    prompt_key = dialogue_match_key(video_prompt)
    missing: list[str] = []
    for match in _QUOTED_TEXT.finditer(narrative):
        prefix = re.split(r"[。！？!?\n]", narrative[: match.start()])[-1]
        cues = list(_SPEECH_CUE.finditer(prefix))
        if not cues or _NON_SPEECH_PREFIX.search(prefix[: cues[-1].start()]):
            continue
        line = next(value for value in match.groups() if value).strip()
        key = dialogue_match_key(line).strip(".,!?:;")
        if key and key not in prompt_key:
            missing.append(line)
    return tuple(dict.fromkeys(missing))
