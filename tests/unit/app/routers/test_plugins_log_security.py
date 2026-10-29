# -*- coding: utf-8 -*-
"""Plugin lifecycle failures preserve diagnostics without forged log lines."""
from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from qwenpaw.app.routers import plugins


@pytest.mark.parametrize("enabled", [True, False])
async def test_enable_failure_sanitizes_exception_in_rendered_log(
    tmp_path,
    monkeypatch,
    caplog,
    enabled,
):
    plugin_id = "plug\r\nFORGED_PLUGIN"
    error = RuntimeError("disk\r\nFORGED_ERROR")
    lifecycle = SimpleNamespace(set_enabled=AsyncMock(side_effect=error))
    loader = SimpleNamespace(
        lifecycle=lifecycle,
        get_loaded_plugin=lambda _: object(),
    )
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(plugin_loader=loader)),
    )
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_plugins_dir",
        lambda: tmp_path,
    )
    with caplog.at_level(logging.ERROR, logger=plugins.__name__):
        with pytest.raises(HTTPException) as caught:
            await plugins.set_plugin_enabled(
                plugin_id,
                plugins.SetPluginEnabledRequest(enabled=enabled),
                request,
            )
    assert caught.value.status_code == 500
    lifecycle.set_enabled.assert_awaited_once_with(plugin_id, enabled)
    records = [r for r in caplog.records if r.name == plugins.__name__]
    assert len(records) == 1
    rendered = logging.Formatter("%(message)s").format(records[0])
    assert f"enabled={enabled}" in rendered
    assert "plugFORGED_PLUGIN" in rendered
    assert "diskFORGED_ERROR" in rendered
    assert "\r" not in rendered
    assert "\nFORGED_" not in rendered
