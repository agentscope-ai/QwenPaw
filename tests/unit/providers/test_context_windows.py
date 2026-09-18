# -*- coding: utf-8 -*-
# pylint: disable=protected-access,missing-function-docstring
# pylint: disable=too-few-public-methods,unused-argument
# pylint: disable=unsubscriptable-object
"""The static context-window catalog and its wiring into providers.

The compaction trigger is ``trigger_ratio * model.context_size``; before the
catalog every model inherited the 128k ``max_input_length`` default, so a
1M-context model compacted exactly like a 128k one.

Since schema v3 the window has three separate slots instead of one
override-plus-flag pair: ``max_input_length`` (user override, ``None`` means
inherit), ``max_input_length_auto_detected`` (provider API) and
``max_input_length_catalog`` (provider catalog document).
"""

from types import SimpleNamespace

import pytest

from qwenpaw.providers.context_windows import (
    DEFAULT_CONTEXT_WINDOW,
    known_context_size,
    resolve_context_window,
    resolve_context_window_details,
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
        ("glm-5.2", 1_000_000),
        ("GLM-5.2[1m]", 1_000_000),
        ("zhipu/glm-5.2", 1_000_000),
        # MiniMax: M3 is a 1M-context flagship; the M2.7 series is 204.8k.
        ("MiniMax-M3", 1_000_000),
        ("MiniMax-M2.7", 204_800),
        ("MiniMax-M2.7-highspeed", 204_800),
    ],
)
def test_known_windows(model_id: str, expected: int):
    assert known_context_size(model_id) == expected


# -- resolve_context_window: the single resolution entry point ---------------


def test_resolve_user_override_wins():
    assert (
        resolve_context_window("claude-sonnet-4-5", override=1_000_000)
        == 1_000_000
    )


def test_resolve_provider_default_does_not_override_api():
    assert (
        resolve_context_window(
            "claude-sonnet-4-5",
            catalog=64_000,
            auto_detected=1_000_000,
        )
        == 1_000_000
    )


def test_resolve_absent_override_falls_to_catalog():
    assert resolve_context_window("claude-sonnet-4-5") == 200_000


def test_resolve_user_override_of_128k_is_honored():
    # The whole point of the split slots: choosing the historical default is
    # representable, so no companion boolean is needed.
    assert (
        resolve_context_window(
            "claude-sonnet-4-5",
            override=DEFAULT_CONTEXT_WINDOW,
        )
        == DEFAULT_CONTEXT_WINDOW
    )


def test_resolve_catalog_slot_wins_over_patterns():
    assert (
        resolve_context_window(
            "claude-sonnet-4-5",
            catalog=1_000_000,
        )
        == 1_000_000
    )


def test_resolve_without_catalog_uses_default():
    # Local-serving providers opt out: family windows don't apply.
    assert (
        resolve_context_window("qwen3-coder:30b", use_catalog=False)
        == DEFAULT_CONTEXT_WINDOW
    )
    # But a user override still wins.
    assert (
        resolve_context_window(
            "qwen3-coder:30b",
            override=32_768,
            use_catalog=False,
        )
        == 32_768
    )


def test_resolve_ignores_non_positive_values():
    # A zero/negative slot must never reach the compaction trigger (it would
    # make every request "over the limit") or the usage percentage.
    assert resolve_context_window("claude-sonnet-4-5", override=0) == 200_000
    assert resolve_context_window("claude-sonnet-4-5", catalog=-5) == 200_000
    assert (
        resolve_context_window("claude-sonnet-4-5", auto_detected=0) == 200_000
    )


