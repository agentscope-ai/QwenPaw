# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from copaw.providers import store
from copaw.providers.models import (
    CustomProviderData,
    ModelSlotConfig,
    ProvidersData,
)


def test_create_custom_provider_persists_affinity_settings(
    monkeypatch,
) -> None:
    data = ProvidersData()
    monkeypatch.setattr(store, "load_providers_json", lambda: data)
    monkeypatch.setattr(store, "save_providers_json", lambda _data: None)
    monkeypatch.setattr(store, "register_custom_provider", lambda _cpd: None)

    out = store.create_custom_provider(
        provider_id="custom-vllm",
        name="Custom vLLM",
        default_base_url="http://127.0.0.1:8000/v1",
        extra_headers={"x-user-header": "abc"},
        enable_session_affinity=True,
        session_affinity_header="x-affinity",
    )

    cpd = out.custom_providers["custom-vllm"]
    assert cpd.extra_headers == {"x-user-header": "abc"}
    assert cpd.enable_session_affinity is True
    assert cpd.session_affinity_header == "x-affinity"


def test_update_provider_settings_updates_custom_affinity_fields(
    monkeypatch,
) -> None:
    data = ProvidersData(
        custom_providers={
            "custom-vllm": CustomProviderData(
                id="custom-vllm",
                name="Custom vLLM",
                default_base_url="http://127.0.0.1:8000/v1",
                base_url="http://127.0.0.1:8000/v1",
                api_key="k",
            ),
        },
    )
    monkeypatch.setattr(store, "load_providers_json", lambda: data)
    monkeypatch.setattr(store, "save_providers_json", lambda _data: None)
    monkeypatch.setattr(store, "register_custom_provider", lambda _cpd: None)

    out = store.update_provider_settings(
        "custom-vllm",
        extra_headers={"x-foo": "bar"},
        enable_session_affinity=True,
        session_affinity_header="x-session-affinity",
    )
    cpd = out.custom_providers["custom-vllm"]
    assert cpd.extra_headers == {"x-foo": "bar"}
    assert cpd.enable_session_affinity is True
    assert cpd.session_affinity_header == "x-session-affinity"


def test_create_custom_provider_rejects_invalid_header_name(
    monkeypatch,
) -> None:
    data = ProvidersData()
    monkeypatch.setattr(store, "load_providers_json", lambda: data)
    monkeypatch.setattr(store, "save_providers_json", lambda _data: None)
    monkeypatch.setattr(store, "register_custom_provider", lambda _cpd: None)

    with pytest.raises(ValueError, match="Invalid header name"):
        store.create_custom_provider(
            provider_id="custom-vllm",
            name="Custom vLLM",
            default_base_url="http://127.0.0.1:8000/v1",
            extra_headers={"bad header": "value"},
        )


def test_create_custom_provider_rejects_duplicate_header_names(
    monkeypatch,
) -> None:
    data = ProvidersData()
    monkeypatch.setattr(store, "load_providers_json", lambda: data)
    monkeypatch.setattr(store, "save_providers_json", lambda _data: None)
    monkeypatch.setattr(store, "register_custom_provider", lambda _cpd: None)

    with pytest.raises(ValueError, match="Duplicate header name"):
        store.create_custom_provider(
            provider_id="custom-vllm",
            name="Custom vLLM",
            default_base_url="http://127.0.0.1:8000/v1",
            extra_headers={
                "X-Affinity": "a",
                "x-affinity": "b",
            },
        )


def test_create_custom_provider_rejects_invalid_header_value(
    monkeypatch,
) -> None:
    data = ProvidersData()
    monkeypatch.setattr(store, "load_providers_json", lambda: data)
    monkeypatch.setattr(store, "save_providers_json", lambda _data: None)
    monkeypatch.setattr(store, "register_custom_provider", lambda _cpd: None)

    with pytest.raises(ValueError, match="control characters"):
        store.create_custom_provider(
            provider_id="custom-vllm",
            name="Custom vLLM",
            default_base_url="http://127.0.0.1:8000/v1",
            extra_headers={"x-affinity": "bad\r\nvalue"},
        )


def test_get_active_llm_config_fallbacks_for_invalid_persisted_affinity_fields(
    monkeypatch,
) -> None:
    data = ProvidersData(
        custom_providers={
            "custom-vllm": CustomProviderData(
                id="custom-vllm",
                name="Custom vLLM",
                default_base_url="http://127.0.0.1:8000/v1",
                base_url="http://127.0.0.1:8000/v1",
                api_key="k",
                extra_headers={"bad header": "value"},
                enable_session_affinity=True,
                session_affinity_header="bad header",
            ),
        },
        active_llm=ModelSlotConfig(provider_id="custom-vllm", model="qwen"),
    )

    monkeypatch.setattr(store, "load_providers_json", lambda: data)

    cfg = store.get_active_llm_config()

    assert cfg is not None
    assert cfg.extra_headers == {}
    assert cfg.session_affinity_header == "x-session-affinity"
    assert cfg.enable_session_affinity is True
