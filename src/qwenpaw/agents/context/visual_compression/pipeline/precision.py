# -*- coding: utf-8 -*-
"""Deterministic exact-value precision lane for rendered text."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from ..config import (
    FACTSHEET_MAX_CHUNK_CHARS,
    FACTSHEET_MAX_DISTINCT,
    FACTSHEET_MAX_ENTRIES,
    FACTSHEET_MAX_SCAN_CHARS,
    FACTSHEET_PAGE_CHARS,
)


@dataclass(frozen=True)
class FactEntry:
    value: str
    count: int = 1


_UUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
)
# Explicit context whitespace includes BOM and Unicode line separators.
_CONTEXT_WHITESPACE = (
    "\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680"
    "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009"
    "\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
)
_NON_WHITESPACE_CLASS = f"[^{re.escape(_CONTEXT_WHITESPACE)}]"
_TEXT_CHUNK = re.compile(f"{_NON_WHITESPACE_CLASS}+")


def _trim_context_whitespace(value: str) -> str:
    return value.strip(_CONTEXT_WHITESPACE)


_EMAIL = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$",
)
_IBAN = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{8,30}$")
_CURRENCY = re.compile(
    r"^(?:[$€£¥]|(?:USD|EUR|GBP|CAD|AUD|CHF|JPY))"
    r"\d(?:[\d,_]*\d)?(?:\.\d{2})?$",
)
_HEX = re.compile(r"^(?=[0-9a-fA-F]*\d)[0-9a-fA-F]{7,40}$")
_CONST = re.compile(r"^[A-Z][A-Z0-9]{2,}(?:_[A-Z0-9]+)+$")
_TICKET = re.compile(r"^(?=[A-Z0-9-]*\d)[A-Z][A-Z0-9]+(?:-[A-Z0-9]+)+$")
_FLAG = re.compile(r"^--?[A-Za-z][\w-]+$", re.ASCII)
_NUMBER = re.compile(r"^\d[\d,_]*$|^\d+\.\d+$")
_URL = re.compile(r"^https?://")
_CAMEL = re.compile(r"^(?:[a-z]+|[A-Z][a-z0-9]+)(?:[A-Z][a-z0-9]*)+$")
_ASSIGNMENT = re.compile(
    rf"^[A-Z][A-Z0-9_]{{2,}}={_NON_WHITESPACE_CLASS}+$",
    re.ASCII,
)
_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        rf"\b[A-Z][A-Z0-9_]{{2,}}="
        rf"[^{re.escape(_CONTEXT_WHITESPACE)})\"'<>]+",
        re.ASCII,
    ),
    re.compile(
        rf"\bhttps?://[^{re.escape(_CONTEXT_WHITESPACE)})\"'<>]+",
        re.ASCII,
    ),
    re.compile(
        r"\b[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
        r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
        r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+\b",
        re.ASCII,
    ),
    re.compile(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b",
        re.ASCII,
    ),
    re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{8,30}\b", re.ASCII),
    re.compile(
        r"(?:[$€£¥]|(?:USD|EUR|GBP|CAD|AUD|CHF|JPY))"
        r"\d(?:[\d,_]*\d)?(?:\.\d{2})?\b",
        re.ASCII,
    ),
    re.compile(r"(?:[\w@~+-]+)?(?:/[\w.@+-]+)+\.[A-Za-z]\w{0,8}\b", re.ASCII),
    re.compile(r"/[\w.@+-]+(?:/[\w.@+-]+)+/?", re.ASCII),
    re.compile(r"\b(?=[0-9a-f]*\d)[0-9a-f]{7,40}\b", re.ASCII),
    re.compile(r"\bv?\d+\.\d+(?:\.\d+)?(?:[-+][\w.]+)?\b", re.ASCII),
    re.compile(r"(?:^|[^\w-])(--?[A-Za-z][\w-]+)", re.ASCII),
    re.compile(r"\b\d[\d,_]{3,}\b", re.ASCII),
    re.compile(r"\b\d+\.\d+\b", re.ASCII),
    re.compile(r"\b[A-Z][A-Z0-9]{2,}(?:_[A-Z0-9]+)+\b", re.ASCII),
    re.compile(r"\b(?:[a-z]+|[A-Z][a-z0-9]+)(?:[A-Z][a-z0-9]*)+\b", re.ASCII),
    re.compile(
        r"\b(?=[A-Z0-9-]{0,119}\d)[A-Z][A-Z0-9]+(?:-[A-Z0-9]+)+\b",
        re.ASCII,
    ),
)


def _priority(token: str) -> int:
    protected = (
        _ASSIGNMENT,
        _HEX,
        _UUID,
        _EMAIL,
        _IBAN,
        _CURRENCY,
        _CONST,
        _TICKET,
        _FLAG,
        _NUMBER,
    )
    if any(pattern.match(token) for pattern in protected) or (
        _CAMEL.match(token) and len(token) >= 8
    ):
        return 1
    return 3 if _URL.match(token) else 2


def _select(counts: dict[str, int], limit: int) -> list[FactEntry]:
    specific: list[str] = []
    for token in sorted(
        counts,
        key=lambda value: (
            -len(value),
            value,
        ),
    ):
        if not any(token in kept for kept in specific):
            specific.append(token)
    ranked = sorted(
        specific,
        key=lambda value: (
            _priority(value),
            -len(value),
            value,
        ),
    )
    selected: list[FactEntry] = []
    urls = 0
    for token in ranked:
        if _URL.match(token):
            if urls >= 8:
                continue
            urls += 1
        selected.append(
            FactEntry(token, counts[token]),
        )
        if len(selected) >= limit:
            break
    return selected


def _extract_page(text: str, limit: int) -> list[FactEntry]:
    counts: dict[str, int] = {}
    for chunk_match in _TEXT_CHUNK.finditer(text):
        chunk = chunk_match.group(0)
        if not 3 <= len(chunk) <= FACTSHEET_MAX_CHUNK_CHARS:
            continue
        spans: set[tuple[int, str]] = set()
        for pattern in _PATTERNS:
            for match in pattern.finditer(chunk):
                token = match.group(1) if match.lastindex else match.group(0)
                token = _trim_context_whitespace(token).rstrip(".,;:!?")
                if not 3 <= len(token) <= 120:
                    continue
                key = (
                    match.start(1) if match.lastindex else match.start(),
                    token,
                )
                if key in spans:
                    continue
                spans.add(key)
                counts[token] = counts.get(token, 0) + 1
        if len(counts) >= FACTSHEET_MAX_DISTINCT:
            break
    return _select(counts, limit)


def extract_fact_entries(
    text: str,
    limit: int = FACTSHEET_MAX_ENTRIES,
) -> list[FactEntry]:
    """Extract high-risk exact tokens under a fixed entry cap."""
    if not text or limit <= 0:
        return []
    if len(text) <= FACTSHEET_MAX_SCAN_CHARS:
        return _extract_page(text, limit)
    merged_counts: dict[str, int] = {}
    pages = max(1, math.ceil(len(text) / FACTSHEET_PAGE_CHARS))
    for page in range(pages):
        start = page * FACTSHEET_PAGE_CHARS
        chunk = text[start : start + FACTSHEET_PAGE_CHARS]
        for entry in _extract_page(chunk, limit):
            merged_counts[entry.value] = (
                merged_counts.get(entry.value, 0) + entry.count
            )
    return _select(merged_counts, limit)


def factsheet_text(text: str, limit: int = FACTSHEET_MAX_ENTRIES) -> str:
    """Format the native precision lane placed next to rendered images."""
    facts = extract_fact_entries(text, limit)
    if not facts:
        return ""
    repeated = any(entry.count >= 2 for entry in facts)
    opener = (
        "[Exact identifiers from the rendered context above (paths, ids, "
        "versions, numbers) — quote these verbatim instead of transcribing "
        "them from the image"
        + (
            "; ×N marks a token that occurs N times within the imaged "
            "content: "
            if repeated
            else ": "
        )
    )
    body = " · ".join(
        entry.value + (f" ×{entry.count}" if entry.count >= 2 else "")
        for entry in facts
    )
    return opener + body + "]"


__all__ = [
    "FactEntry",
    "extract_fact_entries",
    "factsheet_text",
]
