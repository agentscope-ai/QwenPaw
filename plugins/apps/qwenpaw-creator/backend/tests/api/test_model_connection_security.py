# -*- coding: utf-8 -*-
"""Creator connection probes keep stored credentials on approved endpoints."""
# pylint: disable=protected-access

from types import SimpleNamespace

import pytest

from api import model_routes
from domain.errors import ValidationError
from schemas.models import ModelConnectionTestRequest, OssConfig


def _config():
    config = model_routes._defaults()
    config.llm.base_url = "https://approved.example/v1"
    config.llm.api_key = "creator-stored-secret"
    config.llm.model_name = "approved-model"
    config.llm.protocol = "OpenAI 协议"
    return config


def _request(**updates):
    payload = {
        "type": "llm",
        "base_url": "https://approved.example/v1",
        "api_key": model_routes.SECRET_MASK,
        "model_name": "approved-model",
        "protocol": "OpenAI 协议",
        "config_section": "llm",
        "credential_section": "llm",
    }
    payload.update(updates)
    return ModelConnectionTestRequest(**payload)


def test_stored_creator_key_rejects_endpoint_override_before_probe() -> None:
    with pytest.raises(ValidationError) as caught:
        model_routes._resolve_connection_selection(
            _request(base_url="https://attacker.example/collect"),
            _config(),
            None,
        )

    assert "Base URL" in str(caught.value)
    assert "creator-stored-secret" not in str(caught.value)


def test_new_request_key_can_test_an_unsaved_endpoint() -> None:
    selected = model_routes._resolve_connection_selection(
        _request(
            base_url="https://new.example/v1",
            api_key="new-request-key",
        ),
        _config(),
        None,
    )

    assert selected.base_url == "https://new.example/v1"
    assert selected.api_key == "new-request-key"


def test_host_provider_key_is_resolved_only_for_provider_endpoint() -> None:
    provider = SimpleNamespace(
        base_url="https://provider.example/v1",
        api_key="host-provider-secret",
        require_api_key=True,
    )
    manager = SimpleNamespace(
        get_provider=lambda provider_id: (
            provider if provider_id == "approved-provider" else None
        ),
    )
    config = _config()
    config.llm.host_provider_id = "approved-provider"
    config.llm.base_url = provider.base_url

    selected = model_routes._resolve_connection_selection(
        _request(
            base_url=provider.base_url,
            host_provider_id="approved-provider",
        ),
        config,
        manager,
    )
    assert selected.api_key == "host-provider-secret"

    with pytest.raises(ValidationError):
        model_routes._resolve_connection_selection(
            _request(
                base_url="https://attacker.example/collect",
                host_provider_id="approved-provider",
            ),
            config,
            manager,
        )


def test_stored_key_reuse_requires_saved_relationship() -> None:
    config = _config()
    config.video.base_url = "https://approved-video.example/v1"
    config.video.model_name = "approved-video-model"
    config.video.reuse_llm_key = False
    body = _request(
        type="video",
        config_section="video",
        credential_section="llm",
        base_url=config.video.base_url,
        model_name=config.video.model_name,
    )

    with pytest.raises(ValidationError):
        model_routes._resolve_connection_selection(body, config, None)

    config.video.reuse_llm_key = True
    selected = model_routes._resolve_connection_selection(body, config, None)
    assert selected.api_key == "creator-stored-secret"


def test_stored_oss_key_is_bound_to_endpoint_and_bucket() -> None:
    persisted = OssConfig(
        access_key_id="approved-access-key",
        access_key_secret="storage-secret-must-not-leak",
        endpoint="https://approved-oss.example",
        bucket="approved-bucket",
    )
    selected = model_routes._resolve_oss_probe(
        OssConfig(
            access_key_id=persisted.access_key_id,
            access_key_secret=model_routes.SECRET_MASK,
            endpoint=persisted.endpoint,
            bucket=persisted.bucket,
        ),
        persisted,
    )
    assert selected.access_key_secret == "storage-secret-must-not-leak"

    for changed in (
        {"endpoint": "https://attacker.example/collect"},
        {"bucket": "attacker-bucket"},
    ):
        body = OssConfig(
            access_key_id=persisted.access_key_id,
            access_key_secret=model_routes.SECRET_MASK,
            endpoint=persisted.endpoint,
            bucket=persisted.bucket,
        ).model_copy(update=changed)
        with pytest.raises(ValidationError) as caught:
            model_routes._resolve_oss_probe(body, persisted)
        assert "storage-secret-must-not-leak" not in str(caught.value)


def test_secret_returning_routes_are_not_registered(app, api_request) -> None:
    first = api_request(app, "GET", "/models/real-api-key/llm")
    second = api_request(
        app,
        "GET",
        "/models/host-provider/approved-provider/api-key",
    )

    assert first.status_code == 404
    assert second.status_code == 404
