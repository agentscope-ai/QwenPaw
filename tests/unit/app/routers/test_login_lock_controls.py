# -*- coding: utf-8 -*-
"""登录失败提醒、锁定到期与管理员定向解锁的 HTTP 契约。"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.app import rate_limiter as limiter_module
from qwenpaw.app.rate_limiter import LoginRateLimiter
from qwenpaw.app.routers import admin_users, auth
from qwenpaw.identity.governance import UserNotFoundError
from qwenpaw.identity.models import PlatformRole, UserRecord


@pytest.fixture
def login_client(monkeypatch):
    limiter = LoginRateLimiter()
    now = [1000.0]
    monkeypatch.setattr(limiter_module.time, "time", lambda: now[0])
    monkeypatch.setattr(auth, "rate_limiter", limiter)
    monkeypatch.setattr(auth, "is_multi_user_enabled", lambda: True)

    async def authenticate(_username, _password):
        return None

    runtime = SimpleNamespace(users=SimpleNamespace(authenticate=authenticate))
    monkeypatch.setattr(auth, "get_identity_runtime", lambda: runtime)
    app = FastAPI()
    app.include_router(auth.router, prefix="/api")
    return TestClient(app), limiter, now


def fail_login(client, username="member"):
    return client.post(
        "/api/auth/login", json={"username": username, "password": "incorrect"}
    )


def test_failed_login_warns_remaining_attempts_and_fifth_failure_locks(login_client):
    client, _limiter, _now = login_client
    for remaining in (4, 3, 2, 1):
        response = fail_login(client)
        assert response.status_code == 401
        detail = response.json()["detail"]
        assert detail["code"] == "invalid_credentials"
        assert detail["remaining_attempts"] == remaining
        assert "用户名或密码" in detail["message"]
    response = fail_login(client)
    assert response.status_code == 423
    assert response.json()["detail"]["code"] == "account_locked"
    assert response.json()["detail"]["remaining_attempts"] == 0
    assert response.json()["detail"]["retry_after_seconds"] == 900
    assert response.headers["Retry-After"] == "900"


def test_repeated_checks_do_not_extend_lock_and_expiry_restores_attempts(login_client):
    client, limiter, now = login_client
    for _ in range(5):
        fail_login(client)
    deadline = limiter.locked_users["member"]
    now[0] += 65
    # User lock remains in force even though the one-minute count has expired.
    for _ in range(3):
        response = fail_login(client)
        assert response.status_code == 423
        assert response.headers["Retry-After"] == "835"
        assert response.json()["detail"]["remaining_attempts"] == 0
    assert limiter.locked_users["member"] == deadline
    now[0] = deadline
    response = fail_login(client)
    assert response.status_code == 401
    assert response.json()["detail"]["remaining_attempts"] == 4


def test_username_whitespace_cannot_bypass_account_lock(login_client):
    client, _limiter, _now = login_client
    for _ in range(5):
        fail_login(client, " member ")
    assert fail_login(client, "member").status_code == 423


def test_ip_protection_remains_independent_and_returns_chinese_metadata(login_client):
    client, limiter, now = login_client
    # The target account is unlocked; the source IP still has separate protection.
    limiter.locked_ips["testclient"] = now[0] + 47.2
    response = fail_login(client)
    assert response.status_code == 423
    assert response.headers["Retry-After"] == "48"
    assert response.json()["detail"]["code"] == "ip_locked"
    assert "频繁" in response.json()["detail"]["message"]


def test_successful_normalized_login_clears_failures(login_client, monkeypatch):
    client, _limiter, _now = login_client
    monkeypatch.setattr(auth, "is_multi_user_enabled", lambda: False)
    monkeypatch.setattr(auth, "is_auth_enabled", lambda: True)
    calls = []

    def authenticate(username, password, _expires):
        calls.append(username)
        return "test-token" if password == "correct" else None

    monkeypatch.setattr(auth, "authenticate", authenticate)
    assert fail_login(client).json()["detail"]["remaining_attempts"] == 4
    response = client.post(
        "/api/auth/login", json={"username": " member ", "password": "correct"}
    )
    assert response.status_code == 200
    assert response.json()["username"] == "member"
    assert calls[-1] == "member"
    assert fail_login(client).json()["detail"]["remaining_attempts"] == 4


def test_rate_limited_ip_has_retry_metadata_even_after_success(login_client, monkeypatch):
    client, limiter, _now = login_client
    monkeypatch.setattr(auth, "is_multi_user_enabled", lambda: False)
    monkeypatch.setattr(auth, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(auth, "authenticate", lambda *_args: "test-token")
    limiter.ip_max_total_per_minute = 1
    assert fail_login(client).status_code == 200
    response = fail_login(client)
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"
    assert response.json()["detail"]["code"] == "login_rate_limited"


def test_existing_and_unknown_accounts_have_identical_failure_contract(login_client):
    client, _limiter, _now = login_client
    assert fail_login(client, "member").json() == fail_login(client, "unknown").json()


class Governance:
    def __init__(self):
        self.users = {
            "member": UserRecord(id=uuid4(), username="member", platform_role=PlatformRole.MEMBER, status="active"),
            "disabled": UserRecord(id=uuid4(), username="disabled", platform_role=PlatformRole.MEMBER, status="disabled"),
        }
        self.lookups = []

    async def list_users(self):
        return list(self.users.values())

    async def get_user(self, user_id):
        self.lookups.append(user_id)
        for user in self.users.values():
            if user.id == user_id:
                return user
        raise UserNotFoundError()


class Audit:
    def __init__(self):
        self.records = []

    async def record(self, **kwargs):
        self.records.append(kwargs)


def admin_client(monkeypatch, *, role=PlatformRole.ADMIN, audit=None):
    limiter = LoginRateLimiter()
    monkeypatch.setattr(admin_users, "rate_limiter", limiter, raising=False)
    actor = ActorContext(user_id=uuid4(), actor_type=ActorType.USER, platform_role=role, admin_mode=False, request_id="unlock-test")
    governance, audit = Governance(), audit or Audit()
    app = FastAPI()
    app.include_router(admin_users.router, prefix="/api")
    app.dependency_overrides[admin_users.require_multi_user_mode] = lambda: None
    app.dependency_overrides[admin_users.get_actor] = lambda: actor
    app.dependency_overrides[admin_users.get_governance_service] = lambda: governance
    app.dependency_overrides[admin_users.get_user_audit_repository] = lambda: audit
    return TestClient(app), limiter, governance, audit


def lock(limiter, username):
    for _ in range(5):
        limiter.record_login_attempt("shared-ip", username, False)


def test_admin_can_see_lock_and_unlock_only_the_selected_account(monkeypatch):
    client, limiter, governance, audit = admin_client(monkeypatch)
    member = governance.users["member"]
    lock(limiter, "member")
    lock(limiter, "other-user")
    limiter.locked_ips["shared-ip"] = 10**12
    row = next(r for r in client.get("/api/admin/users").json() if r["id"] == str(member.id))
    assert row["login_locked"] is True
    assert row["login_remaining_attempts"] == 0
    response = client.post(f"/api/admin/users/{member.id}/unlock")
    assert response.status_code == 200
    assert response.json()["login_locked"] is False
    assert response.json()["login_remaining_attempts"] == 5
    assert not limiter.is_user_locked("member")
    assert limiter.is_user_locked("other-user")
    assert limiter.is_ip_locked("shared-ip")
    assert len(audit.records) == 1
    assert audit.records[0]["action"] == "admin.user.login.unlock"
    assert audit.records[0]["target_user_id"] == member.id


def test_member_is_rejected_before_target_lookup_and_cannot_unlock(monkeypatch):
    client, limiter, governance, audit = admin_client(monkeypatch, role=PlatformRole.MEMBER)
    member = governance.users["member"]
    lock(limiter, "member")
    assert client.post(f"/api/admin/users/{member.id}/unlock").status_code == 403
    assert governance.lookups == []
    assert limiter.is_user_locked("member")
    assert audit.records == []


def test_unlock_cannot_enable_disabled_accounts_and_unknown_id_is_not_found(monkeypatch):
    client, limiter, governance, audit = admin_client(monkeypatch)
    disabled = governance.users["disabled"]
    lock(limiter, "disabled")
    response = client.post(f"/api/admin/users/{disabled.id}/unlock")
    assert response.status_code == 409
    assert response.json()["detail"] == "user_disabled"
    assert limiter.is_user_locked("disabled")
    assert governance.users["disabled"].status == "disabled"
    assert client.post(f"/api/admin/users/{uuid4()}/unlock").status_code == 404
    assert audit.records == []


def test_failed_audit_does_not_unlock_account(monkeypatch):
    class FailingAudit(Audit):
        async def record(self, **kwargs):
            raise RuntimeError("audit-unavailable")

    client, limiter, governance, _audit = admin_client(monkeypatch, audit=FailingAudit())
    lock(limiter, "member")
    with pytest.raises(RuntimeError, match="audit-unavailable"):
        client.post(f"/api/admin/users/{governance.users['member'].id}/unlock")
    assert limiter.is_user_locked("member")
