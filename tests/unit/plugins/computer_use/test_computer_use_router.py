# -*- coding: utf-8 -*-
"""Tests for the Computer Use plugin status route."""

# Fixtures are requested for their side effects, so some are never read.
# pylint: disable=unused-argument, use-implicit-booleaness-not-comparison

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from computer_use_tool import router as router_module
from computer_use_tool.access import (
    ComputerUseAccessStore,
    PersistentAppAccess,
)
from computer_use_tool.feature_state import ComputerUseFeatureState
from computer_use_tool.router import (
    FeatureToggleRequest,
    PendingDecisionRequest,
    PersistentAccessRequest,
    build_router,
)
from qwenpaw.app.computer_use import HostRuntimeProvider
from qwenpaw.app.computer_use import runtime as runtime_module
from qwenpaw.security.tool_guard.approval import ApprovalDecision


def test_status_route_does_not_acquire_native_runtime(monkeypatch) -> None:
    monkeypatch.setattr(runtime_module.sys, "platform", "darwin")
    monkeypatch.setenv("QWENPAW_COMPUTER_USE_CONTROL_HOST", "127.0.0.1")
    monkeypatch.setenv("QWENPAW_COMPUTER_USE_CONTROL_PORT", "8080")
    monkeypatch.setenv("QWENPAW_COMPUTER_USE_CONTROL_TOKEN", "test-token")

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
        router_module,
        "get_computer_use_access_store",
        lambda: store,
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


def test_status_route_reports_feature_enabled_by_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    state = ComputerUseFeatureState(tmp_path / "feature_state.json")
    monkeypatch.setattr(
        router_module,
        "get_computer_use_feature_state",
        lambda: state,
    )
    route = next(
        route for route in build_router().routes if route.path == "/status"
    )

    assert route.endpoint()["enabled"] is True


class _PendingApprovalService:
    def __init__(self, pending: list[object]) -> None:
        self.pending = pending
        self.decisions: list[tuple[str, ApprovalDecision]] = []

    async def list_pending_by_session(self, session_id: str):
        return [
            item
            for item in self.pending
            if getattr(item, "session_id", None) == session_id
        ]

    async def resolve_request(
        self,
        request_id: str,
        decision: ApprovalDecision,
    ) -> object | None:
        self.decisions.append((request_id, decision))
        return next(
            (
                item
                for item in self.pending
                if getattr(item, "request_id", None) == request_id
            ),
            None,
        )


@pytest.mark.asyncio
async def test_feature_disable_stops_turns_and_denies_pending(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    state = ComputerUseFeatureState(tmp_path / "feature_state.json")
    monkeypatch.setattr(
        router_module,
        "get_computer_use_feature_state",
        lambda: state,
    )

    async def _stop_all() -> int:
        return 2

    monkeypatch.setattr(
        router_module,
        "stop_all_computer_use_turns",
        _stop_all,
    )
    pending = SimpleNamespace(
        request_id="request-1",
        session_id="session-1",
        extra={"source_type": "computer_use_app_access"},
    )
    service = _PendingApprovalService([pending])
    monkeypatch.setattr(
        router_module,
        "get_approval_service",
        lambda: service,
    )
    route = next(
        route for route in build_router().routes if route.path == "/feature"
    )

    response = await route.endpoint(
        FeatureToggleRequest(enabled=False, session_id="session-1"),
    )

    assert response == {"enabled": False, "stopped": 2, "denied": 1}
    assert state.is_enabled() is False
    assert service.decisions == [("request-1", ApprovalDecision.DENIED)]
    # The decision must survive a reload from disk.
    reloaded = ComputerUseFeatureState(tmp_path / "feature_state.json")
    assert reloaded.is_enabled() is False


@pytest.mark.asyncio
async def test_feature_enable_skips_stop_and_persists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    state = ComputerUseFeatureState(tmp_path / "feature_state.json")
    state.set_enabled(False)
    monkeypatch.setattr(
        router_module,
        "get_computer_use_feature_state",
        lambda: state,
    )

    async def _stop_all() -> int:
        raise AssertionError("enable must not stop turns")

    monkeypatch.setattr(
        router_module,
        "stop_all_computer_use_turns",
        _stop_all,
    )
    route = next(
        route for route in build_router().routes if route.path == "/feature"
    )

    response = await route.endpoint(FeatureToggleRequest(enabled=True))

    assert response == {"enabled": True}
    assert state.is_enabled() is True
    reloaded = ComputerUseFeatureState(tmp_path / "feature_state.json")
    assert reloaded.is_enabled() is True
