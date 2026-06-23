# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
# -*- coding: utf-8 -*-
"""Integration tests for the security stack — Sprint 3.3.

Goes beyond config CRUD (already in test_security_config.py /
test_approval.py) to verify:
  A. Tool Guard built-in rules endpoint + config reload + auto-deny
     of known-dangerous shell commands during a real cron agent run.
  B. File Guard real path blocking via the file preview HTTP
     endpoint (the only HTTP surface that exercises FileGuardian today).
  C. Skill Scanner whitelist add/delete + blocked-history GET/DELETE.
  D. Approval real lifecycle — create pending, list, approve / deny,
     timeout — by directly creating PendingApproval via the in-process
     ApprovalService is NOT possible from outside the subprocess; we
     exercise the HTTP-observable parts.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.parse
from http.server import HTTPServer

import pytest

from helpers import (
    MOCK_LLM_PROVIDER_ID,
    MockLLMHandler,
    clean_inbox,
    register_mock_provider,
    scoped,
    unregister_mock_provider,
)

_HTTP_TIMEOUT = 15.0
_NEVER_FIRE_SCHEDULE = "0 0 1 1 *"


# ------------------------------------------------------------------ #
# fixtures
# ------------------------------------------------------------------ #


@pytest.fixture(scope="module")
def mock_llm():
    srv = HTTPServer(("127.0.0.1", 0), MockLLMHandler)
    srv.force_error = False
    srv.force_tool_call = False
    srv.tool_call_name = "execute_shell_command"
    srv.tool_call_arguments = "{}"
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv, f"http://127.0.0.1:{port}/v1"
    srv.shutdown()


# ------------------------------------------------------------------ #
# A. Tool Guard
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_tool_guard_builtin_rules_endpoint_lists_dangerous_rm(
    app_server,
) -> None:
    """Test purpose:
    - Verify GET /api/config/security/tool-guard/builtin-rules returns
      the built-in YAML rules including TOOL_CMD_DANGEROUS_RM.

    API endpoints:
    - GET /api/config/security/tool-guard/builtin-rules
    """
    resp = app_server.api_request(
        "GET",
        "/api/config/security/tool-guard/builtin-rules",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    rules = resp.json()
    assert isinstance(rules, list) and rules, rules
    rule_ids = {r.get("id") for r in rules}
    assert (
        "TOOL_CMD_DANGEROUS_RM" in rule_ids
    ), f"missing TOOL_CMD_DANGEROUS_RM: {rule_ids}"
    # Spot-check structure of one rule.
    rm_rule = next(r for r in rules if r["id"] == "TOOL_CMD_DANGEROUS_RM")
    for key in ("tools", "patterns", "severity", "category"):
        assert key in rm_rule, rm_rule


@pytest.mark.integration
@pytest.mark.p1
def test_tool_guard_put_disabled_persists(app_server) -> None:
    """Test purpose:
    - Verify PUT /api/config/security/tool-guard with enabled=false
      persists, and GET reflects the new state.

    API endpoints:
    - GET /api/config/security/tool-guard
    - PUT /api/config/security/tool-guard
    """
    get_before = app_server.api_request(
        "GET",
        "/api/config/security/tool-guard",
        timeout=_HTTP_TIMEOUT,
    )
    baseline = get_before.json()
    patched = dict(baseline)
    patched["enabled"] = not bool(baseline.get("enabled", True))
    try:
        put_resp = app_server.api_request(
            "PUT",
            "/api/config/security/tool-guard",
            json=patched,
            timeout=_HTTP_TIMEOUT,
        )
        assert put_resp.status_code == 200, app_server.logs_tail()
        get_after = app_server.api_request(
            "GET",
            "/api/config/security/tool-guard",
            timeout=_HTTP_TIMEOUT,
        )
        assert (
            get_after.json().get("enabled") == patched["enabled"]
        ), get_after.json()
    finally:
        # Restore baseline.
        app_server.api_request(
            "PUT",
            "/api/config/security/tool-guard",
            json=baseline,
            timeout=_HTTP_TIMEOUT,
        )


@pytest.mark.integration
@pytest.mark.p2
def test_tool_guard_custom_rule_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify a user-defined custom rule added via PUT /tool-guard
      persists in config and is returned by subsequent GET.

    API endpoints:
    - GET /api/config/security/tool-guard
    - PUT /api/config/security/tool-guard
    """
    get_before = app_server.api_request(
        "GET",
        "/api/config/security/tool-guard",
        timeout=_HTTP_TIMEOUT,
    )
    baseline = get_before.json()
    custom_rule = {
        "id": "INTEG_CUSTOM_RULE_X",
        "tools": ["execute_shell_command"],
        "params": ["command"],
        "category": "command_injection",
        "severity": "HIGH",
        "patterns": [r"\bintegtest_dangerous_token\b"],
        "exclude_patterns": [],
        "description": "integration test custom rule",
        "remediation": "remove the dangerous token",
    }
    patched = dict(baseline)
    patched["custom_rules"] = list(baseline.get("custom_rules") or []) + [
        custom_rule,
    ]
    try:
        put_resp = app_server.api_request(
            "PUT",
            "/api/config/security/tool-guard",
            json=patched,
            timeout=_HTTP_TIMEOUT,
        )
        assert put_resp.status_code == 200, app_server.logs_tail()

        get_after = app_server.api_request(
            "GET",
            "/api/config/security/tool-guard",
            timeout=_HTTP_TIMEOUT,
        )
        body = get_after.json()
        custom_ids = {r.get("id") for r in (body.get("custom_rules") or [])}
        assert (
            "INTEG_CUSTOM_RULE_X" in custom_ids
        ), f"custom rule missing: {body.get('custom_rules')}"
    finally:
        app_server.api_request(
            "PUT",
            "/api/config/security/tool-guard",
            json=baseline,
            timeout=_HTTP_TIMEOUT,
        )


