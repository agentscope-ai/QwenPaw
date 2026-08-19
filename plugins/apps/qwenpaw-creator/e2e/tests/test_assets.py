# -*- coding: utf-8 -*-

from __future__ import annotations

import pytest


pytestmark = pytest.mark.assets


def test_supplement_upload_is_indexed_in_project(page, api, project, tmp_path):
    project_id = project["projectId"]
    source = tmp_path / "source.txt"
    source.write_text("immutable supplement source", encoding="utf-8")

    page.goto(f"/#/project/{project_id}/assets")
    page.get_by_role("heading", name="素材与产物", exact=True).wait_for()
    # The upload button drives one hidden page-level file input.
    page.get_by_role("button", name="上传素材", exact=True).wait_for()
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and response.url.endswith(f"/projects/{project_id}/assets"),
    ) as pending:
        page.locator("input[type=file]").set_input_files(str(source))
    accepted = pending.value.json()
    # Small uploads complete synchronously: the 202 body already carries a
    # terminal status and its synthetic taskId is not queryable afterwards.
    if accepted.get("status") != "SUCCEEDED":
        task = api.wait_task(project_id, accepted["taskId"])
        assert task["status"] == "SUCCEEDED", task

    snapshot = api.project_snapshot(project_id)["project"]
    versions = snapshot["assets"]["source_versions_by_id"]
    assert versions, "upload must register a SourceAssetVersion"
    files = snapshot["assets"]["files_by_id"]
    file_ids = {item["file_id"] for item in versions.values()}
    names = {
        files[file_id].get("original_name")
        or files[file_id].get("display_name")
        or ""
        for file_id in file_ids
        if file_id in files
    }
    assert any("source.txt" in name for name in names) or any(
        "source.txt" in str(item.get("name", "")) for item in versions.values()
    ), {"versions": versions, "files": files}
