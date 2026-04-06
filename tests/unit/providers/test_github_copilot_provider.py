# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from copaw.providers.github_copilot_provider import (
    GitHubCopilotProvider,
    DeviceAuthorizationSession,
)
from copaw.providers.openai_responses_chat_model_compat import (
    OpenAIResponsesChatModelCompat,
)


class FakeSecretStore:
    def __init__(self, *, available: bool = False) -> None:
        self.available = available
        self.secret: str | None = None
        self.delete_calls = 0

    def load_payload(self) -> dict | None:
        if self.secret is None:
            return None
        return json.loads(self.secret)

    def save_payload(self, payload: dict) -> bool:
        if not self.available:
            return False
        self.secret = json.dumps(payload, ensure_ascii=False)
        return True

    def delete_payload(self) -> None:
        self.delete_calls += 1
        self.secret = None


@pytest.fixture(autouse=True)
def fake_secret_store(monkeypatch):
    store = FakeSecretStore(available=False)
    monkeypatch.setattr(
        GitHubCopilotProvider,
        "_load_keyring_auth_payload",
        lambda self: store.load_payload(),
    )
    monkeypatch.setattr(
        GitHubCopilotProvider,
        "_save_keyring_auth_payload",
        lambda self, payload: store.save_payload(payload),
    )
    monkeypatch.setattr(
        GitHubCopilotProvider,
        "_delete_keyring_auth_payload",
        lambda self: store.delete_payload(),
    )
    return store


def _make_provider() -> GitHubCopilotProvider:
    return GitHubCopilotProvider(
        id="github-copilot",
        name="GitHub Copilot",
        base_url="https://api.individual.githubcopilot.com",
        require_api_key=False,
        support_model_discovery=True,
        freeze_url=True,
    )


async def test_start_device_authorization_stores_session(monkeypatch) -> None:
    provider = _make_provider()
    provider._device_sessions["expired-session"] = DeviceAuthorizationSession(
        session_id="expired-session",
        device_code="expired-code",
        user_code="EXPIRED",
        verification_uri="https://github.com/login/device",
        expires_at=1,
        interval=5,
    )

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "device_code": "device-code-1",
                "user_code": "ABCD-EFGH",
                "verification_uri": "https://github.com/login/device",
                "expires_in": 900,
                "interval": 5,
            }

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            _ = args, kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            _ = exc_type, exc, tb
            return False

        async def post(self, *args, **kwargs):
            _ = args, kwargs
            return FakeResponse()

    monkeypatch.setattr(
        "copaw.providers.github_copilot_provider.httpx.AsyncClient",
        FakeAsyncClient,
    )

    session = await provider.start_device_authorization()

    assert session.user_code == "ABCD-EFGH"
    assert session.interval == 5
    assert "expired-session" not in provider._device_sessions
    assert (
        provider._device_sessions[session.session_id].device_code
        == "device-code-1"
    )


async def test_poll_device_authorization_authorized(monkeypatch) -> None:
    provider = _make_provider()
    session = SimpleNamespace(
        session_id="session-1",
        device_code="device-code-1",
        user_code="ABCD-EFGH",
        verification_uri="https://github.com/login/device",
        expires_at=4_102_444_800,
        interval=5,
        status="pending",
        last_message="",
    )
    provider._device_sessions[session.session_id] = session

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "access_token": "gho_test_token",
                "token_type": "bearer",
                "scope": "read:user",
            }

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            _ = args, kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            _ = exc_type, exc, tb
            return False

        async def post(self, *args, **kwargs):
            _ = args, kwargs
            return FakeResponse()

    async def fake_populate_user(timeout: float = 10) -> None:
        _ = timeout
        provider.github_user_login = "octocat"

    async def fake_refresh_copilot(timeout: float = 10) -> None:
        _ = timeout
        provider.copilot_access_token = "copilot_token"
        provider.copilot_token_expires_at = 4_102_444_800
        provider.api_key = "copilot_token"

    monkeypatch.setattr(
        "copaw.providers.github_copilot_provider.httpx.AsyncClient",
        FakeAsyncClient,
    )
    monkeypatch.setattr(provider, "_populate_github_user", fake_populate_user)
    monkeypatch.setattr(
        provider,
        "_refresh_copilot_token_async",
        fake_refresh_copilot,
    )

    result = await provider.poll_device_authorization("session-1")

    assert result.status == "authorized"
    assert result.message == "GitHub authorization completed"
    assert provider.github_oauth_token == "gho_test_token"
    assert provider.github_user_login == "octocat"
    assert provider.api_key == "copilot_token"
    assert "session-1" not in provider._device_sessions


