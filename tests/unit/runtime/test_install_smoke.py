# -*- coding: utf-8 -*-
"""Install / app startup smoke regression tests.

Regression for #5379: install must produce a working app.

After running the equivalent of ``qwenpaw init --defaults --accept-security``
the working dir must contain a valid, parseable ``config.json`` and the
FastAPI application must be importable and serve its critical routes
(GET /, GET /api/version) without raising Internal Server Error.

The Windows ProactorEventLoop test (``test_uvicorn_real_server_windows``)
launches a real uvicorn subprocess to verify the ``get_remote_addr``
transport code path that caused #5379 — ASGI test clients bypass
uvicorn's transport layer entirely, so only a real server can catch
this class of bug.
"""

# pylint: disable=protected-access,import-outside-toplevel,redefined-outer-name,unused-argument,consider-using-from-import  # noqa: E501

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest


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


# ---------------------------------------------------------------------------
# Windows ProactorEventLoop regression — #5379
#
# On Windows + Python 3.12+, ``ProactorEventLoop``'s
# ``transport.get_extra_info("peername")`` can return corrupted data
# (port as bytes instead of int), causing uvicorn's ``get_remote_addr``
# to raise ``ValueError`` → Starlette URL builder crashes → 500.
#
# This test launches a **real uvicorn subprocess** (not an ASGI test
# client) to exercise the actual transport code path. The existing
# ``test_critical_routes_return_200`` above uses ``httpx.ASGITransport``
# which bypasses uvicorn entirely and cannot catch this.
# ---------------------------------------------------------------------------


def _find_free_port() -> int:
    """Return a free TCP port for the subprocess server to bind."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="#5379 is Windows ProactorEventLoop specific; "
    "uvicorn transport corruption does not occur on Linux/macOS",
)
def test_uvicorn_real_server_serves_on_windows(
    isolated_working_dir: Path,
) -> None:
    """Regression for #5379: a real uvicorn server must start and serve
    ``GET /`` without ``Internal Server Error`` on Windows.

    This test launches ``python -m uvicorn qwenpaw.app._app:app`` as a
    subprocess, polls the port until the server is ready (or times out),
    and sends a real HTTP request to verify the full
    transport → uvicorn → Starlette → FastAPI chain works.

    The ASGI test client above bypasses uvicorn's transport layer;
    only a real server exercises ``get_remote_addr``.
    """
    import urllib.request
    import urllib.error

    port = _find_free_port()
    url = f"http://127.0.0.1:{port}/"

    env = os.environ.copy()
    env["QWENPAW_WORKING_DIR"] = str(isolated_working_dir)
    env["QWENPAW_AUTH_ENABLED"] = "false"

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "qwenpaw.app._app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-access-log",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
    )

    try:
        # Poll the server until it responds (30s timeout — agent loading
        # can be slow on Windows CI runners).
        deadline = time.monotonic() + 30
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                # Process exited early — capture output for diagnostics.
                output = proc.stdout.read() if proc.stdout else b""
                pytest.fail(
                    f"uvicorn subprocess exited early (code={proc.returncode}). "
                    f"Output:\n{output.decode('utf-8', errors='replace')[:2000]}",
                )
            try:
                with urllib.request.urlopen(url, timeout=3) as resp:
                    assert resp.status == 200, (
                        f"Expected 200, got {resp.status}: "
                        f"{resp.read().decode('utf-8', errors='replace')[:500]}"
                    )
                return  # success — server is serving
            except (urllib.error.URLError, ConnectionError, OSError) as exc:
                last_error = exc
                time.sleep(0.5)

        pytest.fail(
            f"uvicorn server did not become ready within 30s. "
            f"Last error: {last_error}",
        )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
