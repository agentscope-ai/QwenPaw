# -*- coding: utf-8 -*-
"""CJK-friendly normalization for Markdown emphasis boundaries.

CommonMark's emphasis "flanking" rules classify CJK sentence punctuation as
Unicode punctuation. CJK text, however, is written without inter-word
spaces, so a closing emphasis delimiter that sits immediately after CJK
punctuation and immediately before CJK text is judged "not a valid closer"
and the raw ``**`` leaks into the rendered output, e.g.::

    **没有改动任何设置。**所有内容保持不变。

This module rewrites such boundaries by moving the trailing CJK punctuation
run outside the delimiter, producing the equivalent, renderable form::

    **没有改动任何设置**。所有内容保持不变。

The repair is deliberately conservative and display-oriented:

* Only ``*``, ``_``, ``**``, ``__``, ``***`` and ``___`` are considered.
* Only the punctuation set ``。！？；：，、…`` plus full-width trailing
  closers (``”’」』】》〉）〕］``) is moved, and only when the delimiter is
  immediately followed by Han, Hiragana, Katakana or Hangul text.
* Fenced, indented and inline code, escaped delimiters, CRLF line endings and
  unrelated unfinished Markdown are preserved verbatim.

The approach mirrors the CJK emphasis repair used by other Markdown clients
(see the CommonMark discussion ``commonmark/commonmark-spec#650``); the
implementation here is independent.
"""

from __future__ import annotations

import re
import unicodedata
from typing import List, Optional, Tuple

__all__ = ["normalize_cjk_emphasis"]

# Sentence punctuation whose presence inside a closing delimiter is the
# trigger for a repair.
_CORE_PUNCTUATION = frozenset("。！？；：，、…")

# Full-width trailing closers that may appear after the core punctuation.
_TRAILING_CLOSERS = frozenset("”’」』】》〉）〕］")

# Han / Hiragana / Katakana / Hangul code point ranges (approximate script
# property, since the stdlib ``re`` module has no ``\p{Script=...}``).
# Expressed as explicit ranges rather than a regex character class: the intent
# is unambiguous, supplementary planes are handled per code point, and no
# "overly permissive regular expression range" analysis can misfire.
_CJK_RANGES: Tuple[Tuple[int, int], ...] = (
    (0x2E80, 0x2EFF),  # CJK radicals
    (0x3005, 0x3005),  # ideographic iteration mark
    (0x3007, 0x3007),  # ideographic number zero
    (0x3021, 0x3029),
    (0x3038, 0x303B),
    (0x3041, 0x3096),  # Hiragana
    (0x309D, 0x309F),
    (0x30A1, 0x30FA),  # Katakana
    (0x30FD, 0x30FF),
    (0x31F0, 0x31FF),
    (0xFF66, 0xFF9D),  # Halfwidth Katakana
    (0x3400, 0x4DBF),  # CJK Extension A
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs
    (0xF900, 0xFAFF),  # CJK Compatibility Ideographs
    (0x1100, 0x11FF),  # Hangul Jamo
    (0x3130, 0x318F),  # Hangul Compatibility Jamo
    (0xA960, 0xA97F),  # Hangul Jamo Extended-A
    (0xAC00, 0xD7A3),  # Hangul syllables
    (0xD7B0, 0xD7FF),  # Hangul Jamo Extended-B
    (0x20000, 0x2A6DF),  # Supplementary Ideographic Plane
    (0x2A700, 0x2EBEF),
    (0x2F800, 0x2FA1F),  # CJK Compatibility Ideographs Supplement
)


def _is_cjk(character: str) -> bool:
    point = ord(character)
    for start, end in _CJK_RANGES:
        if start <= point <= end:
            return True
    return False


_OPENING_FENCE_RE = re.compile(r"^( {0,3})(`{3,}|~{3,})(.*)$")
_LEADING_SPACE_RE = re.compile(r"^ {0,3}")
_INDENT_RE = re.compile(r"^(?: {4}|\t)")
_BLANK_RE = re.compile(r"^[ \t]*$")