async def test_poll_device_authorization_slow_down_updates_interval(
    monkeypatch,
) -> None:
    provider = _make_provider()
    provider._device_sessions["session-1"] = DeviceAuthorizationSession(
        session_id="session-1",
        device_code="device-code-1",
        user_code="ABCD-EFGH",
        verification_uri="https://github.com/login/device",
        expires_at=4_102_444_800,
        interval=5,
    )

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "error": "slow_down",
                "error_description": "Slow down",
            }

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            _ = args, kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            _ = exc_type, exc, tb
            return False

        async def post(self, *args, **kwargs):
            _ = args, kwargs
            return FakeResponse()

    monkeypatch.setattr(
        "copaw.providers.github_copilot_provider.httpx.AsyncClient",
        FakeAsyncClient,
    )

    result = await provider.poll_device_authorization("session-1")

    assert result.status == "pending"
    assert result.slow_down is True
    assert result.interval == 10
    assert provider._device_sessions["session-1"].interval == 10


async def test_get_info_reports_auth_state() -> None:
    provider = _make_provider()
    provider.github_oauth_token = "gho_test"
    provider.github_user_login = "octocat"
    provider.copilot_access_token = "copilot-token"
    provider.copilot_token_expires_at = 4_102_444_800
    provider.api_key = "copilot-token"

    info = await provider.get_info(mock_secret=False)

    assert info.supports_oauth_login is True
    assert info.is_authenticated is True
    assert info.auth_account_label == "octocat"
    assert info.auth_expires_at == 4_102_444_800
    assert info.api_key == ""


def test_logout_clears_auth_state() -> None:
    provider = _make_provider()
    provider.github_oauth_token = "gho_test"
    provider.github_user_login = "octocat"
    provider.copilot_access_token = "copilot-token"
    provider.copilot_token_expires_at = 4_102_444_800
    provider.api_key = "copilot-token"
    provider._device_sessions["session-1"] = SimpleNamespace()

    provider.logout()

    assert provider.github_oauth_token == ""
    assert provider.github_user_login == ""
    assert provider.copilot_access_token == ""
    assert provider.copilot_token_expires_at is None
    assert provider.api_key == ""
    assert provider.base_url == "https://api.individual.githubcopilot.com"
    assert provider._device_sessions == {}


def test_to_persisted_dict_persists_refresh_credentials_only() -> None:
    fake_store = FakeSecretStore(available=True)
    provider = _make_provider()
    provider._load_keyring_auth_payload = fake_store.load_payload
    provider._save_keyring_auth_payload = fake_store.save_payload
    provider._delete_keyring_auth_payload = fake_store.delete_payload
    provider.is_authenticated = True
    provider.auth_account_label = "octocat"
    provider.auth_expires_at = 4_102_444_800
    provider.github_oauth_token = "gho_test"
    provider.github_scope = "read:user"
    provider.github_user_login = "octocat"
    provider.github_user_id = 1
    provider.copilot_access_token = "copilot-token"
    provider.copilot_token_expires_at = 4_102_444_800
    provider.api_key = "copilot-token"

    persisted = provider.to_persisted_dict()

    assert persisted["github_auth_storage"] == "keychain"
    assert "github_oauth_token" not in persisted
    assert json.loads(fake_store.secret or "{}") == {
        "github_oauth_token": "gho_test",
        "github_token_type": "bearer",
        "github_scope": "read:user",
        "github_user_login": "octocat",
        "github_user_id": 1,
    }
    assert "api_key" not in persisted
    assert "is_authenticated" not in persisted
    assert "copilot_access_token" not in persisted


def test_to_persisted_dict_falls_back_to_json_without_keychain(
    fake_secret_store,
) -> None:
    provider = _make_provider()
    provider.is_authenticated = True
    provider.github_oauth_token = "gho_test"
    provider.github_scope = "read:user"
    provider.github_user_login = "octocat"
    provider.github_user_id = 1

    persisted = provider.to_persisted_dict()

    assert fake_secret_store.secret is None
    assert persisted["github_auth_storage"] == "json"
    assert persisted["github_oauth_token"] == "gho_test"
    assert persisted["github_scope"] == "read:user"
    assert persisted["github_user_login"] == "octocat"
    assert persisted["github_user_id"] == 1


