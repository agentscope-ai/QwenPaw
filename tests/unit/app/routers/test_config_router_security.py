# -*- coding: utf-8 -*-
"""Endpoint tests for config router: ACP, timezone, file guard,
skill-scanner whitelist, allow-no-auth-hosts, deny-paths protection.

Complements ``test_config_router.py`` (channels/heartbeat/tool-guard/
sandbox) by covering the remaining uncovered endpoints.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.exception_handlers import register_exception_handlers
from qwenpaw.app.routers.config import router as config_router
from qwenpaw.config.config import ACPAgentConfig, ACPConfig


def _root_transaction(config, calls=None):
    def mutate(mutator):
        mutator(config)
        if calls is not None:
            calls.append(config)
        return config

    return mutate


@pytest.fixture
def app() -> FastAPI:
    application = FastAPI()
    application.state.multi_agent_manager = MagicMock(name="ManagerStub")
    register_exception_handlers(application)
    application.include_router(config_router, prefix="/api")
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def fake_agent_workspace():
    workspace = MagicMock(name="Workspace")
    workspace.agent_id = "default"
    workspace.config = MagicMock(name="AgentConfig")
    workspace.config.acp = None
    return workspace


@pytest.fixture
def patch_get_agent(fake_agent_workspace):
    with patch(
        "qwenpaw.app.agent_context.get_agent_for_request",
        new=AsyncMock(return_value=fake_agent_workspace),
    ) as patched:
        yield patched


# ---------------------------------------------------------------------------
# ACP config endpoints
# ---------------------------------------------------------------------------


class TestAcpConfig:
    def test_get_acp_agent_config_returns_entry(
        self,
        client,
        patch_get_agent,
        fake_agent_workspace,
    ):
        fake_agent_workspace.config.acp = ACPConfig(
            agents={
                "opencode": ACPAgentConfig(
                    enabled=True,
                    command="opencode",
                ),
            },
        )
        response = client.get("/api/config/acp/opencode")
        assert response.status_code == 200
        body = response.json()
        assert body["enabled"] is True
        assert body["command"] == "opencode"

    def test_get_unknown_acp_agent_returns_404(
        self,
        client,
        patch_get_agent,
        fake_agent_workspace,
    ):
        fake_agent_workspace.config.acp = ACPConfig(agents={})
        response = client.get("/api/config/acp/ghost")
        assert response.status_code == 404

    def test_get_acp_agent_defaults_when_acp_none(
        self,
        client,
        patch_get_agent,
        fake_agent_workspace,
    ):
        fake_agent_workspace.config.acp = None
        response = client.get("/api/config/acp/opencode")
        assert response.status_code == 200
        assert response.json()["command"] == "opencode"

    def test_put_acp_agent_config_saves_and_reloads(
        self,
        client,
        patch_get_agent,
        fake_agent_workspace,
    ):
        fake_agent_workspace.config.acp = ACPConfig(agents={})
        with (
            patch(
                "qwenpaw.config.config.save_agent_config",
            ) as save_mock,
            patch(
                "qwenpaw.app.routers.config.schedule_agent_reload",
            ) as reload_mock,
        ):
            response = client.put(
                "/api/config/acp/myagent",
                json={
                    "enabled": True,
                    "command": "mybin",
                    "args": ["--acp"],
                    "tool_parse_mode": "call_title",
                },
            )
        assert response.status_code == 200
        assert response.json()["command"] == "mybin"
        assert "myagent" in fake_agent_workspace.config.acp.agents
        save_mock.assert_called_once()
        reload_mock.assert_called_once()

    def test_put_acp_agent_rejects_invalid_parse_mode(
        self,
        client,
        patch_get_agent,
    ):
        response = client.put(
            "/api/config/acp/myagent",
            json={
                "enabled": True,
                "command": "mybin",
                "tool_parse_mode": "bogus_mode",
            },
        )
        assert response.status_code == 400
        assert "tool_parse_mode" in response.json()["detail"]

    def test_put_acp_agent_whitespace_name_returns_400(
        self,
        client,
        patch_get_agent,
        fake_agent_workspace,
    ):
        fake_agent_workspace.config.acp = ACPConfig(agents={})
        response = client.put(
            "/api/config/acp/%20%20",
            json={
                "enabled": True,
                "command": "mybin",
                "tool_parse_mode": "call_title",
            },
        )
        assert response.status_code == 400

    def test_put_acp_config_replaces_and_saves(
        self,
        client,
        patch_get_agent,
        fake_agent_workspace,
    ):
        with (
            patch(
                "qwenpaw.config.config.save_agent_config",
            ) as save_mock,
            patch(
                "qwenpaw.app.routers.config.schedule_agent_reload",
            ),
        ):
            response = client.put(
                "/api/config/acp",
                json={"node_path": "/usr/bin/node", "agents": {}},
            )
        assert response.status_code == 200
        assert response.json()["node_path"] == "/usr/bin/node"
        assert fake_agent_workspace.config.acp.node_path == "/usr/bin/node"
        save_mock.assert_called_once()


class TestAcpNodeRuntime:
    def test_get_node_runtime(self, client):
        fake_cfg = MagicMock()
        fake_cfg.acp.node_path = ""
        status = SimpleNamespace(
            node_path="",
            effective_node_path="/usr/bin/node",
            candidates=[],
        )
        with (
            patch(
                "qwenpaw.app.routers.config.load_config",
                return_value=fake_cfg,
            ),
            patch(
                "qwenpaw.app.routers.config.get_node_runtime_status",
                return_value=status,
            ),
        ):
            response = client.get("/api/config/acp/node-runtime")
        assert response.status_code == 200
        assert response.json()["effective_node_path"] == "/usr/bin/node"

    def test_put_node_runtime_validates_unavailable_path(self, client):
        candidate = SimpleNamespace(
            available=False,
            reason_code="not_found",
            reason="no such file",
        )
        with patch(
            "qwenpaw.app.routers.config.resolve_node_runtime",
            return_value=candidate,
        ):
            response = client.put(
                "/api/config/acp/node-runtime",
                json={"node_path": "/missing/node"},
            )
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert detail["reason_code"] == "not_found"

    def test_put_node_runtime_accepts_valid_path(self, client):
        candidate = SimpleNamespace(available=True, reason_code="ok")
        status = SimpleNamespace(
            node_path="/usr/bin/node",
            effective_node_path="/usr/bin/node",
            candidates=[],
        )
        fake_cfg = MagicMock()
        fake_cfg.acp = SimpleNamespace(node_path="")
        calls = []
        with (
            patch(
                "qwenpaw.app.routers.config.resolve_node_runtime",
                return_value=candidate,
            ),
            patch(
                "qwenpaw.app.routers.config.mutate_config",
                side_effect=_root_transaction(fake_cfg, calls),
            ),
            patch(
                "qwenpaw.app.routers.config.get_node_runtime_status",
                return_value=status,
            ),
        ):
            response = client.put(
                "/api/config/acp/node-runtime",
                json={"node_path": "/usr/bin/node"},
            )
        assert response.status_code == 200
        assert fake_cfg.acp.node_path == "/usr/bin/node"
        assert calls == [fake_cfg]

    def test_put_node_runtime_empty_path_clears(self, client):
        status = SimpleNamespace(
            node_path="",
            effective_node_path="",
            candidates=[],
        )
        fake_cfg = MagicMock()
        fake_cfg.acp = SimpleNamespace(node_path="/old/node")
        with (
            patch(
                "qwenpaw.app.routers.config.resolve_node_runtime",
            ) as resolve_mock,
            patch(
                "qwenpaw.app.routers.config.mutate_config",
                side_effect=_root_transaction(fake_cfg),
            ),
            patch(
                "qwenpaw.app.routers.config.get_node_runtime_status",
                return_value=status,
            ),
        ):
            response = client.put(
                "/api/config/acp/node-runtime",
                json={"node_path": "   "},
            )
        assert response.status_code == 200
        resolve_mock.assert_not_called()
        assert fake_cfg.acp.node_path == ""


# ---------------------------------------------------------------------------
# user timezone
# ---------------------------------------------------------------------------


class TestUserTimezone:
    def test_get_timezone(self, client):
        fake_cfg = MagicMock()
        fake_cfg.user_timezone = "Asia/Shanghai"
        with patch(
            "qwenpaw.app.routers.config.load_config",
            return_value=fake_cfg,
        ):
            response = client.get("/api/config/user-timezone")
        assert response.status_code == 200
        assert response.json() == {"timezone": "Asia/Shanghai"}

    def test_put_timezone_normalizes_and_saves(self, client):
        fake_cfg = MagicMock()
        fake_cfg.user_timezone = ""
        calls = []
        with patch(
            "qwenpaw.app.routers.config.mutate_config",
            side_effect=_root_transaction(fake_cfg, calls),
        ):
            response = client.put(
                "/api/config/user-timezone",
                json={"timezone": "UTC"},
            )
        assert response.status_code == 200
        assert response.json()["timezone"] == "UTC"
        assert fake_cfg.user_timezone == "UTC"
        assert calls == [fake_cfg]

    def test_put_timezone_empty_returns_400(self, client):
        response = client.put(
            "/api/config/user-timezone",
            json={"timezone": "  "},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "timezone is required"

    def test_put_timezone_invalid_returns_400(self, client):
        response = client.put(
            "/api/config/user-timezone",
            json={"timezone": "Mars/Olympus"},
        )
        assert response.status_code == 400
        assert "Invalid IANA timezone" in response.json()["detail"]


# ---------------------------------------------------------------------------
# LLM routing
# ---------------------------------------------------------------------------


class TestAgentsLlmRouting:
    def test_get_routing(self, client):
        fake_cfg = MagicMock()
        fake_cfg.agents.llm_routing = {"default_provider": "dashscope"}
        with patch(
            "qwenpaw.app.routers.config.load_config",
            return_value=fake_cfg,
        ):
            response = client.get("/api/config/agents/llm-routing")
        assert response.status_code == 200

    def test_put_routing_saves(self, client):
        fake_cfg = MagicMock()
        calls = []
        body = client
        from qwenpaw.config.config import AgentsLLMRoutingConfig

        routing = AgentsLLMRoutingConfig()
        with patch(
            "qwenpaw.app.routers.config.mutate_config",
            side_effect=_root_transaction(fake_cfg, calls),
        ):
            response = client.put(
                "/api/config/agents/llm-routing",
                json=routing.model_dump(mode="json"),
            )
        assert response.status_code == 200
        assert fake_cfg.agents.llm_routing == routing
        assert calls == [fake_cfg]


# ---------------------------------------------------------------------------
# run heartbeat now
# ---------------------------------------------------------------------------


class TestRunHeartbeatNow:
    def test_starts_background_task(
        self,
        client,
        patch_get_agent,
        fake_agent_workspace,
    ):
        created: list = []

        def fake_create_task(coro):
            created.append(coro)
            coro.close()  # avoid RuntimeWarning; we do not run it
            return MagicMock()

        with patch("asyncio.create_task", side_effect=fake_create_task):
            response = client.post("/api/config/heartbeat/run")
        assert response.status_code == 200
        assert response.json() == {"started": True}
        assert len(created) == 1


# ---------------------------------------------------------------------------
# file guard
# ---------------------------------------------------------------------------


class TestFileGuard:
    def test_get_file_guard(self, client):
        fake_cfg = MagicMock()
        fake_cfg.security.file_guard = SimpleNamespace(
            enabled=True,
            sensitive_files=["/etc/passwd"],
            allow_preview_outside_workspace=False,
        )
        with patch(
            "qwenpaw.app.routers.config.load_config",
            return_value=fake_cfg,
        ):
            response = client.get("/api/config/security/file-guard")
        assert response.status_code == 200
        body = response.json()
        assert body["enabled"] is True
        assert "/etc/passwd" in body["paths"]

    def test_put_file_guard_applies_all_fields(self, client):
        fake_cfg = MagicMock()
        file_guard = SimpleNamespace(
            enabled=False,
            sensitive_files=[],
            allow_preview_outside_workspace=False,
        )
        fake_cfg.security.file_guard = file_guard
        engine = MagicMock()
        calls = []
        with (
            patch(
                "qwenpaw.app.routers.config.mutate_config",
                side_effect=_root_transaction(fake_cfg, calls),
            ),
            patch(
                "qwenpaw.security.tool_guard.guardians.file_guardian.ensure_file_guard_paths",
                side_effect=lambda paths: sorted(set(paths)),
            ),
            patch(
                "qwenpaw.security.tool_guard.engine.get_guard_engine",
                return_value=engine,
            ),
        ):
            response = client.put(
                "/api/config/security/file-guard",
                json={
                    "enabled": True,
                    "paths": ["/secrets/a", "/secrets/b"],
                    "allow_preview_outside_workspace": True,
                },
            )
        assert response.status_code == 200
        body = response.json()
        assert body["enabled"] is True
        assert body["paths"] == ["/secrets/a", "/secrets/b"]
        assert body["allow_preview_outside_workspace"] is True
        assert file_guard.enabled is True
        engine.reload_rules.assert_called_once()
        assert calls == [fake_cfg]

    def test_put_file_guard_partial_update_keeps_others(self, client):
        fake_cfg = MagicMock()
        file_guard = SimpleNamespace(
            enabled=True,
            sensitive_files=["/keep"],
            allow_preview_outside_workspace=True,
        )
        fake_cfg.security.file_guard = file_guard
        engine = MagicMock()
        with (
            patch(
                "qwenpaw.app.routers.config.mutate_config",
                side_effect=_root_transaction(fake_cfg),
            ),
            patch(
                "qwenpaw.security.tool_guard.engine.get_guard_engine",
                return_value=engine,
            ),
        ):
            response = client.put(
                "/api/config/security/file-guard",
                json={"enabled": False},
            )
        assert response.status_code == 200
        assert file_guard.enabled is False
        assert file_guard.sensitive_files == ["/keep"]
        assert file_guard.allow_preview_outside_workspace is True


# ---------------------------------------------------------------------------
# deny paths protection (force the non-Windows branch regardless of the
# test host platform — the endpoint imports ``sys`` locally, so patching
# the global sys.platform applies)
# ---------------------------------------------------------------------------


class TestDenyPathsProtection:
    def test_get_unsupported_platform(self, client, monkeypatch):
        import sys as _sys

        monkeypatch.setattr(_sys, "platform", "linux")
        response = client.get(
            "/api/config/security/sandbox/deny-paths-protection",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["active"] is False
        assert body["platform_supported"] is False

    def test_put_unsupported_platform(self, client, monkeypatch):
        import sys as _sys

        monkeypatch.setattr(_sys, "platform", "linux")
        response = client.put(
            "/api/config/security/sandbox/deny-paths-protection",
            json={"enabled": True},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["active"] is False
        assert body["platform_supported"] is False
        assert "Windows" in body["message"]


# ---------------------------------------------------------------------------
# skill scanner whitelist
# ---------------------------------------------------------------------------


def _scanner_config_with_whitelist(entries):
    fake_cfg = MagicMock()
    fake_cfg.security.skill_scanner.whitelist = list(entries)
    return fake_cfg


class TestSkillScannerWhitelist:
    def test_add_to_whitelist(self, client):
        from qwenpaw.config.config import SkillScannerWhitelistEntry

        fake_cfg = _scanner_config_with_whitelist([])
        calls = []
        with patch(
            "qwenpaw.app.routers.config.mutate_config",
            side_effect=_root_transaction(fake_cfg, calls),
        ):
            response = client.post(
                "/api/config/security/skill-scanner/whitelist",
                json={"skill_name": "my_skill", "content_hash": "abc123"},
            )
        assert response.status_code == 200
        assert response.json() == {
            "whitelisted": True,
            "skill_name": "my_skill",
        }
        whitelist = fake_cfg.security.skill_scanner.whitelist
        assert len(whitelist) == 1
        assert isinstance(whitelist[0], SkillScannerWhitelistEntry)
        assert whitelist[0].content_hash == "abc123"
        assert whitelist[0].added_at

    def test_add_duplicate_returns_409(self, client):
        from qwenpaw.config.config import SkillScannerWhitelistEntry

        existing = SkillScannerWhitelistEntry(
            skill_name="dup_skill",
            content_hash="old",
            added_at="2026-01-01T00:00:00+00:00",
        )
        fake_cfg = _scanner_config_with_whitelist([existing])
        with patch(
            "qwenpaw.app.routers.config.mutate_config",
            side_effect=_root_transaction(fake_cfg),
        ):
            response = client.post(
                "/api/config/security/skill-scanner/whitelist",
                json={"skill_name": "  dup_skill  "},
            )
        assert response.status_code == 409
        assert "already whitelisted" in response.json()["detail"]

    def test_add_empty_name_returns_400(self, client):
        response = client.post(
            "/api/config/security/skill-scanner/whitelist",
            json={"skill_name": "   "},
        )
        assert response.status_code == 400

    def test_remove_from_whitelist(self, client):
        from qwenpaw.config.config import SkillScannerWhitelistEntry

        entries = [
            SkillScannerWhitelistEntry(
                skill_name="keep_me",
                added_at="2026-01-01T00:00:00+00:00",
            ),
            SkillScannerWhitelistEntry(
                skill_name="drop_me",
                added_at="2026-01-01T00:00:00+00:00",
            ),
        ]
        fake_cfg = _scanner_config_with_whitelist(entries)
        with patch(
            "qwenpaw.app.routers.config.mutate_config",
            side_effect=_root_transaction(fake_cfg),
        ):
            response = client.delete(
                "/api/config/security/skill-scanner/whitelist/drop_me",
            )
        assert response.status_code == 200
        assert response.json() == {"removed": True, "skill_name": "drop_me"}
        remaining = fake_cfg.security.skill_scanner.whitelist
        assert [entry.skill_name for entry in remaining] == ["keep_me"]

    def test_remove_missing_returns_404(self, client):
        fake_cfg = _scanner_config_with_whitelist([])
        with patch(
            "qwenpaw.app.routers.config.mutate_config",
            side_effect=_root_transaction(fake_cfg),
        ):
            response = client.delete(
                "/api/config/security/skill-scanner/whitelist/ghost",
            )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# allow no auth hosts
# ---------------------------------------------------------------------------


class TestAllowNoAuthHosts:
    def test_get_hosts(self, client):
        fake_cfg = MagicMock()
        fake_cfg.security.allow_no_auth_hosts = ["127.0.0.1", "::1"]
        with patch(
            "qwenpaw.app.routers.config.load_config",
            return_value=fake_cfg,
        ):
            response = client.get("/api/config/security/allow-no-auth-hosts")
        assert response.status_code == 200
        assert response.json()["hosts"] == ["127.0.0.1", "::1"]

    def test_put_normalizes_deduplicates_and_saves(self, client):
        fake_cfg = MagicMock()
        fake_cfg.security.allow_no_auth_hosts = []
        calls = []
        with patch(
            "qwenpaw.app.routers.config.mutate_config",
            side_effect=_root_transaction(fake_cfg, calls),
        ):
            response = client.put(
                "/api/config/security/allow-no-auth-hosts",
                json={
                    "hosts": [
                        " 127.0.0.1 ",
                        "127.0.0.1",
                        "",
                        "2001:0db8:0000:0000:0000:0000:0000:0001",
                    ],
                },
            )
        assert response.status_code == 200
        saved = fake_cfg.security.allow_no_auth_hosts
        # IPv6 is compressed to canonical form.
        assert saved == ["127.0.0.1", "2001:db8::1"]
        assert calls == [fake_cfg]

    def test_put_invalid_ip_returns_400(self, client):
        response = client.put(
            "/api/config/security/allow-no-auth-hosts",
            json={"hosts": ["127.0.0.1", "not-an-ip", "999.1.1.1"]},
        )
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert "not-an-ip" in detail
        assert "999.1.1.1" in detail
