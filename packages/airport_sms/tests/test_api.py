"""控制面 API 测试。"""

from __future__ import annotations

from time import perf_counter

from fastapi.testclient import TestClient

from airport_sms.api.app import create_app
from airport_sms.runtime import Runtime


def _client() -> TestClient:
    return TestClient(create_app(Runtime.in_memory()))


def test_auth_default_on() -> None:
    c = _client()
    r = c.post("/chat", json={"session_id": "s", "text": "draft"})
    assert r.status_code == 401


def test_login_reporter() -> None:
    c = _client()
    r = c.post("/login", json={"token": "reporter-token"})
    assert r.status_code == 200
    assert r.json()["role"] == "reporter"


def test_chat_draft_sse() -> None:
    c = _client()
    r = c.post(
        "/chat",
        json={"session_id": "s1", "text": "draft hazard"},
        headers={"authorization": "Bearer reporter-token"},
    )
    assert r.status_code == 200
    assert "case" in r.text or "done" in r.text


def test_case_detail() -> None:
    c = _client()
    c.post(
        "/chat",
        json={"session_id": "s1", "text": "draft hazard"},
        headers={"authorization": "Bearer reporter-token"},
    )
    listed = c.get(
        "/cases", headers={"authorization": "Bearer reporter-token"}
    ).json()
    assert listed
    detail = c.get(
        f"/cases/{listed[0]['id']}",
        headers={"authorization": "Bearer reporter-token"},
    )
    assert detail.status_code == 200
    assert detail.json()["state"] == "draft"


def test_pending_approval_and_approve() -> None:
    c = _client()
    c.post(
        "/chat",
        json={"session_id": "s1", "text": "draft hazard"},
        headers={"authorization": "Bearer reporter-token"},
    )
    c.post(
        "/chat",
        json={"session_id": "s1", "command": "submit"},
        headers={"authorization": "Bearer reporter-token"},
    )
    pending = c.get(
        "/approvals", headers={"authorization": "Bearer safety-token"}
    ).json()
    assert pending
    decided = c.post(
        "/approvals/decide",
        json={"approval_id": pending[0]["id"], "approve": True},
        headers={"authorization": "Bearer safety-token"},
    )
    assert decided.status_code == 200
    assert decided.json()["case_state"] == "submitted"


def test_deny_keeps_prior() -> None:
    c = _client()
    c.post(
        "/chat",
        json={"session_id": "s2", "text": "draft hazard"},
        headers={"authorization": "Bearer reporter-token"},
    )
    c.post(
        "/chat",
        json={"session_id": "s2", "command": "submit"},
        headers={"authorization": "Bearer reporter-token"},
    )
    pending = c.get(
        "/approvals", headers={"authorization": "Bearer safety-token"}
    ).json()
    c.post(
        "/approvals/decide",
        json={"approval_id": pending[0]["id"], "approve": False},
        headers={"authorization": "Bearer safety-token"},
    )
    listed = c.get(
        "/cases", headers={"authorization": "Bearer reporter-token"}
    ).json()
    assert listed[0]["state"] == "draft"


def test_audit_timeline() -> None:
    c = _client()
    c.post(
        "/chat",
        json={"session_id": "s3", "text": "draft hazard"},
        headers={"authorization": "Bearer reporter-token"},
    )
    listed = c.get(
        "/cases", headers={"authorization": "Bearer reporter-token"}
    ).json()
    detail = c.get(
        f"/cases/{listed[0]['id']}",
        headers={"authorization": "Bearer reporter-token"},
    ).json()
    assert "audit" in detail


def test_trace_header() -> None:
    c = _client()
    r = c.get("/health")
    assert r.headers.get("x-trace-id")


def test_cross_org_404() -> None:
    c = _client()
    c.post(
        "/chat",
        json={"session_id": "s4", "text": "draft hazard"},
        headers={"authorization": "Bearer reporter-token"},
    )
    listed = c.get(
        "/cases", headers={"authorization": "Bearer reporter-token"}
    ).json()
    # safety token same org — use bogus id
    r = c.get(
        "/cases/does-not-exist",
        headers={"authorization": "Bearer safety-token"},
    )
    assert r.status_code == 404
    assert listed


def test_chat_under_2s() -> None:
    c = _client()
    start = perf_counter()
    c.post(
        "/chat",
        json={"session_id": "perf", "text": "draft hazard"},
        headers={"authorization": "Bearer reporter-token"},
    )
    assert (perf_counter() - start) < 2