def test_model_post_init_restores_auth_from_keychain(fake_secret_store) -> None:
    fake_secret_store.available = True
    fake_secret_store.secret = json.dumps(
        {
            "github_oauth_token": "gho_test",
            "github_token_type": "bearer",
            "github_scope": "read:user",
            "github_user_login": "octocat",
            "github_user_id": 1,
        },
    )

    provider = GitHubCopilotProvider(
        id="github-copilot",
        name="GitHub Copilot",
        base_url="https://api.individual.githubcopilot.com",
        require_api_key=False,
        support_model_discovery=True,
        freeze_url=True,
        github_auth_storage="keychain",
        copilot_access_token="stale-token",
        api_key="stale-token",
    )

    assert provider.github_oauth_token == "gho_test"
    assert provider.github_user_login == "octocat"
    assert provider.is_authenticated is True
    assert provider.auth_account_label == "octocat"
    assert provider.copilot_access_token == ""
    assert provider.api_key == ""


async def test_fetch_models_requires_and_uses_auth(monkeypatch) -> None:
    provider = _make_provider()
    provider.github_oauth_token = "gho_test"

    async def fake_refresh(timeout: float = 5) -> None:
        _ = timeout
        provider.copilot_access_token = "copilot-token"
        provider.api_key = "copilot-token"

    class FakeModels:
        async def list(self, timeout=None):
            _ = timeout
            return SimpleNamespace(
                data=[SimpleNamespace(id="gpt-4o", name="GPT-4o")],
            )

    monkeypatch.setattr(provider, "_refresh_copilot_token_async", fake_refresh)
    monkeypatch.setattr(
        provider,
        "_copilot_discovery_client",
        lambda timeout=5: SimpleNamespace(models=FakeModels()),
    )

    models = await provider.fetch_models(timeout=3)

    assert [model.id for model in models] == ["gpt-4o"]


async def test_fetch_models_enforces_dynamic_base_url(monkeypatch) -> None:
    provider = _make_provider()
    provider.github_oauth_token = "gho_test"
    provider.base_url = "https://wrong.example.com"

    async def fake_refresh(timeout: float = 5) -> None:
        _ = timeout
        provider.copilot_access_token = "tid=abc; proxy-ep=https://proxy.enterprise.githubcopilot.com; foo=bar"
        provider.api_key = provider.copilot_access_token

    captured: dict[str, str] = {}

    class FakeModels:
        async def list(self, timeout=None):
            _ = timeout
            return SimpleNamespace(
                data=[SimpleNamespace(id="gpt-4o", name="GPT-4o")],
            )

    class FakeAsyncOpenAI:
        def __init__(self, *, base_url, api_key, timeout, default_headers):
            captured["base_url"] = base_url
            captured["api_key"] = api_key
            captured["timeout"] = str(timeout)
            captured["has_headers"] = str(bool(default_headers))
            self.models = FakeModels()

    monkeypatch.setattr(provider, "_refresh_copilot_token_async", fake_refresh)
    monkeypatch.setattr(
        "copaw.providers.github_copilot_provider.AsyncOpenAI",
        FakeAsyncOpenAI,
    )

    models = await provider.fetch_models(timeout=3)

    assert [model.id for model in models] == ["gpt-4o"]
    assert captured["base_url"] == "https://api.enterprise.githubcopilot.com"
    assert provider.base_url == "https://api.enterprise.githubcopilot.com"


async def test_check_connection_enforces_dynamic_base_url(monkeypatch) -> None:
    provider = _make_provider()
    provider.github_oauth_token = "gho_test"
    provider.base_url = "https://wrong.example.com"

    async def fake_refresh(timeout: float = 5) -> None:
        _ = timeout
        provider.copilot_access_token = "tid=abc; proxy-ep=https://proxy.business.githubcopilot.com; foo=bar"
        provider.api_key = provider.copilot_access_token

    captured: dict[str, str] = {}

    class FakeModels:
        async def list(self, timeout=None):
            _ = timeout
            return SimpleNamespace(data=[])

    class FakeAsyncOpenAI:
        def __init__(self, *, base_url, api_key, timeout, default_headers):
            captured["base_url"] = base_url
            captured["api_key"] = api_key
            self.models = FakeModels()

    monkeypatch.setattr(provider, "_refresh_copilot_token_async", fake_refresh)
    monkeypatch.setattr(
        "copaw.providers.github_copilot_provider.AsyncOpenAI",
        FakeAsyncOpenAI,
    )

    ok, message = await provider.check_connection(timeout=3)

    assert ok is True
    assert message == ""
    assert captured["base_url"] == "https://api.business.githubcopilot.com"
    assert provider.base_url == "https://api.business.githubcopilot.com"