@pytest.mark.parametrize(
    ("model_id", "kwargs", "expected_source"),
    [
        ("claude-sonnet-4-5", {"override": 1_000}, "user"),
        ("claude-sonnet-4-5", {"auto_detected": 1_000}, "api"),
        ("claude-sonnet-4-5", {"catalog": 1_000}, "catalog"),
        ("claude-sonnet-4-5", {}, "catalog"),  # static pattern table
        ("totally-unknown-model", {}, "default"),
    ],
)
def test_resolve_reports_provenance(model_id, kwargs, expected_source):
    resolution = resolve_context_window_details(model_id, **kwargs)
    assert resolution.source == expected_source
    assert resolution.value == resolve_context_window(model_id, **kwargs)


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

    def get_discovered_model_info(self, model_id):
        return None

    get_context_size = Provider.get_context_size
    get_context_window_details = Provider.get_context_window_details
    _get_context_size = Provider._get_context_size
    _context_catalog_enabled = Provider._context_catalog_enabled
    # ``_context_catalog_enabled`` delegates to this class-level hook, so a
    # stand-in that binds the method has to bind its dependency too.
    context_catalog_enabled = Provider.context_catalog_enabled


class _MutableCatalogProvider(_CatalogProvider):
    models: list[ModelInfo]
    extra_models: list[ModelInfo]

    update_model_config = Provider.update_model_config


def test_context_size_prefers_user_override():
    p = _CatalogProvider()
    p._info = ModelInfo(
        id="claude-sonnet-4-5",
        name="x",
        max_input_length=1_000_000,
    )
    assert p.get_context_size("claude-sonnet-4-5") == 1_000_000


def test_context_size_falls_back_to_catalog_when_inherited():
    p = _CatalogProvider()
    p._info = ModelInfo(id="claude-sonnet-4-5", name="x")
    assert p.get_context_size("claude-sonnet-4-5") == 200_000


def test_context_size_honors_user_override_of_128k():
    p = _CatalogProvider()
    p._info = ModelInfo(
        id="claude-sonnet-4-5",
        name="x",
        max_input_length=DEFAULT_CONTEXT_WINDOW,
    )
    assert p.get_context_size("claude-sonnet-4-5") == DEFAULT_CONTEXT_WINDOW


def test_context_size_reports_user_override_source():
    p = _CatalogProvider()
    p._info = ModelInfo(
        id="claude-sonnet-4-5",
        name="x",
        max_input_length=1_000_000,
    )
    assert p.get_context_window_details("claude-sonnet-4-5").source == "user"


def test_model_config_update_sets_and_clears_the_override():
    p = _MutableCatalogProvider()
    model = ModelInfo(id="claude-sonnet-4-5", name="x")
    p.models = [model]
    p.extra_models = []
    p._info = model

    assert p.update_model_config(model.id, {"max_input_length": 1_000})
    assert model.max_input_length == 1_000
    assert p.get_context_size(model.id) == 1_000
    assert "max_input_length" in model.config_overrides

    # Present-with-None clears the override and drops the protection.
    assert p.update_model_config(model.id, {"max_input_length": None})
    assert model.max_input_length is None
    assert "max_input_length" not in model.config_overrides
    assert p.get_context_size(model.id) == 200_000


def test_model_config_update_clears_a_restored_128k_override():
    # A user-chosen 128k must survive a "clear" round-trip the same way.
    p = _MutableCatalogProvider()
    model = ModelInfo(
        id="claude-sonnet-4-5",
        name="x",
        max_input_length=DEFAULT_CONTEXT_WINDOW,
    )
    p.models = [model]
    p.extra_models = []
    p._info = model
    assert p.get_context_size(model.id) == DEFAULT_CONTEXT_WINDOW

    assert p.update_model_config(model.id, {"max_input_length": None})
    assert p.get_context_size(model.id) == 200_000


def test_unrelated_model_config_update_keeps_the_catalog_window():
    p = _MutableCatalogProvider()
    model = ModelInfo(id="claude-sonnet-4-5", name="x")
    p.models = [model]
    p.extra_models = []
    p._info = model

    assert p.update_model_config(model.id, {"max_tokens": 4096})
    assert model.max_input_length is None
    assert p.get_context_size(model.id) == 200_000


def test_context_size_default_when_unknown_everywhere():
    p = _CatalogProvider()
    p._info = None
    assert (
        p.get_context_size("totally-unknown-model") == DEFAULT_CONTEXT_WINDOW
    )


