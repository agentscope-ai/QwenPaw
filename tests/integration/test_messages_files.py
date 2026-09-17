# -*- coding: utf-8 -*-
"""Integration tests for messages and files APIs."""
from __future__ import annotations

from urllib.parse import quote

import pytest

_MESSAGES_FILES_TIMEOUT = 20.0


@pytest.mark.integration
@pytest.mark.p0
def test_messages_send_console(app_server) -> None:
    """Test purpose:
    - Verify messages/send endpoint can proactively dispatch a text message to
      the console channel for the default agent.

    Test flow:
    1. POST /api/messages/send with channel=console and sample target IDs.
    2. Assert 200 response and ``success=true``.
    3. Assert response message indicates successful send.

    API endpoints:
    - POST /api/messages/send
    """
    resp = app_server.api_request(
        "POST",
        "/api/messages/send",
        json={
            "channel": "console",
            "target_user": "integ-user",
            "target_session": "integ-session",
            "text": "integration hello",
        },
        timeout=_MESSAGES_FILES_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert payload.get("success") is True
    assert "Message sent successfully" in payload.get("message", "")


@pytest.mark.integration
@pytest.mark.p2
def test_messages_send_invalid_channel(app_server) -> None:
    """Test purpose:
    - Verify messages/send returns 404 when the requested channel does not
      exist for the agent runtime.

    Test flow:
    1. POST /api/messages/send with a non-existent channel name.
    2. Assert 404 response and error detail mentions channel not found.

    API endpoints:
    - POST /api/messages/send
    """
    resp = app_server.api_request(
        "POST",
        "/api/messages/send",
        json={
            "channel": "nonexistent_channel",
            "target_user": "integ-user",
            "target_session": "integ-session",
            "text": "integration hello",
        },
        timeout=_MESSAGES_FILES_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()
    detail = resp.json().get("detail", "")
    assert "Channel not found" in detail


@pytest.mark.integration
@pytest.mark.p0
def test_messages_send_without_agent_header_uses_default_agent(
    app_server,
) -> None:
    """Test purpose:
    - Verify messages/send works without X-Agent-Id and follows default-agent
      routing behavior.

    Test flow:
    1. POST /api/messages/send without X-Agent-Id.
    2. POST /api/messages/send with X-Agent-Id=default.
    3. Assert both responses are 200 and ``success=true``.

    API endpoints:
    - POST /api/messages/send
    """
    payload = {
        "channel": "console",
        "target_user": "integ-user-default-route",
        "target_session": "integ-session-default-route",
        "text": "default route check",
    }
    no_header_resp = app_server.api_request(
        "POST",
        "/api/messages/send",
        json=payload,
        timeout=_MESSAGES_FILES_TIMEOUT,
    )
    assert no_header_resp.status_code == 200, app_server.logs_tail()
    assert no_header_resp.json().get("success") is True

    explicit_default_resp = app_server.api_request(
        "POST",
        "/api/messages/send",
        headers={"X-Agent-Id": "default"},
        json=payload,
        timeout=_MESSAGES_FILES_TIMEOUT,
    )
    assert explicit_default_resp.status_code == 200, app_server.logs_tail()
    assert explicit_default_resp.json().get("success") is True


@pytest.mark.integration
@pytest.mark.p2
def test_messages_send_missing_agent_returns_404(app_server) -> None:
    """Test purpose:
    - Verify messages/send returns 404 when X-Agent-Id points to a missing
      agent.

    Test flow:
    1. POST /api/messages/send with a non-existing X-Agent-Id.
    2. Assert 404 status and ``Agent not found`` in detail.

    API endpoints:
    - POST /api/messages/send
    """
    resp = app_server.api_request(
        "POST",
        "/api/messages/send",
        headers={"X-Agent-Id": "integ_missing_agent_for_messages"},
        json={
            "channel": "console",
            "target_user": "integ-user",
            "target_session": "integ-session",
            "text": "missing agent check",
        },
        timeout=_MESSAGES_FILES_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()
    detail = resp.json().get("detail", "")
    assert "Agent not found" in detail


@pytest.mark.integration
@pytest.mark.p1
def test_messages_send_does_not_create_chat_record(app_server) -> None:
    """Test purpose:
    - Verify proactive channel message sending does not implicitly create chat
      records under /api/chats.

    Test flow:
    1. Create a dedicated agent for isolation.
    2. GET /api/chats and store existing chat IDs as baseline.
    3. POST /api/messages/send with X-Agent-Id on the same agent.
    4. GET /api/chats again and assert chat ID set is unchanged.
    5. Delete test agent.

    API endpoints:
    - POST /api/agents
    - GET /api/chats
    - POST /api/messages/send
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_messages_chat_boundary_01"
    headers = {"X-Agent-Id": agent_id}

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Messages boundary agent",
            "description": "",
        },
        timeout=_MESSAGES_FILES_TIMEOUT,
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        chats_before = app_server.api_request(
            "GET",
            "/api/chats",
            headers=headers,
            timeout=_MESSAGES_FILES_TIMEOUT,
        )
        assert chats_before.status_code == 200, app_server.logs_tail()
        before_ids = {item.get("id") for item in chats_before.json()}

        send_resp = app_server.api_request(
            "POST",
            "/api/messages/send",
            headers=headers,
            json={
                "channel": "console",
                "target_user": "integ-user",
                "target_session": "integ-session",
                "text": "boundary check",
            },
            timeout=_MESSAGES_FILES_TIMEOUT,
        )
        assert send_resp.status_code == 200, app_server.logs_tail()
        assert send_resp.json().get("success") is True

        chats_after = app_server.api_request(
            "GET",
            "/api/chats",
            headers=headers,
            timeout=_MESSAGES_FILES_TIMEOUT,
        )
        assert chats_after.status_code == 200, app_server.logs_tail()
        after_ids = {item.get("id") for item in chats_after.json()}
        assert after_ids == before_ids
    finally:
        app_server.api_request(
            "DELETE",
            f"/api/agents/{agent_id}",
            timeout=_MESSAGES_FILES_TIMEOUT,
        )


@pytest.mark.integration
@pytest.mark.p1
def test_files_preview_existing_file(app_server, tmp_path) -> None:
    """Test purpose:
    - Verify files preview endpoint can stream an existing absolute-path file.

    Test flow:
    1. Create a temporary local text file.
    2. URL-encode absolute path and request /api/files/preview/{filepath}.
    3. Assert 200 response and body contains expected content bytes.

    API endpoints:
    - GET /api/files/preview/{filepath:path}
    """
    target_file = tmp_path / "preview_target.txt"
    expected = "preview integration payload\n"
    # Use write_bytes to avoid platform-specific newline translation
    # (write_text in text mode converts \n -> \r\n on Windows).
    target_file.write_bytes(expected.encode("utf-8"))

    encoded_path = quote(str(target_file), safe="")
    resp = app_server.client.get(
        f"{app_server.base_url}/api/files/preview/{encoded_path}",
        timeout=_MESSAGES_FILES_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    assert resp.content.decode("utf-8") == expected


@pytest.mark.integration
@pytest.mark.p2
def test_files_preview_not_found(app_server, tmp_path) -> None:
    """Test purpose:
    - Verify files preview endpoint returns 404 for non-existing file paths.

    Test flow:
    1. Build a path to a missing file.
    2. URL-encode and request /api/files/preview/{filepath}.
    3. Assert 404 with ``detail=Not found``.

    API endpoints:
    - GET /api/files/preview/{filepath:path}
    """
    missing_file = tmp_path / "missing_file_404.txt"
    encoded_path = quote(str(missing_file), safe="")
    resp = app_server.client.get(
        f"{app_server.base_url}/api/files/preview/{encoded_path}",
        timeout=_MESSAGES_FILES_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()
    assert resp.json().get("detail") == "Not found"


@pytest.mark.integration
@pytest.mark.p2
def test_files_preview_head_existing_file_contract(
    app_server,
    tmp_path,
) -> None:
    """Test purpose:
    - Verify HEAD /api/files/preview keeps a stable response contract for
      existing files.

    Test flow:
    1. Create a temporary local file and URL-encode its absolute path.
    2. Send HEAD /api/files/preview/{filepath}.
    3. Assert 200 status, key headers exist, and response body is empty.

    API endpoints:
    - HEAD /api/files/preview/{filepath:path}
    """
    target_file = tmp_path / "preview_target_head.txt"
    target_file.write_text("head contract payload\n", encoding="utf-8")

    encoded_path = quote(str(target_file), safe="")
    resp = app_server.client.head(
        f"{app_server.base_url}/api/files/preview/{encoded_path}",
        timeout=_MESSAGES_FILES_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    content_disposition = resp.headers.get("content-disposition", "")
    assert "preview_target_head.txt" in content_disposition
    assert resp.content == b""


@pytest.mark.integration
@pytest.mark.p2
def test_files_preview_head_not_found(app_server, tmp_path) -> None:
    """Test purpose:
    - Verify HEAD /api/files/preview returns 404 for a missing file path.

    Test flow:
    1. Build a path to a non-existing file.
    2. Send HEAD /api/files/preview/{filepath}.
    3. Assert 404 status and empty response body for HEAD semantics.

    API endpoints:
    - HEAD /api/files/preview/{filepath:path}
    """
    missing_file = tmp_path / "missing_head_404.txt"
    encoded_path = quote(str(missing_file), safe="")
    resp = app_server.client.head(
        f"{app_server.base_url}/api/files/preview/{encoded_path}",
        timeout=_MESSAGES_FILES_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()
    assert resp.content == b""


@pytest.mark.integration
@pytest.mark.p2
def test_files_preview_directory_path_returns_404(
    app_server,
    tmp_path,
) -> None:
    """Test purpose:
    - Verify GET /api/files/preview rejects directory paths (non-file targets).

    Test flow:
    1. Create a temporary directory path.
    2. URL-encode that directory path and call /api/files/preview/{filepath}.
    3. Assert 404 status and ``detail=Not found``.

    API endpoints:
    - GET /api/files/preview/{filepath:path}
    """
    target_dir = tmp_path / "preview_dir_target"
    target_dir.mkdir(parents=True, exist_ok=True)

    encoded_path = quote(str(target_dir), safe="")
    resp = app_server.client.get(
        f"{app_server.base_url}/api/files/preview/{encoded_path}",
        timeout=_MESSAGES_FILES_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()
    assert resp.json().get("detail") == "Not found"
