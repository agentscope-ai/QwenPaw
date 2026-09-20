# -*- coding: utf-8 -*-
"""Hub token defaults and management limits share resolver provenance."""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.hub.model_service import provider_setup
from qwenpaw.hub.model_service.catalog import ModelCatalog
from qwenpaw.hub.model_service.routes import governance_router
from qwenpaw.hub.model_service.storage import GovernanceStore
from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.provider import ModelInfo


@pytest.mark.parametrize(
    ("model_id", "expected", "known"),
    [
        ("review-unknown-model", 131_072, False),
        ("gpt-4.1", 1_047_576, True),
        ("qwen-max", 131_072, True),
    ],
)
def test_token_defaults_resolve_real_presets(model_id, expected, known):
    result = provider_setup.model_token_defaults(
        model_id,
        {"id": "test", "name": "Test", "provider_id": "openai"},
    )

    assert result["input_token_limit"] == expected
    assert result["input_limit_known"] is known


@pytest.mark.parametrize(
    "field",
    [
        "max_input_length",
        "max_input_length_auto_detected",
        "max_input_length_catalog",
    ],
)
def test_real_128k_window_is_known(monkeypatch, field):
    model = ModelInfo(
        id="review-unknown-model",
        name="Unknown",
        max_output_length=8192,
        **{field: 131_072},
    )
    provider = OpenAIProvider(id="test", name="Test", models=[model])
    monkeypatch.setattr(
        provider_setup,
        "model_provider",
        lambda _model, _connection: provider,
    )

    assert provider_setup.model_token_defaults(model.id, {}) == {
        "input_token_limit": 131_072,
        "input_limit_known": True,
        "output_token_limit": 8192,
        "output_limit_known": True,
    }


@pytest.fixture
def model_client(tmp_path):
    """Exercise real governance routes with a temporary SQLite catalog."""
    store = GovernanceStore(tmp_path / "hub.db")
    with store.connect() as db:
        db.execute(
            "INSERT INTO hub_model_connections (id, value_json) "
            "VALUES (?, ?)",
            ("test", '{"name": "Test"}'),
        )
    catalog = ModelCatalog(store, None)
    app = FastAPI()
    app.include_router(
        governance_router(
            store=store,
            catalog=catalog,
            budgets=None,
            gateway=None,
            invitations=None,
            auth=None,
            require_user=lambda: None,
            require_admin=lambda: None,
            audit=AsyncMock(),
        ),
    )
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize(
    ("model_id", "known", "limit", "status"),
    [
        ("review-unknown-model", False, 262_144, 200),
        ("gpt-4.1", True, 2_000_000, 409),
    ],
)
def test_management_endpoints_enforce_only_known_limits(
    model_client,
    model_id,
    known,
    limit,
    status,
):
    prefix = "/api/hub/admin"
    defaults = model_client.get(
        f"{prefix}/model-connections/test/token-defaults",
        params={"model_id": model_id},
    )
    assert defaults.status_code == 200
    assert defaults.json()["input_limit_known"] is known

    body = {
        "connection_id": "test",
        "upstream_model": model_id,
        "name": "Test",
    }
    created = model_client.post(f"{prefix}/models", json=body)
    assert created.status_code == 200
    resource_id = created.json()["id"]
    body["input_token_limit"] = limit
    assert (
        model_client.post(
            f"{prefix}/models",
            json=body,
        ).status_code
        == status
    )
    body["revision"] = 1
    updated = model_client.put(
        f"{prefix}/models/{resource_id}",
        json=body,
    )
    assert updated.status_code == status
    rows = model_client.get(f"{prefix}/models").json()
    row = next(item for item in rows if item["id"] == resource_id)
    expected = limit if status == 200 else defaults.json()["input_token_limit"]
    assert row["input_token_limit"] == expected
