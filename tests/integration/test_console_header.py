# -*- coding: utf-8 -*-
"""Integration tests for the Console header (default-agent) endpoints.

These cover ``/api/console/*`` endpoints that resolve the active agent
via ``get_agent_for_request`` (header variant) rather than the
``/api/agents/{agentId}/console/*`` scoped variant. The inbox subset
of the same prefix is exercised separately in ``test_inbox.py``; this
module focuses on the remaining 4 header endpoints (chat/stop,
push-messages, debug/backend-logs, upload).

POST ``/api/console/chat`` (the main conversation submit) is
intentionally NOT covered here — it requires an LLM round-trip and
will be revisited in Sprint 2.3 with a mock LLM.
"""
from __future__ import annotations

import pytest

_CONSOLE_HTTP_TIMEOUT = 30.0
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # mirrors console.py MAX_UPLOAD_BYTES


@pytest.mark.integration
@pytest.mark.p1
def test_console_chat_stop_header_returns_stopped_false_for_unknown_chat_id(
    app_server,
) -> None:
    """Test purpose:
    - Verify POST /api/console/chat/stop returns 200 + ``stopped=false``
      when the supplied chat_id is not tracked. Console's "停止生成"
      button must succeed quietly when no task is running (otherwise
      every idle-state click would surface as an error toast).

    Test flow:
    1. POST /api/console/chat/stop?chat_id=<synthetic-unknown>.
    2. Assert 200 + response body ``{"stopped": false}``.

    API endpoints:
    - POST /api/console/chat/stop
    """
    resp = app_server.api_request(
        "POST",
        "/api/console/chat/stop",
        params={"chat_id": "integ-header-no-running-chat-0001"},
        timeout=_CONSOLE_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    assert resp.json() == {"stopped": False}


@pytest.mark.integration
@pytest.mark.p2
def test_console_push_messages_header_returns_dict_contract(
    app_server,
) -> None:
    """Test purpose:
    - Verify GET /api/console/push-messages returns the documented
      contract ``{"messages": [...], "pending_approvals": [...]}`` on
      a fresh workspace. Console polls this endpoint regularly for
      live notifications and approvals; a broken contract breaks the
      whole notification subsystem.

    Test flow:
    1. GET /api/console/push-messages without session_id (global mode
       — returns recent push messages from the last 60s).
    2. Assert 200 and both ``messages`` and ``pending_approvals`` are
       lists (each may be empty on a fresh workspace).

    API endpoints:
    - GET /api/console/push-messages
    """
    resp = app_server.api_request(
        "GET",
        "/api/console/push-messages",
        timeout=_CONSOLE_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, dict)
    assert isinstance(payload.get("messages"), list)
    assert isinstance(payload.get("pending_approvals"), list)


@pytest.mark.integration
@pytest.mark.p2
def test_console_debug_backend_logs_header_returns_contract(
    app_server,
) -> None:
    """Test purpose:
    - Verify GET /api/console/debug/backend-logs returns the documented
      contract (``path / exists / lines / updated_at / size / content``)
      so the Console "调试 / 后端日志" panel always renders.

    Test flow:
    1. GET /api/console/debug/backend-logs?lines=50.
    2. Assert 200, response is a dict containing the 6 documented
       fields; ``lines`` echoes the request value; ``content`` is a
       string (possibly empty on a fresh workspace whose log file
       hasn't been populated yet); ``exists`` is a boolean.

    API endpoints:
    - GET /api/console/debug/backend-logs
    """
    resp = app_server.api_request(
        "GET",
        "/api/console/debug/backend-logs",
        params={"lines": 50},
        timeout=_CONSOLE_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, dict)
    for key in ("path", "exists", "lines", "updated_at", "size", "content"):
        assert key in payload, f"missing field: {key}"
    assert payload["lines"] == 50
    assert isinstance(payload["exists"], bool)
    assert isinstance(payload["content"], str)


@pytest.mark.integration
@pytest.mark.p2
def test_console_upload_header_accepts_file_at_max_size_limit(
    app_server,
) -> None:
    """Test purpose:
    - Verify a payload of EXACTLY ``MAX_UPLOAD_BYTES`` succeeds (200 +
      normal upload contract). Paired with the ``+1 byte → 400`` case
      below this locks in the boundary; an off-by-one in either
      direction would surface here.

    Test flow:
    1. POST multipart upload with payload size == MAX_UPLOAD_BYTES.
    2. Assert 200 + response is a dict with url/file_name/size fields,
       and size matches what we sent.

    API endpoints:
    - POST /api/console/upload
    """
    at_limit = b"\x00" * _MAX_UPLOAD_BYTES
    resp = app_server.api_request(
        "POST",
        "/api/console/upload",
        files={
            "file": (
                "at_limit.bin",
                at_limit,
                "application/octet-stream",
            ),
        },
        timeout=_CONSOLE_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, dict)
    assert payload.get("file_name") == "at_limit.bin"
    assert payload.get("size") == _MAX_UPLOAD_BYTES
    assert isinstance(payload.get("url"), str) and payload["url"]


@pytest.mark.integration
@pytest.mark.p2
def test_console_upload_header_rejects_oversized_file(app_server) -> None:
    """Test purpose:
    - Verify POST /api/console/upload rejects files larger than the
      ``MAX_UPLOAD_BYTES`` (10 MiB) limit with 400, before storing
      anything on disk. A regression here lets users DoS storage by
      uploading huge attachments.

    Test flow:
    1. POST multipart upload with payload size = MAX_UPLOAD_BYTES + 1.
    2. Assert 400 + detail contains "File too large" + the size limit
       (10 MB).

    API endpoints:
    - POST /api/console/upload
    """
    oversized = b"\x00" * (_MAX_UPLOAD_BYTES + 1)
    resp = app_server.api_request(
        "POST",
        "/api/console/upload",
        files={
            "file": (
                "oversized.bin",
                oversized,
                "application/octet-stream",
            ),
        },
        timeout=_CONSOLE_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, app_server.logs_tail()
    detail = resp.json().get("detail", "")
    assert "File too large" in detail
    assert "10" in detail  # the "(max 10 MB)" suffix
