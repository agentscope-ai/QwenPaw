# -*- coding: utf-8 -*-
"""Static catalog of known model context windows (input tokens).

The compaction trigger scales with ``model.context_size``
(= the resolved ``ModelInfo.max_input_length``), but built-in provider
catalogs never set that field, so every model used to inherit the 128k
default — a 1M-context model compacted exactly like a 128k one. This table
supplies real windows for well-known model families; anything not listed
keeps the default.

:func:`resolve_context_window` is the single resolution entry point — both
the compaction path (``Provider._get_context_size`` → ``model.context_size``)
and the display/usage path (``config.get_model_max_input_length``) go through
it, so what the UI reports and when compression fires can never diverge.
:func:`resolve_context_window_details` additionally reports which level
produced the value, for the read-only ``effective_max_input_length_source``
projection that the console renders next to the override box.
Precedence:

1. a per-model ``max_input_length`` override set by the user (``None`` means
   "inherit", so an intentional 131072 is representable);
2. context metadata auto-detected from the provider API;
3. ``max_input_length_catalog``, a window documented by the packaged/OTA/local
   model catalog for this provider variant. The catalog loader normalizes a
   documented value that equals :data:`DEFAULT_CONTEXT_WINDOW` to "not
   provided" before it ever reaches this module;
4. this pattern catalog (skipped for local-serving providers such as Ollama,
   the family's cloud window says nothing about a local ``num_ctx``);
5. :data:`DEFAULT_CONTEXT_WINDOW` (128k).

Values are deliberately CONSERVATIVE: a too-small window merely compacts
earlier, while a too-large one lets the live context grow past what the API
accepts and requests start failing. When a family's window varies by
snapshot, the safe lower documented bound is listed (e.g. ``claude-*`` is
200k — the 1M variant is an opt-in beta header the user can express via a
per-model override).

Matching is case-insensitive substring-at-a-word-boundary, so one entry
covers the same model across providers: ``qwen-long``,
``anthropic/claude-sonnet-4.5`` (OpenRouter), ``us.anthropic.claude-...``
(Bedrock) all resolve. The longest pattern wins, so a specific entry
(``claude-2``) beats its family catch-all (``claude``) regardless of the
order entries are written in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# The fallback window when nothing else resolves. Also the default of
# ``ModelInfo.max_input_length`` in the sense that an untouched install
# behaves this way — but the field itself now defaults to ``None`` (inherit),
# so an intentional 128k override no longer needs a companion flag to stay
# distinguishable from "never configured".
DEFAULT_CONTEXT_WINDOW = 128 * 1024

# Where a resolved window came from. Rendered by the console and asserted by
# the projection tests, so keep the labels stable.
ContextWindowSource = Literal["user", "api", "catalog", "default"]

# (pattern, max input tokens) — longest pattern wins (see _PATTERNS below).
_KNOWN_CONTEXT_WINDOWS: tuple[tuple[str, int], ...] = (
    # --- Qwen / DashScope --------------------------------------------------
    ("qwen-long", 10_000_000),
    ("qwen-flash", 1_000_000),
    ("qwen-turbo-latest", 1_000_000),
    ("qwen-turbo", 131_072),  # stable alias: snapshot windows vary
    ("qwen3.8", 1_000_000),
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
    ("claude-instant", 100_000),  # legacy 100k models still served by
    ("claude-2", 100_000),  # some gateways/Bedrock
    ("claude", 200_000),
    # --- OpenAI -------------------------------------------------------------
    ("gpt-4.1", 1_047_576),
    ("gpt-5", 272_000),
    ("o4-mini", 200_000),
    ("o3", 200_000),
    # --- Google (1.5-pro is 2M; the rest of the family is 1M) --------------
    ("gemini-1.5-pro", 2_097_152),
    ("gemini", 1_048_576),
    # --- MiniMax (M3 is a 1M-context multimodal flagship; the M2.7 series
    #     is 204.8k. Legacy M2.5/M2.1/M2 keep the conservative default.) -----
    ("minimax-m3", 1_000_000),
    ("minimax-m2.7", 204_800),
    # --- Others -------------------------------------------------------------
    ("kimi-k3", 1_000_000),
    ("kimi-k2", 262_144),
    ("glm-5.2", 1_000_000),
    ("glm-4.6", 200_000),
    ("grok-4-fast", 2_000_000),
    ("grok-4", 256_000),
)


# Longest pattern first: a specific entry ("claude-2") always beats its
# family catch-all ("claude") no matter where it sits in the table above.
_PATTERNS: tuple[tuple[str, int], ...] = tuple(
    sorted(_KNOWN_CONTEXT_WINDOWS, key=lambda kv: len(kv[0]), reverse=True),
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

    None means "not in the table" — the caller falls back to
    :data:`DEFAULT_CONTEXT_WINDOW`.
    """
    normalized = (model_id or "").lower()
    if not normalized:
        return None
    for pattern, tokens in _PATTERNS:
        if _matches_at_boundary(normalized, pattern):
            return tokens
    return None


@dataclass(frozen=True)
class ContextWindowResolution:
    """A resolved input-context window plus the level that produced it."""

    value: int
    source: ContextWindowSource


def resolve_context_window_details(
    model_id: str,
    *,
    override: int | None = None,
    auto_detected: int | None = None,
    catalog: int | None = None,
    use_catalog: bool = True,
) -> ContextWindowResolution:
    """Resolve a model's input-context window and its provenance.

    Resolution order is the user override, API-detected metadata, the
    provider catalog's documented window, the static pattern catalog when
    enabled, and finally :data:`DEFAULT_CONTEXT_WINDOW`. ``use_catalog``
    should be false for local-serving providers whose actual runtime context
    is deployment specific. This function is the single implementation of
    that order; every caller resolves through it.
    """
    if override is not None and override > 0:
        return ContextWindowResolution(override, "user")
    if auto_detected is not None and auto_detected > 0:
        return ContextWindowResolution(auto_detected, "api")
    if catalog is not None and catalog > 0:
        return ContextWindowResolution(catalog, "catalog")
    if use_catalog:
        known = known_context_size(model_id)
        if known is not None:
            return ContextWindowResolution(known, "catalog")
    return ContextWindowResolution(DEFAULT_CONTEXT_WINDOW, "default")


def resolve_context_window(
    model_id: str,
    *,
    override: int | None = None,
    auto_detected: int | None = None,
    catalog: int | None = None,
    use_catalog: bool = True,
) -> int:
    """The resolved window as a plain int (see the details variant)."""
    return resolve_context_window_details(
        model_id,
        override=override,
        auto_detected=auto_detected,
        catalog=catalog,
        use_catalog=use_catalog,
    ).value
