# -*- coding: utf-8 -*-
"""HTTP smoke tests for workspace file APIs (working/memory + zip up/down)."""
from __future__ import annotations

import io
import zipfile

import pytest


@pytest.mark.integration
@pytest.mark.p1
def test_api_workspace_working_file_list_put_get(app_server) -> None:
    """Test purpose:
    - Verify workspace working-file APIs are usable: builtin seed files exist,
      new file writes succeed, reads match, and list results include new files.

    Test flow:
    1. POST /api/agents to create a test agent.
    2. GET /api/workspace/files with X-Agent-Id; check seed files.
    3. PUT /api/workspace/files/{md_name} to write a test markdown file.
    4. GET /api/workspace/files/{md_name} and verify content roundtrip.
    5. GET /api/workspace/files again and confirm the new file appears.
    6. DELETE /api/agents/{agentId} for cleanup.

    API endpoints:
    - POST /api/agents
    - GET /api/workspace/files
    - PUT /api/workspace/files/{md_name}
    - GET /api/workspace/files/{md_name}
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_ws_01"
    headers = {"X-Agent-Id": agent_id}
    md_stem = "integ_smoke_note"
    expected_seed_files = {
        "SOUL.md",
        "PROFILE.md",
        "MEMORY.md",
        "HEARTBEAT.md",
        "BOOTSTRAP.md",
        "AGENTS.md",
    }

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Workspace smoke agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        list_before = app_server.api_request(
            "GET",
            "/api/workspace/files",
            headers=headers,
        )
        assert list_before.status_code == 200, app_server.logs_tail()
        list_before_payload = list_before.json()
        assert isinstance(list_before_payload, list)
        seed_names = {f["filename"] for f in list_before_payload}
        missing_seed_files = sorted(expected_seed_files - seed_names)
        assert not missing_seed_files, (
            f"workspace seed files missing: {missing_seed_files}; "
            f"have={sorted(seed_names)}"
        )

        content = "# integration\nline2\n"
        put_resp = app_server.api_request(
            "PUT",
            f"/api/workspace/files/{md_stem}",
            headers=headers,
            json={"content": content},
        )
        assert put_resp.status_code == 200, app_server.logs_tail()
        assert put_resp.json() == {"written": True}

        get_resp = app_server.api_request(
            "GET",
            f"/api/workspace/files/{md_stem}",
            headers=headers,
        )
        assert get_resp.status_code == 200, app_server.logs_tail()
        assert get_resp.json()["content"] == content.strip()

        list_after = app_server.api_request(
            "GET",
            "/api/workspace/files",
            headers=headers,
        )
        assert list_after.status_code == 200, app_server.logs_tail()
        names = {f["filename"] for f in list_after.json()}
        assert f"{md_stem}.md" in names
    finally:
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p1
def test_api_workspace_memory_file_list_put_get(app_server) -> None:
    """Test purpose:
    - Verify workspace memory-file APIs support write/read/list roundtrip under
      an explicit agent context.

    Test flow:
    1. Create a test agent.
    2. GET /api/workspace/memory and assert list response shape.
    3. PUT /api/workspace/memory/{md_name} with test content.
    4. GET /api/workspace/memory/{md_name} and verify content matches.
    5. GET /api/workspace/memory again and assert new file appears.
    6. Delete test agent for cleanup.

    API endpoints:
    - POST /api/agents
    - GET /api/workspace/memory
    - PUT /api/workspace/memory/{md_name}
    - GET /api/workspace/memory/{md_name}
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_mem_01"
    headers = {"X-Agent-Id": agent_id}
    md_stem = "integ_memory_note"
    content = "# memory integration\nfacts: 42\n"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={"id": agent_id, "name": "Memory smoke agent", "description": ""},
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        list_before = app_server.api_request(
            "GET",
            "/api/workspace/memory",
            headers=headers,
        )
        assert list_before.status_code == 200, app_server.logs_tail()
        assert isinstance(list_before.json(), list)

        put_resp = app_server.api_request(
            "PUT",
            f"/api/workspace/memory/{md_stem}",
            headers=headers,
            json={"content": content},
        )
        assert put_resp.status_code == 200, app_server.logs_tail()
        assert put_resp.json() == {"written": True}

        get_resp = app_server.api_request(
            "GET",
            f"/api/workspace/memory/{md_stem}",
            headers=headers,
        )
        assert get_resp.status_code == 200, app_server.logs_tail()
        assert get_resp.json()["content"] == content.strip()

        list_after = app_server.api_request(
            "GET",
            "/api/workspace/memory",
            headers=headers,
        )
        assert list_after.status_code == 200, app_server.logs_tail()
        names = {f["filename"] for f in list_after.json()}
        assert f"{md_stem}.md" in names
    finally:
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p1
def test_api_workspace_header_and_scoped_consistency(app_server) -> None:
    """Test purpose:
    - Verify workspace file APIs are consistent between header-based agent
      context and explicit agent-scoped routes.

    Test flow:
    1. Create a test agent.
    2. Write a working file via header route (X-Agent-Id).
    3. Read the same file via scoped route and verify content matches.
    4. Overwrite via scoped route and read back via header route.
    5. Cleanup by deleting the test agent.

    API endpoints:
    - POST /api/agents
    - PUT /api/workspace/files/{md_name}
    - GET /api/workspace/files/{md_name}
    - PUT /api/agents/{agentId}/workspace/files/{md_name}
    - GET /api/agents/{agentId}/workspace/files/{md_name}
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_ws_scope_01"
    headers = {"X-Agent-Id": agent_id}
    md_stem = "scope_consistency_note"
    v1 = "# scope consistency v1\n"
    v2 = "# scope consistency v2\n"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Workspace scoped agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        put_header = app_server.api_request(
            "PUT",
            f"/api/workspace/files/{md_stem}",
            headers=headers,
            json={"content": v1},
        )
        assert put_header.status_code == 200, app_server.logs_tail()
        assert put_header.json() == {"written": True}

        get_scoped = app_server.api_request(
            "GET",
            f"/api/agents/{agent_id}/workspace/files/{md_stem}",
        )
        assert get_scoped.status_code == 200, app_server.logs_tail()
        assert get_scoped.json()["content"] == v1.strip()

        put_scoped = app_server.api_request(
            "PUT",
            f"/api/agents/{agent_id}/workspace/files/{md_stem}",
            json={"content": v2},
        )
        assert put_scoped.status_code == 200, app_server.logs_tail()
        assert put_scoped.json() == {"written": True}

        get_header = app_server.api_request(
            "GET",
            f"/api/workspace/files/{md_stem}",
            headers=headers,
        )
        assert get_header.status_code == 200, app_server.logs_tail()
        assert get_header.json()["content"] == v2.strip()
    finally:
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p0
def test_api_workspace_download_zip_contract(app_server) -> None:
    """Test purpose:
    - Verify workspace download returns a valid zip stream with expected HTTP
      contract and readable archive entries.

    Test flow:
    1. Create a test agent.
    2. Write a marker markdown file into workspace via API.
    3. Download workspace zip through /api/workspace/download.
    4. Validate status/content-type/content-disposition and zip signature.
    5. Open zip in-memory and assert seed file plus marker file exist.
    6. Delete test agent.

    API endpoints:
    - POST /api/agents
    - PUT /api/workspace/files/{md_name}
    - GET /api/workspace/download
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_ws_zip_01"
    headers = {"X-Agent-Id": agent_id}
    marker_stem = "zip_marker_note"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Workspace zip agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        seed_file_resp = app_server.api_request(
            "PUT",
            f"/api/workspace/files/{marker_stem}",
            headers=headers,
            json={"content": "# zip marker\n"},
        )
        assert seed_file_resp.status_code == 200, app_server.logs_tail()

        download_resp = app_server.client.get(
            f"{app_server.base_url}/api/workspace/download",
            headers=headers,
        )
        assert download_resp.status_code == 200, app_server.logs_tail()

        content_type = download_resp.headers.get("content-type", "").lower()
        assert "application/zip" in content_type
        content_disposition = download_resp.headers.get(
            "content-disposition",
            "",
        ).lower()
        assert "attachment;" in content_disposition
        assert "qwenpaw_workspace_" in content_disposition
        assert agent_id.lower() in content_disposition

        zip_bytes = download_resp.content
        assert zip_bytes.startswith(
            b"PK",
        ), "zip stream must start with PK signature"

        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            names = set(zf.namelist())

        assert "AGENTS.md" in names
        assert f"{marker_stem}.md" in names
    finally:
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p0
def test_api_workspace_upload_zip_merge(app_server) -> None:
    """Test purpose:
    - Verify workspace upload accepts a zip archive and merges files into the
      target agent workspace.

    Test flow:
    1. Create a test agent.
    2. Build an in-memory zip with one markdown file.
    3. POST /api/workspace/upload using multipart form-data.
    4. GET /api/workspace/files/{md_name} and verify uploaded content exists.
    5. Delete test agent.

    API endpoints:
    - POST /api/agents
    - POST /api/workspace/upload
    - GET /api/workspace/files/{md_name}
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_ws_upload_01"
    headers = {"X-Agent-Id": agent_id}
    uploaded_name = "uploaded_merge_note.md"
    uploaded_content = "# uploaded by integration\n"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Workspace upload agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(uploaded_name, uploaded_content)
        buf.seek(0)

        upload_resp = app_server.client.post(
            f"{app_server.base_url}/api/workspace/upload",
            headers=headers,
            files={
                "file": ("workspace.zip", buf.getvalue(), "application/zip"),
            },
        )
        assert upload_resp.status_code == 200, app_server.logs_tail()
        upload_payload = upload_resp.json()
        assert upload_payload.get("success") is True

        get_uploaded = app_server.api_request(
            "GET",
            f"/api/workspace/files/{uploaded_name}",
            headers=headers,
        )
        assert get_uploaded.status_code == 200, app_server.logs_tail()
        assert get_uploaded.json().get("content") == uploaded_content.strip()
    finally:
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p2
def test_api_workspace_upload_reject_non_zip(app_server) -> None:
    """Test purpose:
    - Verify workspace upload rejects non-zip multipart content with 400.

    Test flow:
    1. Create a test agent.
    2. POST /api/workspace/upload with text/plain file.
    3. Assert status is 400 and error mentions expected zip content-type.
    4. Delete test agent.

    API endpoints:
    - POST /api/agents
    - POST /api/workspace/upload
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_ws_upload_bad_01"
    headers = {"X-Agent-Id": agent_id}

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Workspace bad upload agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        bad_upload = app_server.client.post(
            f"{app_server.base_url}/api/workspace/upload",
            headers=headers,
            files={"file": ("not-zip.txt", b"plain text", "text/plain")},
        )
        assert bad_upload.status_code == 400, app_server.logs_tail()
        detail = bad_upload.json().get("detail", "")
        assert "Expected a zip file" in detail
    finally:
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p1
def test_api_workspace_upload_overwrite_existing_file(app_server) -> None:
    """Test purpose:
    - Verify workspace zip upload overwrites existing files with the same path.

    Test flow:
    1. Create a test agent.
    2. Seed a working file via PUT with old content.
    3. Upload a zip containing the same filename with new content.
    4. Read the file and verify content is overwritten by uploaded payload.
    5. Delete test agent.

    API endpoints:
    - POST /api/agents
    - PUT /api/workspace/files/{md_name}
    - POST /api/workspace/upload
    - GET /api/workspace/files/{md_name}
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_ws_upload_overwrite_01"
    headers = {"X-Agent-Id": agent_id}
    md_stem = "overwrite_target_note"
    old_content = "# old content\n"
    new_content = "# new content from zip\n"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Workspace upload overwrite agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        seed_resp = app_server.api_request(
            "PUT",
            f"/api/workspace/files/{md_stem}",
            headers=headers,
            json={"content": old_content},
        )
        assert seed_resp.status_code == 200, app_server.logs_tail()

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"{md_stem}.md", new_content)
        buf.seek(0)

        upload_resp = app_server.client.post(
            f"{app_server.base_url}/api/workspace/upload",
            headers=headers,
            files={
                "file": ("workspace.zip", buf.getvalue(), "application/zip"),
            },
        )
        assert upload_resp.status_code == 200, app_server.logs_tail()
        assert upload_resp.json().get("success") is True

        get_after = app_server.api_request(
            "GET",
            f"/api/workspace/files/{md_stem}",
            headers=headers,
        )
        assert get_after.status_code == 200, app_server.logs_tail()
        assert get_after.json().get("content") == new_content.strip()
    finally:
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p2
def test_api_workspace_download_upload_cross_agent_roundtrip(
    app_server,
) -> None:
    """Test purpose:
    - Verify a downloaded workspace zip can be uploaded into another agent
      workspace and preserve user-authored files.

    Test flow:
    1. Create source and target test agents.
    2. Write a marker file in source workspace.
    3. Download source workspace zip.
    4. Upload downloaded zip to target workspace.
    5. Read marker file from target and verify content matches source.
    6. Delete both agents.

    API endpoints:
    - POST /api/agents
    - PUT /api/workspace/files/{md_name}
    - GET /api/workspace/download
    - POST /api/workspace/upload
    - GET /api/workspace/files/{md_name}
    - DELETE /api/agents/{agentId}
    """
    source_agent = "integ_ws_round_src_01"
    target_agent = "integ_ws_round_tgt_01"
    source_headers = {"X-Agent-Id": source_agent}
    target_headers = {"X-Agent-Id": target_agent}
    marker_stem = "roundtrip_marker"
    marker_content = "# roundtrip marker\nfrom source agent\n"

    create_source = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": source_agent,
            "name": "Workspace roundtrip source",
            "description": "",
        },
    )
    assert create_source.status_code == 201, app_server.logs_tail()

    create_target = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": target_agent,
            "name": "Workspace roundtrip target",
            "description": "",
        },
    )
    assert create_target.status_code == 201, app_server.logs_tail()

    try:
        put_source = app_server.api_request(
            "PUT",
            f"/api/workspace/files/{marker_stem}",
            headers=source_headers,
            json={"content": marker_content},
        )
        assert put_source.status_code == 200, app_server.logs_tail()

        download_source = app_server.client.get(
            f"{app_server.base_url}/api/workspace/download",
            headers=source_headers,
        )
        assert download_source.status_code == 200, app_server.logs_tail()
        zip_blob = download_source.content
        assert zip_blob.startswith(b"PK")

        upload_target = app_server.client.post(
            f"{app_server.base_url}/api/workspace/upload",
            headers=target_headers,
            files={"file": ("roundtrip.zip", zip_blob, "application/zip")},
        )
        assert upload_target.status_code == 200, app_server.logs_tail()
        assert upload_target.json().get("success") is True

        get_target = app_server.api_request(
            "GET",
            f"/api/workspace/files/{marker_stem}",
            headers=target_headers,
        )
        assert get_target.status_code == 200, app_server.logs_tail()
        assert get_target.json().get("content") == marker_content.strip()
    finally:
        app_server.api_request("DELETE", f"/api/agents/{source_agent}")
        app_server.api_request("DELETE", f"/api/agents/{target_agent}")
