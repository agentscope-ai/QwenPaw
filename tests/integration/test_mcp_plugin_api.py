# -*- coding: utf-8 -*-
"""Retained MCP HTTP contract without activating an inactive workspace.

These tests mount real routers and persist actual cards/credentials in a temp
workspace. The manager is deliberately unable to start a workspace: saved
configuration must remain usable without the optional protocol runtime.
"""


# Test fixtures observe host ownership to prove no lazy workspace startup.
# pylint: disable=protected-access,redefined-outer-name
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.routers import mcp
from qwenpaw.config import utils
from qwenpaw.config.config import Config
from qwenpaw.drivers.contracts import DriverCard
from qwenpaw.drivers.storage import dump_card, load_card


@pytest.fixture
def offline_api(tmp_path, monkeypatch):
    workspace = tmp_path / "inactive-workspace"
    workspace.mkdir()
    (workspace / "agent.json").write_text('{"id":"inactive"}')
    config = Config.model_validate(
        {
            "agents": {
                "active_agent": "inactive",
                "profiles": {
                    "inactive": {
                        "id": "inactive",
                        "workspace_dir": str(workspace),
                    },
                },
            },
            "plugins": {"qwenpaw-mcp": {"enabled": False}},
        },
    )
    config_path = tmp_path / "config.json"
    utils.save_config(config, config_path)
    monkeypatch.setattr(utils, "get_config_path", lambda: config_path)
    monkeypatch.setattr(utils, "_config_cache", None)
    monkeypatch.setattr(utils, "_config_mtime", None)
    manager = SimpleNamespace(
        get_agent=AsyncMock(side_effect=AssertionError("workspace startup")),
        _agents={},
    )
    app = FastAPI()
    app.state.multi_agent_manager = manager
    app.state.plugin_loader = None
    from qwenpaw.app.routers.mcp_oauth import router as oauth_router

    app.include_router(oauth_router, prefix="/api")
    app.include_router(mcp.router, prefix="/api")
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, workspace, manager


def seed_card(workspace, *, enabled=True):
    path = workspace / "drivers/mcp/retained.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    value = DriverCard(
        **{
            "name": "retained",
            "protocol": "mcp",
            "enabled": enabled,
            "endpoint": {"transport": "stdio", "command": "offline-command"},
            "config": {"tools": ["old_tool"]},
            "policy": {"default_effect": "ask"},
        },
    )
    dump_card(value, path)
    return path


@pytest.mark.parametrize(
    "path",
    [
        "/api/mcp",
        "/api/mcp/retained",
        "/api/mcp/policy/retained",
    ],
)
def test_saved_configuration_read_does_not_start_workspace(offline_api, path):
    client, workspace, manager = offline_api
    card_path = seed_card(workspace)
    before = card_path.read_bytes()
    response = client.get(path, headers={"X-Agent-Id": "inactive"})
    assert response.status_code == 200, response.text
    assert card_path.read_bytes() == before
    manager.get_agent.assert_not_awaited()
    payload = response.json()
    if path == "/api/mcp":
        assert [(row["key"], row["enabled"]) for row in payload] == [
            ("retained", True),
        ]
    elif "/policy/" in path:
        assert payload["default_effect"] == "ask"
    else:
        assert payload["key"] == "retained"
        assert payload["command"] == "offline-command"


