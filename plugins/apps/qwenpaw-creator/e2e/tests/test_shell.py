# -*- coding: utf-8 -*-

from uuid import uuid4

import pytest
from playwright.sync_api import expect

from pages.home_page import HomePage


pytestmark = pytest.mark.shell


def test_home_and_composer_use_current_project_contract(page):
    home = HomePage(page).open()
    expect(page.get_by_role("heading", name="我的项目")).to_be_visible()
    composer = home.open_composer()
    expect(
        page.get_by_text("开始创作吧！请将目标、素材和限制交给 Agent"),
    ).to_be_visible()
    composer.select_scenario("通用")
    composer.fill_name("E2E 冒烟项目").fill_goal("只验证当前 Composer")
    composer.add_url("https://example.com/ref.mp4")
    expect(
        composer.attachment_chip("https://example.com/ref.mp4"),
    ).to_be_visible()
    expect(
        composer.root.get_by_role("button", name="启动 Agent", exact=True),
    ).to_be_enabled()


def test_model_config_values_are_visible_without_legacy_surfaces(page, api):
    config = api.models_config()
    assert set(config) == {
        "llm",
        "vlm",
        "asr",
        "image",
        "video",
        "oss",
        "executionAuthorization",
    }
    HomePage(page).open().open_model_config()
    modal = page.locator(".model-config-modal")
    expect(modal.locator("button.segmented-tab")).to_have_count(6)


def test_create_snapshot_and_delete_project(api):
    created = api.create_project(f"E2E contract {uuid4().hex[:8]}")
    project_id = created["projectId"]
    assert created["projectSnapshotId"]
    try:
        snapshot = api.project_snapshot(project_id)
        assert snapshot["projectId"] == project_id
        assert snapshot["project"]["schema_version"] == 2
        assert snapshot["project"]["timelines"]["order"] == ["timeline:main"]
        session = api.get(f"/projects/{project_id}/session")
        assert session.status_code == 200
        assert session.json()["session"]["status"] == "IDLE"
    finally:
        api.delete_project(project_id)
    assert api.get(f"/projects/{project_id}/project").status_code == 404
