# -*- coding: utf-8 -*-
"""Regression tests for the QwenPaw Pet ``ApprovalService`` patch.

Issue #7856: the shipped wrapper replaced
``ApprovalService.resolve_request`` with a hand-written signature that
omitted the keyword-only ``actor`` parameter upstream added in
``v2.2.2-beta.1``. Argument binding failed before the original method
could run, so every Console approve/deny returned HTTP 500 and the
pending tool call was never resolved.

``scope`` had already failed the same way when it was added, which is
why the wrapper now has to forward parameters it does not read itself
instead of listing them.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

import patch_approval
from qwenpaw.app.approvals import (
    ApprovalActor,
    ApprovalIdentityPolicy,
    ApprovalRequestSummary,
    ApprovalService,
    get_approval_service,
)
from qwenpaw.app.routers.approval import router as approval_router
from qwenpaw.security.tool_guard.approval import ApprovalDecision

# Methods the plugin replaces, paired with the attribute it stashes the
# original under.
_PATCHED_METHODS = (
    ("create_pending", "_ORIG_CREATE_PENDING"),
    ("resolve_request", "_ORIG_RESOLVE_REQUEST"),
    ("cancel_all_pending_by_root_session", "_ORIG_CANCEL_ALL"),
)


@pytest.fixture
def pet_patch():
    """Install the plugin patch for one test and always restore it.

    The patch replaces class attributes on ``ApprovalService``, which is
    process-global state: leaking it would corrupt unrelated approval
    tests running in the same interpreter.
    """
    patch_approval.patch_approval_service()
    try:
        yield patch_approval
    finally:
        patch_approval.restore_approval_service()


@pytest.fixture
def approval_app() -> FastAPI:
    """A minimal app carrying only the real approval router."""
    app = FastAPI()
    app.include_router(approval_router, prefix="/api")
    return app


def _admin_actor(pending) -> ApprovalActor:
    """Build the actor the Console route assigns to a click."""
    return ApprovalActor(
        session_id=pending.session_id,
        root_session_id=pending.root_session_id,
        user_id="console",
        channel="console",
        agent_id=pending.agent_id,
        is_admin=True,
    )


async def _seed_pending(
    *,
    identity_policy: ApprovalIdentityPolicy = (ApprovalIdentityPolicy.AGENT),
):
    """Create a real pending approval in the shared singleton service."""
    svc = get_approval_service()
    pending = await svc.create_pending_summary(
        session_id="sess-1",
        root_session_id="sess-1",
        owner_agent_id="agent-1",
        user_id="console",
        channel="console",
        agent_id="agent-1",
        summary=ApprovalRequestSummary(
            source_type="pytest",
            name="execute_shell_command",
        ),
        identity_policy=identity_policy,
    )
    return svc, pending


def _drop_pending(svc, request_id: str) -> None:
    """Remove a seeded record so tests do not leak into each other."""
    svc._pending.pop(request_id, None)  # pylint: disable=protected-access


@pytest.mark.parametrize(("method_name", "orig_attr"), _PATCHED_METHODS)
def test_wrapper_preserves_every_native_parameter(
    pet_patch,
    method_name: str,
    orig_attr: str,
):
    """The wrapper must stay able to forward the full native signature.

    Upstream added ``scope`` (2.0) and ``actor`` (2.2.2b1) to
    ``resolve_request``; both times a hand-written wrapper signature
    turned into a production failure. Absorbing ``**kwargs`` keeps this
    assertion true for whatever parameter comes next.
    """
    native = inspect.signature(getattr(pet_patch, orig_attr)).parameters
    wrapped = inspect.signature(
        getattr(ApprovalService, method_name),
    ).parameters
    accepts_any_keyword = any(
        param.kind is inspect.Parameter.VAR_KEYWORD
        for param in wrapped.values()
    )
    missing = sorted(set(native) - set(wrapped))

    assert accepts_any_keyword or not missing, (
        f"{method_name} wrapper cannot accept {missing}: upstream added a "
        "parameter the wrapper does not forward"
    )


async def test_admin_actor_is_forwarded_to_the_native_method(pet_patch):
    """A Console admin must satisfy the EXACT_REQUESTER identity policy.

    Accepting ``actor`` is not enough — silently dropping it would raise
    ``ApprovalIdentityMismatchError`` instead of resolving the call.
    """
    svc, pending = await _seed_pending(
        identity_policy=ApprovalIdentityPolicy.EXACT_REQUESTER,
    )
    try:
        resolved = await svc.resolve_request(
            pending.request_id,
            ApprovalDecision.APPROVED,
            actor=_admin_actor(pending),
        )
    finally:
        _drop_pending(svc, pending.request_id)

    assert resolved is not None
    assert pending.future.result() is ApprovalDecision.APPROVED


@pytest.mark.parametrize(
    ("route", "decision"),
    [
        ("approve", ApprovalDecision.APPROVED),
        ("deny", ApprovalDecision.DENIED),
    ],
)
async def test_console_route_resolves_the_pending_call(
    pet_patch,
    approval_app: FastAPI,
    route: str,
    decision: ApprovalDecision,
):
    """The Console routes must answer 200 instead of the 500 of #7856."""
    svc, pending = await _seed_pending()
    transport = httpx.ASGITransport(
        app=approval_app,
        raise_app_exceptions=False,
    )
    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post(
                f"/api/approval/{route}",
                json={
                    "request_id": pending.request_id,
                    "session_id": pending.session_id,
                    "reason": "pytest",
                },
            )
    finally:
        _drop_pending(svc, pending.request_id)

    assert response.status_code == 200, response.text
    assert pending.future.result() is decision


async def test_pet_events_are_still_emitted(pet_patch, monkeypatch):
    """The wrapper's own purpose — pet lifecycle events — must survive."""
    events: list = []
    monkeypatch.setattr(
        patch_approval,
        "schedule_emit_pet_event",
        lambda event, **payload: events.append((event, payload)),
    )
    svc, pending = await _seed_pending()
    try:
        await svc.resolve_request(
            pending.request_id,
            ApprovalDecision.APPROVED,
            actor=_admin_actor(pending),
        )
    finally:
        _drop_pending(svc, pending.request_id)

    assert [event for event, _ in events] == ["approval.approved"]
    assert events[0][1]["session_id"] == pending.session_id


async def test_patch_tolerates_an_upstream_without_actor(monkeypatch):
    """The wrapper must not inject keywords older targets would reject.

    The manifest declares ``min: 1.1.5``, so a caller on <=2.1.0 that
    omits ``actor`` still has to work after the patch is installed.
    """

    async def legacy_resolve_request(self, request_id, decision):
        return SimpleNamespace(
            tool_name="execute_shell_command",
            session_id="sess-1",
            agent_id="agent-1",
        )

    monkeypatch.setattr(
        ApprovalService,
        "resolve_request",
        legacy_resolve_request,
    )
    patch_approval.restore_approval_service()
    patch_approval.patch_approval_service()
    try:
        svc = get_approval_service()
        resolved = await svc.resolve_request(
            "legacy-request",
            ApprovalDecision.APPROVED,
        )
    finally:
        patch_approval.restore_approval_service()

    assert resolved.tool_name == "execute_shell_command"
