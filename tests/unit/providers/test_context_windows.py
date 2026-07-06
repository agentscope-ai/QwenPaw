# -*- coding: utf-8 -*-
# pylint: disable=protected-access,missing-function-docstring
# pylint: disable=too-few-public-methods,unused-argument
# pylint: disable=unsubscriptable-object
"""The static context-window catalog and its wiring into providers.

The compaction trigger is ``trigger_ratio * model.context_size``; before the
catalog every model inherited the 128k ``max_input_length`` default, so a
1M-context model compacted exactly like a 128k one.
"""

import pytest

from qwenpaw.providers.context_windows import known_context_size
from qwenpaw.providers.provider import ModelInfo, Provider


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [
        # Qwen family, including the specific over the generic.
        ("qwen-long", 10_000_000),
        ("qwen3.7-max", 1_000_000),
        ("qwen3.7-plus-2026-01-01", 1_000_000),
        ("qwen3.6-plus", 1_000_000),
        ("qwen-plus-latest", 1_000_000),
        ("qwen-plus", 131_072),
        ("qwen3-max", 262_144),
        ("qwen-max", 131_072),
        # One entry covers the same model across provider id formats.
        ("claude-sonnet-4-5", 200_000),
        ("anthropic/claude-opus-4.6", 200_000),
        ("us.anthropic.claude-haiku-4-5-20251001-v1:0", 200_000),
        ("gpt-4.1-mini", 1_047_576),
        ("gpt-5-codex", 272_000),
        ("o3", 200_000),
        ("openai/o3-mini", 200_000),
        # gemini: 1.5-pro (2M) must win over the family catch-all (1M).
        ("gemini-1.5-pro", 2_097_152),
        ("gemini-2.5-flash", 1_048_576),
        ("kimi-k2-thinking", 262_144),
    ],
)
def test_known_windows(model_id: str, expected: int):
    assert known_context_size(model_id) == expected


def test_unknown_model_returns_none():
    assert known_context_size("totally-unknown-model") is None
    assert known_context_size("") is None


def test_short_patterns_require_a_word_boundary():
    # "o3" must not fire inside another token.
    assert known_context_size("gpt-4o3x") is None
    assert known_context_size("foo-bar-o3") == 200_000


class _CatalogProvider:
    """Minimal stand-in exposing what _get_context_size touches.

    Binds the real ``Provider._get_context_size`` without instantiating the
    abstract ``Provider`` class.
    """

    _info: ModelInfo | None = None

    def get_model_info(self, model_id):
        return self._info

    _get_context_size = Provider._get_context_size


def test_context_size_prefers_explicit_user_config():
    p = _CatalogProvider()
    p._info = ModelInfo(
        id="claude-sonnet-4-5",
        name="x",
        max_input_length=1_000_000,
    )
    assert p._get_context_size("claude-sonnet-4-5") == 1_000_000


def test_context_size_falls_back_to_catalog_when_default():
    p = _CatalogProvider()
    p._info = ModelInfo(id="claude-sonnet-4-5", name="x")  # default 128k
    assert p._get_context_size("claude-sonnet-4-5") == 200_000


def test_context_size_default_when_unknown_everywhere():
    p = _CatalogProvider()
    p._info = None
    default = ModelInfo.model_fields["max_input_length"].default
    assert p._get_context_size("totally-unknown-model") == default