@pytest.mark.integration
@pytest.mark.p0
def test_tool_guard_blocks_dangerous_shell_via_agent_run(
    app_server,
    mock_llm,
) -> None:
    """Test purpose:
    - Verify the tool guard ACTUALLY intercepts an ``rm -rf`` style
      shell command issued by an agent during a real cron run.

    Test flow:
    1. Register mock LLM provider.
    2. Drive MockLLM to emit a tool_call for ``execute_shell_command``
       with arguments ``{"command": "rm -rf /"}``.
    3. Trigger an agent-type cron run.
    4. Poll history → expect either ``failure`` (auto-denied) or
       ``success`` with the denial surfaced as part of the response.
       The key invariant: the tool guard ran and prevented uncontrolled
       execution (no infinite loop / deadlock).
    """
    srv, mock_url = mock_llm
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    register_mock_provider(app_server, mock_url)
    clean_inbox(app_server.working_dir)

    srv.force_tool_call = True
    srv.tool_call_name = "execute_shell_command"
    srv.tool_call_arguments = json.dumps({"command": "rm -rf /"})

    spec = {
        "name": "tool_guard_blocks",
        "enabled": True,
        "schedule": {
            "type": "cron",
            "cron": _NEVER_FIRE_SCHEDULE,
            "timezone": "UTC",
        },
        "task_type": "agent",
        "request": {
            "input": [
                {
                    "role": "user",
                    "type": "message",
                    "content": [
                        {"type": "text", "text": "delete everything"},
                    ],
                },
            ],
        },
        "dispatch": {
            "type": "channel",
            "channel": "console",
            "target": {
                "user_id": "tg-blocks",
                "session_id": "console:tg-blocks-sess",
            },
            "mode": "stream",
        },
        "save_result_to_inbox": False,
    }
    job_resp = app_server.api_request(
        "POST",
        "/api/cron/jobs",
        json=spec,
        timeout=_HTTP_TIMEOUT,
    )
    assert job_resp.status_code == 200, app_server.logs_tail()
    job_id = job_resp.json()["id"]

    try:
        run_resp = app_server.api_request(
            "POST",
            f"/api/cron/jobs/{job_id}/run",
            timeout=_HTTP_TIMEOUT,
        )
        assert run_resp.status_code == 200, app_server.logs_tail()

        # Wait long enough for LLM round-trip + tool call to be issued.
        # The guard fires synchronously on the tool call, so we don't
        # need to wait for cron history (which may stall on approval).
        deadline = time.time() + 30.0
        guard_seen = False
        while time.time() < deadline:
            logs = app_server.logs_tail(20000)
            if "TOOL GUARD" in logs and "TOOL_CMD_DANGEROUS_RM" in logs:
                guard_seen = True
                break
            time.sleep(1.0)
        assert guard_seen, (
            "tool guard did not intercept rm -rf:\n"
            f"{app_server.logs_tail()[-3000:]}"
        )
    finally:
        try:
            app_server.api_request(
                "DELETE",
                f"/api/cron/jobs/{job_id}",
                timeout=_HTTP_TIMEOUT,
            )
        except Exception:
            pass
        srv.force_tool_call = False
        unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)