def test_context_size_uses_discovered_only_api_metadata():
    p = _CatalogProvider()
    p.get_discovered_model_info = lambda _model_id: ModelInfo(
        id="remote-only",
        name="Remote Only",
        max_input_length_auto_detected=512_000,
    )

    assert p.get_context_size("remote-only") == 512_000


def test_context_size_api_supplements_catalog_slot():
    p = _CatalogProvider()
    p._info = ModelInfo(
        id="claude-sonnet-4-5",
        name="Configured",
        max_input_length_catalog=64_000,
    )
    p.get_discovered_model_info = lambda _model_id: ModelInfo(
        id="claude-sonnet-4-5",
        name="Discovered",
        max_input_length_auto_detected=1_000_000,
    )

    assert p.get_context_size("claude-sonnet-4-5") == 1_000_000


def test_context_size_uses_catalog_slot_for_unknown_model():
    p = _CatalogProvider()
    p._info = ModelInfo(
        id="catalog-only-model",
        name="Catalog Only",
        max_input_length_catalog=2_000_000,
    )

    assert p.get_context_size("catalog-only-model") == 2_000_000


def test_context_size_api_wins_over_catalog_slot():
    p = _CatalogProvider()
    p._info = ModelInfo(
        id="catalog-only-model",
        name="Catalog Only",
        max_input_length_catalog=2_000_000,
    )
    p.get_discovered_model_info = lambda _model_id: ModelInfo(
        id="catalog-only-model",
        name="Discovered",
        max_input_length_auto_detected=3_000_000,
    )

    assert p.get_context_size("catalog-only-model") == 3_000_000


def test_context_size_catalog_slot_falls_back_to_discovered_metadata():
    """A fetch-reported window lands in the discovery entry's catalog slot.

    For a configured model that entry is the only place the value lives (a
    fetch must not write the override slot), so the catalog lookup has to fall
    back to it the same way the API-detected lookup does.
    """
    p = _CatalogProvider()
    p._info = ModelInfo(id="vendor/model", name="Configured")
    p.get_discovered_model_info = lambda _model_id: ModelInfo(
        id="vendor/model",
        name="Discovered",
        max_input_length_catalog=512_000,
    )

    details = p.get_context_window_details("vendor/model")

    assert details.value == 512_000
    assert details.source == "catalog"


def test_context_size_configured_catalog_slot_wins_over_discovered():
    """The window documented for the configured model stays authoritative."""
    p = _CatalogProvider()
    p._info = ModelInfo(
        id="vendor/model",
        name="Configured",
        max_input_length_catalog=1_000_000,
    )
    p.get_discovered_model_info = lambda _model_id: ModelInfo(
        id="vendor/model",
        name="Discovered",
        max_input_length_catalog=512_000,
    )

    assert p.get_context_size("vendor/model") == 1_000_000


def test_context_size_user_override_wins_over_discovered_metadata():
    p = _CatalogProvider()
    p._info = ModelInfo(
        id="claude-sonnet-4-5",
        name="Configured",
        max_input_length=64_000,
    )
    p.get_discovered_model_info = lambda _model_id: ModelInfo(
        id="claude-sonnet-4-5",
        name="Discovered",
        max_input_length_auto_detected=1_000_000,
    )

    assert p.get_context_size("claude-sonnet-4-5") == 64_000


def test_private_alias_still_works():
    # Providers call self._get_context_size internally; it must stay wired.
    p = _CatalogProvider()
    p._info = ModelInfo(id="claude-sonnet-4-5", name="x")
    assert p._get_context_size("claude-sonnet-4-5") == 200_000