def test_offline_saved_updates_keep_shape_policy_and_whitelist(offline_api):
    client, workspace, manager = offline_api
    path = seed_card(workspace)
    headers = {"X-Agent-Id": "inactive"}
    renamed = client.put(
        "/api/mcp/retained",
        json={"name": "Renamed"},
        headers=headers,
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["key"] == "retained"
    assert renamed.json()["name"] == "Renamed"
    toggled = client.patch("/api/mcp/toggle/retained", headers=headers)
    assert toggled.status_code == 200, toggled.text
    assert toggled.json()["enabled"] is False
    saved = load_card(path)
    assert saved.config["tools"] == ["old_tool"]
    assert saved.policy.default_effect == "ask"
    manager.get_agent.assert_not_awaited()


def test_runtime_tool_listing_has_stable_unavailable_error(offline_api):
    client, workspace, manager = offline_api
    path = seed_card(workspace)
    before = path.read_bytes()
    response = client.get(
        "/api/mcp/tools/retained",
        headers={"X-Agent-Id": "inactive"},
    )
    assert response.status_code == 503, response.text
    assert response.json()["detail"]["code"] == "mcp_plugin_unavailable"
    assert path.read_bytes() == before
    manager.get_agent.assert_not_awaited()


def test_offline_create_policy_whitelist_and_delete_retain_http_contract(
    offline_api,
):
    client, workspace, manager = offline_api
    headers = {"X-Agent-Id": "inactive"}
    created = client.post(
        "/api/mcp",
        headers=headers,
        json={
            "client_key": "plugin",
            "client": {
                "name": "Plugin named client",
                "command": "synthetic-command",
                "transport": "stdio",
                "enabled": False,
            },
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["key"] == "plugin"
    assert (
        client.get("/api/mcp/plugin", headers=headers).json()["key"]
        == "plugin"
    )
    policy = {
        "default_effect": "deny",
        "client_overrides": [],
        "tool_defaults": [{"tool_name": "old_tool", "effect": "ask"}],
        "tool_overrides": [],
        "unmanaged_rules_count": 0,
    }
    saved = client.put("/api/mcp/policy/plugin", json=policy, headers=headers)
    assert saved.status_code == 200, saved.text
    assert saved.json() == policy
    whitelisted = client.put(
        "/api/mcp/tools/plugin",
        json={"tools": ["old_tool"]},
        headers=headers,
    )
    assert whitelisted.status_code == 200, whitelisted.text
    assert whitelisted.json() == []
    card = load_card(workspace / "drivers/mcp/plugin.yaml")
    assert card.config["tools"] == ["old_tool"]
    assert card.policy.default_effect == "deny"
    deleted = client.delete("/api/mcp/plugin", headers=headers)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {
        "message": "MCP client 'plugin' deleted successfully",
    }
    assert client.get("/api/mcp/plugin", headers=headers).status_code == 404
    manager.get_agent.assert_not_awaited()


@pytest.mark.parametrize(
    "headers, expected",
    [
        ({"X-Agent-Id": "unknown"}, 404),
    ],
)
def test_saved_config_resolver_does_not_bypass_profile_validation(
    offline_api,
    headers,
    expected,
):
    client, _, manager = offline_api
    assert client.get("/api/mcp", headers=headers).status_code == expected
    manager.get_agent.assert_not_awaited()


async def test_lifecycle_state_read_never_installs_or_starts_workspace(
    tmp_path,
    monkeypatch,
):
    from importlib import import_module
    from qwenpaw.plugins.testing import PluginTestHost

    module = import_module("qwenpaw.app.routers.mcp_plugin")
    async with PluginTestHost(tmp_path / "host") as host:
        host._http_app.state.plugin_loader = host._loader
        host._http_app.include_router(module.router, prefix="/api")
        before = set(host._workspaces)
        installer = AsyncMock(side_effect=AssertionError("implicit install"))
        monkeypatch.setattr(host._loader, "install_plugin_files", installer)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=host._http_app),
            base_url="http://testserver",
        ) as client:
            response = await client.get("/api/mcp-plugin")
        assert response.status_code == 200, response.text
        assert response.json() == {
            "id": "qwenpaw-mcp",
            "installed": False,
            "enabled": False,
            "status": "not_installed",
            "diagnostics": [],
        }
        assert set(host._workspaces) == before
        assert not (host.root / "plugins/qwenpaw-mcp").exists()
        installer.assert_not_awaited()


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("GET", "/api/mcp/oauth/status/retained", None),
        ("DELETE", "/api/mcp/oauth/retained", None),
        (
            "POST",
            "/api/mcp/oauth/start/retained",
            {"url": "https://mcp.invalid"},
        ),
    ],
)
def test_oauth_runtime_unavailable_has_same_stable_error(
    offline_api,
    method,
    path,
    body,
):
    client, workspace, manager = offline_api
    seed_card(workspace)
    response = client.request(
        method,
        path,
        json=body,
        headers={"X-Agent-Id": "inactive"},
    )
    assert response.status_code == 503, response.text
    assert response.json()["detail"]["code"] == "mcp_plugin_unavailable"
    manager.get_agent.assert_not_awaited()


