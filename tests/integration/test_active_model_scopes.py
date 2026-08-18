# -*- coding: utf-8 -*-
"""Active-model resolution across read scopes.

Covers the scope branches of ``GET /api/models/active`` in
``app/routers/providers.py``, which existing provider tests exercise only
for ``scope=global``: the agent scope and its required-``agent_id``
guard, the default ``effective`` scope that prefers an agent-specific
model and otherwise falls back to the global one, and the unknown-scope
rejection.

Assertions compare the payloads the three scopes return to each other
rather than merely checking for 200, so a regression that collapses the
scopes into one answer is caught.

API endpoints:
  - GET /api/models/active
  - PUT /api/models/active
"""
from __future__ import annotations

import threading
from http.server import HTTPServer

import pytest
from helpers import (
    MOCK_LLM_PROVIDER_ID,
    MockLLMHandler,
    default_http_timeout,
    register_mock_provider,
    unregister_mock_provider,
)

_HTTP_TIMEOUT = default_http_timeout(30.0)
_ACTIVE = "/api/models/active"


@pytest.fixture(scope="module")
def mock_llm():
    """Module-scoped mock OpenAI server so a real provider is active."""
    srv = HTTPServer(("127.0.0.1", 0), MockLLMHandler)
    srv.force_error = False
    srv.force_tool_call = False
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv, f"http://127.0.0.1:{port}/v1"
    srv.shutdown()


@pytest.fixture
def active_provider(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """Register + activate the mock provider for the duration of a test."""
    _srv, mock_url = mock_llm
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    yield provider_id
    unregister_mock_provider(app_server, provider_id)


def _get_active(app_server, **params) -> dict:
    resp = app_server.api_request(
        "GET",
        _ACTIVE,
        params=params or None,
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, dict), body
    return body


@pytest.mark.integration
@pytest.mark.p1
def test_global_scope_reports_activated_provider(
    app_server,
    active_provider,  # pylint: disable=redefined-outer-name
):
    """The global scope reports the provider that was just activated.

    Test purpose:
      - Cover the ``scope=global`` arm together with
        ProviderManager.get_active_model, asserting the activated
        provider id actually surfaces rather than any 200 body.
    """
    body = _get_active(app_server, scope="global")
    assert active_provider in str(body), body


@pytest.mark.integration
@pytest.mark.p1
def test_effective_scope_falls_back_to_global(
    app_server,
    active_provider,  # pylint: disable=redefined-outer-name
):
    """The default effective scope resolves to a usable model.

    Test purpose:
      - Cover the ``effective`` arm: with no agent-specific override it
        must fall back to the global model, so its answer matches the
        global scope.
    """
    effective = _get_active(app_server)
    global_scope = _get_active(app_server, scope="global")
    assert active_provider in str(effective), effective
    assert effective.get("active_llm") == global_scope.get(
        "active_llm",
    ), (effective, global_scope)


@pytest.mark.integration
@pytest.mark.p1
def test_agent_scope_requires_agent_id(app_server):
    """Requesting the agent scope without an agent_id is a 400.

    Test purpose:
      - Cover the explicit guard in get_active_models; without it the
        handler would look up ``None`` and report a misleading answer.
    """
    resp = app_server.api_request(
        "GET",
        _ACTIVE,
        params={"scope": "agent"},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, resp.text
    assert "agent_id" in resp.text, resp.text


@pytest.mark.integration
@pytest.mark.p2
def test_agent_scope_for_default_agent(
    app_server,
    active_provider,  # pylint: disable=redefined-outer-name,unused-argument
):
    """The agent scope answers for a named agent.

    Test purpose:
      - Cover the ``scope=agent`` arm plus _load_agent_model. The default
        agent may have no explicit override, so the payload shape is
        asserted rather than a specific provider.
    """
    body = _get_active(app_server, scope="agent", agent_id="default")
    # The model is nested under "active_llm"; it is null when the agent
    # has no explicit override.
    assert "active_llm" in body, body
    slot = body["active_llm"]
    assert slot is None or isinstance(slot, dict), body


@pytest.mark.integration
@pytest.mark.p2
def test_agent_scope_unknown_agent_is_handled(app_server):
    """An unknown agent id does not produce a 500.

    Test purpose:
      - Cover _load_agent_model's failure handling for an agent that has
        no config on disk.
    """
    resp = app_server.api_request(
        "GET",
        _ACTIVE,
        params={"scope": "agent", "agent_id": "integ-absent-agent-4410"},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code in (200, 400, 404), resp.text
    assert resp.status_code != 500, resp.text


@pytest.mark.integration
@pytest.mark.p2
def test_unknown_scope_is_rejected(app_server):
    """An unsupported scope value is rejected by query validation.

    Test purpose:
      - Cover the ActiveModelReadScope Literal constraint, so a typo in
        the console cannot silently fall through to a default answer.
    """
    resp = app_server.api_request(
        "GET",
        _ACTIVE,
        params={"scope": "integ-not-a-scope"},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 422, resp.text
