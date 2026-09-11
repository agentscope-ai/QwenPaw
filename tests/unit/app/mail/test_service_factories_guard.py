# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for the backend guard in create_mail_monitor_service."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

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


def test_qwenpaw_backend_still_starts_monitor(tmp_path):
    ws = _fake_workspace("qwenpaw", tmp_path)
    monitor, published = _create_monitor(ws)
    assert monitor is not None
    assert published == [monitor]