Replacement = Tuple[
    int,
    int,
    int,
]  # (punctuation_start, delimiter_start, delimiter_end)


# pylint: disable-next=too-many-branches,too-many-statements
def normalize_cjk_emphasis(text: str) -> str:
    """Move CJK sentence punctuation out of malformed emphasis boundaries.

    Returns ``text`` unchanged when there is nothing to repair. The function
    is pure, stateless and idempotent.
    """
    if not text:
        return text
    block, protected, paragraph_reset = _build_protection_masks(text)
    replacements: List[Replacement] = []
    delimiters: List[Tuple[str, int]] = []
    was_block = False

    length = len(text)
    index = 0
    while index < length:
        if paragraph_reset[index]:
            delimiters = []

        if block[index]:
            if not was_block:
                delimiters = []
            was_block = True
            index += 1
            continue
        if was_block:
            delimiters = []
            was_block = False
        if protected[index]:
            index += 1
            continue

        character = text[index]
        if character not in "*_":
            index += 1
            continue

        run_length = _count_run(text, protected, index, character)
        if run_length not in (1, 2, 3):
            index += run_length
            continue
        if _is_escaped(text, index):
            index += run_length
            continue

        punctuation_start = _find_trailing_punctuation_start(text, index)
        matching_top = False
        if delimiters:
            top_character, top_length = delimiters[-1]
            matching_top = (
                top_character == character and top_length == run_length
            )
        is_repair_candidate = (
            punctuation_start >= 0
            and _is_cjk_at(text, index + run_length)
            and _range_unprotected(
                protected,
                punctuation_start,
                index + run_length,
            )
        )

        if is_repair_candidate and matching_top:
            delimiters.pop()
            replacements.append(
                (punctuation_start, index, index + run_length),
            )
            index += run_length
            continue

        can_open, can_close = _delimiter_flanking(
            text,
            index,
            run_length,
        )
        if can_close and matching_top:
            delimiters.pop()
        elif can_open:
            delimiters.append((character, run_length))
        index += run_length

    if not replacements:
        return text

    output: List[str] = []
    copied_through = 0
    for punct_start, delim_start, delim_end in replacements:
        output.append(text[copied_through:punct_start])
        output.append(text[delim_start:delim_end])
        output.append(text[punct_start:delim_start])
        copied_through = delim_end
    output.append(text[copied_through:])
    return "".join(output)


def _build_protection_masks(
    text: str,
) -> Tuple[bytearray, bytearray, bytearray]:
    """Return (block, protected, paragraph_reset) masks.

    ``block`` marks fenced/indented code, ``protected`` adds inline code, and
    ``paragraph_reset`` marks paragraph boundaries.
    """
    length = len(text)
    block = bytearray(length)
    paragraph_reset = bytearray(length + 1)
    fence: Optional[Tuple[str, int]] = None

    line_start = 0
    while line_start < length:
        newline = text.find("\n", line_start)
        line_end_with_newline = length if newline < 0 else newline + 1
        content_end = length if newline < 0 else newline
        if content_end > line_start and text[content_end - 1] == "\r":
            content_end -= 1
        line = text[line_start:content_end]

        if fence is not None:
            block[line_start:line_end_with_newline] = b"\x01" * (
                line_end_with_newline - line_start
            )
            if _is_closing_fence(line, fence):
                fence = None
        else:
            opening_fence = _get_opening_fence(line)
            if opening_fence is not None:
                fence = opening_fence
                block[line_start:line_end_with_newline] = b"\x01" * (
                    line_end_with_newline - line_start
                )
            elif _INDENT_RE.match(line):
                block[line_start:line_end_with_newline] = b"\x01" * (
                    line_end_with_newline - line_start
                )
            elif _BLANK_RE.match(line):
                paragraph_reset[line_start] = 1
                paragraph_reset[line_end_with_newline] = 1
        line_start = line_end_with_newline

    protected = bytearray(block)
    _mark_inline_code(text, block, protected)
    return block, protected, paragraph_reset