async def test_check_model_connection_uses_responses_api(monkeypatch) -> None:
    provider = _make_provider()
    provider.github_oauth_token = "gho_test"

    async def fake_refresh(timeout: float = 5) -> None:
        _ = timeout
        provider.copilot_access_token = "copilot-token"
        provider.api_key = "copilot-token"

    calls: list[dict] = []

    class FakeResponses:
        async def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace()

    monkeypatch.setattr(provider, "_refresh_copilot_token_async", fake_refresh)
    monkeypatch.setattr(
        provider,
        "_copilot_responses_client",
        lambda timeout=5: SimpleNamespace(responses=FakeResponses()),
    )

    ok, message = await provider.check_model_connection(
        "gpt-5.4-mini", timeout=3
    )

    assert ok is True
    assert message == ""
    assert calls[0]["model"] == "gpt-5.4-mini"
    assert calls[0]["input"][0]["content"][0]["type"] == "input_text"
    assert calls[0]["max_output_tokens"] == 16


async def test_check_model_connection_enforces_dynamic_base_url(
    monkeypatch,
) -> None:
    provider = _make_provider()
    provider.github_oauth_token = "gho_test"
    provider.base_url = "https://wrong.example.com"

    async def fake_refresh(timeout: float = 5) -> None:
        _ = timeout
        provider.copilot_access_token = "tid=abc; proxy-ep=https://proxy.enterprise.githubcopilot.com; foo=bar"
        provider.api_key = provider.copilot_access_token

    captured: dict[str, str] = {}

    class FakeResponses:
        async def create(self, **kwargs):
            captured["model"] = kwargs["model"]
            return SimpleNamespace()

    class FakeAsyncOpenAI:
        def __init__(self, *, base_url, api_key, timeout, default_headers):
            captured["base_url"] = base_url
            captured["api_key"] = api_key
            self.responses = FakeResponses()

    monkeypatch.setattr(provider, "_refresh_copilot_token_async", fake_refresh)
    monkeypatch.setattr(
        "copaw.providers.github_copilot_provider.AsyncOpenAI",
        FakeAsyncOpenAI,
    )

    ok, message = await provider.check_model_connection(
        "gpt-5.4-mini", timeout=3
    )

    assert ok is True
    assert message == ""
    assert captured["model"] == "gpt-5.4-mini"
    assert captured["base_url"] == "https://api.enterprise.githubcopilot.com"
    assert provider.base_url == "https://api.enterprise.githubcopilot.com"


def test_get_chat_model_instance_uses_responses_chat_model(
    monkeypatch,
) -> None:
    provider = _make_provider()
    provider.copilot_access_token = "copilot-token"

    monkeypatch.setattr(
        provider, "_refresh_copilot_token_sync", lambda timeout=10: None
    )

    model = provider.get_chat_model_instance("gpt-5.4-mini")

    assert isinstance(model, OpenAIResponsesChatModelCompat)
    assert model.model_name == "gpt-5.4-mini"


def test_apply_copilot_token_payload_updates_dynamic_base_url() -> None:
    provider = _make_provider()

    provider._apply_copilot_token_payload(
        {
            "token": (
                "tid=abc; proxy-ep=https://proxy.business.githubcopilot.com; "
                "foo=bar"
            ),
            "expires_at": 4_102_444_800,
        },
    )

    assert provider.base_url == "https://api.business.githubcopilot.com"


def test_refresh_uses_cached_token_to_restore_dynamic_base_url() -> None:
    provider = _make_provider()
    provider.copilot_access_token = (
        "tid=abc; proxy-ep=https://proxy.enterprise.githubcopilot.com; foo=bar"
    )
    provider.copilot_token_expires_at = 4_102_444_800
    provider.base_url = "https://wrong.example.com"

    provider._refresh_copilot_token_sync(timeout=1)

    assert provider.base_url == "https://api.enterprise.githubcopilot.com"
