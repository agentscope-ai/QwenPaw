# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for the backend guard in create_mail_monitor_service."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from qwenpaw.app.workspace.service_factories import (
    create_mail_monitor_service,
)
from qwenpaw.config.config import (
    AgentMailConfig,
    AgentMailCredential,
    AgentMailPushConfig,
)


def _mail_config() -> AgentMailConfig:
    return AgentMailConfig(
        is_new_account=False,
        credential=AgentMailCredential(
            name="tester",
            domain="163.com",
            auth_code="a" * 16,
            password="pw",
            phone_number="13800000000",
        ),
        push=AgentMailPushConfig(mode="agent_all"),
    )


def _fake_workspace(backend: str, tmp_path) -> SimpleNamespace:
    return SimpleNamespace(
        agent_id="agent-1",
        workspace_dir=str(tmp_path),
        _config=SimpleNamespace(backend=backend, mail=_mail_config()),
        _service_manager=SimpleNamespace(services={}),
    )


def _create_monitor(ws):
    published = []
    monitor = asyncio.run(
        create_mail_monitor_service(ws, None, published.append),
    )
    return monitor, published


def test_third_party_backend_never_starts_monitor(tmp_path):
    ws = _fake_workspace("claude_code", tmp_path)
    monitor, published = _create_monitor(ws)
    assert monitor is None
    assert not published


def test_qwenpaw_backend_still_starts_monitor(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "qwenpaw.app.mcp.feature_gate.is_mcp_ready",
        lambda **_kwargs: True,
    )
    ws = _fake_workspace("qwenpaw", tmp_path)
    monitor, published = _create_monitor(ws)
    assert monitor is not None
    assert published == [monitor]


@pytest.mark.parametrize(
    "raw, expected",
    [
        (
            {"mail": {"credential": {"name": "tester", "domain": "163.com"}}},
            "configured",
        ),
        (
            {
                "tools": {
                    "builtin_tools": {
                        "delegate_external_agent": {"enabled": True},
                    },
                },
            },
            "configured",
        ),
        (
            {
                "acp": {
                    "agents": {
                        "reviewer": {"enabled": True, "command": "runner"},
                    },
                },
            },
            "configured",
        ),
        (
            {
                "acp": {
                    "agents": {
                        "opencode": {
                            "enabled": True,
                            "command": "opencode",
                            "args": ["acp"],
                        },
                    },
                },
            },
            "unused",
        ),
    ],
)
def test_mail_and_acp_history_prepare_mcp_without_loading_workspace(
    tmp_path,
    raw,
    expected,
):
    from qwenpaw.app.mcp_plugin_migration import classify_mcp_usage
    from qwenpaw.app.mcp_plugin_upgrade import inventory_mcp_usage

    config = tmp_path / "config.json"
    config.write_text(json.dumps(raw))
    decision = classify_mcp_usage(
        inventory_mcp_usage(
            config_path=config,
            plugins_dir=tmp_path / "plugins",
        ),
    )
    assert decision.status == expected


def test_mail_monitor_is_not_created_without_mcp(tmp_path):
    monitor, published = _create_monitor(_fake_workspace("qwenpaw", tmp_path))
    assert monitor is None
    assert not published
    assert not (tmp_path / "MAIL_TRIAGE.md").exists()


@pytest.mark.asyncio
async def test_healthy_mcp_mail_check_does_not_reenter_installation(
    tmp_path,
    monkeypatch,
):
    from pathlib import Path
    from unittest.mock import AsyncMock
    from qwenpaw.app.mcp.feature_gate import reconcile_mcp_features
    from qwenpaw.app.driver_runtime_service import LazyDriverService
    from qwenpaw.app import mcp_plugin_upgrade
    from qwenpaw.plugins.testing import PluginTestHost

    async with PluginTestHost(tmp_path / "host") as host:
        from qwenpaw.app.mcp.feature_gate import is_mcp_ready

        workspace = await host._workspace("mail")
        workspace._started = True
        workspace.workspace_dir.mkdir(parents=True, exist_ok=True)
        (workspace.workspace_dir / "agent.json").write_text(
            json.dumps(
                {
                    "mail": {
                        "credential": {"name": "tester", "domain": "163.com"},
                    },
                    "mcp": {"clients": {}},
                },
            ),
        )
        migrate = AsyncMock()
        monkeypatch.setattr(
            "qwenpaw.drivers.adapters.mcp_legacy_config.migrate_legacy_mcp_if_needed",
            migrate,
        )
        starts = []

        async def start():
            # Model the monitor's own admission; projection is precommit.
            if is_mcp_ready(host._loader, "mail"):
                starts.append("started")

        monitor = SimpleNamespace(start=start, stop=AsyncMock())
        workspace._service_manager.services["mail_monitor"] = monitor
        workspace._service_manager.services[
            "driver_manager"
        ] = LazyDriverService(
            workspace,
            registry=host._loader.registry,
        )
        coordinator = mcp_plugin_upgrade.get_coordinator(host._loader)
        source = Path(__file__).resolve().parents[4] / "plugins/protocol/mcp"
        monkeypatch.setattr(
            mcp_plugin_upgrade,
            "get_optional_mcp_plugin_dir",
            lambda: source,
        )
        await coordinator.ensure_protocol("mcp")
        assert starts == ["started"]
        migrate.assert_not_awaited()

        def unexpected_inventory(**_kwargs):
            raise AssertionError("Healthy MCP must not reenter migration")

        monkeypatch.setattr(
            mcp_plugin_upgrade,
            "inventory_mcp_usage",
            unexpected_inventory,
        )
        await coordinator.ensure_protocol("mcp")
        assert starts == ["started"]
        assert "qwenpaw-mcp" not in host._loader.startup_blocked_plugins
        await host.set_enabled("qwenpaw-mcp", False)
        monitor.stop.assert_awaited_once()
        await host.set_enabled("qwenpaw-mcp", True)
        await reconcile_mcp_features(host._loader, "qwenpaw-mcp")
        assert starts == ["started", "started"]
        # This test double owns no worker; leave no workspace service behind.
        workspace._service_manager.services.pop("mail_monitor")
        await workspace.driver_manager.shutdown_all()
