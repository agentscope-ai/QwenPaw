"""Tests for the Computer Use plugin status route."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from computer_use_tool import router as router_module
from computer_use_tool.access import (
    ComputerUseAccessStore,
    PersistentAppAccess,
)
from computer_use_tool.router import (
    PendingDecisionRequest,
    PersistentAccessRequest,
    build_router,
)
from qwenpaw.app.computer_use import HostRuntimeProvider
from qwenpaw.security.tool_guard.approval import ApprovalDecision


def test_status_route_does_not_acquire_native_runtime(monkeypatch) -> None:
    monkeypatch.setenv("QWENPAW_COMPUTER_USE_CONTROL_HOST", "127.0.0.1")
    monkeypatch.setenv("QWENPAW_COMPUTER_USE_CONTROL_PORT", "8080")
    monkeypatch.setenv("QWENPAW_COMPUTER_USE_CONTROL_TOKEN", "test-token")
    monkeypatch.setenv("QWENPAW_COMPUTER_USE_CONTROL_PROTOCOL", "1")

    route = next(
        route for route in build_router().routes if route.path == "/status"
    )
    payload = route.endpoint()

    assert payload["runtime_available"] is True
    assert payload["connection_active"] is False
    assert HostRuntimeProvider.get_capability() is None


@pytest.mark.asyncio
async def test_session_route_reads_access_without_acquiring_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = next(
        route for route in build_router().routes if route.path == "/session"
    )
    payload = await route.endpoint("session-1")

    assert payload["automation_active"] is False
    assert HostRuntimeProvider.get_capability() is None


def test_revoke_persistent_access(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    store = ComputerUseAccessStore(tmp_path / "app_access.json")
    store.record_persistent("win32:contoso.editor", "Contoso Editor")
    monkeypatch.setattr(
        router_module, "get_computer_use_access_store", lambda: store
    )
    route = next(
        route
        for route in build_router().routes
        if route.path == "/access" and "DELETE" in route.methods
    )

    response = route.endpoint(
        PersistentAccessRequest(canonical_app_id="win32:contoso.editor"),
    )

    assert response == {"revoked": True}
    assert store.list_persistent() == []


class _ApprovalService:
    def __init__(self, pending: object) -> None:
        self.pending = pending
        self.decisions: list[tuple[str, ApprovalDecision]] = []

    async def get_request(self, request_id: str):
        if getattr(self.pending, "request_id", None) == request_id:
            return self.pending
        return None

    async def resolve_request(
        self,
        request_id: str,
        decision: ApprovalDecision,
    ) -> object | None:
        self.decisions.append((request_id, decision))
        return self.pending


@pytest.mark.asyncio
async def test_pending_decision_only_resolves_computer_use_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = SimpleNamespace(
        request_id="request-1",
        session_id="session-1",
        extra={"source_type": "computer_use_app_access"},
    )
    service = _ApprovalService(pending)
    monkeypatch.setattr(
        router_module,
        "get_approval_service",
        lambda: service,
    )
    route = next(
        route
        for route in build_router().routes
        if route.path == "/session/pending/decision"
    )

    response = await route.endpoint(
        PendingDecisionRequest(
            session_id="session-1",
            request_id="request-1",
            decision="session",
        ),
    )

    assert response == {"resolved": True, "decision": "session"}
    assert service.decisions == [("request-1", ApprovalDecision.APPROVED)]


@pytest.mark.asyncio
async def test_pending_decision_rejects_non_computer_use_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = SimpleNamespace(
        request_id="request-1",
        session_id="session-1",
        extra={"source_type": "tool_guard"},
    )
    service = _ApprovalService(pending)
    monkeypatch.setattr(
        router_module,
        "get_approval_service",
        lambda: service,
    )
    route = next(
        route
        for route in build_router().routes
        if route.path == "/session/pending/decision"
    )

    with pytest.raises(HTTPException, match="Pending approval not found"):
        await route.endpoint(
            PendingDecisionRequest(
                session_id="session-1",
                request_id="request-1",
                decision="session",
            ),
        )

    assert service.decisions == []


@pytest.mark.asyncio
async def test_pending_always_decision_records_persistent_access(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    pending = SimpleNamespace(
        request_id="request-1",
        session_id="session-1",
        extra={
            "source_type": "computer_use_app_access",
            "computer_use_app": {
                "canonical_app_id": "win32:contoso.editor",
                "display_name": "Contoso Editor",
            },
        },
    )
    service = _ApprovalService(pending)
    store = ComputerUseAccessStore(tmp_path / "app_access.json")
    monkeypatch.setattr(
        router_module,
        "get_approval_service",
        lambda: service,
    )
    monkeypatch.setattr(
        router_module,
        "get_computer_use_access_store",
        lambda: store,
    )
    route = next(
        route
        for route in build_router().routes
        if route.path == "/session/pending/decision"
    )

    response = await route.endpoint(
        PendingDecisionRequest(
            session_id="session-1",
            request_id="request-1",
            decision="always",
        ),
    )

    assert response == {"resolved": True, "decision": "always"}
    assert store.list_persistent() == [
        PersistentAppAccess(
            canonical_app_id="win32:contoso.editor",
            display_name="Contoso Editor",
        ),
    ]
