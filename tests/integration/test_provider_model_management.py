# -*- coding: utf-8 -*-
"""Per-model management on a custom provider.

Covers the model-level endpoints of ``app/routers/providers.py`` that the
existing provider tests do not reach: adding a model to a provider,
writing per-model generation config (max_tokens, thinking budget,
generate_kwargs), removing a model, and the 404/400 branches for unknown
providers and unknown model ids.

Every mutation is verified by reading the provider back and inspecting
the model entry, so a write that is accepted but not persisted fails the
test. All work happens on a provider this module creates and deletes, so
no shared provider state is disturbed and no external API is contacted.

API endpoints:
  - GET    /api/models
  - POST   /api/models/custom-providers
  - DELETE /api/models/custom-providers/{provider_id}
  - GET    /api/models/custom-providers
  - POST   /api/models/{provider_id}/models
  - PUT    /api/models/{provider_id}/models/{model_id}/config
  - DELETE /api/models/{provider_id}/models/{model_id}
"""
from __future__ import annotations

import pytest
from helpers import default_http_timeout

_HTTP_TIMEOUT = default_http_timeout(30.0)

_PROVIDER_ID = "integ-model-mgmt-provider"
# A closed local port: the provider is never actually called, so no
# outbound request can succeed even if something tried.
_BASE_URL = "http://127.0.0.1:9/v1"


