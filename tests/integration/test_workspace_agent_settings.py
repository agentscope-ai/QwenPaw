# -*- coding: utf-8 -*-
"""Smoke tests for agent-scoped workspace settings."""
from __future__ import annotations


import pytest


@pytest.mark.integration
@pytest.mark.p1
def test_agent_scoped_workspace_language_put_get_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify scoped workspace language GET/PUT roundtrip for a test agent.

    Test flow:
    1. Create a dedicated test agent.
    2. GET scoped /workspace/language baseline.
    3. PUT a different valid language (en <-> zh) and GET to verify.
    4. Restore baseline and delete agent.

    API endpoints:
    - POST /api/agents
    - GET /api/agents/{agentId}/workspace/language
    - PUT /api/agents/{agentId}/workspace/language
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_scoped_ws_lang_01"
    base = f"/api/agents/{agent_id}/workspace/language"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Scoped language agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    baseline_lang = None
    try:
        get_before = app_server.api_request("GET", base)
        assert get_before.status_code == 200, app_server.logs_tail()
        baseline_lang = get_before.json().get("language")
        assert baseline_lang in ("en", "zh", "ru")

        alt = "zh" if baseline_lang == "en" else "en"
        put_resp = app_server.api_request("PUT", base, json={"language": alt})
        assert put_resp.status_code == 200, app_server.logs_tail()
        assert put_resp.json().get("language") == alt

        get_after = app_server.api_request("GET", base)
        assert get_after.status_code == 200, app_server.logs_tail()
        assert get_after.json().get("language") == alt
    finally:
        if baseline_lang is not None:
            restore = app_server.api_request(
                "PUT",
                base,
                json={"language": baseline_lang},
            )
            assert restore.status_code == 200, app_server.logs_tail()
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p1
def test_agent_scoped_workspace_audio_mode_put_get_roundtrip(
    app_server,
) -> None:
    """Test purpose:
    - Verify scoped workspace audio-mode roundtrip (auto/native).

    Test flow:
    1. Create a dedicated test agent.
    2. GET scoped /workspace/audio-mode baseline.
    3. PUT the alternate valid mode and GET to verify.
    4. Restore baseline and delete agent.

    API endpoints:
    - POST /api/agents
    - GET /api/agents/{agentId}/workspace/audio-mode
    - PUT /api/agents/{agentId}/workspace/audio-mode
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_scoped_ws_audio_01"
    base = f"/api/agents/{agent_id}/workspace/audio-mode"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Scoped audio mode agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    baseline_mode = None
    try:
        get_before = app_server.api_request("GET", base)
        assert get_before.status_code == 200, app_server.logs_tail()
        baseline_mode = get_before.json().get("audio_mode")
        assert baseline_mode in ("auto", "native")

        alt = "native" if baseline_mode == "auto" else "auto"
        put_resp = app_server.api_request(
            "PUT",
            base,
            json={"audio_mode": alt},
        )
        assert put_resp.status_code == 200, app_server.logs_tail()
        assert put_resp.json().get("audio_mode") == alt

        get_after = app_server.api_request("GET", base)
        assert get_after.status_code == 200, app_server.logs_tail()
        assert get_after.json().get("audio_mode") == alt
    finally:
        if baseline_mode is not None:
            restore = app_server.api_request(
                "PUT",
                base,
                json={"audio_mode": baseline_mode},
            )
            assert restore.status_code == 200, app_server.logs_tail()
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p2
def test_agent_scoped_agent_status_minimal_contract(app_server) -> None:
    """Test purpose:
    - Verify agent-scoped agent-status endpoint returns a stable JSON contract.

    Test flow:
    1. Create a dedicated test agent.
    2. GET /api/agents/{agentId}/agent-status.
    3. Assert status is one of idle/running/disabled and task count is int.
    4. Delete test agent.

    API endpoints:
    - POST /api/agents
    - GET /api/agents/{agentId}/agent-status
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_agent_status_01"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={"id": agent_id, "name": "Agent status agent", "description": ""},
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        resp = app_server.api_request(
            "GET",
            f"/api/agents/{agent_id}/agent-status",
        )
        assert resp.status_code == 200, app_server.logs_tail()
        body = resp.json()
        assert body.get("status") in {"idle", "running", "disabled"}
        assert isinstance(body.get("running_task_count"), int)
        assert body["running_task_count"] >= 0
    finally:
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p0
def test_agent_scoped_workspace_system_prompt_files_put_get_roundtrip(
    app_server,
) -> None:
    """Test purpose:
    - Verify scoped system-prompt-files GET/PUT roundtrip for a test agent.

    Test flow:
    1. Create a dedicated test agent.
    2. GET baseline list of system prompt filenames.
    3. PUT a reordered copy (when length >= 2) or the same list, then GET.
    4. Restore original list and delete agent.

    API endpoints:
    - POST /api/agents
    - GET /api/agents/{agentId}/workspace/system-prompt-files
    - PUT /api/agents/{agentId}/workspace/system-prompt-files
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_scoped_sys_prompt_01"
    base = f"/api/agents/{agent_id}/workspace/system-prompt-files"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "System prompt agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    baseline: list[str] | None = None
    try:
        get_before = app_server.api_request("GET", base)
        assert get_before.status_code == 200, app_server.logs_tail()
        baseline = get_before.json()
        assert isinstance(baseline, list)

        reordered = (
            list(reversed(baseline)) if len(baseline) >= 2 else list(baseline)
        )

        put_resp = app_server.api_request("PUT", base, json=reordered)
        assert put_resp.status_code == 200, app_server.logs_tail()
        assert put_resp.json() == reordered

        get_after = app_server.api_request("GET", base)
        assert get_after.status_code == 200, app_server.logs_tail()
        assert get_after.json() == reordered
    finally:
        if isinstance(baseline, list):
            restore = app_server.api_request("PUT", base, json=baseline)
            assert restore.status_code == 200, app_server.logs_tail()
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p1
def test_agent_scoped_workspace_transcription_provider_type_put_roundtrip(
    app_server,
) -> None:
    """Test purpose:
    - Verify scoped transcription-provider-type PUT persists and can be read
      back. The backing field is global; restore via global workspace path.

    Test flow:
    1. Record baseline from GET /api/workspace/transcription-provider-type.
    2. Create a dedicated test agent.
    3. PUT alternate valid type via scoped path and GET scoped path to verify.
    4. Restore baseline via PUT /api/workspace/transcription-provider-type.
    5. Delete test agent.

    API endpoints:
    - GET /api/workspace/transcription-provider-type
    - PUT /api/workspace/transcription-provider-type
    - POST /api/agents
    - GET /api/agents/{agentId}/workspace/transcription-provider-type
    - PUT /api/agents/{agentId}/workspace/transcription-provider-type
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_scoped_transcription_type_01"
    global_path = "/api/workspace/transcription-provider-type"
    scoped_base = (
        f"/api/agents/{agent_id}/workspace/transcription-provider-type"
    )

    get_global_before = app_server.api_request("GET", global_path)
    assert get_global_before.status_code == 200, app_server.logs_tail()
    baseline = get_global_before.json().get("transcription_provider_type")
    assert baseline in ("disabled", "whisper_api", "local_whisper")

    alt = "whisper_api" if baseline == "disabled" else "disabled"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Transcription type agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        put_alt = app_server.api_request(
            "PUT",
            scoped_base,
            json={"transcription_provider_type": alt},
        )
        assert put_alt.status_code == 200, app_server.logs_tail()
        assert put_alt.json().get("transcription_provider_type") == alt

        get_scoped = app_server.api_request("GET", scoped_base)
        assert get_scoped.status_code == 200, app_server.logs_tail()
        assert get_scoped.json().get("transcription_provider_type") == alt
    finally:
        restore = app_server.api_request(
            "PUT",
            global_path,
            json={"transcription_provider_type": baseline},
        )
        assert restore.status_code == 200, app_server.logs_tail()
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p1
def test_agent_scoped_workspace_memory_put_get_list(app_server) -> None:
    """Test purpose:
    - Verify agent-scoped memory file PUT/GET and list visibility.

    Test flow:
    1. Create a dedicated test agent.
    2. PUT scoped memory file with markdown content.
    3. GET the same path and assert content roundtrip.
    4. GET scoped memory list and assert filename stem appears.
    5. Delete test agent (workspace cleanup).

    API endpoints:
    - POST /api/agents
    - PUT /api/agents/{agentId}/workspace/memory/{md_name}
    - GET /api/agents/{agentId}/workspace/memory/{md_name}
    - GET /api/agents/{agentId}/workspace/memory
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_scoped_memory_01"
    md_stem = "integ_scoped_memory_note"
    base_mem = f"/api/agents/{agent_id}/workspace/memory"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Scoped memory agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        body = "# Scoped memory\n\nintegration line.\n"
        put_resp = app_server.api_request(
            "PUT",
            f"{base_mem}/{md_stem}",
            json={"content": body},
        )
        assert put_resp.status_code == 200, app_server.logs_tail()

        get_one = app_server.api_request("GET", f"{base_mem}/{md_stem}")
        assert get_one.status_code == 200, app_server.logs_tail()
        # read_memory_md returns stripped file text
        assert get_one.json().get("content") == body.strip()

        list_resp = app_server.api_request("GET", base_mem)
        assert list_resp.status_code == 200, app_server.logs_tail()
        filenames = {item.get("filename") for item in list_resp.json()}
        assert f"{md_stem}.md" in filenames
    finally:
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")