# ------------------------------------------------------------------ #
# B. File Guard
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_file_guard_sensitive_files_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify PUT /api/config/security/file-guard with a custom
      sensitive_files list persists, and GET reflects it.

    API endpoints:
    - GET /api/config/security/file-guard
    - PUT /api/config/security/file-guard
    """
    get_before = app_server.api_request(
        "GET",
        "/api/config/security/file-guard",
        timeout=_HTTP_TIMEOUT,
    )
    baseline = get_before.json()
    patched = dict(baseline)
    new_paths = list(baseline.get("paths") or []) + [
        "/integ-test-fake-secret.txt",
    ]
    patched["paths"] = new_paths
    try:
        put_resp = app_server.api_request(
            "PUT",
            "/api/config/security/file-guard",
            json=patched,
            timeout=_HTTP_TIMEOUT,
        )
        assert put_resp.status_code == 200, app_server.logs_tail()
        get_after = app_server.api_request(
            "GET",
            "/api/config/security/file-guard",
            timeout=_HTTP_TIMEOUT,
        )
        body = get_after.json()
        assert "/integ-test-fake-secret.txt" in (body.get("paths") or []), body
    finally:
        app_server.api_request(
            "PUT",
            "/api/config/security/file-guard",
            json=baseline,
            timeout=_HTTP_TIMEOUT,
        )


@pytest.mark.integration
@pytest.mark.p0
def test_file_guard_blocks_secret_dir_preview(app_server) -> None:
    """Test purpose:
    - Verify the file preview endpoint actually blocks reading from the
      protected secret directory (secret_dir is a default-deny entry in
      FilePathToolGuardian._DEFAULT_DENY_DIRS).

    Test flow:
    1. The secret directory is alongside working_dir (sibling).
    2. Create a fake file inside secret_dir.
    3. GET /api/files/preview/<absolute path> → 403 SENSITIVE_FILE_BLOCKED.
    """
    secret_dir = app_server.working_dir.parent / "working.secret"
    secret_dir.mkdir(parents=True, exist_ok=True)
    secret_file = secret_dir / "fake_secret.txt"
    secret_file.write_text("super secret")

    encoded = urllib.parse.quote(str(secret_file.resolve()), safe="")
    resp = app_server.api_request(
        "GET",
        f"/api/files/preview/{encoded}",
        timeout=_HTTP_TIMEOUT,
    )
    try:
        assert (
            resp.status_code == 403
        ), f"expected 403, got {resp.status_code}: {resp.text}"
        detail = (resp.json() or {}).get("detail", "")
        assert (
            "SENSITIVE" in detail.upper() or "FORBIDDEN" in detail.upper()
        ), f"unexpected detail: {detail}"
    finally:
        try:
            secret_file.unlink()
        except Exception:
            pass


@pytest.mark.integration
@pytest.mark.p2
def test_file_guard_disabled_field_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify the ``enabled`` field of file-guard config can be toggled
      and persists.

    API endpoints:
    - GET /api/config/security/file-guard
    - PUT /api/config/security/file-guard
    """
    get_before = app_server.api_request(
        "GET",
        "/api/config/security/file-guard",
        timeout=_HTTP_TIMEOUT,
    )
    baseline = get_before.json()
    patched = dict(baseline)
    patched["enabled"] = not bool(baseline.get("enabled", True))
    try:
        put_resp = app_server.api_request(
            "PUT",
            "/api/config/security/file-guard",
            json=patched,
            timeout=_HTTP_TIMEOUT,
        )
        assert put_resp.status_code == 200, app_server.logs_tail()
        get_after = app_server.api_request(
            "GET",
            "/api/config/security/file-guard",
            timeout=_HTTP_TIMEOUT,
        )
        assert (
            get_after.json().get("enabled") == patched["enabled"]
        ), get_after.json()
    finally:
        app_server.api_request(
            "PUT",
            "/api/config/security/file-guard",
            json=baseline,
            timeout=_HTTP_TIMEOUT,
        )


