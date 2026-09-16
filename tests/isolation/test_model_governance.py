# -*- coding: utf-8 -*-
"""模型管理入口与凭据响应边界隔离测试。"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.access.agent_repository import AgentResourceRole
from qwenpaw.access import dependencies as access_dependencies
from qwenpaw.app.routers import local_models, provider_oauth, providers
from qwenpaw.identity.models import PlatformRole
from qwenpaw.providers.provider import ModelInfo, Provider, ProviderInfo

SECRET = "synthetic-secret-never-return"
NEW_SECRET = "synthetic-replacement-never-return"


def assert_secret_absent(response, secret: str) -> None:
    assert secret not in response.text


class SyntheticProvider(Provider):
    def get_chat_model_instance(self, model_id: str, **kwargs):
        raise NotImplementedError

    async def check_connection(self, timeout: float = 5) -> tuple[bool, str]:
        return False, f"connection failed for {self.base_url}: {self.api_key}"

    async def fetch_models(self, timeout: float = 5):
        return []

    async def check_model_connection(
        self,
        model_id: str,
        timeout: float = 5,
    ) -> tuple[bool, str]:
        return False, f"model error: {self.api_key}"


class MemoryProviderManager:
    def __init__(self) -> None:
        self.provider = SyntheticProvider(
            id="synthetic",
            name="Synthetic",
            base_url=(
                f"https://user:{SECRET}@[2001:db8::1]:8443/v1"
                f"?key={SECRET}&sig={SECRET}&signature={SECRET}"
                f"&label={SECRET}&region=cn#credential={SECRET}"
            ),
            api_key=SECRET,
            custom_headers={"Authorization": f"Bearer {SECRET}"},
            generate_kwargs={
                "auth_token": SECRET,
                "tools": [{"name": "safe", "secret": SECRET}],
            },
            meta={
                "credential_url": f"https://example.invalid/?key={SECRET}",
                "display_note": SECRET,
            },
        )
        self.update_count = 0

    async def list_provider_info(self):
        return [ProviderInfo(**self.provider.model_dump())]

    def get_provider(self, provider_id: str):
        return self.provider if provider_id == self.provider.id else None

    def update_provider(self, provider_id: str, config: dict) -> bool:
        provider = self.get_provider(provider_id)
        if provider is None:
            return False
        provider.update_config(config)
        self.update_count += 1
        return True

    def get_active_model(self):
        return None

    async def get_provider_info(self, provider_id: str):
        provider = self.get_provider(provider_id)
        return ProviderInfo(**provider.model_dump()) if provider else None


class MemoryLocalManager:
    def get_config(self):
        return {"max_context_length": 32768, "port": None}


def _actor(role: PlatformRole) -> ActorContext:
    return ActorContext(
        user_id=uuid4(),
        actor_type=ActorType.USER,
        platform_role=role,
        admin_mode=False,
        request_id="model-governance-test",
    )


def _client(role: PlatformRole) -> tuple[TestClient, MemoryProviderManager]:
    manager = MemoryProviderManager()
    app = FastAPI()
    app.state.provider_manager = manager
    app.state.local_model_manager = MemoryLocalManager()

    @app.middleware("http")
    async def actor_middleware(request, call_next):
        request.state.actor = _actor(role)
        return await call_next(request)

    app.include_router(providers.router)
    app.include_router(local_models.router)
    app.include_router(provider_oauth.router)
    return TestClient(app), manager


@pytest.fixture(autouse=True)
def _multi_user(monkeypatch):
    monkeypatch.setattr(providers, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(local_models, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(provider_oauth, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(access_dependencies, "is_multi_user_enabled", lambda: True)


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("put", "/models/synthetic/config", {"base_url": "https://changed.invalid"}),
        ("get", "/models/active?scope=global", None),
        ("get", "/local-models/config", None),
        ("post", "/providers/openrouter/oauth/start", None),
    ],
)
def test_member_cannot_reach_model_management_or_mutate(
    method: str,
    path: str,
    json_body: dict | None,
) -> None:
    client, manager = _client(PlatformRole.MEMBER)
    before = manager.provider.model_dump()

    response = client.request(method, path, json=json_body)

    assert response.status_code == 403
    assert manager.provider.model_dump() == before
    assert manager.update_count == 0


def _prepare_agent_model_write(monkeypatch, role: AgentResourceRole):
    client, manager = _client(PlatformRole.MEMBER)
    manager.provider.models = [ModelInfo(id="allowed", name="Allowed")]
    manager.maybe_probe_multimodal = lambda *_args: None
    saved = {
        "active_model": {"provider_id": "synthetic", "model": "original"},
    }
    private_chat = {
        "model_override": {"provider_id": "synthetic", "model": "private"},
    }

    async def get_agent(request, agent_id=None):
        request.state.agent_access = SimpleNamespace(
            role=role,
            historical_read_only=False,
        )
        return SimpleNamespace(agent_id=agent_id)

    def load_agent(_agent_id):
        return SimpleNamespace(active_model=saved["active_model"])

    def save_agent(_agent_id, config):
        saved["active_model"] = config.active_model.model_dump()

    monkeypatch.setattr(providers, "get_agent_for_request", get_agent)
    monkeypatch.setattr(providers, "load_agent_config", load_agent)
    monkeypatch.setattr(providers, "save_agent_config", save_agent)
    monkeypatch.setattr(providers, "schedule_agent_reload", lambda *_args: None)
    return client, saved, private_chat


def test_public_agent_user_cannot_change_shared_agent_default(monkeypatch) -> None:
    client, saved, private_chat = _prepare_agent_model_write(
        monkeypatch,
        AgentResourceRole.USER,
    )
    before_config = dict(saved["active_model"])
    before_private = dict(private_chat["model_override"])

    response = client.put(
        "/models/active",
        json={
            "scope": "agent",
            "agent_id": "public-agent",
            "provider_id": "synthetic",
            "model": "allowed",
        },
    )

    assert response.status_code == 403
    assert saved["active_model"] == before_config
    assert private_chat["model_override"] == before_private


@pytest.mark.parametrize(
    "role",
    [AgentResourceRole.OWNER, AgentResourceRole.COLLABORATOR],
)
def test_agent_config_editor_can_change_default_without_touching_private_chat(
    monkeypatch,
    role: AgentResourceRole,
) -> None:
    client, saved, private_chat = _prepare_agent_model_write(monkeypatch, role)
    before_private = dict(private_chat["model_override"])

    response = client.put(
        "/models/active",
        json={
            "scope": "agent",
            "agent_id": "shared-agent",
            "provider_id": "synthetic",
            "model": "allowed",
        },
    )

    assert response.status_code == 200
    assert saved["active_model"] == {
        "provider_id": "synthetic",
        "model": "allowed",
    }
    assert private_chat["model_override"] == before_private


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/models"),
        ("get", "/local-models/config"),
        ("post", "/providers/openrouter/oauth/start"),
    ],
)
def test_admin_can_reach_model_management(method: str, path: str) -> None:
    client, _ = _client(PlatformRole.ADMIN)
    response = client.request(method, path)
    assert response.status_code < 400


def test_provider_catalog_is_compatible_but_never_returns_secrets() -> None:
    for role in (PlatformRole.ADMIN, PlatformRole.MEMBER):
        client, _ = _client(role)
        response = client.get("/models")
        assert response.status_code == 200
        assert response.json()[0]["api_key"] == ""
        assert response.json()[0]["api_key_configured"] is True
        assert response.json()[0]["custom_headers"] == {}
        assert response.json()[0]["base_url"] == (
            "https://[2001:db8::1]:8443/v1"
            "?key=%5Bredacted%5D&sig=%5Bredacted%5D"
            "&signature=%5Bredacted%5D&label=%5Bredacted%5D&region=cn"
        )
        assert response.json()[0]["meta"]["display_note"] == "[redacted]"
        assert_secret_absent(response, SECRET)


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        (
            f"https://example.invalid/v1/{SECRET}/models",
            "https://example.invalid/v1/[redacted]/models",
        ),
        (
            f"example.invalid/v1/{SECRET}/models",
            "example.invalid/v1/[redacted]/models",
        ),
    ],
)
def test_provider_catalog_redacts_known_secret_from_every_base_url_path(
    base_url: str,
    expected: str,
) -> None:
    client, manager = _client(PlatformRole.MEMBER)
    manager.provider.base_url = base_url

    response = client.get("/models")

    assert response.status_code == 200
    assert response.json()[0]["base_url"] == expected
    assert_secret_absent(response, SECRET)


def test_save_response_and_connection_error_never_return_secrets() -> None:
    client, _ = _client(PlatformRole.ADMIN)

    saved = client.put(
        "/models/synthetic/config",
        json={"api_key": NEW_SECRET},
    )
    failed = client.post(
        "/models/synthetic/test",
        json={"api_key": NEW_SECRET},
    )

    assert saved.status_code == 200
    assert saved.json()["api_key"] == ""
    assert saved.json()["api_key_configured"] is True
    assert_secret_absent(saved, NEW_SECRET)
    assert_secret_absent(failed, NEW_SECRET)
    assert_secret_absent(failed, SECRET)


def test_secret_update_preserve_replace_clear_and_ignore_mask() -> None:
    client, manager = _client(PlatformRole.ADMIN)

    response = client.put(
        "/models/synthetic/config",
        json={"base_url": "https://one.invalid"},
    )
    assert response.status_code == 200
    assert manager.provider.api_key == SECRET

    response = client.put(
        "/models/synthetic/config",
        json={"api_key": NEW_SECRET},
    )
    assert response.status_code == 200
    assert manager.provider.api_key == NEW_SECRET

    response = client.put("/models/synthetic/config", json={"api_key": ""})
    assert response.status_code == 200
    assert manager.provider.api_key == NEW_SECRET

    response = client.put(
        "/models/synthetic/config",
        json={"api_key": "sk-******"},
    )
    assert response.status_code == 200
    assert manager.provider.api_key == NEW_SECRET

    response = client.put(
        "/models/synthetic/config",
        json={"clear_api_key": True},
    )
    assert response.status_code == 200
    assert manager.provider.api_key == ""


def test_hidden_nested_credentials_require_explicit_clear() -> None:
    client, manager = _client(PlatformRole.ADMIN)

    response = client.put(
        "/models/synthetic/config",
        json={"custom_headers": {}, "generate_kwargs": {"temperature": 0.2}},
    )
    assert response.status_code == 200
    assert manager.provider.custom_headers["Authorization"] == f"Bearer {SECRET}"
    assert manager.provider.generate_kwargs["auth_token"] == SECRET

    response = client.put(
        "/models/synthetic/config",
        json={"clear_custom_headers": True},
    )
    assert response.status_code == 200
    assert manager.provider.custom_headers == {}


def test_sensitive_list_projection_roundtrip_preserves_original_list() -> None:
    client, manager = _client(PlatformRole.ADMIN)
    original = manager.provider.generate_kwargs["tools"]

    response = client.put(
        "/models/synthetic/config",
        json={"generate_kwargs": {"tools": [{"name": "safe"}]}},
    )

    assert response.status_code == 200
    assert manager.provider.generate_kwargs["tools"] == original


@pytest.mark.parametrize(
    "submitted_tools",
    [
        [],
        [{"name": "inserted"}, {"name": "safe"}],
        [{"name": "renamed"}],
        [{"name": "second"}, {"name": "first"}],
    ],
)
def test_sensitive_list_edit_is_rejected_without_mutation(submitted_tools) -> None:
    client, manager = _client(PlatformRole.ADMIN)
    manager.provider.generate_kwargs["tools"] = [
        {"name": "first", "secret": SECRET},
        {"name": "second", "secret": NEW_SECRET},
    ]
    original = manager.provider.model_copy(deep=True).generate_kwargs

    response = client.put(
        "/models/synthetic/config",
        json={"generate_kwargs": {"tools": submitted_tools}},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Cannot edit a list containing hidden credentials; replace the "
        "credential-bearing configuration explicitly."
    )
    assert manager.provider.generate_kwargs == original


def test_non_sensitive_list_can_be_edited() -> None:
    client, manager = _client(PlatformRole.ADMIN)
    manager.provider.generate_kwargs = {"stops": ["one", "two"]}

    response = client.put(
        "/models/synthetic/config",
        json={"generate_kwargs": {"stops": ["two"]}},
    )

    assert response.status_code == 200
    assert manager.provider.generate_kwargs == {"stops": ["two"]}


def test_base_url_is_preserved_until_explicitly_changed_or_cleared() -> None:
    client, manager = _client(PlatformRole.ADMIN)
    original = manager.provider.base_url

    response = client.put("/models/synthetic/config", json={"base_url": ""})
    assert response.status_code == 200
    assert manager.provider.base_url == original

    response = client.put(
        "/models/synthetic/config",
        json={"base_url": "https://replacement.invalid/v1"},
    )
    assert response.status_code == 200
    assert manager.provider.base_url == "https://replacement.invalid/v1"

    response = client.put(
        "/models/synthetic/config",
        json={"clear_base_url": True},
    )
    assert response.status_code == 200
    assert manager.provider.base_url == ""