def _get_opening_fence(line: str) -> Optional[Tuple[str, int]]:
    match = _OPENING_FENCE_RE.match(line)
    if not match:
        return None
    run = match.group(2)
    if run[0] == "`" and "`" in match.group(3):
        return None
    return run[0], len(run)


def _is_closing_fence(line: str, fence: Tuple[str, int]) -> bool:
    offset = _LEADING_SPACE_RE.match(line).end()
    end = offset
    while end < len(line) and line[end] == fence[0]:
        end += 1
    return end - offset >= fence[1] and bool(
        _BLANK_RE.match(line[end:]),
    )


def _mark_inline_code(
    text: str,
    block: bytearray,
    protected: bytearray,
) -> None:
    length = len(text)
    index = 0
    while index < length:
        if block[index] or text[index] != "`" or _is_escaped(text, index):
            index += 1
            continue

        opening_length = _count_character_run(text, index, "`")
        closing_start = -1
        cursor = index + opening_length
        while cursor < length:
            if block[cursor]:
                break
            if text[cursor] != "`" or _is_escaped(text, cursor):
                cursor += 1
                continue
            closing_length = _count_character_run(text, cursor, "`")
            if closing_length == opening_length:
                closing_start = cursor
                break
            cursor += closing_length

        if closing_start < 0:
            protected[index:] = b"\x01" * (length - index)
            return
        end = closing_start + opening_length
        protected[index:end] = b"\x01" * (end - index)
        index = end


def _count_run(
    text: str,
    protected: bytearray,
    start: int,
    character: str,
) -> int:
    end = start
    length = len(text)
    while end < length and not protected[end] and text[end] == character:
        end += 1
    return end - start


def _count_character_run(text: str, start: int, character: str) -> int:
    end = start
    length = len(text)
    while end < length and text[end] == character:
        end += 1
    return end - start


def _is_escaped(text: str, index: int) -> bool:
    backslashes = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    return backslashes % 2 == 1


def _find_trailing_punctuation_start(text: str, end: int) -> int:
    cursor = end
    while cursor > 0 and text[cursor - 1] in _TRAILING_CLOSERS:
        cursor -= 1
    before_core = cursor
    while cursor > 0 and text[cursor - 1] in _CORE_PUNCTUATION:
        cursor -= 1
    return cursor if cursor < before_core else -1


def _is_cjk_at(text: str, index: int) -> bool:
    if index >= len(text):
        return False
    return _is_cjk(text[index])


def _range_unprotected(
    protected: bytearray,
    start: int,
    end: int,
) -> bool:
    for index in range(start, end):
        if protected[index]:
            return False
    return True


def _is_punctuation_or_symbol(character: str) -> bool:
    return unicodedata.category(character)[0] in ("P", "S")


def _delimiter_flanking(
    text: str,
    start: int,
    length: int,
) -> Tuple[bool, bool]:
    previous = text[start - 1] if start > 0 else None
    following = text[start + length] if start + length < len(text) else None

    previous_whitespace = previous is None or previous.isspace()
    next_whitespace = following is None or following.isspace()
    previous_punctuation = previous is not None and _is_punctuation_or_symbol(
        previous,
    )
    next_punctuation = following is not None and _is_punctuation_or_symbol(
        following,
    )

    left_flanking = (not next_whitespace) and (
        (not next_punctuation) or previous_whitespace or previous_punctuation
    )
    right_flanking = (not previous_whitespace) and (
        (not previous_punctuation) or next_whitespace or next_punctuation
    )

    if text[start] == "*":
        return left_flanking, right_flanking
    return (
        left_flanking and ((not right_flanking) or previous_punctuation),
        right_flanking and ((not left_flanking) or next_punctuation),
    )
