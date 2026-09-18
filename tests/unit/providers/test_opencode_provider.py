# -*- coding: utf-8 -*-
"""Unit tests for the OpenCode built-in provider."""
# pylint: disable=protected-access

from agentscope.model import OpenAIChatModel

from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.provider_catalog import (
    KILO_MODELS,
)
from qwenpaw.providers.provider_manager import (
    OPENCODE_MODELS,
    PROVIDER_OPENCODE,
    ProviderManager,
)


class TestOpenCodeProvider:
    """Test the OpenCode provider with merged OpenCode Go models."""

    def test_opencode_provider_is_openai_compatible(self):
        """PROVIDER_OPENCODE should be an OpenAIProvider."""
        assert isinstance(PROVIDER_OPENCODE, OpenAIProvider)

    def test_opencode_catalog_excludes_expired_free_models(self):
        """Expired promotions and unsupported IDs stay out of the catalog."""
        model_ids = {model.id for model in OPENCODE_MODELS}
        assert "deepseek-v4-flash-free" not in model_ids
        assert "nemotron-3-super-free" not in model_ids

    def test_kilo_catalog_contains_current_free_models(self):
        """Kilo's catalog keeps the currently published free routes."""
        model_ids = {model.id for model in KILO_MODELS if model.is_free}
        assert {
            "kilo-auto/free",
            "nvidia/nemotron-3-ultra-550b-a55b:free",
            "nvidia/nemotron-3-super-120b-a12b:free",
            "stepfun/step-3.7-flash:free",
        } <= model_ids
        assert "poolside/laguna-m.1:free" not in model_ids
        assert "poolside/laguna-xs.2:free" not in model_ids
        assert "nex-agi/nex-n2-pro:free" not in model_ids

    def test_opencode_provider_key_attributes(self):
        """Provider-level attributes should be correctly set."""
        assert PROVIDER_OPENCODE.id == "opencode"
        assert PROVIDER_OPENCODE.api_key_prefix == ""
        assert PROVIDER_OPENCODE.require_api_key is False
        assert PROVIDER_OPENCODE.freeze_url is False
        assert PROVIDER_OPENCODE.base_url == "https://opencode.ai/zen/v1"
        assert (
            PROVIDER_OPENCODE.base_url
            == PROVIDER_OPENCODE.meta["base_url_options"][0]["value"]
        )

    def test_opencode_provider_meta_base_url_options(self):
        """meta should contain two base_url_options for endpoint switching."""
        meta = PROVIDER_OPENCODE.meta
        assert "base_url_options" in meta
        urls = meta["base_url_options"]
        assert len(urls) == 2
        assert urls[0]["label"] == "OpenCode"
        assert urls[0]["value"] == "https://opencode.ai/zen/v1"
        assert urls[1]["label"] == "OpenCode Go"
        assert urls[1]["value"] == "https://opencode.ai/zen/go/v1"

    def test_opencode_models_non_empty_and_unique(self):
        """Models list is non-empty with unique IDs."""
        assert len(OPENCODE_MODELS) > 0
        model_ids = [m.id for m in OPENCODE_MODELS]
        assert len(model_ids) == len(set(model_ids))

    def test_opencode_models_have_required_fields(self):
        """Every model has required fields set."""
        for m in OPENCODE_MODELS:
            assert m.id, "Model must have an id"
            assert m.name, "Model must have a name"
            assert isinstance(m.supports_image, bool)
            assert isinstance(m.supports_video, bool)

    def test_opencode_models_probe_source(self):
        """All models should have probe_source='documentation'."""
        for m in OPENCODE_MODELS:
            assert m.probe_source == "documentation"

    def test_opencode_models_all_free(self):
        """All OpenCode models should be marked as free."""
        assert all(
            m.is_free for m in OPENCODE_MODELS
        ), "All OPENCODE_MODELS should be free"

    def test_opencode_registered_in_provider_manager(self):
        """opencode provider should be registerable via built-in init."""
        mgr = ProviderManager()
        assert PROVIDER_OPENCODE.id in mgr.builtin_providers
        provider = mgr.builtin_providers[PROVIDER_OPENCODE.id]
        assert provider.id == PROVIDER_OPENCODE.id
        assert isinstance(provider, OpenAIProvider)

    def test_get_info_returns_all_models(self):
        """get_info() should return the maintained OpenCode models."""
        import asyncio

        provider = PROVIDER_OPENCODE.model_copy()
        info = asyncio.run(provider.get_info())
        assert len(info.models) == len(OPENCODE_MODELS)
        model_ids = {m.id for m in info.models}
        assert model_ids == {m.id for m in OPENCODE_MODELS}