@pytest.fixture
def provider(app_server):
    """Create a throwaway custom provider; remove it afterwards."""
    app_server.api_request(
        "DELETE",
        f"/api/models/custom-providers/{_PROVIDER_ID}",
        timeout=_HTTP_TIMEOUT,
    )
    created = app_server.api_request(
        "POST",
        "/api/models/custom-providers",
        json={
            "id": _PROVIDER_ID,
            "name": "Integration Model Mgmt",
            "default_base_url": _BASE_URL,
            "chat_model": "OpenAIChatModel",
            "models": [{"id": "base-model", "name": "Base Model"}],
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert created.status_code in (200, 201), created.text
    yield _PROVIDER_ID
    app_server.api_request(
        "DELETE",
        f"/api/models/custom-providers/{_PROVIDER_ID}",
        timeout=_HTTP_TIMEOUT,
    )


def _models_of(app_server, provider_id: str) -> dict[str, dict]:
    """Return the provider's models keyed by model id.

    Custom-provider models are reported under ``extra_models``; the
    ``models`` list holds the built-in catalogue, which is empty here.
    """
    # There is no GET /custom-providers: the catalogue lives at GET
    # /api/models, which includes custom providers.
    resp = app_server.api_request(
        "GET",
        "/api/models",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    for item in resp.json():
        if item.get("id") == provider_id:
            entries = list(item.get("models") or []) + list(
                item.get("extra_models") or [],
            )
            return {m["id"]: m for m in entries}
    raise AssertionError(f"provider {provider_id} not found in listing")


# ============================ A. add / remove ==============================


@pytest.mark.integration
@pytest.mark.p1
def test_add_model_then_remove_it(
    app_server,
    provider,  # pylint: disable=redefined-outer-name
):
    """A model added to a provider appears, then disappears on delete.

    Test purpose:
      - Cover add_model_endpoint and remove_model_endpoint, verifying
        the provider's model list changes in both directions rather
        than trusting the 201/200 alone.

    Test flow:
      1. POST a new model with multimodal flags set.
      2. Read the provider back and assert the model and its flags.
      3. DELETE the model and assert it is gone.
    """
    added = app_server.api_request(
        "POST",
        f"/api/models/{provider}/models",
        json={
            "id": "integ-added-model",
            "name": "Integ Added Model",
            "supports_multimodal": True,
            "supports_image": True,
            "supports_video": False,
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert added.status_code == 201, added.text

    models = _models_of(app_server, provider)
    assert "integ-added-model" in models, list(models)
    entry = models["integ-added-model"]
    assert entry["supports_image"] is True, entry
    assert entry["supports_video"] is False, entry

    removed = app_server.api_request(
        "DELETE",
        f"/api/models/{provider}/models/integ-added-model",
        timeout=_HTTP_TIMEOUT,
    )
    assert removed.status_code == 200, removed.text
    assert "integ-added-model" not in _models_of(app_server, provider)


@pytest.mark.integration
@pytest.mark.p2
def test_add_model_to_unknown_provider_returns_404(app_server):
    """Adding a model to a provider that does not exist is a 404.

    Test purpose:
      - Cover add_model_endpoint's ValueError path from the manager.
    """
    resp = app_server.api_request(
        "POST",
        "/api/models/integ-no-such-provider-5512/models",
        json={"id": "m1", "name": "M1"},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
@pytest.mark.p2
def test_remove_unknown_model_is_idempotent(
    app_server,
    provider,  # pylint: disable=redefined-outer-name
):
    """Removing a model that is not present leaves the provider intact.

    Test purpose:
      - Cover remove_model_endpoint for a model id the provider never
        had: the delete is idempotent, so it must succeed without
        disturbing the models that do exist.
    """
    before = set(_models_of(app_server, provider))
    resp = app_server.api_request(
        "DELETE",
        f"/api/models/{provider}/models/integ-not-present-model",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    assert (
        set(_models_of(app_server, provider)) == before
    ), "an idempotent delete changed the model list"


# =========================== B. per-model config ===========================


@pytest.mark.integration
@pytest.mark.p1
def test_model_config_persists_generation_settings(
    app_server,
    provider,  # pylint: disable=redefined-outer-name
):
    """Per-model generation settings are stored on the model entry.

    Test purpose:
      - Cover configure_model / update_model_config: max_tokens,
        max_input_length and generate_kwargs must survive the round trip
        so they can override provider-level defaults at request time.

    Test flow:
      1. PUT a config for the provider's base model.
      2. Read the provider back and assert each field landed.
    """
    resp = app_server.api_request(
        "PUT",
        f"/api/models/{provider}/models/base-model/config",
        json={
            "max_tokens": 4096,
            "max_input_length": 32768,
            "generate_kwargs": {"temperature": 0.25},
            "relay_reasoning": True,
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text

    entry = _models_of(app_server, provider)["base-model"]
    assert entry["max_tokens"] == 4096, entry
    assert entry["max_input_length"] == 32768, entry
    assert entry["generate_kwargs"].get("temperature") == 0.25, entry
    assert entry["relay_reasoning"] is True, entry


@pytest.mark.integration
@pytest.mark.p2
def test_model_config_thinking_fields_persist(
    app_server,
    provider,  # pylint: disable=redefined-outer-name
):
    """Thinking-related settings are stored alongside the model.

    Test purpose:
      - Cover the thinking_enabled / thinking_budget / reasoning_effort
        arms of update_model_config, which are separate fields from the
        token limits above.
    """
    resp = app_server.api_request(
        "PUT",
        f"/api/models/{provider}/models/base-model/config",
        json={
            "thinking_enabled": True,
            "thinking_budget": 2048,
            "reasoning_effort": "high",
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text

    entry = _models_of(app_server, provider)["base-model"]
    assert entry["thinking_enabled"] is True, entry
    assert entry["thinking_budget"] == 2048, entry
    assert entry["reasoning_effort"] == "high", entry


@pytest.mark.integration
@pytest.mark.p2
def test_model_config_unknown_model_returns_404(
    app_server,
    provider,  # pylint: disable=redefined-outer-name
):
    """Configuring a model the provider does not have is a 404.

    Test purpose:
      - Cover configure_model's error branch, which must not create the
        model implicitly.
    """
    resp = app_server.api_request(
        "PUT",
        f"/api/models/{provider}/models/integ-absent-model/config",
        json={"max_tokens": 128},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
@pytest.mark.p2
def test_model_config_unknown_provider_returns_404(app_server):
    """Configuring a model on an unknown provider is a 404.

    Test purpose:
      - Cover the provider-lookup failure ahead of the model lookup.
    """
    resp = app_server.api_request(
        "PUT",
        "/api/models/integ-no-such-provider-9931/models/m1/config",
        json={"max_tokens": 128},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, resp.text
