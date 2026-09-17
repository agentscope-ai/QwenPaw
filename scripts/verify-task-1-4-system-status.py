# -*- coding: utf-8 -*-
"""在独立 Vite 端口验收 Task 1.4 只读系统状态页。"""

from __future__ import annotations

import json
import os
from pathlib import Path

from playwright.sync_api import Route, sync_playwright

STATUS_PAYLOAD = {
    "status": "legacy",
    "connected": False,
    "schema_version": None,
    "expected_schema_version": "0003_governance_operations",
    "schema_ready": False,
    "storage_mode": "legacy",
    "active_repository": "legacy",
    "migration_lock_state": "not_applicable",
    "error_code": None,
}


def _browser_executable() -> str | None:
    configured = os.environ.get(
        "QWENPAW_E2E_BROWSER_EXECUTABLE",
        "",
    ).strip()
    candidates = [
        configured,
        "C:/Program Files/Google/Chrome/Application/chrome.exe",
        "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
        "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
    ]
    return next(
        (
            candidate
            for candidate in candidates
            if candidate and Path(candidate).is_file()
        ),
        None,
    )


def _fulfill_status(route: Route) -> None:
    route.fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps(STATUS_PAYLOAD),
    )


def main() -> None:
    screenshot_path = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "project-audit"
        / "evidence"
        / "task-1.4-system-status.png"
    )
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        executable = _browser_executable()
        launch_options = {"headless": True}
        if executable is not None:
            launch_options["executable_path"] = executable
        browser = playwright.chromium.launch(**launch_options)
        page = browser.new_page(viewport={"width": 1440, "height": 960})
        page.route("**/api/system/storage-status", _fulfill_status)
        page.goto("http://127.0.0.1:4174/system-status")
        page.wait_for_load_state("networkidle")

        heading = page.get_by_text(
            "Legacy storage is active",
            exact=True,
        ).or_(page.get_by_text("当前仍使用原存储", exact=True))
        heading.wait_for(state="visible", timeout=15_000)

        dismiss_tour = page.get_by_role("button", name="我知道了")
        if dismiss_tour.count() and dismiss_tour.is_visible():
            dismiss_tour.click()

        refresh = page.get_by_role(
            "button",
            name="Refresh",
        ).or_(page.get_by_role("button", name="刷新"))
        assert refresh.count() == 1

        for dangerous_label in ("Migrate", "Rebuild", "DROP", "Delete"):
            assert page.get_by_role("button", name=dangerous_label).count() == 0

        page.screenshot(path=str(screenshot_path), full_page=True)
        print(screenshot_path)
        browser.close()


if __name__ == "__main__":
    main()
