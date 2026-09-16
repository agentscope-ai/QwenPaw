# -*- coding: utf-8 -*-
"""Agent copy, pin and memory-reindex endpoints.

Covers the parts of ``app/routers/agents.py`` that existing agent tests
do not reach: copying an agent's configuration into a new profile, the
pinned-state toggle with its default-agent protection, and the ReMe
memory reindex guard for agents that do not use that backend.

The copy test verifies the new agent actually exists afterwards and then
deletes it, and the pin tests restore the original pinned value, so no
shared agent state is left modified.

API endpoints:
  - GET    /api/agents
  - POST   /api/agents/{agentId}/copy
  - PATCH  /api/agents/{agentId}/pin
  - POST   /api/agents/{agentId}/memory/reindex
  - DELETE /api/agents/{agentId}
"""
from __future__ import annotations

import time

import pytest
from helpers import default_http_timeout

_HTTP_TIMEOUT = default_http_timeout(60.0)

_ABSENT_AGENT = "integ-absent-agent-6690"


def _agent_ids(app_server) -> set[str]:
    resp = app_server.api_request(
        "GET",
        "/api/agents",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    items = body if isinstance(body, list) else body.get("agents") or []
    return {item["id"] for item in items if item.get("id")}


def _agent_entry(app_server, agent_id: str) -> dict:
    resp = app_server.api_request(
        "GET",
        "/api/agents",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    items = body if isinstance(body, list) else body.get("agents") or []
    for item in items:
        if item.get("id") == agent_id:
            return item
    raise AssertionError(f"agent {agent_id} not found")


def _delete_agent_when_ready(app_server, agent_id: str) -> None:
    """Delete an agent once it has finished starting.

    A freshly copied agent boots its workspace asynchronously; DELETE
    returns 409 Conflict while ``startup_status`` is still "starting".
    """
    deadline = time.time() + 60.0
    while time.time() < deadline:
        resp = app_server.api_request(
            "DELETE",
            f"/api/agents/{agent_id}",
            timeout=_HTTP_TIMEOUT,
        )
        if resp.status_code in (200, 204, 404):
            return
        time.sleep(1.0)


# =============================== A. copy ===================================


@pytest.mark.integration
@pytest.mark.p1
def test_copy_agent_creates_new_profile(app_server):
    """Copying an agent produces a new, listed agent.

    Test purpose:
      - Cover copy_agent: it must create a distinct profile from the
        source's config files and register it, which is verified by the
        agent listing rather than the 201 alone.

    Test flow:
      1. POST a copy of the default agent with a distinctive name.
      2. Assert the returned id is new and appears in GET /api/agents.
      3. Delete the copy.
    """
    created_id = None
    try:
        resp = app_server.api_request(
            "POST",
            "/api/agents/default/copy",
            json={
                "name": "Integ Copied Agent",
                "copy_agent_json": True,
                "copy_md_files": True,
                "copy_skills": False,
                "copy_jobs": False,
            },
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 201, resp.text
        created_id = resp.json()["id"]
        assert created_id != "default", resp.json()
        assert created_id in _agent_ids(app_server), created_id
    finally:
        if created_id:
            _delete_agent_when_ready(app_server, created_id)
    assert created_id not in _agent_ids(
        app_server,
    ), "copied agent was not removed during cleanup"


@pytest.mark.integration
@pytest.mark.p2
def test_copy_unknown_agent_returns_404(app_server):
    """Copying an agent that does not exist is a 404.

    Test purpose:
      - Cover copy_agent's source-profile lookup, which runs before any
        directory is created.
    """
    resp = app_server.api_request(
        "POST",
        f"/api/agents/{_ABSENT_AGENT}/copy",
        json={"name": "Should Not Exist", "copy_agent_json": True},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, resp.text
    assert "not found" in resp.text.lower(), resp.text


# ================================ B. pin ===================================


@pytest.mark.integration
@pytest.mark.p1
def test_pin_state_roundtrip_on_copied_agent(app_server):
    """Pinning an agent persists in the agent listing.

    Test purpose:
      - Cover set_agent_pinned's success path. A throwaway copy is used
        as the subject so no long-lived agent's pinned state changes.

    Test flow:
      1. Copy the default agent.
      2. PUT pinned=true and assert the listing reflects it.
      3. PUT pinned=false and assert it flips back.
      4. Delete the copy.
    """
    created = app_server.api_request(
        "POST",
        "/api/agents/default/copy",
        json={"name": "Integ Pin Target", "copy_agent_json": True},
        timeout=_HTTP_TIMEOUT,
    )
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]
    try:
        pin_on = app_server.api_request(
            "PATCH",
            f"/api/agents/{agent_id}/pin",
            json={"pinned": True},
            timeout=_HTTP_TIMEOUT,
        )
        assert pin_on.status_code == 200, pin_on.text
        assert _agent_entry(app_server, agent_id).get("pinned") is True

        pin_off = app_server.api_request(
            "PATCH",
            f"/api/agents/{agent_id}/pin",
            json={"pinned": False},
            timeout=_HTTP_TIMEOUT,
        )
        assert pin_off.status_code == 200, pin_off.text
        assert _agent_entry(app_server, agent_id).get("pinned") is False
    finally:
        _delete_agent_when_ready(app_server, agent_id)


@pytest.mark.integration
@pytest.mark.p1
def test_default_agent_cannot_be_unpinned(app_server):
    """The default agent's pin cannot be removed.

    Test purpose:
      - Cover the explicit default-agent guard: unpinning it would let
        the selector present no agent at all, so the API must refuse.
    """
    resp = app_server.api_request(
        "PATCH",
        "/api/agents/default/pin",
        json={"pinned": False},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, resp.text
    assert "default" in resp.text.lower(), resp.text


@pytest.mark.integration
@pytest.mark.p2
def test_pin_unknown_agent_returns_404(app_server):
    """Pinning a non-existent agent is a 404.

    Test purpose:
      - Cover the profile lookup in set_agent_pinned, distinct from the
        default-agent guard.
    """
    resp = app_server.api_request(
        "PATCH",
        f"/api/agents/{_ABSENT_AGENT}/pin",
        json={"pinned": True},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
@pytest.mark.p2
def test_pin_requires_embedded_boolean(app_server):
    """A pin request without the embedded field is rejected.

    Test purpose:
      - Cover the embedded-Body requirement; without a value there is
        nothing to persist.
    """
    resp = app_server.api_request(
        "PATCH",
        "/api/agents/default/pin",
        json={},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 422, resp.text


# =========================== C. memory reindex =============================


@pytest.mark.integration
@pytest.mark.p2
def test_memory_reindex_rejected_for_non_reme_backend(app_server):
    """Reindex is refused when the agent does not use the ReMe backend.

    Test purpose:
      - Cover the backend guard in rebuild_agent_memory_index: the job
        is expensive and backend-specific, so it must not run for an
        agent configured with a different memory manager.
    """
    resp = app_server.api_request(
        "POST",
        "/api/agents/default/memory/reindex",
        timeout=_HTTP_TIMEOUT,
    )
    # 503 when no memory manager is running, 400/409 when one is up but
    # configured with a non-ReMe backend.
    assert resp.status_code in (400, 409, 503), resp.text
    assert resp.status_code != 500, resp.text


@pytest.mark.integration
@pytest.mark.p2
def test_memory_reindex_unknown_agent_returns_404(app_server):
    """Reindexing an unknown agent is a 404.

    Test purpose:
      - Cover the profile lookup ahead of the backend check.
    """
    resp = app_server.api_request(
        "POST",
        f"/api/agents/{_ABSENT_AGENT}/memory/reindex",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, resp.text
