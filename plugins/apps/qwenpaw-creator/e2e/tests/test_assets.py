# -*- coding: utf-8 -*-

from __future__ import annotations

import pytest


pytestmark = pytest.mark.assets


def test_supplement_upload_is_indexed_in_project(page, api, project, tmp_path):
    project_id = project["projectId"]
    source = tmp_path / "source.txt"
    source.write_text("immutable supplement source", encoding="utf-8")

    page.goto(f"/#/project/{project_id}/assets")
    page.get_by_role("heading", level=1, name="资产库").wait_for()
    page.get_by_role("button", name="补充资料", exact=True).first.click()
    modal = page.locator(".ant-modal").filter(
        has=page.get_by_text("补充资料", exact=True),
    )
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and response.url.endswith(f"/projects/{project_id}/assets"),
    ) as pending:
        modal.locator("input[type=file]").set_input_files(str(source))
    accepted = pending.value.json()
    task = api.wait_task(project_id, accepted["taskId"])
    assert task["status"] == "SUCCEEDED", task

    snapshot = api.project_snapshot(project_id)["project"]
    versions = snapshot["assets"]["source_versions_by_id"]
    assert any(item["name"] == "source.txt" for item in versions.values())