def test_provider_info_serialization_does_not_rescan_per_model():
    """Guard the response shape, not the wall clock.

    ``get_info()`` used to resolve every derived per-model field by scanning
    the model collections, which made one response quadratic -- and since the
    method never awaits, it blocked the event loop for ~40 ms with 800 models.
    Counting id comparisons keeps this deterministic: a per-model scan gives
    2N^2 comparisons (80,000 at 200 models), while a linear number of lookups
    stays within a small multiple of N.
    """
    import asyncio

    from qwenpaw.providers.openai_provider import OpenAIProvider

    def comparisons_for(model_count: int) -> int:
        counts = {"cmp": 0}

        class _Counting(OpenAIProvider):
            def get_model_info(self, model_id):
                counts["cmp"] += len(self.extra_models) + len(self.models)
                return super().get_model_info(model_id)

            def get_discovered_model_info(self, model_id):
                counts["cmp"] += len(self.discovered_models)
                return super().get_discovered_model_info(model_id)

        provider = _Counting(
            id="openai",
            name="OpenAI",
            api_key="sk-test",
            models=[
                ModelInfo(id=f"gpt-5-mini-{index}", name=f"m{index}")
                for index in range(model_count)
            ],
            extra_models=[],
            discovered_models=[],
        )
        asyncio.run(provider.get_info())
        return counts["cmp"]

    model_count = 200
    assert comparisons_for(model_count) <= 2 * model_count


def test_provider_info_projection_matches_the_resolution():
    """The console renders this read-only projection instead of the raw
    override field (issue #7810), so it must equal what compaction uses."""
    import asyncio

    from qwenpaw.providers.openai_provider import OpenAIProvider

    provider = OpenAIProvider(
        id="openai",
        name="OpenAI",
        api_key="sk-test",
        models=[
            ModelInfo(id="gpt-5", name="gpt-5"),
            ModelInfo(
                id="claude-sonnet-4-5",
                name="claude",
                max_input_length=131_072,
            ),
            ModelInfo(
                id="qwen3-max",
                name="qwen3-max",
                max_input_length_catalog=262_144,
            ),
        ],
        extra_models=[],
    )

    info = asyncio.run(provider.get_info())
    for model in info.models:
        assert model.effective_max_input_length == provider.get_context_size(
            model.id,
        )

    projected = {
        model.id: (
            model.effective_max_input_length,
            model.effective_max_input_length_source,
        )
        for model in info.models
    }
    assert projected["gpt-5"] == (272_000, "catalog")
    assert projected["claude-sonnet-4-5"] == (131_072, "user")
    assert projected["qwen3-max"] == (262_144, "catalog")

    # Response-only: the projection never lands on the live model.
    assert provider.models[0].effective_max_input_length is None


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
        SimpleNamespace(  # absent → no detected window
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
    # The API value is auto-detected metadata: it must not occupy the user
    # override slot, or a later refresh could not update it.
    reported = models["anthropic/claude-sonnet-4.5"]
    assert reported.max_input_length is None
    assert reported.max_input_length_auto_detected == 1_000_000
    absent = models["mistralai/mistral-large"]
    assert absent.max_input_length is None
    assert absent.max_input_length_auto_detected is None
    assert models["foo/bar"].max_input_length_auto_detected is None


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


def test_provider_info_works_with_legacy_thinking_overrides():
    """A provider subclass that overrides ``supports_agent_thinking`` with the
    historical single-argument signature must keep working.

    It is called by the per-response serializer, and ``list_provider_info``
    gathers every provider without ``return_exceptions``, so a signature change
    would break the whole provider list (plugins register arbitrary provider
    classes through ``plugins.registry.register_provider``).
    """
    import asyncio

    from qwenpaw.providers.openai_provider import OpenAIProvider

    class _LegacyPluginProvider(OpenAIProvider):
        def supports_agent_thinking(self, model_id: str) -> bool:
            return True

    provider = _LegacyPluginProvider(
        id="plugin",
        name="Plugin",
        api_key="sk-test",
        models=[
            ModelInfo(
                id="gpt-5",
                name="gpt-5",
                max_input_length_catalog=272_000,
            ),
        ],
        extra_models=[],
    )

    info = asyncio.run(provider.get_info())

    assert info.models[0].supports_agent_thinking is True
    assert info.models[0].effective_max_input_length == 272_000