class TestOpenCodeSessionHeader:
    """OpenCode Go rejects requests without ``x-opencode-session``.

    See QwenPaw#7599: selecting the "OpenCode Go" endpoint that the provider
    itself offers fails with ``400 MissingSessionID`` because QwenPaw never
    sends the header.
    """

    HEADER = "x-opencode-session"

    def test_connection_client_sends_a_session_header(self):
        """``_client()`` backs check_connection / check_model_connection."""
        provider = PROVIDER_OPENCODE.model_copy(
            update={"base_url": "https://opencode.ai/zen/go/v1"},
        )

        client = provider._client()

        assert client.default_headers[self.HEADER]

    async def test_chat_model_sends_a_session_header(self, monkeypatch):
        """Real generation requests go through the chat model instance.

        ``OpenAIChatModelCompat`` forwards its ``default_headers`` as
        ``extra_headers`` on every call, so assert at that boundary.
        """
        captured: dict = {}

        async def fake_call_api(self, *args, **kwargs):
            del self, args
            captured.update(kwargs)
            return "ok"

        monkeypatch.setattr(OpenAIChatModel, "_call_api", fake_call_api)
        provider = PROVIDER_OPENCODE.model_copy(
            update={"base_url": "https://opencode.ai/zen/go/v1"},
        )
        model = provider.get_chat_model_instance(OPENCODE_MODELS[0].id)

        await model._call_api(OPENCODE_MODELS[0].id, [])

        assert captured["extra_headers"][self.HEADER]

    async def test_chat_model_session_is_stable_across_calls(
        self,
        monkeypatch,
    ):
        """Every request of one conversation carries the same id."""
        seen: list = []
        header = self.HEADER

        async def fake_call_api(self, *args, **kwargs):
            del self, args
            seen.append(kwargs["extra_headers"][header])
            return "ok"

        monkeypatch.setattr(OpenAIChatModel, "_call_api", fake_call_api)
        provider = PROVIDER_OPENCODE.model_copy()
        model = provider.get_chat_model_instance(OPENCODE_MODELS[0].id)

        await model._call_api(OPENCODE_MODELS[0].id, [])
        await model._call_api(OPENCODE_MODELS[0].id, [])

        assert len(seen) == 2
        assert seen[0] == seen[1]

    def test_session_id_is_stable_within_one_built_object(self):
        """One conversation must keep one id, or caching is defeated."""
        provider = PROVIDER_OPENCODE.model_copy()

        client = provider._client()

        assert (
            client.default_headers[self.HEADER]
            == client.default_headers[self.HEADER]
        )

    def test_separate_builds_get_separate_sessions(self):
        """A later build is a different conversation."""
        provider = PROVIDER_OPENCODE.model_copy()

        first = provider._build_default_headers()[self.HEADER]
        second = provider._build_default_headers()[self.HEADER]

        assert first != second

    def test_user_supplied_session_header_is_preserved(self):
        """An explicit custom header always wins over the generated one."""
        provider = PROVIDER_OPENCODE.model_copy(
            update={"custom_headers": {"X-OpenCode-Session": "mine"}},
        )

        headers = provider._build_default_headers()

        assert headers["X-OpenCode-Session"] == "mine"
        assert self.HEADER not in headers

    def test_header_is_sent_on_the_default_endpoint_too(self):
        """The docs recommend the header for caching on both endpoints."""
        provider = PROVIDER_OPENCODE.model_copy()

        assert provider._build_default_headers()[self.HEADER]

    def test_other_openai_providers_are_unaffected(self):
        """The header is OpenCode-specific and must not leak elsewhere."""
        provider = OpenAIProvider(
            id="plain",
            name="Plain",
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
        )

        assert not provider._build_default_headers()
