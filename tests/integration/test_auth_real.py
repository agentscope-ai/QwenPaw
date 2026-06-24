# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
# -*- coding: utf-8 -*-
"""Auth=true real-link integration tests — Sprint 3.4-A.

Spawns a dedicated subprocess with QWENPAW_AUTH_ENABLED=true and
seeded credentials, then exercises:
  A1 GET /api/auth/status reflects auth enabled + has_users
  A2 POST /api/auth/login with correct credentials returns token
  A3 POST /api/auth/login with wrong password returns 401
  A4 Protected endpoint without token returns 401
  A5 Protected endpoint with valid Bearer token returns 200
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import Iterator

import httpx
import pytest


_HTTP_TIMEOUT = 15.0
_AUTH_USERNAME = "integ-admin"
_AUTH_PASSWORD = "integ-pass-12345"


@dataclass
class _AuthAppServer:
    host: str
    port: int
    client: httpx.Client
    logs: list[str]

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def get(self, path: str, **kwargs):
        return self.client.get(f"{self.base_url}{path}", **kwargs)

    def post(self, path: str, **kwargs):
        return self.client.post(f"{self.base_url}{path}", **kwargs)


def _find_free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        sock.listen(1)
        return sock.getsockname()[1]


def _tee(stream, buf: list[str]) -> None:
    for line in stream:
        buf.append(line)


@pytest.fixture(scope="module")
def auth_app_server(  # pylint: disable=too-many-statements
    tmp_path_factory,
) -> Iterator[_AuthAppServer]:
    """Spawn a qwenpaw app subprocess with auth=true + seeded user."""
    tmp_path = tmp_path_factory.mktemp("auth_app_server")
    host = "127.0.0.1"
    port = _find_free_port(host)

    working_dir = tmp_path / "working"
    secret_dir = tmp_path / "working.secret"
    backups_dir = tmp_path / "working.backups"
    working_dir.mkdir(parents=True, exist_ok=True)
    secret_dir.mkdir(parents=True, exist_ok=True)
    backups_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    for key in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "DASHSCOPE_API_KEY",
    ):
        env.pop(key, None)
    env["QWENPAW_WORKING_DIR"] = str(working_dir)
    env["QWENPAW_SECRET_DIR"] = str(secret_dir)
    env["QWENPAW_BACKUP_DIR"] = str(backups_dir)
    env["QWENPAW_AUTH_ENABLED"] = "true"
    env["QWENPAW_AUTH_USERNAME"] = _AUTH_USERNAME
    env["QWENPAW_AUTH_PASSWORD"] = _AUTH_PASSWORD
    env["QWENPAW_UPLOAD_MAX_SIZE_MB"] = "10"
    env["NO_PROXY"] = "*"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    logs: list[str] = []
    with subprocess.Popen(
        [
            sys.executable,
            "-m",
            "qwenpaw",
            "app",
            "--host",
            host,
            "--port",
            str(port),
            "--log-level",
            "info",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
        env=env,
    ) as process:
        assert process.stdout is not None
        log_thread = threading.Thread(
            target=_tee,
            args=(process.stdout, logs),
            daemon=True,
        )
        log_thread.start()

        client = httpx.Client(timeout=_HTTP_TIMEOUT, trust_env=False)
        try:
            deadline = time.time() + 60.0
            ready = False
            while time.time() < deadline:
                if process.poll() is not None:
                    raise AssertionError(
                        "qwenpaw app exited during startup\n"
                        f"logs:\n{''.join(logs)[-3000:]}",
                    )
                try:
                    r = client.get(
                        f"http://{host}:{port}/api/version",
                    )
                    if r.status_code == 200:
                        ready = True
                        break
                except (httpx.ConnectError, httpx.TimeoutException):
                    pass
                time.sleep(0.5)
            if not ready:
                raise AssertionError(
                    f"app not ready in time:\n" f"{''.join(logs)[-3000:]}",
                )

            yield _AuthAppServer(
                host=host,
                port=port,
                client=client,
                logs=logs,
            )
        finally:
            client.close()
            try:
                if sys.platform != "win32":
                    process.send_signal(2)  # SIGINT
                else:
                    process.terminate()
                process.wait(timeout=15)
            except Exception:
                process.kill()
                process.wait(timeout=5)
            shutil.rmtree(tmp_path, ignore_errors=True)


# ------------------------------------------------------------------ #
# A. Auth=true tests
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_auth_status_reports_enabled_after_auto_register(
    auth_app_server,
) -> None:
    """Test purpose:
    - Verify GET /api/auth/status reports auth enabled and has_users=true
      after auto_register_from_env() seeds the credentials.

    API endpoints:
    - GET /api/auth/status (public)
    """
    resp = auth_app_server.get(
        "/api/auth/status",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("enabled") is True, body
    assert body.get("has_users") is True, body


@pytest.mark.integration
@pytest.mark.p0
def test_auth_login_success_returns_token(auth_app_server) -> None:
    """Test purpose:
    - Verify POST /api/auth/login with correct credentials returns a
      non-empty token.

    API endpoints:
    - POST /api/auth/login (public)
    """
    resp = auth_app_server.post(
        "/api/auth/login",
        json={
            "username": _AUTH_USERNAME,
            "password": _AUTH_PASSWORD,
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    token = body.get("token")
    assert isinstance(token, str) and token, body
    assert body.get("username") == _AUTH_USERNAME, body


@pytest.mark.integration
@pytest.mark.p1
def test_auth_login_wrong_password_returns_401(auth_app_server) -> None:
    """Test purpose:
    - Verify POST /api/auth/login with wrong password returns 401.

    API endpoints:
    - POST /api/auth/login
    """
    resp = auth_app_server.post(
        "/api/auth/login",
        json={
            "username": _AUTH_USERNAME,
            "password": "definitely-wrong",
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 401, resp.text


@pytest.mark.integration
@pytest.mark.p0
def test_protected_endpoint_without_token_returns_401(
    auth_app_server,
) -> None:
    """Test purpose:
    - Verify GET /api/agents (protected) returns 401 without a token.
      Use X-Forwarded-For to simulate a non-localhost client (default
      allow_no_auth_hosts whitelists 127.0.0.1/::1).

    API endpoints:
    - GET /api/agents
    """
    resp = auth_app_server.get(
        "/api/agents",
        headers={"X-Forwarded-For": "203.0.113.7"},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 401, resp.text


@pytest.mark.integration
@pytest.mark.p0
def test_protected_endpoint_with_valid_token_returns_200(
    auth_app_server,
) -> None:
    """Test purpose:
    - Verify GET /api/agents with a valid Bearer token returns 200.
      Uses X-Forwarded-For so the no-auth-hosts whitelist does not
      mask the test (otherwise localhost would pass without a token).

    Test flow:
    1. POST /api/auth/login → obtain token.
    2. GET /api/agents with Authorization: Bearer <token> → 200.

    API endpoints:
    - POST /api/auth/login
    - GET  /api/agents
    """
    login = auth_app_server.post(
        "/api/auth/login",
        json={
            "username": _AUTH_USERNAME,
            "password": _AUTH_PASSWORD,
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert login.status_code == 200, login.text
    token = login.json()["token"]

    resp = auth_app_server.get(
        "/api/agents",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Forwarded-For": "203.0.113.7",
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    agents = body if isinstance(body, list) else body.get("agents", [])
    assert isinstance(agents, list), body