async def test_explicit_install_disable_enable_uninstall_uses_real_loader(
    tmp_path,
):
    from qwenpaw.app.routers import mcp_plugin, plugins
    from qwenpaw.plugins.testing import PluginTestHost
    from tests.unit.plugins.mcp.fixtures import (
        card as source_card,
        seed_card as seed_source,
    )

    async with PluginTestHost(tmp_path / "host") as host:
        host._http_app.state.plugin_loader = host._loader
        host._http_app.include_router(mcp_plugin.router, prefix="/api")
        host._http_app.include_router(plugins.router, prefix="/api")
        path = seed_source(host.root, source_card("kept", enabled=False))
        before = path.read_bytes()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=host._http_app),
            base_url="http://testserver",
        ) as client:
            installed = await client.post("/api/mcp-plugin/install")
            assert installed.status_code == 200, installed.text
            assert installed.json()["status"] == "active"
            assert installed.json()["installed"] is True
            assert installed.json()["enabled"] is True
            assert (
                host._loader.get_loaded_plugin("qwenpaw-mcp").status
                == "active"
            )
            assert not host._workspaces
            disabled = await client.post(
                "/api/plugins/qwenpaw-mcp/enabled",
                json={"enabled": False},
            )
            assert disabled.status_code == 200, disabled.text
            assert (await client.get("/api/mcp-plugin")).json()[
                "status"
            ] == "disabled"
            assert path.read_bytes() == before
            enabled = await client.post(
                "/api/plugins/qwenpaw-mcp/enabled",
                json={"enabled": True},
            )
            assert enabled.status_code == 200, enabled.text
            assert (await client.get("/api/mcp-plugin")).json()[
                "status"
            ] == "active"
            removed = await client.delete("/api/plugins/qwenpaw-mcp")
            assert removed.status_code == 200, removed.text
            state = (await client.get("/api/mcp-plugin")).json()
            assert state["status"] == "not_installed"
            assert state["installed"] is False
            assert state["enabled"] is False
            assert path.read_bytes() == before


async def test_oauth_status_reads_inactive_workspace_without_starting_it(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.app.routers.mcp_oauth import router
    from qwenpaw.config.config import AgentProfileRef
    from qwenpaw.drivers.credentials.store import AsyncCredentialStore
    from qwenpaw.drivers.credentials.types import CredentialRecord
    from qwenpaw.plugins.testing import PluginTestHost
    from tests.unit.plugins.mcp.fixtures import PLUGIN

    async with PluginTestHost(tmp_path / "host") as host:
        await host.install(PLUGIN)
        host._http_app.state.plugin_loader = host._loader
        host._http_app.include_router(router, prefix="/api")
        workspace = host.root / "workspaces/saved-inactive"
        path = seed_card(workspace, enabled=False)
        config = utils.load_config()
        config.agents.profiles["saved-inactive"] = AgentProfileRef(
            id="saved-inactive",
            workspace_dir=str(workspace),
        )
        utils.save_config(config)
        store = AsyncCredentialStore(workspace / "credentials.yaml")
        await store.put(
            CredentialRecord(
                ref="mcp/retained/oauth",
                kind="oauth2_auth_code",
                public={"scope": "read", "expires_at": 4102444800},
                secrets={"access_token": "synthetic-access"},
            ),
        )
        before = path.read_bytes()
        start = AsyncMock(
            side_effect=AssertionError("OAuth status started workspace"),
        )
        monkeypatch.setattr(host._workspace_manager, "get_agent", start)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=host._http_app),
            base_url="http://testserver",
        ) as client:
            response = await client.get(
                "/api/mcp/oauth/status/retained",
                headers={"X-Agent-Id": "saved-inactive"},
            )
        assert response.status_code == 200, response.text
        assert response.json() == {
            "authorized": True,
            "expires_at": 4102444800,
            "scope": "read",
        }
        start.assert_not_awaited()
        assert not host._workspaces
        assert path.read_bytes() == before


