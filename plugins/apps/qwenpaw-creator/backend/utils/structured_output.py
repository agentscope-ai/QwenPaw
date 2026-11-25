# -*- coding: utf-8 -*-
"""Helpers for extracting structured JSON from model responses."""

from __future__ import annotations

import json
from typing import Any


def _strip_fenced_block(text: str) -> str | None:
    if "```json" in text:
        return text.split("```json", 1)[1].split("```", 1)[0].strip()
    if "```" in text:
        return text.split("```", 1)[1].split("```", 1)[0].strip()
    return None


def _find_balanced_json(text: str) -> str:
    starts = [index for index, char in enumerate(text) if char in "[{"]
    if not starts:
        raise json.JSONDecodeError("No JSON object or array found", text, 0)

    pairs = {"{": "}", "[": "]"}
    for start in starts:
        stack: list[str] = []
        in_string = False
        escaped = False

        for index in range(start, len(text)):
            char = text[index]

            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char in pairs:
                stack.append(pairs[char])
            elif stack and char == stack[-1]:
                stack.pop()
                if not stack:
                    candidate = text[start : index + 1]
                    try:
                        json.loads(candidate)
                    except json.JSONDecodeError:
                        # Balanced prose brackets such as "[note]" are not
                        # JSON; try the next opening bracket.
                        break
                    return candidate

    raise json.JSONDecodeError("No valid JSON object or array found", text, 0)


def extract_json_payload(response_text: str) -> Any:
    """Parse JSON from a plain, fenced, or lightly narrated model response.

    Robustness: when the fenced block is invalid, fall back to a balanced
    bracket scan for the first valid JSON in the whole text, so a slightly
    malformed code block does not fail the entire round (the model body
    often contains valid JSON anyway).
    """
    fenced = _strip_fenced_block(response_text)
    if fenced is not None:
        try:
            return json.loads(fenced)
        except json.JSONDecodeError:
            # Invalid inside the fence: balanced-scan the fenced fragment
            # first, then fall back to scanning the whole text.
            try:
                return json.loads(_find_balanced_json(fenced))
            except json.JSONDecodeError:
                pass

    try:
        return json.loads(response_text.strip())
    except json.JSONDecodeError:
        return json.loads(_find_balanced_json(response_text))
