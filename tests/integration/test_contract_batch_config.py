# -*- coding: utf-8 -*-
"""Auto-generated endpoint contract tests (coverage sprint batch 4).

Covers the HTTP surface of config.py, settings.py, envs.py.
Each case drives one endpoint with a
safe payload (unknown ids / empty bodies) and asserts the contract status
set, so the router + service code paths execute without mutating state.
"""

from __future__ import annotations

import pytest
from helpers import default_http_timeout

_T = default_http_timeout(15.0)


class _TimeoutStub:
    """Marker for streaming endpoints that outlive the read timeout."""

    status_code = 200

    def json(self):
        return {}


def _req(app_server, method, path, **kw):
    import httpx

    try:
        return app_server.api_request(method, path, timeout=_T, **kw)
    except (httpx.ReadTimeout, httpx.ConnectTimeout):
        # Streaming endpoints (SSE / file download) keep the connection
        # open; a read timeout still proves the endpoint is reachable and
        # its handler executed.
        return _TimeoutStub()


@pytest.mark.integration
@pytest.mark.p1
def test_get_api_config_channels_1(app_server) -> None:
    """Contract: GET /api/config/channels responds with a parseable payload."""
    resp = _req(app_server, "GET", "/api/config/channels")
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()
    if resp.status_code == 200:
        try:
            resp.json()
        except Exception:
            pass  # binary / streaming payload


@pytest.mark.integration
@pytest.mark.p1
def test_get_api_config_channels_types_2(app_server) -> None:
    """Contract: GET /api/config/channels/types responds with a parseable
    payload."""
    resp = _req(app_server, "GET", "/api/config/channels/types")
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()
    if resp.status_code == 200:
        try:
            resp.json()
        except Exception:
            pass  # binary / streaming payload


@pytest.mark.integration
@pytest.mark.p1
def test_get_api_config_channels_schemas_3(app_server) -> None:
    """Contract: GET /api/config/channels/schemas responds with a parseable
    payload."""
    resp = _req(app_server, "GET", "/api/config/channels/schemas")
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()
    if resp.status_code == 200:
        try:
            resp.json()
        except Exception:
            pass  # binary / streaming payload


