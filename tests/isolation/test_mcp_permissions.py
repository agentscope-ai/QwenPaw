# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest
from fastapi import HTTPException
from types import SimpleNamespace
from contextlib import asynccontextmanager

from qwenpaw.app.mcp.config_service import (
    MCPConfigService,
    _credential_fields,
    _postgres_credential_record,
    _postgres_update_values,
)
from qwenpaw.app.routers.mcp import _safe_user_projection
from qwenpaw.app.mcp.schemas import (
    MCPClientCreateRequest,
    MCPClientInfo,
    MCPClientUpdateRequest,
    SecretAction,
)
from qwenpaw.drivers.credentials.types import CredentialRecord
from qwenpaw.app.mcp.scoped_credentials import ScopedPostgresMCPCredentialStore
from uuid import uuid4


@pytest.mark.asyncio
async def test_postgres_service_keep_preserves_bound_header_in_rebuilt_card():
    """The public response model must never participate in secret merging."""
    existing_card = SimpleNamespace(
        name="safe",
        protocol="mcp",
        endpoint={
            "transport": "streamable_http",
            "url": "https://example.invalid/mcp",
            "headers": {
                "Authorization": {
                    "source": "credential",
                    "credential": "static",
                    "field": "authorization",
                },
                "X-OAuth-Token": {
                    "source": "credential",
                    "credential": "oauth",
                    "field": "access_token",
                },
            },
        },
        credentials={
            "static": SimpleNamespace(kind="mcp-static", ref="pgmcp/safe/static"),
            "oauth": SimpleNamespace(kind="oauth2_auth_code", ref="pgmcp/safe/oauth"),
        },
        config={"display_name": "Safe", "description": "", "tools": None},
        enabled=True,
        policy=SimpleNamespace(default_effect="deny", rules=[]),
    )
    stored = CredentialRecord(
        ref=str(uuid4()),
        kind="mcp-static",
        secrets={"authorization": "Bearer synthetic-token"},
    )

    class DriverConfig:
        async def load_optional_credential(self, _ref):
            return stored

        async def save_card(self, _card):
            return None

    class Repository:
        def __init__(self):
            self.config = None
            self.secrets = None

        @asynccontextmanager
        async def transaction(self):
            yield object()

        async def update_driver(self, **kwargs):
            self.config = kwargs["config"]
            return SimpleNamespace(revision=2)

        async def get_oauth_target(self, **_kwargs):
            return SimpleNamespace()

        async def replace_bound_credential(self, **kwargs):
            self.secrets = kwargs["secrets"]

    repository = Repository()
    service = MCPConfigService.__new__(MCPConfigService)
    service._workspace = SimpleNamespace(agent_id="agent-a")
    service._actor_user_id = uuid4()
    service._driver_config = DriverConfig()
    service._postgres = repository
    service._uses_postgres = lambda: _async_value(True)
    service.load_card = lambda _key: _async_value(existing_card)
    service.list_cards = lambda: _async_value([existing_card])
    service.build_info_from_card = lambda _card: _async_value(SimpleNamespace())

    await service.update_client(
        "safe",
        MCPClientUpdateRequest.model_validate(
            {
                "expected_revision": 1,
                "description": "edited",
                "credential_updates": {
                    "headers": {"Authorization": {"action": "keep"}}
                },
            }
        ),
    )

    binding = repository.config["endpoint"]["headers"]["Authorization"]
    assert binding["source"] == "credential"
    assert binding["field"] == "authorization"
    oauth_binding = repository.config["endpoint"]["headers"]["X-OAuth-Token"]
    assert oauth_binding == {
        "source": "credential",
        "credential": "oauth",
        "field": "access_token",
    }
    assert repository.secrets == {"authorization": "Bearer synthetic-token"}


def test_credential_fields_exclude_oauth_managed_bindings():
    card = SimpleNamespace(
        endpoint={
            "headers": {
                "X-Static": {
                    "source": "credential",
                    "credential": "static",
                    "field": "x_static",
                },
                "Authorization": {
                    "source": "credential",
                    "credential": "oauth",
                    "field": "access_token",
                },
            }
        }
    )
    assert _credential_fields(card) == {"headers": ["X-Static"], "env": []}


async def _async_value(value):
    return value


@pytest.mark.asyncio
async def test_postgres_principals_use_agent_members_without_reading_private_chats():
    class ChatManager:
        async def list_chats(self):
            raise AssertionError("PG principal discovery must not read chats")

    class MCPRepository:
        async def list_principal_identities(self, *, agent_key):
            assert agent_key == "agent-a"
            return [
                SimpleNamespace(
                    user_id=uuid4(),
                    username="owner-safe-label",
                    role="owner",
                )
            ]

    service = MCPConfigService.__new__(MCPConfigService)
    service._workspace = SimpleNamespace(
        agent_id="agent-a",
        chat_manager=ChatManager(),
    )
    service._postgres = MCPRepository()
    service._uses_postgres = lambda: _async_value(True)

    principals = await service.list_access_principals()

    assert len(principals) == 1
    assert principals[0].source_value == "console"
    assert principals[0].subject_value
    assert principals[0].label == "owner-safe-label"
    assert principals[0].chat_id == ""
    assert principals[0].chat_name == ""
    assert principals[0].session_id == ""


