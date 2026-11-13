# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Turning the feature off has to reach every session, not just one.

Off is the global kill switch. A session left waiting on an approval would be
granted access later and act on a desktop the user had already switched the
feature off for -- so the switch has to refuse all of them, including sessions
the person flipping it was never looking at.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from computer_use import client as client_module
from computer_use import router as router_module


@dataclass
class _Pending:
    request_id: str
    session_id: str


@dataclass
class _ApprovalService:
    """Stands in for the host's approval service, per session."""

    pending: dict[str, list[_Pending]]
    resolved: list[str] = field(default_factory=list)

    async def list_pending_by_session(
        self,
        session_id: str,
        include_subagents: bool = True,  # pylint: disable=unused-argument
    ) -> list[_Pending]:
        return list(self.pending.get(session_id, ()))

    async def resolve_request(self, request_id: str, _decision) -> object:
        self.resolved.append(request_id)
        for items in self.pending.values():
            items[:] = [
                item for item in items if item.request_id != request_id
            ]
        return object()


@pytest.mark.asyncio
async def test_switching_off_refuses_every_waiting_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _ApprovalService(
        pending={
            "session-a": [_Pending("approval-a", "session-a")],
            "session-b": [_Pending("approval-b", "session-b")],
        },
    )
    monkeypatch.setattr(router_module, "get_approval_service", lambda: service)
    monkeypatch.setattr(
        router_module,
        "_is_computer_use_pending",
        lambda _item: True,
    )
    # Both sessions hold a client, which is how a pending approval reaches
    # here.
    monkeypatch.setattr(
        router_module,
        "known_computer_use_sessions",
        lambda: ["session-a", "session-b"],
    )

    stopped: list[bool] = []

    async def _stop_all() -> int:
        # Recorded to pin the order: the release has to be signalled before
        # anything waits on the actions it is releasing.
        stopped.append(bool(service.resolved))
        return 2

    monkeypatch.setattr(
        router_module,
        "stop_all_computer_use_turns",
        _stop_all,
    )

    feature = _FeatureState()
    monkeypatch.setattr(
        router_module,
        "get_computer_use_feature_state",
        lambda: feature,
    )

    result = await _call_feature_off(session_id="session-a")

    assert result["enabled"] is False
    # Both, not only the session named in the request.
    assert sorted(service.resolved) == ["approval-a", "approval-b"]
    assert stopped == [
        True,
    ], "approvals must be denied before turns are reaped"


@pytest.mark.asyncio
async def test_switching_off_covers_a_session_with_no_client_yet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The caller's own session counts even if it holds no client."""
    service = _ApprovalService(
        pending={"session-new": [_Pending("approval-new", "session-new")]},
    )
    monkeypatch.setattr(router_module, "get_approval_service", lambda: service)
    monkeypatch.setattr(
        router_module,
        "_is_computer_use_pending",
        lambda _item: True,
    )
    monkeypatch.setattr(
        router_module,
        "known_computer_use_sessions",
        lambda: [],
    )

    async def _stop_all() -> int:
        return 0

    monkeypatch.setattr(
        router_module,
        "stop_all_computer_use_turns",
        _stop_all,
    )
    feature = _FeatureState()
    monkeypatch.setattr(
        router_module,
        "get_computer_use_feature_state",
        lambda: feature,
    )

    await _call_feature_off(session_id="session-new")
    assert service.resolved == ["approval-new"]


def test_the_session_list_comes_from_the_client_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        client_module,
        "_clients",
        {"one": object(), "two": object()},
    )
    assert sorted(client_module.known_computer_use_sessions()) == [
        "one",
        "two",
    ]


class _FeatureState:
    def __init__(self) -> None:
        self.enabled = True

    def set_enabled(self, value: bool) -> None:
        self.enabled = value

    def is_enabled(self) -> bool:
        return self.enabled


async def _call_feature_off(session_id: str | None) -> dict:
    """Invoke the /feature route function directly, off the HTTP stack."""
    router = router_module.build_router()
    route = next(
        item
        for item in router.routes
        if getattr(item, "path", "") == "/feature"
    )
    request = router_module.FeatureToggleRequest(
        enabled=False,
        session_id=session_id,
    )
    return await route.endpoint(request)
