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
from pathlib import Path
from typing import Iterator

import httpx
import pytest
from helpers import default_http_timeout


_HTTP_TIMEOUT = default_http_timeout(15.0)
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

    # This module spawns its own app subprocess, so it must opt into the
    # same subprocess-coverage wiring the shared app_server fixture uses;
    # without it these tests trace nothing under
    # QWENPAW_INTEGRATION_COVERAGE=1. The settings are inlined rather than
    # imported from the sibling conftest, whose bare module name collides
    # with tests/conftest.py during static analysis.
    if os.environ.get(
        "QWENPAW_INTEGRATION_COVERAGE",
        "",
    ).strip().lower() in ("1", "true", "yes"):
        cov_dir = Path(__file__).resolve().parents[2] / ".integration_coverage"
        rcfile = cov_dir / "coverage_subprocess.ini"
        if rcfile.is_file():
            env["COVERAGE_PROCESS_START"] = str(rcfile)
            env["COVERAGE_FILE"] = str(cov_dir / "integration_subproc")

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


# ------------------------------------------------------------------ #
# B. Token verification / profile / revocation
# ------------------------------------------------------------------ #


def _login(auth_app_server, password: str = _AUTH_PASSWORD) -> str:
    """Return a fresh Bearer token for the seeded user."""
    resp = auth_app_server.post(
        "/api/auth/login",
        json={"username": _AUTH_USERNAME, "password": password},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


@pytest.mark.integration
@pytest.mark.p1
def test_auth_verify_accepts_fresh_token(auth_app_server) -> None:
    """Test purpose:
    - Verify GET /api/auth/verify confirms a freshly issued token and
      echoes the owning username.

    API endpoints:
    - POST /api/auth/login
    - GET  /api/auth/verify
    """
    token = _login(auth_app_server)
    resp = auth_app_server.get(
        "/api/auth/verify",
        headers={"Authorization": f"Bearer {token}"},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("valid") is True, body
    assert body.get("username") == _AUTH_USERNAME, body


@pytest.mark.integration
@pytest.mark.p2
def test_auth_verify_without_token_returns_401(auth_app_server) -> None:
    """Test purpose:
    - Verify GET /api/auth/verify rejects a request carrying no Bearer
      header (the "No token provided" branch).

    API endpoints:
    - GET /api/auth/verify
    """
    resp = auth_app_server.get(
        "/api/auth/verify",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 401, resp.text


@pytest.mark.integration
@pytest.mark.p2
def test_auth_verify_with_garbage_token_returns_401(auth_app_server) -> None:
    """Test purpose:
    - Verify GET /api/auth/verify rejects a malformed token via the
      "Invalid or expired token" branch, distinct from a missing one.

    API endpoints:
    - GET /api/auth/verify
    """
    resp = auth_app_server.get(
        "/api/auth/verify",
        headers={"Authorization": "Bearer not-a-real-token"},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 401, resp.text


@pytest.mark.integration
@pytest.mark.p2
def test_update_profile_requires_authentication(auth_app_server) -> None:
    """Test purpose:
    - Verify POST /api/auth/update-profile refuses an unauthenticated
      caller before touching stored credentials.

    API endpoints:
    - POST /api/auth/update-profile
    """
    resp = auth_app_server.post(
        "/api/auth/update-profile",
        json={
            "current_password": _AUTH_PASSWORD,
            "new_password": "should-not-apply",
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 401, resp.text
    # The original password must still work.
    _login(auth_app_server)


@pytest.mark.integration
@pytest.mark.p2
def test_update_profile_without_changes_returns_400(auth_app_server) -> None:
    """Test purpose:
    - Verify POST /api/auth/update-profile rejects a request that names
      neither a new username nor a new password.

    API endpoints:
    - POST /api/auth/update-profile
    """
    token = _login(auth_app_server)
    resp = auth_app_server.post(
        "/api/auth/update-profile",
        json={"current_password": _AUTH_PASSWORD},
        headers={"Authorization": f"Bearer {token}"},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, resp.text
    assert "Nothing to update" in resp.text, resp.text


@pytest.mark.integration
@pytest.mark.p2
def test_update_profile_wrong_current_password_returns_401(
    auth_app_server,
) -> None:
    """Test purpose:
    - Verify POST /api/auth/update-profile refuses to rotate the
      password when current_password is wrong, and that the original
      password still works afterwards.

    API endpoints:
    - POST /api/auth/update-profile
    - POST /api/auth/login
    """
    token = _login(auth_app_server)
    resp = auth_app_server.post(
        "/api/auth/update-profile",
        json={
            "current_password": "definitely-wrong",
            "new_password": "must-not-be-applied",
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 401, resp.text
    _login(auth_app_server)


@pytest.mark.integration
@pytest.mark.p2
def test_update_profile_empty_password_returns_400(auth_app_server) -> None:
    """Test purpose:
    - Verify a blank new_password is rejected before reaching the
      credential store.

    API endpoints:
    - POST /api/auth/update-profile
    """
    token = _login(auth_app_server)
    resp = auth_app_server.post(
        "/api/auth/update-profile",
        json={
            "current_password": _AUTH_PASSWORD,
            "new_password": "   ",
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, resp.text
    _login(auth_app_server)


@pytest.mark.integration
@pytest.mark.p1
def test_revoke_current_token_invalidates_it(auth_app_server) -> None:
    """Test purpose:
    - Verify POST /api/auth/revoke-token with no body token revokes the
      caller's own token, so a subsequent verify with that token fails
      while a freshly issued token still works.

    Test flow:
    1. Login → token A; confirm verify accepts it.
    2. POST /api/auth/revoke-token with no token field.
    3. Verify with token A → 401.
    4. Login again → token B; verify accepts it.

    API endpoints:
    - POST /api/auth/login
    - POST /api/auth/revoke-token
    - GET  /api/auth/verify
    """
    token_a = _login(auth_app_server)
    assert (
        auth_app_server.get(
            "/api/auth/verify",
            headers={"Authorization": f"Bearer {token_a}"},
            timeout=_HTTP_TIMEOUT,
        ).status_code
        == 200
    )

    revoked = auth_app_server.post(
        "/api/auth/revoke-token",
        json={},
        headers={"Authorization": f"Bearer {token_a}"},
        timeout=_HTTP_TIMEOUT,
    )
    assert revoked.status_code == 200, revoked.text
    body = revoked.json()
    assert body.get("revoked") is True, body
    assert body.get("revoked_current_token") is True, body

    after = auth_app_server.get(
        "/api/auth/verify",
        headers={"Authorization": f"Bearer {token_a}"},
        timeout=_HTTP_TIMEOUT,
    )
    assert after.status_code == 401, (
        "revoked token still verified: " + after.text
    )

    token_b = _login(auth_app_server)
    assert token_b != token_a, "login returned the revoked token"
    assert (
        auth_app_server.get(
            "/api/auth/verify",
            headers={"Authorization": f"Bearer {token_b}"},
            timeout=_HTTP_TIMEOUT,
        ).status_code
        == 200
    )


@pytest.mark.integration
@pytest.mark.p1
def test_revoke_specific_other_token(auth_app_server) -> None:
    """Test purpose:
    - Verify a caller can revoke a *different* token (the leaked-device
      case) while keeping its own session usable.

    Test flow:
    1. Login twice → tokens A and B.
    2. Using A, revoke B explicitly.
    3. Verify B → 401 while A still verifies.

    API endpoints:
    - POST /api/auth/login
    - POST /api/auth/revoke-token
    - GET  /api/auth/verify
    """
    token_a = _login(auth_app_server)
    token_b = _login(auth_app_server)
    if token_a == token_b:
        pytest.skip("login reuses one token; cannot target another session")

    revoked = auth_app_server.post(
        "/api/auth/revoke-token",
        json={"token": token_b},
        headers={"Authorization": f"Bearer {token_a}"},
        timeout=_HTTP_TIMEOUT,
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json().get("revoked_current_token") is False, revoked.json()

    assert (
        auth_app_server.get(
            "/api/auth/verify",
            headers={"Authorization": f"Bearer {token_b}"},
            timeout=_HTTP_TIMEOUT,
        ).status_code
        == 401
    ), "explicitly revoked token still verified"
    assert (
        auth_app_server.get(
            "/api/auth/verify",
            headers={"Authorization": f"Bearer {token_a}"},
            timeout=_HTTP_TIMEOUT,
        ).status_code
        == 200
    ), "revoking another token invalidated the caller's own session"


@pytest.mark.integration
@pytest.mark.p2
def test_revoke_token_requires_authentication(auth_app_server) -> None:
    """Test purpose:
    - Verify POST /api/auth/revoke-token rejects an unauthenticated
      caller, so tokens cannot be revoked anonymously.

    API endpoints:
    - POST /api/auth/revoke-token
    """
    resp = auth_app_server.post(
        "/api/auth/revoke-token",
        json={"token": "some-other-token"},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 401, resp.text


@pytest.mark.integration
@pytest.mark.p2
def test_revoke_all_tokens_requires_authentication(auth_app_server) -> None:
    """Test purpose:
    - Verify POST /api/auth/revoke-all-tokens rejects an
      unauthenticated caller. Runs last in this module because a
      successful rotation would invalidate every other token.

    API endpoints:
    - POST /api/auth/revoke-all-tokens
    """
    resp = auth_app_server.post(
        "/api/auth/revoke-all-tokens",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 401, resp.text
    # The seeded credentials must still be usable.
    _login(auth_app_server)


@pytest.mark.integration
@pytest.mark.p2
def test_register_rejected_when_user_exists(auth_app_server) -> None:
    """Test purpose:
    - Verify POST /api/auth/register refuses a second account: the
      seeded user was auto-registered from the environment, so the
      single-user guard must reject this and the original credentials
      must keep working.

    API endpoints:
    - POST /api/auth/register
    - POST /api/auth/login
    """
    resp = auth_app_server.post(
        "/api/auth/register",
        json={
            "username": "integ-second-user",
            "password": "integ-second-pass-123",
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 403, resp.text
    assert "already registered" in resp.text.lower(), resp.text
    # The seeded account must be unaffected.
    _login(auth_app_server)


@pytest.mark.integration
@pytest.mark.p2
def test_login_unknown_username_returns_401(auth_app_server) -> None:
    """Test purpose:
    - Verify POST /api/auth/login rejects a username that was never
      registered, which is a different branch from a wrong password on
      a known user.

    API endpoints:
    - POST /api/auth/login
    """
    resp = auth_app_server.post(
        "/api/auth/login",
        json={
            "username": "integ-nobody-here",
            "password": _AUTH_PASSWORD,
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 401, resp.text


@pytest.mark.integration
@pytest.mark.p2
def test_login_permanent_token_is_accepted(auth_app_server) -> None:
    """Test purpose:
    - Verify a login requesting a permanent token (expires_in=-1) yields
      a usable token, covering the no-expiry arm of create_token.

    API endpoints:
    - POST /api/auth/login
    - GET  /api/auth/verify
    """
    resp = auth_app_server.post(
        "/api/auth/login",
        json={
            "username": _AUTH_USERNAME,
            "password": _AUTH_PASSWORD,
            "expires_in": -1,
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["token"]
    verified = auth_app_server.get(
        "/api/auth/verify",
        headers={"Authorization": f"Bearer {token}"},
        timeout=_HTTP_TIMEOUT,
    )
    assert verified.status_code == 200, verified.text
    assert verified.json().get("valid") is True, verified.json()


@pytest.mark.integration
@pytest.mark.p2
def test_revoke_token_rejects_garbage_caller_token(auth_app_server) -> None:
    """Test purpose:
    - Verify POST /api/auth/revoke-token refuses a caller presenting a
      malformed Bearer token, so an unauthenticated client cannot
      blacklist someone else's session.

    API endpoints:
    - POST /api/auth/revoke-token
    """
    resp = auth_app_server.post(
        "/api/auth/revoke-token",
        json={"token": "victim-token"},
        headers={"Authorization": "Bearer not-a-real-token"},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 401, resp.text


@pytest.mark.integration
@pytest.mark.p1
def test_repeated_failures_lock_that_account_only(auth_app_server) -> None:
    """Test purpose:
    - Verify the login rate limiter locks an account after repeated
      failures (423 Locked) and that the lockout is scoped to that
      username: the real seeded account must still log in.

    Test flow:
    1. Fail login 6 times for a throwaway username (threshold is 5).
    2. Expect a 423 once the account is locked.
    3. Log in with the seeded credentials to prove the lockout did not
       leak across accounts or lock the shared client IP.

    API endpoints:
    - POST /api/auth/login
    """
    victim = "integ-lockout-target"
    saw_locked = False
    for _ in range(6):
        resp = auth_app_server.post(
            "/api/auth/login",
            json={"username": victim, "password": "wrong-on-purpose"},
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code in (401, 423), resp.text
        if resp.status_code == 423:
            saw_locked = True
            break
    assert saw_locked, "account was never locked after repeated failed logins"

    # The lockout must be per-account, not per-IP: the seeded user works.
    _login(auth_app_server)


@pytest.mark.integration
@pytest.mark.p2
def test_locked_account_stays_locked_on_correct_password(
    auth_app_server,
) -> None:
    """Test purpose:
    - Verify a locked account is refused even when the *correct*
      password is supplied, proving the lock is checked before
      authentication rather than after.

    API endpoints:
    - POST /api/auth/login
    """
    victim = "integ-lockout-precedence"
    for _ in range(6):
        resp = auth_app_server.post(
            "/api/auth/login",
            json={"username": victim, "password": "wrong-on-purpose"},
            timeout=_HTTP_TIMEOUT,
        )
        if resp.status_code == 423:
            break
    # Even a valid-looking attempt must hit the lock first.  This user
    # does not exist, so a 401 here would mean the lock was bypassed.
    final = auth_app_server.post(
        "/api/auth/login",
        json={"username": victim, "password": _AUTH_PASSWORD},
        timeout=_HTTP_TIMEOUT,
    )
    assert final.status_code == 423, final.text
    _login(auth_app_server)