@pytest.mark.parametrize("operation", ["create", "enable", "update"])
async def test_available_plugin_write_activates_inactive_workspace(
    tmp_path,
    monkeypatch,
    operation,
):
    """Explicit writes cross the real workspace/service-factory boundary.

    PluginTestHost intentionally starts no driver facade on workspace creation;
    its manager's lazy boundary therefore uses the production Task5 factory.
    Only the external MCP client endpoint is substituted.
    """
    import asyncio

    from qwenpaw.app.workspace.service_factories import create_driver_service
    from qwenpaw.config.config import AgentProfileRef
    from qwenpaw.plugins.testing import PluginTestHost
    from mcp.types import CallToolResult
    from tests.unit.plugins.mcp.fixtures import PLUGIN, Peer

    peer = Peer()
    peer.install(monkeypatch)
    peer.result = CallToolResult(
        content=[],
        structuredContent={"echo": {"message": "actual route write"}},
    )

    async with PluginTestHost(tmp_path / "host") as host:
        await host.install(PLUGIN)
        host._http_app.state.plugin_loader = host._loader
        host._http_app.include_router(mcp.router, prefix="/api")
        directory = host.root / "workspaces/inactive-write"
        config = utils.load_config()
        config.agents.profiles["inactive-write"] = AgentProfileRef(
            id="inactive-write",
            workspace_dir=str(directory),
        )
        utils.save_config(config)
        _seed_available_write_case(directory, operation)
        activated, published = [], []

        async def activate_workspace(agent_id):
            workspace = await host._workspace(agent_id)
            activated.append(workspace)
            if workspace.driver_manager is None:

                def publish(service):
                    published.append(service)
                    workspace._service_manager.services[
                        "driver_manager"
                    ] = service

                await create_driver_service(workspace, None, publish)
            return workspace

        monkeypatch.setattr(
            host._workspace_manager,
            "get_agent",
            activate_workspace,
        )
        headers = {"X-Agent-Id": "inactive-write"}
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=host._http_app),
                base_url="http://testserver",
            ) as client:
                assert (
                    await client.get("/api/mcp", headers=headers)
                ).status_code == 200
                assert not host._workspaces
                assert not activated
                assert not peer.opens
                if operation == "create":
                    response = await client.post(
                        "/api/mcp",
                        headers=headers,
                        json={
                            "client_key": "retained",
                            "client": {
                                "name": "Retained",
                                "transport": "stdio",
                                "command": "synthetic-mcp",
                                "enabled": True,
                            },
                        },
                    )
                    assert response.status_code == 201, response.text
                elif operation == "enable":
                    response = await client.patch(
                        "/api/mcp/toggle/retained",
                        headers=headers,
                    )
                    assert response.status_code == 200, response.text
                else:
                    response = await client.put(
                        "/api/mcp/retained",
                        headers=headers,
                        json={"command": "updated-mcp", "enabled": True},
                    )
                    assert response.status_code == 200, response.text
                assert activated, (
                    "Available-plugin explicit write never resolved "
                    "the real workspace"
                )
                workspace = host._workspaces["inactive-write"]
                assert activated == [workspace]
                assert published == [workspace.driver_manager]
                await _assert_active_mcp_client(
                    client,
                    headers,
                    workspace,
                    peer,
                    operation,
                )
        finally:
            for service in published:
                await asyncio.wait_for(service.shutdown_all(), 3)


def _seed_available_write_case(directory, operation):
    if operation == "create":
        return
    path = seed_card(directory, enabled=operation == "update")
    saved = load_card(path)
    saved.config["tools"] = ["echo"]
    saved.policy.default_effect = "allow"
    dump_card(saved, path)


async def _assert_active_mcp_client(
    client,
    headers,
    workspace,
    peer,
    operation,
):
    import asyncio
    from qwenpaw.drivers.capabilities import DriverInvocation

    runtime = workspace.driver_manager
    expected_command = {
        "create": "synthetic-mcp",
        "enable": "offline-command",
        "update": "updated-mcp",
    }[operation]
    async with asyncio.timeout(3):
        while not (
            peer.opens
            and peer.opens[-1][1].command == expected_command
            and any(
                row.status == "active"
                for row in await runtime.list_drivers(protocol="mcp")
            )
        ):
            await asyncio.sleep(0.005)
    assert runtime.manager is not None
    assert runtime.watcher is not None
    tools = await client.get(
        "/api/mcp/tools/retained",
        headers=headers,
    )
    assert tools.status_code == 200, tools.text
    assert "echo" in [tool["name"] for tool in tools.json()]
    policy = await client.put(
        "/api/mcp/policy/retained",
        headers=headers,
        json={
            "default_effect": "allow",
            "client_overrides": [],
            "tool_defaults": [],
            "tool_overrides": [],
            "unmanaged_rules_count": 0,
        },
    )
    assert policy.status_code == 200, policy.text
    capability = next(
        item
        for item in await runtime.list_driver_capabilities(
            "retained",
        )
        if item.name == "echo"
    )
    result = await runtime.invoke_capability(
        DriverInvocation(
            capability_id=capability.capability_id,
            payload={"message": "actual route write"},
            request_context={
                "channel": "console",
                "user_id": "alice",
            },
        ),
    )
    assert result.ok, result.message
    assert result.value.structured_content == {
        "echo": {"message": "actual route write"},
    }
    assert peer.calls == [
        ("echo", {"message": "actual route write"}),
    ]
    if operation == "update":
        assert peer.opens[-1][1].command == "updated-mcp"
