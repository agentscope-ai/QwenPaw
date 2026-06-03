# -*- coding: utf-8 -*-
"""Integration tests for console routes (no LLM / no external API keys)."""
from __future__ import annotations

import io
import uuid

import pytest

_CONSOLE_HTTP_TIMEOUT = 30.0


@pytest.mark.integration
@pytest.mark.p0
def test_agent_scoped_console_chat_stop_no_running_task(app_server) -> None:
    """Test purpose:
    - Verify scoped console chat/stop returns a stable JSON contract when no
      stream is attached for the given chat id (no model call).

    Test flow:
    1. Create a dedicated test agent.
    2. POST /console/chat/stop with a random UUID chat_id.
    3. Assert 200 and ``stopped`` is a boolean (typically False).
    4. Delete test agent.

    API endpoints:
    - POST /api/agents
    - POST /api/agents/{agentId}/console/chat/stop
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_console_stop_01"
    fake_chat_id = str(uuid.uuid4())

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={"id": agent_id, "name": "Console stop agent", "description": ""},
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        stop_url = (
            f"{app_server.base_url}/api/agents/{agent_id}/console/chat/stop"
            f"?chat_id={fake_chat_id}"
        )
        resp = app_server.client.post(stop_url, timeout=_CONSOLE_HTTP_TIMEOUT)
        print(
            (
                f"[integration]"
                f"[{'PASS' if resp.status_code == 200 else 'FAIL'}] "
                f"POST /api/agents/{agent_id}/console/chat/stop | "
                f"params=chat_id={fake_chat_id} | request=- | "
                f"status={resp.status_code} | response={resp.text[:500]}"
            ),
            flush=True,
        )
        assert resp.status_code == 200, app_server.logs_tail()
        body = resp.json()
        assert isinstance(body.get("stopped"), bool)
    finally:
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p0
def test_agent_scoped_console_upload_small_file(app_server) -> None:
    """Test purpose:
    - Verify scoped console upload accepts a small file and returns metadata
      without calling external services.

    Test flow:
    1. Create a dedicated test agent.
    2. POST multipart upload to scoped console upload with tiny text content.
    3. Assert JSON includes file_name and expected byte size.
    4. Delete test agent.

    API endpoints:
    - POST /api/agents
    - POST /api/agents/{agentId}/console/upload
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_console_upload_01"
    payload = b"integration-console-upload\n"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Console upload agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        upload_url = (
            f"{app_server.base_url}/api/agents/{agent_id}/console/upload"
        )
        files = {
            "file": ("integ-upload.txt", io.BytesIO(payload), "text/plain"),
        }
        resp = app_server.client.post(
            upload_url,
            files=files,
            timeout=_CONSOLE_HTTP_TIMEOUT,
        )
        print(
            (
                f"[integration]"
                f"[{'PASS' if resp.status_code == 200 else 'FAIL'}] "
                f"POST /api/agents/{agent_id}/console/upload | "
                f"params=- | request=(multipart file) | "
                f"status={resp.status_code} | response={resp.text[:800]}"
            ),
            flush=True,
        )
        assert resp.status_code == 200, app_server.logs_tail()
        body = resp.json()
        assert body.get("file_name") == "integ-upload.txt"
        assert body.get("size") == len(payload)
        assert "url" in body
    finally:
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")
