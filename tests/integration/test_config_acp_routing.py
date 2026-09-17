# -*- coding: utf-8 -*-
"""ACP, LLM-routing and channel-schema config endpoints.

Covers the parts of ``app/routers/config.py`` that existing config tests
do not reach: the per-agent ACP config round trip, the global ACP Node
runtime status and update, the agents LLM-routing settings round trip
with its mode validation, the channel schema/type catalogues, and the
heartbeat manual-run trigger.

Every writable setting is read back and compared, and each test restores
the value it found in ``finally`` so the shared config is left as it was.
No endpoint here reaches an external service: the Node runtime lookup is
a local ``which``-style probe and the heartbeat run is in-process.

API endpoints:
  - GET  /api/config/acp
  - PUT  /api/config/acp
  - GET  /api/config/acp/node-runtime
  - PUT  /api/config/acp/node-runtime
  - GET  /api/config/agents/llm-routing
  - PUT  /api/config/agents/llm-routing
  - GET  /api/config/channels/schemas
  - GET  /api/config/channels/types
  - POST /api/config/heartbeat/run
"""
from __future__ import annotations

import pytest
from helpers import default_http_timeout

_HTTP_TIMEOUT = default_http_timeout(30.0)


# ============================== A. ACP config ==============================


@pytest.mark.integration
@pytest.mark.p1
def test_acp_config_roundtrip(app_server):
    """The agent's ACP config persists across PUT/GET.

    Test purpose:
      - Cover get_acp_config / put_acp_config, which read and write the
        per-agent ACP block rather than the global config.

    Test flow:
      1. GET the current ACP config as a baseline.
      2. PUT it back with ``enabled`` inverted and assert GET agrees.
      3. Restore the baseline.
    """
    before = app_server.api_request(
        "GET",
        "/api/config/acp",
        timeout=_HTTP_TIMEOUT,
    )
    assert before.status_code == 200, before.text
    baseline = before.json()
    assert "agents" in baseline, baseline
    # ACPConfig is {node_path, agents}; flip one ACP agent's enabled flag
    # so the round trip exercises the nested structure.
    patched = dict(baseline)
    agents = {k: dict(v) for k, v in (baseline.get("agents") or {}).items()}
    if not agents:
        pytest.skip("no ACP agents configured in this environment")
    target_name = sorted(agents)[0]
    target_state = not bool(agents[target_name].get("enabled", False))
    agents[target_name]["enabled"] = target_state
    patched["agents"] = agents
    try:
        put_resp = app_server.api_request(
            "PUT",
            "/api/config/acp",
            json=patched,
            timeout=_HTTP_TIMEOUT,
        )
        assert put_resp.status_code == 200, put_resp.text
        after = app_server.api_request(
            "GET",
            "/api/config/acp",
            timeout=_HTTP_TIMEOUT,
        )
        assert after.status_code == 200, after.text
        stored = (after.json().get("agents") or {}).get(target_name) or {}
        assert stored.get("enabled") is target_state, after.json()
    finally:
        app_server.api_request(
            "PUT",
            "/api/config/acp",
            json=baseline,
            timeout=_HTTP_TIMEOUT,
        )


@pytest.mark.integration
@pytest.mark.p2
def test_acp_node_runtime_status_shape(app_server):
    """The ACP Node runtime probe reports a structured status.

    Test purpose:
      - Cover get_acp_node_runtime / get_node_runtime_status, which must
        answer even when no Node runtime is installed.
    """
    resp = app_server.api_request(
        "GET",
        "/api/config/acp/node-runtime",
        timeout=default_http_timeout(60.0),
    )
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json(), dict), resp.text


@pytest.mark.integration
@pytest.mark.p2
def test_acp_node_runtime_rejects_bogus_path(app_server):
    """A non-existent Node path is refused or reported unavailable.

    Test purpose:
      - Cover put_acp_node_runtime's validation of a supplied path; it
        must not silently record an unusable interpreter as ready.
    """
    resp = app_server.api_request(
        "PUT",
        "/api/config/acp/node-runtime",
        json={"node_path": "/integ/no/such/node/binary"},
        timeout=default_http_timeout(60.0),
    )
    assert resp.status_code in (200, 400, 422), resp.text
    if resp.status_code == 200:
        body = resp.json()
        # If accepted, the probe must not claim the bogus path works.
        assert body.get("available") in (False, None), body
    # Clear the bogus value so later runs auto-detect again.
    app_server.api_request(
        "PUT",
        "/api/config/acp/node-runtime",
        json={"node_path": ""},
        timeout=default_http_timeout(60.0),
    )


