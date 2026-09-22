# -*- coding: utf-8 -*-
"""Unit tests for the OpenCode built-in provider."""
# pylint: disable=protected-access

from qwenpaw.providers.provider_catalog import (
    KILO_MODELS,
)
from qwenpaw.providers.provider_manager import (
    OPENCODE_MODELS,
    PROVIDER_OPENCODE,
    ProviderManager,
)
from qwenpaw.providers.adapters.request_context import (
    model_session,
    session_header,
)
from qwenpaw.providers.openai_provider import OpenAIProvider


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
        assert PROVIDER_OPENCODE.require_api_key is True
        assert PROVIDER_OPENCODE.enabled is False
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

    def test_get_info_keeps_unranked_free_models_discoverable(self):
        """Unranked free models require manual selection."""
        import asyncio

        provider = PROVIDER_OPENCODE.model_copy()
        info = asyncio.run(provider.get_info())
        assert info.models == []
        model_ids = {m.id for m in info.discovered_models}
        assert model_ids >= {m.id for m in OPENCODE_MODELS}
        assert all(m.recommendation_reason for m in info.discovered_models)


class TestOpenCodeSessionHeaderOnClient:
    """Connection tests must carry ``x-opencode-session`` like inference.

    ``prepare_request`` adds the header to model calls, but
    ``check_connection`` / ``check_model_connection`` build their own SDK
    client through ``_client()``; without the header OpenCode Go rejects
    them with ``400 MissingSessionID`` (QwenPaw#7599).
    """

    HEADER = "x-opencode-session"

    @staticmethod
    def _go_provider(**update):
        return PROVIDER_OPENCODE.model_copy(
            update={"base_url": "https://opencode.ai/zen/go/v1", **update},
        )

    def test_connection_client_carries_the_session_header(self):
        provider = self._go_provider()

        client = provider._client()

        assert client.default_headers[self.HEADER]

    def test_client_uses_the_same_session_as_inference(self):
        """One id per provider instance outside a conversation."""
        provider = self._go_provider()

        assert provider._client().default_headers[self.HEADER] == (
            session_header(provider._request_session)
        )

    def test_client_follows_the_conversation_scope(self):
        """Inside a turn the client carries the conversation's id."""
        provider = self._go_provider()
        context = {"session_id": "session-a", "agent_id": "agent-1"}

        with model_session(context, provider._request_session):
            scoped = provider._client().default_headers[self.HEADER]
            expected = session_header(provider._request_session)
        unscoped = provider._client().default_headers[self.HEADER]

        assert scoped == expected
        assert scoped != unscoped

    def test_explicit_custom_header_is_preserved(self):
        provider = self._go_provider(
            custom_headers={"X-OpenCode-Session": "mine"},
        )

        headers = provider._build_default_headers()

        assert headers["X-OpenCode-Session"] == "mine"
        assert self.HEADER not in headers

    def test_blank_custom_header_is_replaced(self):
        """The console persists empty values; an empty header still 400s."""
        provider = self._go_provider(
            custom_headers={"X-OpenCode-Session": "  "},
        )

        headers = provider._build_default_headers()

        assert [k for k in headers if k.lower() == self.HEADER] == [
            self.HEADER,
        ]
        assert headers[self.HEADER].strip()

    def test_providers_without_a_session_header_are_unaffected(self):
        provider = OpenAIProvider(
            id="plain",
            name="Plain",
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
        )

        assert not provider._build_default_headers()
