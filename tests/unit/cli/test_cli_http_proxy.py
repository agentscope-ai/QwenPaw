# -*- coding: utf-8 -*-
from __future__ import annotations

from qwenpaw.agents.tools import agent_management
from qwenpaw.cli import http as cli_http


# CLI API clients hit the local QwenPaw service, so loopback URLs skip proxies.
def test_cli_http_client_bypasses_env_for_loopback(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_client(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(cli_http.httpx, "Client", _fake_client)

    cli_http.client("http://127.1.2.3:8088")

    assert captured["trust_env"] is False


# Explicit remote API targets should still honor the user's proxy env.
def test_cli_http_client_keeps_env_for_remote_base_url(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_client(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(cli_http.httpx, "Client", _fake_client)

    cli_http.client("http://192.168.1.10:8088")

    assert captured["trust_env"] is True


# Agent-management API helpers share the same local API proxy policy.
def test_agent_api_client_bypasses_env_for_loopback(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_client(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(agent_management.httpx, "Client", _fake_client)

    agent_management.create_agent_api_client("http://localhost:8088")

    assert captured["trust_env"] is False
