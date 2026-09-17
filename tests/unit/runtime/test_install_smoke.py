# -*- coding: utf-8 -*-
"""Install / app startup smoke regression tests.

Regression for #5379: install must produce a working app.

After running the equivalent of ``qwenpaw init --defaults --accept-security``
the working dir must contain a valid, parseable ``config.json`` and the
FastAPI application must be importable and serve its critical routes
(GET /, GET /api/version) without raising Internal Server Error.
"""

# pylint: disable=protected-access,import-outside-toplevel
# pylint: disable=redefined-outer-name,unused-argument
# pylint: disable=consider-using-from-import,line-too-long
# pylint: disable=consider-using-with
# flake8: noqa: E501

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_app_module_state() -> object:
    """Prevent this module's ``from qwenpaw.app._app import app`` calls
    from leaking import state into sibling tests.

    ``test_app_factory_importable`` / ``test_critical_routes_return_200``
    import ``qwenpaw.app._app``, which leaves it in ``sys.modules`` for
    the rest of the worker. Later, ``tests/unit/tauri/test_entry.py::
    test_install_desktop_runtime_preserves_existing_cors_values`` calls
    ``_ensure_qwenpaw_app_not_loaded()``, which asserts the app module
    is NOT in ``sys.modules`` and raises ``RuntimeError`` if it is.
    Under ``pytest -n auto --dist=loadscope`` both tests land on the
    same worker (scope-grouped), so the polluted state reliably fails
    the tauri test in CI.

    Snapshot and restore every ``qwenpaw.app.*`` module entry so our
    imports stay local to these tests. (monkeypatch.setitem on
    sys.modules is the idiomatic way, but snapshot/restore covers the
    deletion case too.)
    """
    saved_app = sys.modules.get("qwenpaw.app._app")
    # Only isolate the heavy app factory module this test imports.
    # Blanket-deleting every qwenpaw.app.* (prior version) re-created
    # agent_context etc. as new module objects, which broke sibling
    # tests monkeypatching qwenpaw.app.agent_context.get_current_session_id
    # (their patch landed on the old object; _record_usage imported the
    # new one). Removing only _app avoids that cross-module aliasing.
    sys.modules.pop("qwenpaw.app._app", None)
    yield
    # teardown: drop the app factory our tests imported, restore prior
    sys.modules.pop("qwenpaw.app._app", None)
    if saved_app is not None:
        sys.modules["qwenpaw.app._app"] = saved_app


@pytest.fixture
def isolated_working_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Point QWENPAW at a clean tmp working dir for both constant & config.

    ``qwenpaw.constant.WORKING_DIR`` is read at import time, so we patch the
    already-imported module attribute as well as the consumers that cached it.
    """
    work_dir = tmp_path / "qwenpaw-home"
    work_dir.mkdir(parents=True, exist_ok=True)

    import qwenpaw.constant as constant
    import qwenpaw.config.utils as config_utils

    monkeypatch.setattr(constant, "WORKING_DIR", work_dir, raising=True)
    # ``config.utils`` imports WORKING_DIR symbol at module load — patch the
    # reference there too so ``get_config_path()`` returns the tmp path.
    if hasattr(config_utils, "WORKING_DIR"):
        monkeypatch.setattr(
            config_utils,
            "WORKING_DIR",
            work_dir,
            raising=True,
        )
    monkeypatch.setenv("QWENPAW_WORKING_DIR", str(work_dir))
    return work_dir


def test_init_defaults_produces_valid_config(
    isolated_working_dir: Path,
) -> None:
    """Regression for #5379: init --defaults --accept-security writes a
    parseable config.json that round-trips through Config validation."""
    # We replicate the config-writing contract of ``init_cmd`` rather than
    # invoking the full Click command (which performs telemetry + skill-pool
    # downloads that require network and would make the test fragile). The
    # bug in #5379 is that a freshly-initialised config left the app in a
    # broken state; this test pins that the written config is valid.
    from qwenpaw.config import Config, get_config_path, save_config
    from qwenpaw.config.config import AgentsDefaultsConfig, HeartbeatConfig
    from qwenpaw.constant import HEARTBEAT_DEFAULT_EVERY

    cfg = Config()
    if cfg.agents.defaults is None:
        cfg.agents.defaults = AgentsDefaultsConfig()
    cfg.agents.defaults.heartbeat = HeartbeatConfig(
        every=HEARTBEAT_DEFAULT_EVERY,
        target="main",
        active_hours=None,
    )
    cfg.show_tool_details = True

    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    save_config(cfg, config_path)

    assert config_path.exists(), "config.json was not written"
    raw = config_path.read_text(encoding="utf-8")
    parsed = json.loads(raw)  # must be valid JSON
    assert isinstance(parsed, dict)

    # Round-trip through Config to guarantee schema validity — this is what
    # the app does on startup and what was breaking in #5379.
    reloaded = Config.model_validate_json(raw)
    assert reloaded is not None


def test_app_factory_importable() -> None:
    """Regression for #5379: the FastAPI app object must be importable
    without raising (the app factory is what ``qwenpaw app`` serves)."""
    from qwenpaw.app._app import app  # noqa: F401

    assert app is not None


@pytest.mark.asyncio
async def test_critical_routes_return_200() -> None:
    """Regression for #5379: critical routes (GET /, GET /api/version) must
    return 200 via httpx.ASGITransport after a fresh install.

    These routes do not depend on lifespan-started state (no agent manager,
    no provider manager) so we can hit them without entering the lifespan,
    which keeps the test hermetic."""
    import httpx
    from qwenpaw.app._app import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        r_root = await client.get("/")
        assert r_root.status_code == 200, r_root.text

        r_version = await client.get("/api/version")
        assert r_version.status_code == 200, r_version.text
        body = r_version.json()
        assert "version" in body, body
