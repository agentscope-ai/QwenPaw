# -*- coding: utf-8 -*-
"""多用户启动时旧智能体治理同步的装配测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.app import _app


@pytest.mark.asyncio
async def test_startup_sync_uses_current_identity_schema(monkeypatch) -> None:
    config = SimpleNamespace(agents=SimpleNamespace(profiles={}))
    repository = object()
    captured: dict[str, object] = {}

    monkeypatch.setattr(_app, "load_config", lambda: config)
    monkeypatch.setattr(_app, "get_identity_schema", lambda: "tenant_schema")
    monkeypatch.setattr(
        _app,
        "PostgresAgentRepository",
        lambda *, schema: repository if schema == "tenant_schema" else None,
    )

    async def synchronize(**kwargs) -> int:
        captured.update(kwargs)
        return 2

    monkeypatch.setattr(_app, "synchronize_legacy_agent_governance", synchronize)

    count = await _app._synchronize_legacy_agent_governance_on_startup()

    assert count == 2
    assert captured == {"config": config, "repository": repository}


@pytest.mark.asyncio
async def test_startup_model_mode_sync_uses_current_identity_schema(
    monkeypatch,
) -> None:
    config = SimpleNamespace(agents=SimpleNamespace(profiles={}))
    repository = object()
    captured: dict[str, object] = {}

    monkeypatch.setattr(_app, "load_config", lambda: config)
    monkeypatch.setattr(_app, "get_identity_schema", lambda: "tenant_schema")
    monkeypatch.setattr(
        _app,
        "PostgresAgentRepository",
        lambda *, schema: repository if schema == "tenant_schema" else None,
    )

    async def synchronize(**kwargs) -> int:
        captured.update(kwargs)
        return 3

    monkeypatch.setattr(_app, "synchronize_agent_model_modes", synchronize)

    count = await _app._synchronize_agent_model_modes_on_startup()

    assert count == 3
    assert captured == {"config": config, "repository": repository}