def test_mcp_dto_exposes_only_credential_field_names():
    info = MCPClientInfo(
        key="safe",
        name="Safe",
        enabled=True,
        transport="stdio",
        headers={"Authorization": "synthetic-secret"},
        env={"TOKEN": "synthetic-secret"},
        credential_fields={
            "headers": ["Authorization"],
            "env": ["TOKEN"],
        },
        revision=3,
        runtime_status="active",
        can_edit=True,
    )
    payload = info.model_dump(mode="json")
    assert payload["headers"] == {}
    assert payload["env"] == {}
    assert payload["credential_fields"] == {
        "headers": ["Authorization"],
        "env": ["TOKEN"],
    }
    assert "synthetic-secret" not in repr(info)


def test_credential_updates_require_explicit_supported_actions():
    update = MCPClientUpdateRequest.model_validate(
        {
            "expected_revision": 4,
            "credential_updates": {
                "headers": {
                    "Authorization": {"action": "keep"},
                    "X-Key": {"action": "replace", "value": "new"},
                },
                "env": {"OLD": {"action": "delete"}},
            },
        }
    )
    assert update.expected_revision == 4
    assert update.credential_updates.headers["Authorization"] == SecretAction(
        action="keep"
    )


def test_postgres_replace_equal_to_legacy_mask_is_not_restored():
    update = MCPClientUpdateRequest.model_validate(
        {
            "credential_updates": {
                "headers": {
                    "Authorization": {
                        "action": "replace",
                        "value": "abc***xyz",
                    }
                }
            }
        }
    )
    values = _postgres_update_values(
        {
            "headers": {
                "Authorization": {
                    "source": "credential",
                    "credential": "static",
                    "field": "Authorization",
                }
            }
        },
        CredentialRecord(
            ref="old",
            kind="mcp-static",
            secrets={"Authorization": "abc-original-xyz"},
        ),
        update,
    )
    assert values["headers"] == {"Authorization": "abc***xyz"}
    rebuilt = _postgres_credential_record(
        "safe",
        MCPClientCreateRequest(
            name="Safe",
            transport="streamable_http",
            headers=values["headers"],
        ),
        CredentialRecord(
            ref="old",
            kind="mcp-static",
            secrets={"Authorization": "abc-original-xyz"},
        ),
    )
    assert rebuilt.secrets == {"authorization": "abc***xyz"}


def test_postgres_update_rejects_raw_header_or_env_maps():
    update = MCPClientUpdateRequest(headers={"Authorization": "raw"})
    with pytest.raises(HTTPException) as captured:
        _postgres_update_values({}, None, update)
    assert captured.value.status_code == 400
    assert captured.value.detail == "credential_updates_required"


def test_user_projection_hides_whitelist_and_configuration():
    projected = _safe_user_projection(
        MCPClientInfo(
            key="safe",
            name="Safe",
            enabled=True,
            transport="stdio",
            command="private-command",
            args=["private-arg"],
            tools=["governed-tool"],
            revision=9,
            credential_fields={"headers": ["Authorization"], "env": []},
        )
    )
    assert projected.tools is None
    assert projected.command == ""
    assert projected.args == []
    assert projected.revision is None
    assert projected.credential_fields.headers == []


@pytest.mark.asyncio
async def test_tool_discovery_error_does_not_expose_exception(caplog):
    secret = "synthetic-secret C:/private/host/path"

    class FailingDriverConfig:
        async def list_driver_capabilities(self, *_args, **_kwargs):
            raise RuntimeError(secret)

    service = __import__(
        "qwenpaw.app.mcp.config_service",
        fromlist=["MCPConfigService"],
    ).MCPConfigService(SimpleNamespace())
    service._driver_config = FailingDriverConfig()

    async def load_card(*_args, **_kwargs):
        return SimpleNamespace(enabled=True, config={})

    service.load_card = load_card
    with pytest.raises(HTTPException) as captured:
        await service.list_tools("safe-client")
    assert captured.value.detail == "mcp_tools_unavailable"
    assert secret not in caplog.text


@pytest.mark.asyncio
async def test_scoped_store_allows_only_resolved_oauth_refresh():
    credential_id = uuid4()

    class Repository:
        def __init__(self):
            self.refreshed = None

        async def refresh_oauth_credential(self, **kwargs):
            self.refreshed = kwargs

    repository = Repository()
    store = ScopedPostgresMCPCredentialStore(
        agent_key="agent-a",
        repository=repository,
    )
    record = CredentialRecord(
        ref=str(credential_id),
        kind="oauth2_auth_code",
        secrets={"access_token": "fresh"},
    )
    await store.put(record)
    assert repository.refreshed == {
        "agent_key": "agent-a",
        "credential_id": credential_id,
        "record": record,
    }
    with pytest.raises(Exception):
        await store.put(
            CredentialRecord(
                ref="pgmcp/other/oauth",
                kind="oauth2_auth_code",
                secrets={"access_token": "forbidden"},
            )
        )
