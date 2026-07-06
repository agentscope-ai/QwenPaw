# -*- coding: utf-8 -*-
"""Static catalog of known model context windows (input tokens).

The compaction trigger scales with ``model.context_size``
(= ``ModelInfo.max_input_length``), but built-in provider catalogs never set
that field, so every model used to inherit the 128k default — a 1M-context
model compacted exactly like a 128k one. This table supplies real windows
for well-known model families; anything not listed keeps the default.

Precedence (see ``Provider._get_context_size``):

1. an explicit per-model ``max_input_length`` configured by the user;
2. this catalog;
3. the ``ModelInfo.max_input_length`` field default (128k).

Values are deliberately CONSERVATIVE: a too-small window merely compacts
earlier, while a too-large one lets the live context grow past what the API
accepts and requests start failing. When a family's window varies by
snapshot, the safe lower documented bound is listed (e.g. ``claude-*`` is
200k — the 1M variant is an opt-in beta header the user can express via a
per-model override).

Matching is case-insensitive substring-at-a-word-boundary, so one entry
covers the same model across providers: ``qwen-long``,
``anthropic/claude-sonnet-4.5`` (OpenRouter), ``us.anthropic.claude-...``
(Bedrock) all resolve. First match wins — keep more specific patterns above
their prefixes.
"""

from __future__ import annotations

# (pattern, max input tokens) — ordered, first match wins.
_KNOWN_CONTEXT_WINDOWS: tuple[tuple[str, int], ...] = (
    # --- Qwen / DashScope --------------------------------------------------
    ("qwen-long", 10_000_000),
    ("qwen-flash", 1_000_000),
    ("qwen-turbo", 1_000_000),
    ("qwen3.7-max", 1_000_000),
    ("qwen3.7-plus", 1_000_000),
    ("qwen3.6-plus", 1_000_000),
    ("qwen-plus-latest", 1_000_000),
    ("qwen-plus", 131_072),  # stable alias: snapshot windows vary
    ("qwen3-coder-plus", 1_000_000),
    ("qwen3-coder", 262_144),
    ("qwen3-max", 262_144),
    ("qwen-max", 131_072),
    ("qwq", 131_072),
    # --- Anthropic (200k standard; 1M sonnet is a beta-header opt-in) ------
    ("claude", 200_000),
    # --- OpenAI -------------------------------------------------------------
    ("gpt-4.1", 1_047_576),
    ("gpt-5", 272_000),
    ("o4-mini", 200_000),
    ("o3", 200_000),
    # --- Google (1.5-pro is 2M; the rest of the family is 1M) --------------
    ("gemini-1.5-pro", 2_097_152),
    ("gemini", 1_048_576),
    # --- Others -------------------------------------------------------------
    ("kimi-k2", 262_144),
    ("glm-4.6", 200_000),
    ("grok-4-fast", 2_000_000),
    ("grok-4", 256_000),
)


def _matches_at_boundary(model_id: str, pattern: str) -> bool:
    """True if ``pattern`` occurs in ``model_id`` at a word boundary.

    Boundary = start of string or preceded by a non-alphanumeric char, so
    ``o3`` matches ``o3-mini`` and ``openai/o3`` but not ``gpt-4o3x``.
    """
    i = model_id.find(pattern)
    while i != -1:
        if i == 0 or not model_id[i - 1].isalnum():
            return True
        i = model_id.find(pattern, i + 1)
    return False


def known_context_size(model_id: str) -> int | None:
    """The cataloged input-context window for ``model_id``, or None.

    None means "not in the table" — the caller falls back to the
    ``ModelInfo.max_input_length`` default.
    """
    normalized = (model_id or "").lower()
    if not normalized:
        return None
    for pattern, tokens in _KNOWN_CONTEXT_WINDOWS:
        if _matches_at_boundary(normalized, pattern):
            return tokens
    return None