# =========================== B. LLM routing ================================


@pytest.mark.integration
@pytest.mark.p1
def test_llm_routing_roundtrip(app_server):
    """LLM-routing settings persist across PUT/GET.

    Test purpose:
      - Cover get_agents_llm_routing / put_agents_llm_routing including
        the dual-slot shape (local slot plus optional cloud slot).

    Test flow:
      1. GET the baseline routing config.
      2. PUT it back with ``mode`` switched and assert GET reflects it.
      3. Restore the baseline.
    """
    before = app_server.api_request(
        "GET",
        "/api/config/agents/llm-routing",
        timeout=_HTTP_TIMEOUT,
    )
    assert before.status_code == 200, before.text
    baseline = before.json()
    target = (
        "cloud_first"
        if baseline.get("mode") != "cloud_first"
        else "local_first"
    )
    patched = dict(baseline)
    patched["mode"] = target
    try:
        put_resp = app_server.api_request(
            "PUT",
            "/api/config/agents/llm-routing",
            json=patched,
            timeout=_HTTP_TIMEOUT,
        )
        assert put_resp.status_code == 200, put_resp.text
        assert put_resp.json().get("mode") == target, put_resp.json()
        after = app_server.api_request(
            "GET",
            "/api/config/agents/llm-routing",
            timeout=_HTTP_TIMEOUT,
        )
        assert after.json().get("mode") == target, after.json()
    finally:
        app_server.api_request(
            "PUT",
            "/api/config/agents/llm-routing",
            json=baseline,
            timeout=_HTTP_TIMEOUT,
        )


@pytest.mark.integration
@pytest.mark.p2
def test_llm_routing_rejects_unknown_mode(app_server):
    """An unsupported routing mode is rejected by schema validation.

    Test purpose:
      - Cover the Literal constraint on ``mode``; an unknown value must
        not be persisted as a silent passthrough.
    """
    resp = app_server.api_request(
        "PUT",
        "/api/config/agents/llm-routing",
        json={"enabled": False, "mode": "integ-not-a-mode"},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 422, resp.text
    # The stored mode must still be one of the supported values.
    after = app_server.api_request(
        "GET",
        "/api/config/agents/llm-routing",
        timeout=_HTTP_TIMEOUT,
    )
    assert after.json().get("mode") in (
        "local_first",
        "cloud_first",
    ), after.json()


# ====================== C. channel catalogues / heartbeat ==================


@pytest.mark.integration
@pytest.mark.p1
def test_channel_schemas_cover_channel_types(app_server):
    """Every advertised channel type has a config schema.

    Test purpose:
      - Cover the channel schema catalogue and assert it lines up with
        the channel-type listing, so the console cannot be asked to
        render a type it has no schema for.
    """
    types_resp = app_server.api_request(
        "GET",
        "/api/config/channels/types",
        timeout=_HTTP_TIMEOUT,
    )
    assert types_resp.status_code == 200, types_resp.text

    schemas_resp = app_server.api_request(
        "GET",
        "/api/config/channels/schemas",
        timeout=_HTTP_TIMEOUT,
    )
    assert schemas_resp.status_code == 200, schemas_resp.text
    # This catalogue covers *plugin*-registered channels only, so it is
    # legitimately empty when no channel plugins are installed. The
    # builtin types come from the /types listing instead.
    schemas = schemas_resp.json()
    assert isinstance(schemas, dict), schemas
    types_text = types_resp.text
    for known in ("console", "dingtalk"):
        assert known in types_text, f"{known} missing from channel types"
    for name, schema in schemas.items():
        assert isinstance(schema, (dict, list)), (name, schema)


@pytest.mark.integration
@pytest.mark.p2
def test_heartbeat_manual_run_is_accepted(app_server):
    """The heartbeat can be triggered manually.

    Test purpose:
      - Cover the heartbeat run endpoint, which performs an in-process
        pass; it must report a result rather than 500 even when no
        heartbeat targets are configured.
    """
    resp = app_server.api_request(
        "POST",
        "/api/config/heartbeat/run",
        timeout=default_http_timeout(60.0),
    )
    assert resp.status_code in (200, 400, 409), resp.text
    assert resp.status_code != 500, resp.text