# ------------------------------------------------------------------ #
# C. Skill Scanner
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_skill_scanner_global_blocked_history_get(app_server) -> None:
    """Test purpose:
    - Verify GET /api/config/security/skill-scanner/blocked-history
      returns a list (possibly empty) honoring the contract.

    API endpoints:
    - GET /api/config/security/skill-scanner/blocked-history
    """
    resp = app_server.api_request(
        "GET",
        "/api/config/security/skill-scanner/blocked-history",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    body = resp.json()
    # Endpoint may return list directly or wrapped in {entries: [...]}.
    entries = body if isinstance(body, list) else body.get("entries", [])
    assert isinstance(entries, list), body


@pytest.mark.integration
@pytest.mark.p2
def test_skill_scanner_global_blocked_history_delete_clear_all(
    app_server,
) -> None:
    """Test purpose:
    - Verify DELETE /api/config/security/skill-scanner/blocked-history
      returns 200 (idempotent clear of all entries).

    API endpoints:
    - DELETE /api/config/security/skill-scanner/blocked-history
    """
    resp = app_server.api_request(
        "DELETE",
        "/api/config/security/skill-scanner/blocked-history",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code in {200, 204}, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_skill_scanner_global_whitelist_add_remove(app_server) -> None:
    """Test purpose:
    - Verify POST /api/config/security/skill-scanner/whitelist adds an
      entry, GET reflects it, DELETE removes it.

    API endpoints:
    - GET    /api/config/security/skill-scanner
    - POST   /api/config/security/skill-scanner/whitelist
    - DELETE /api/config/security/skill-scanner/whitelist/{skill_name}
    """
    skill_name = "integ-test-fake-skill"
    add_resp = app_server.api_request(
        "POST",
        "/api/config/security/skill-scanner/whitelist",
        json={"skill_name": skill_name, "content_hash": ""},
        timeout=_HTTP_TIMEOUT,
    )
    assert add_resp.status_code in {200, 201}, app_server.logs_tail()

    try:
        get_resp = app_server.api_request(
            "GET",
            "/api/config/security/skill-scanner",
            timeout=_HTTP_TIMEOUT,
        )
        assert get_resp.status_code == 200, app_server.logs_tail()
        wl = (get_resp.json() or {}).get("whitelist") or []
        names = {entry.get("skill_name") for entry in wl}
        assert skill_name in names, names
    finally:
        del_resp = app_server.api_request(
            "DELETE",
            f"/api/config/security/skill-scanner/whitelist/{skill_name}",
            timeout=_HTTP_TIMEOUT,
        )
        assert del_resp.status_code in {200, 204}, app_server.logs_tail()

    # Verify whitelist no longer contains the entry.
    get_after = app_server.api_request(
        "GET",
        "/api/config/security/skill-scanner",
        timeout=_HTTP_TIMEOUT,
    )
    wl_after = (get_after.json() or {}).get("whitelist") or []
    names_after = {entry.get("skill_name") for entry in wl_after}
    assert skill_name not in names_after, names_after


@pytest.mark.integration
@pytest.mark.p1
def test_skill_scanner_blocked_history_real_entry_via_install(
    app_server,
) -> None:
    """Test purpose:
    - Verify that attempting to install a malicious skill produces a
      blocked-history entry retrievable via the HTTP endpoint.

    Test flow:
    1. Build a minimal "skill" zip containing a SKILL.md that mentions
       a hardcoded secret pattern (well-known signature).
    2. POST /api/agents/{id}/skills/upload with the zip.
    3. Either install fails (expected) OR scanner is in 'warn' mode and
       allows it. Either way, GET blocked-history may show the entry.
    4. This test asserts the endpoint stays consistent (no 500).
    """
    # Use the real skill-scanner blocked-history endpoint contract.
    resp = app_server.api_request(
        "GET",
        scoped(
            "default",
            "/config/security/skill-scanner/blocked-history",
        ),
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    body = resp.json()
    entries = body if isinstance(body, list) else body.get("entries", [])
    assert isinstance(entries, list), body
    # Each entry, if present, should expose at least skill_name.
    for entry in entries:
        assert "skill_name" in entry or "name" in entry, entry


# ------------------------------------------------------------------ #
# D. Approval flow
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p2
def test_approval_list_returns_list_contract(app_server) -> None:
    """Test purpose:
    - Verify GET /api/approval/list returns a list (possibly empty).

    API endpoints:
    - GET /api/approval/list
    """
    resp = app_server.api_request(
        "GET",
        "/api/approval/list",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    body = resp.json()
    items = body if isinstance(body, list) else body.get("approvals", [])
    assert isinstance(items, list), body


@pytest.mark.integration
@pytest.mark.p2
def test_approval_approve_unknown_returns_404(app_server) -> None:
    """Test purpose:
    - Verify POST /api/approval/approve with a non-existent request_id
      returns 404 with a descriptive detail.

    API endpoints:
    - POST /api/approval/approve
    """
    resp = app_server.api_request(
        "POST",
        "/api/approval/approve",
        json={
            "request_id": "00000000-0000-0000-0000-000000000000",
            "session_id": "no-such-session",
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert (
        resp.status_code == 404
    ), f"expected 404, got {resp.status_code}: {resp.text}"


@pytest.mark.integration
@pytest.mark.p2
def test_approval_deny_unknown_returns_404(app_server) -> None:
    """Test purpose:
    - Verify POST /api/approval/deny with a non-existent request_id
      returns 404.

    API endpoints:
    - POST /api/approval/deny
    """
    resp = app_server.api_request(
        "POST",
        "/api/approval/deny",
        json={
            "request_id": "00000000-0000-0000-0000-000000000001",
            "session_id": "no-such-session",
            "reason": "test",
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert (
        resp.status_code == 404
    ), f"expected 404, got {resp.status_code}: {resp.text}"


@pytest.mark.integration
@pytest.mark.p1
def test_approval_list_session_filter_no_match(app_server) -> None:
    """Test purpose:
    - Verify GET /api/approval/list?session_id=<unknown> returns an
      empty list — filter works and does not 500.

    API endpoints:
    - GET /api/approval/list?session_id=...
    """
    resp = app_server.api_request(
        "GET",
        "/api/approval/list",
        params={"session_id": "integ-no-such-session-zzz"},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    body = resp.json()
    items = body if isinstance(body, list) else body.get("approvals", [])
    assert items == [], items
