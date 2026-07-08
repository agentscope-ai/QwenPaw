# -*- coding: utf-8 -*-
# pylint: disable=protected-access,missing-function-docstring
# pylint: disable=too-few-public-methods,unused-argument
# pylint: disable=unsubscriptable-object
"""The static context-window catalog and its wiring into providers.

The compaction trigger is ``trigger_ratio * model.context_size``; before the
catalog every model inherited the 128k ``max_input_length`` default, so a
1M-context model compacted exactly like a 128k one.
"""

from types import SimpleNamespace

import pytest

from qwenpaw.providers.context_windows import (
    DEFAULT_CONTEXT_WINDOW,
    known_context_size,
    resolve_context_window,
)
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
        ("qwen-turbo-latest", 1_000_000),
        ("qwen-turbo", 131_072),  # stable alias: conservative bound
        ("qwen3-max", 262_144),
        ("qwen-max", 131_072),
        # One entry covers the same model across provider id formats.
        ("claude-sonnet-4-5", 200_000),
        ("anthropic/claude-opus-4.6", 200_000),
        ("us.anthropic.claude-haiku-4-5-20251001-v1:0", 200_000),
        # Legacy 100k models must NOT inherit the family's 200k.
        ("claude-2.0", 100_000),
        ("anthropic/claude-2", 100_000),
        ("claude-instant-1.2", 100_000),
        ("us.anthropic.claude-instant-v1:0", 100_000),
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


# -- resolve_context_window: the single resolution entry point ---------------


def test_resolve_explicit_config_wins():
    assert (
        resolve_context_window("claude-sonnet-4-5", configured=1_000_000)
        == 1_000_000
    )


def test_resolve_default_valued_config_falls_to_catalog():
    assert (
        resolve_context_window(
            "claude-sonnet-4-5",
            configured=DEFAULT_CONTEXT_WINDOW,
        )
        == 200_000
    )


def test_resolve_without_catalog_uses_default():
    # Local-serving providers opt out: family windows don't apply.
    assert (
        resolve_context_window("qwen3-coder:30b", use_catalog=False)
        == DEFAULT_CONTEXT_WINDOW
    )
    # But an explicit config still wins.
    assert (
        resolve_context_window(
            "qwen3-coder:30b",
            configured=32_768,
            use_catalog=False,
        )
        == 32_768
    )


def test_resolve_unknown_model_uses_default():
    assert (
        resolve_context_window("totally-unknown-model")
        == DEFAULT_CONTEXT_WINDOW
    )


def test_unknown_model_returns_none():
    assert known_context_size("totally-unknown-model") is None
    assert known_context_size("") is None


def test_short_patterns_require_a_word_boundary():
    # "o3" must not fire inside another token.
    assert known_context_size("gpt-4o3x") is None
    assert known_context_size("foo-bar-o3") == 200_000


class _CatalogProvider:
    """Minimal stand-in exposing what get_context_size touches.

    Binds the real ``Provider`` methods without instantiating the abstract
    ``Provider`` class.
    """

    _info: ModelInfo | None = None

    def get_model_info(self, model_id):
        return self._info

    get_context_size = Provider.get_context_size
    _get_context_size = Provider._get_context_size
    _context_catalog_enabled = Provider._context_catalog_enabled


def test_context_size_prefers_explicit_user_config():
    p = _CatalogProvider()
    p._info = ModelInfo(
        id="claude-sonnet-4-5",
        name="x",
        max_input_length=1_000_000,
    )
    assert p.get_context_size("claude-sonnet-4-5") == 1_000_000


def test_context_size_falls_back_to_catalog_when_default():
    p = _CatalogProvider()
    p._info = ModelInfo(id="claude-sonnet-4-5", name="x")  # default 128k
    assert p.get_context_size("claude-sonnet-4-5") == 200_000


def test_context_size_default_when_unknown_everywhere():
    p = _CatalogProvider()
    p._info = None
    assert (
        p.get_context_size("totally-unknown-model") == DEFAULT_CONTEXT_WINDOW
    )


def test_private_alias_still_works():
    # Providers call self._get_context_size internally; it must stay wired.
    p = _CatalogProvider()
    p._info = ModelInfo(id="claude-sonnet-4-5", name="x")
    assert p._get_context_size("claude-sonnet-4-5") == 200_000


# -- Ollama: local serving opts out of the cloud catalog ----------------------


def _make_ollama(**kw):
    from qwenpaw.providers.ollama_provider import OllamaProvider

    return OllamaProvider(
        id="ollama",
        name="Ollama",
        base_url="http://localhost:11434",
        api_key="EMPTY",
        chat_model="OpenAIChatModel",
        **kw,
    )


def test_ollama_skips_catalog():
    """A local qwen3-coder:30b must NOT get the family's cloud 262k — the
    local serve truncates at num_ctx, so assuming a huge window would
    disable compression while the server drops the prompt head."""
    provider = _make_ollama()
    assert (
        provider.get_context_size("qwen3-coder:30b") == DEFAULT_CONTEXT_WINDOW
    )


def test_ollama_explicit_config_still_wins():
    provider = _make_ollama(
        models=[
            ModelInfo(
                id="qwen3-coder:30b",
                name="qwen3-coder",
                max_input_length=32_768,
            ),
        ],
    )
    assert provider.get_context_size("qwen3-coder:30b") == 32_768


# -- OpenRouter: the API's context_length is authoritative --------------------


def _openrouter_payload(*rows):
    return SimpleNamespace(data=list(rows))


def test_openrouter_reads_context_length():
    from qwenpaw.providers.openrouter_provider import OpenRouterProvider

    payload = _openrouter_payload(
        SimpleNamespace(
            id="anthropic/claude-sonnet-4.5",
            name="Claude Sonnet 4.5",
            pricing=None,
            context_length=1_000_000,
        ),
        SimpleNamespace(  # absent → field default → catalog resolves
            id="mistralai/mistral-large",
            name="Mistral Large",
            pricing=None,
        ),
        SimpleNamespace(  # invalid → ignored
            id="foo/bar",
            name="Bar",
            pricing=None,
            context_length="not-a-number",
        ),
    )
    models = {
        m.id: m for m in OpenRouterProvider._normalize_models_payload(payload)
    }
    assert models["anthropic/claude-sonnet-4.5"].max_input_length == 1_000_000
    assert (
        models["mistralai/mistral-large"].max_input_length
        == DEFAULT_CONTEXT_WINDOW
    )
    assert models["foo/bar"].max_input_length == DEFAULT_CONTEXT_WINDOW


# -- config display path resolves through the SAME provider method -----------


def test_get_model_max_input_length_uses_provider_resolution(monkeypatch):
    """/history, usage%%, and daemon status must report the same window the
    compaction trigger uses — the display path delegates to
    Provider.get_context_size instead of reading the raw field."""
    from qwenpaw.config import config as config_mod

    class _Provider:
        def get_context_size(self, model_id):
            assert model_id == "claude-sonnet-4-5"
            return 200_000

    class _Manager:
        def get_provider(self, provider_id):
            return _Provider()

    monkeypatch.setattr(
        "qwenpaw.providers.ProviderManager.get_instance",
        staticmethod(_Manager),
    )
    agent_config = SimpleNamespace(
        id="agent-1",
        active_model=SimpleNamespace(
            provider_id="anthropic",
            model="claude-sonnet-4-5",
        ),
    )
    assert config_mod.get_model_max_input_length(agent_config) == 200_000
