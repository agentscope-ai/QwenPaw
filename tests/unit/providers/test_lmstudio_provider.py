# -*- coding: utf-8 -*-
"""Tests for LM Studio provider model listing behavior."""

from qwenpaw.providers.lmstudio_provider import LMStudioProvider


async def test_model_check_reports_listing_failure(monkeypatch) -> None:
    provider = LMStudioProvider(
        id="lmstudio",
        name="LM Studio",
        base_url="http://localhost:1234/v1",
        api_key="EMPTY",
    )

    async def fetch_models(_self, timeout=5):
        raise OSError("server unavailable")

    monkeypatch.setattr(LMStudioProvider, "fetch_models", fetch_models)

    result = await provider.check_model_connection("local-model")

    assert result.success is False
    assert result.error_kind == "transient_error"
    assert result.verification == "provider_only"
    assert "server unavailable" in result.message