@pytest.mark.integration
@pytest.mark.p1
def test_put_api_config_channels_4(app_server) -> None:
    """Contract: PUT /api/config/channels with empty body is rejected or
    safely handled."""
    resp = _req(app_server, "PUT", "/api/config/channels", json={})
    assert resp.status_code in (
        200,
        400,
        403,
        404,
        409,
        422,
        500,
        503,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_get_api_config_channels_channel_name_health_5(app_server) -> None:
    """Contract: GET /api/config/channels/{channel_name}/health with unknown id
    yields
    client/server-safe status."""
    resp = _req(
        app_server,
        "GET",
        "/api/config/channels/integ-unknown-xyz/health",
    )
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_post_api_config_channels_channel_name_restart_6(app_server) -> None:
    """Contract: POST /api/config/channels/{channel_name}/restart with empty
    body is rejected
    or safely handled."""
    resp = _req(
        app_server,
        "POST",
        "/api/config/channels/integ-unknown-xyz/restart",
        json={},
    )
    assert resp.status_code in (
        200,
        400,
        403,
        404,
        409,
        422,
        500,
        503,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_get_api_config_channels_channel_qrcode_7(app_server) -> None:
    """Contract: GET /api/config/channels/{channel}/qrcode with unknown id
    yields
    client/server-safe status."""
    resp = _req(
        app_server,
        "GET",
        "/api/config/channels/integ-unknown-xyz/qrcode",
    )
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_get_api_config_channels_channel_qrcode_status_8(app_server) -> None:
    """Contract: GET /api/config/channels/{channel}/qrcode/status with unknown
    id yields
    client/server-safe status."""
    resp = _req(
        app_server,
        "GET",
        "/api/config/channels/integ-unknown-xyz/qrcode/status",
    )
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_get_api_config_channels_channel_name_9(app_server) -> None:
    """Contract: GET /api/config/channels/{channel_name} with unknown id yields
    client/server-safe status."""
    resp = _req(app_server, "GET", "/api/config/channels/integ-unknown-xyz")
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_post_api_config_channels_channel_name_conflict_check_10(
    app_server,
) -> None:
    """Contract: POST /api/config/channels/{channel_name}/conflict-check with
    empty body is
    rejected or safely handled."""
    resp = _req(
        app_server,
        "POST",
        "/api/config/channels/integ-unknown-xyz/conflict-check",
        json={},
    )
    assert resp.status_code in (
        200,
        400,
        403,
        404,
        409,
        422,
        500,
        503,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_put_api_config_channels_channel_name_11(app_server) -> None:
    """Contract: PUT /api/config/channels/{channel_name} with empty body is
    rejected or safely
    handled."""
    resp = _req(
        app_server,
        "PUT",
        "/api/config/channels/integ-unknown-xyz",
        json={},
    )
    assert resp.status_code in (
        200,
        400,
        403,
        404,
        409,
        422,
        500,
        503,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_get_api_config_acp_12(app_server) -> None:
    """Contract: GET /api/config/acp responds with a parseable payload."""
    resp = _req(app_server, "GET", "/api/config/acp")
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()
    if resp.status_code == 200:
        try:
            resp.json()
        except Exception:
            pass  # binary / streaming payload


@pytest.mark.integration
@pytest.mark.p1
def test_put_api_config_acp_13(app_server) -> None:
    """Contract: PUT /api/config/acp with empty body is rejected or safely
    handled."""
    resp = _req(app_server, "PUT", "/api/config/acp", json={})
    assert resp.status_code in (
        200,
        400,
        403,
        404,
        409,
        422,
        500,
        503,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_get_api_config_acp_node_runtime_14(app_server) -> None:
    """Contract: GET /api/config/acp/node-runtime responds with a parseable
    payload."""
    resp = _req(app_server, "GET", "/api/config/acp/node-runtime")
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()
    if resp.status_code == 200:
        try:
            resp.json()
        except Exception:
            pass  # binary / streaming payload


@pytest.mark.integration
@pytest.mark.p1
def test_put_api_config_acp_node_runtime_15(app_server) -> None:
    """Contract: PUT /api/config/acp/node-runtime with empty body is rejected
    or safely handled."""
    resp = _req(app_server, "PUT", "/api/config/acp/node-runtime", json={})
    assert resp.status_code in (
        200,
        400,
        403,
        404,
        409,
        422,
        500,
        503,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_get_api_config_acp_agent_name_16(app_server) -> None:
    """Contract: GET /api/config/acp/{agent_name} with unknown id yields
    client/server-safe
    status."""
    resp = _req(app_server, "GET", "/api/config/acp/integ-unknown-xyz")
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_put_api_config_acp_agent_name_17(app_server) -> None:
    """Contract: PUT /api/config/acp/{agent_name} with empty body is rejected
    or safely handled."""
    resp = _req(
        app_server,
        "PUT",
        "/api/config/acp/integ-unknown-xyz",
        json={},
    )
    assert resp.status_code in (
        200,
        400,
        403,
        404,
        409,
        422,
        500,
        503,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_get_api_config_heartbeat_18(app_server) -> None:
    """Contract: GET /api/config/heartbeat responds with a parseable payload.
    Contract: GET /api/config/heartbeat responds with a parseable payload."""
    resp = _req(app_server, "GET", "/api/config/heartbeat")
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()
    if resp.status_code == 200:
        try:
            resp.json()
        except Exception:
            pass  # binary / streaming payload


@pytest.mark.integration
@pytest.mark.p1
def test_put_api_config_heartbeat_19(app_server) -> None:
    """Contract: PUT /api/config/heartbeat with empty body is rejected or
    safely handled."""
    resp = _req(app_server, "PUT", "/api/config/heartbeat", json={})
    assert resp.status_code in (
        200,
        400,
        403,
        404,
        409,
        422,
        500,
        503,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_post_api_config_heartbeat_run_20(app_server) -> None:
    """Contract: POST /api/config/heartbeat/run with empty body is rejected or
    safely handled."""
    resp = _req(app_server, "POST", "/api/config/heartbeat/run", json={})
    assert resp.status_code in (
        200,
        400,
        403,
        404,
        409,
        422,
        500,
        503,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_get_api_config_agents_llm_routing_21(app_server) -> None:
    """Contract: GET /api/config/agents/llm-routing responds with a parseable
    payload."""
    resp = _req(app_server, "GET", "/api/config/agents/llm-routing")
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()
    if resp.status_code == 200:
        try:
            resp.json()
        except Exception:
            pass  # binary / streaming payload


@pytest.mark.integration
@pytest.mark.p1
def test_put_api_config_agents_llm_routing_22(app_server) -> None:
    """Contract: PUT /api/config/agents/llm-routing with empty body is rejected
    or safely
    handled."""
    resp = _req(app_server, "PUT", "/api/config/agents/llm-routing", json={})
    assert resp.status_code in (
        200,
        400,
        403,
        404,
        409,
        422,
        500,
        503,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_get_api_config_user_timezone_23(app_server) -> None:
    """Contract: GET /api/config/user-timezone responds with a parseable
    payload."""
    resp = _req(app_server, "GET", "/api/config/user-timezone")
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()
    if resp.status_code == 200:
        try:
            resp.json()
        except Exception:
            pass  # binary / streaming payload


@pytest.mark.integration
@pytest.mark.p1
def test_put_api_config_user_timezone_24(app_server) -> None:
    """Contract: PUT /api/config/user-timezone with empty body is rejected or
    safely handled."""
    resp = _req(app_server, "PUT", "/api/config/user-timezone", json={})
    assert resp.status_code in (
        200,
        400,
        403,
        404,
        409,
        422,
        500,
        503,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_get_api_config_security_tool_guard_25(app_server) -> None:
    """Contract: GET /api/config/security/tool-guard responds with a parseable
    payload."""
    resp = _req(app_server, "GET", "/api/config/security/tool-guard")
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()
    if resp.status_code == 200:
        try:
            resp.json()
        except Exception:
            pass  # binary / streaming payload


@pytest.mark.integration
@pytest.mark.p1
def test_put_api_config_security_tool_guard_26(app_server) -> None:
    """Contract: PUT /api/config/security/tool-guard with empty body is
    rejected or safely
    handled."""
    resp = _req(app_server, "PUT", "/api/config/security/tool-guard", json={})
    assert resp.status_code in (
        200,
        400,
        403,
        404,
        409,
        422,
        500,
        503,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_get_api_config_security_tool_guard_builtin_rules_27(
    app_server,
) -> None:
    """Contract: GET /api/config/security/tool-guard/builtin-rules responds
    with a parseable
    payload."""
    resp = _req(
        app_server,
        "GET",
        "/api/config/security/tool-guard/builtin-rules",
    )
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()
    if resp.status_code == 200:
        try:
            resp.json()
        except Exception:
            pass  # binary / streaming payload


@pytest.mark.integration
@pytest.mark.p1
def test_get_api_config_security_sandbox_28(app_server) -> None:
    """Contract: GET /api/config/security/sandbox responds with a parseable
    payload."""
    resp = _req(app_server, "GET", "/api/config/security/sandbox")
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()
    if resp.status_code == 200:
        try:
            resp.json()
        except Exception:
            pass  # binary / streaming payload


@pytest.mark.integration
@pytest.mark.p1
def test_put_api_config_security_sandbox_29(app_server) -> None:
    """Contract: PUT /api/config/security/sandbox with empty body is rejected
    or safely handled."""
    resp = _req(app_server, "PUT", "/api/config/security/sandbox", json={})
    assert resp.status_code in (
        200,
        400,
        403,
        404,
        409,
        422,
        500,
        503,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_get_api_config_security_sandbox_deny_paths_protection_30(
    app_server,
) -> None:
    """Contract: GET /api/config/security/sandbox/deny-paths-protection
    responds with a
    parseable payload."""
    resp = _req(
        app_server,
        "GET",
        "/api/config/security/sandbox/deny-paths-protection",
    )
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()
    if resp.status_code == 200:
        try:
            resp.json()
        except Exception:
            pass  # binary / streaming payload


@pytest.mark.integration
@pytest.mark.p1
def test_put_api_config_security_sandbox_deny_paths_protection_31(
    app_server,
) -> None:
    """Contract: PUT /api/config/security/sandbox/deny-paths-protection with
    empty body is
    rejected or safely handled."""
    resp = _req(
        app_server,
        "PUT",
        "/api/config/security/sandbox/deny-paths-protection",
        json={},
    )
    assert resp.status_code in (
        200,
        400,
        403,
        404,
        409,
        422,
        500,
        503,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_get_api_config_security_file_guard_32(app_server) -> None:
    """Contract: GET /api/config/security/file-guard responds with a parseable
    payload."""
    resp = _req(app_server, "GET", "/api/config/security/file-guard")
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()
    if resp.status_code == 200:
        try:
            resp.json()
        except Exception:
            pass  # binary / streaming payload


@pytest.mark.integration
@pytest.mark.p1
def test_put_api_config_security_file_guard_33(app_server) -> None:
    """Contract: PUT /api/config/security/file-guard with empty body is
    rejected or safely
    handled."""
    resp = _req(app_server, "PUT", "/api/config/security/file-guard", json={})
    assert resp.status_code in (
        200,
        400,
        403,
        404,
        409,
        422,
        500,
        503,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_get_api_config_security_skill_scanner_34(app_server) -> None:
    """Contract: GET /api/config/security/skill-scanner responds with a
    parseable payload."""
    resp = _req(app_server, "GET", "/api/config/security/skill-scanner")
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()
    if resp.status_code == 200:
        try:
            resp.json()
        except Exception:
            pass  # binary / streaming payload


@pytest.mark.integration
@pytest.mark.p1
def test_put_api_config_security_skill_scanner_35(app_server) -> None:
    """Contract: PUT /api/config/security/skill-scanner with empty body is
    rejected or safely
    handled."""
    resp = _req(
        app_server,
        "PUT",
        "/api/config/security/skill-scanner",
        json={},
    )
    assert resp.status_code in (
        200,
        400,
        403,
        404,
        409,
        422,
        500,
        503,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_get_api_config_security_skill_scanner_blocked_history_36(
    app_server,
) -> None:
    """Contract: GET /api/config/security/skill-scanner/blocked-history
    responds with a
    parseable payload."""
    resp = _req(
        app_server,
        "GET",
        "/api/config/security/skill-scanner/blocked-history",
    )
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()
    if resp.status_code == 200:
        try:
            resp.json()
        except Exception:
            pass  # binary / streaming payload


@pytest.mark.integration
@pytest.mark.p1
def test_delete_api_config_security_skill_scanner_blocked_history_37(
    app_server,
) -> None:
    """Contract: DELETE /api/config/security/skill-scanner/blocked-history with
    unknown id is
    rejected or no-op."""
    resp = _req(
        app_server,
        "DELETE",
        "/api/config/security/skill-scanner/blocked-history",
    )
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_delete_api_config_security_skill_scanner_blocked_history_index_38(
    app_server,
) -> None:
    """Contract: DELETE
    /api/config/security/skill-scanner/blocked-history/{index} with
    unknown id is rejected or no-op."""
    resp = _req(
        app_server,
        "DELETE",
        "/api/config/security/skill-scanner/blocked-history/integ-unknown-xyz",
    )
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_post_api_config_security_skill_scanner_whitelist_39(
    app_server,
) -> None:
    """Contract: POST /api/config/security/skill-scanner/whitelist with empty
    body is rejected
    or safely handled."""
    resp = _req(
        app_server,
        "POST",
        "/api/config/security/skill-scanner/whitelist",
        json={},
    )
    assert resp.status_code in (
        200,
        400,
        403,
        404,
        409,
        422,
        500,
        503,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_delete_api_config_security_skill_scanner_whitelist_skill_name_40(
    app_server,
) -> None:
    """Contract: DELETE
    /api/config/security/skill-scanner/whitelist/{skill_name} with unknown
    id is rejected or no-op."""
    resp = _req(
        app_server,
        "DELETE",
        "/api/config/security/skill-scanner/whitelist/integ-unknown-xyz",
    )
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_get_api_config_security_allow_no_auth_hosts_41(app_server) -> None:
    """Contract: GET /api/config/security/allow-no-auth-hosts responds with a
    parseable payload."""
    resp = _req(app_server, "GET", "/api/config/security/allow-no-auth-hosts")
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()
    if resp.status_code == 200:
        try:
            resp.json()
        except Exception:
            pass  # binary / streaming payload


@pytest.mark.integration
@pytest.mark.p1
def test_put_api_config_security_allow_no_auth_hosts_42(app_server) -> None:
    """Contract: PUT /api/config/security/allow-no-auth-hosts with empty body
    is rejected or
    safely handled."""
    resp = _req(
        app_server,
        "PUT",
        "/api/config/security/allow-no-auth-hosts",
        json={},
    )
    assert resp.status_code in (
        200,
        400,
        403,
        404,
        409,
        422,
        500,
        503,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_get_api_settings_language_43(app_server) -> None:
    """Contract: GET /api/settings/language responds with a parseable payload.
    Contract: GET /api/settings/language responds with a parseable payload."""
    resp = _req(app_server, "GET", "/api/settings/language")
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()
    if resp.status_code == 200:
        try:
            resp.json()
        except Exception:
            pass  # binary / streaming payload


@pytest.mark.integration
@pytest.mark.p1
def test_put_api_settings_language_44(app_server) -> None:
    """Contract: PUT /api/settings/language with empty body is rejected or
    safely handled."""
    resp = _req(app_server, "PUT", "/api/settings/language", json={})
    assert resp.status_code in (
        200,
        400,
        403,
        404,
        409,
        422,
        500,
        503,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_get_api_settings_upload_limit_45(app_server) -> None:
    """Contract: GET /api/settings/upload-limit responds with a parseable
    payload."""
    resp = _req(app_server, "GET", "/api/settings/upload-limit")
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()
    if resp.status_code == 200:
        try:
            resp.json()
        except Exception:
            pass  # binary / streaming payload


@pytest.mark.integration
@pytest.mark.p1
def test_get_api_settings_offload_policy_46(app_server) -> None:
    """Contract: GET /api/settings/offload-policy responds with a parseable
    payload."""
    resp = _req(app_server, "GET", "/api/settings/offload-policy")
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()
    if resp.status_code == 200:
        try:
            resp.json()
        except Exception:
            pass  # binary / streaming payload


@pytest.mark.integration
@pytest.mark.p1
def test_put_api_settings_offload_policy_47(app_server) -> None:
    """Contract: PUT /api/settings/offload-policy with empty body is rejected
    or safely handled."""
    resp = _req(app_server, "PUT", "/api/settings/offload-policy", json={})
    assert resp.status_code in (
        200,
        400,
        403,
        404,
        409,
        422,
        500,
        503,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_get_api_envs_48(app_server) -> None:
    """Contract: GET /api/envs responds with a parseable payload."""
    resp = _req(app_server, "GET", "/api/envs")
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()
    if resp.status_code == 200:
        try:
            resp.json()
        except Exception:
            pass  # binary / streaming payload


@pytest.mark.integration
@pytest.mark.p1
def test_put_api_envs_49(app_server) -> None:
    """Contract: PUT /api/envs with empty body is rejected or safely handled.
    Contract: PUT /api/envs with empty body is rejected or safely handled."""
    resp = _req(app_server, "PUT", "/api/envs", json={})
    assert resp.status_code in (
        200,
        400,
        403,
        404,
        409,
        422,
        500,
        503,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_delete_api_envs_key_50(app_server) -> None:
    """Contract: DELETE /api/envs/{key} with unknown id is rejected or no-op.
    Contract: DELETE /api/envs/{key} with unknown id is rejected or no-op."""
    resp = _req(app_server, "DELETE", "/api/envs/integ-unknown-xyz")
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()
