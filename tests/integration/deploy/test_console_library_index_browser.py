# -*- coding: utf-8 -*-
"""生产构建的资料索引交互验收；全部业务 API 使用独立测试响应。"""

import json
import os
from urllib.parse import parse_qs, urlsplit

import pytest

BASE_URL = os.environ.get("WELDON_TEST_CONSOLE_URL", "")


@pytest.mark.skipif(
    not BASE_URL, reason="Set WELDON_TEST_CONSOLE_URL to a built console"
)
def test_library_index_rebuild_upload_and_browser_tab_return():
    from playwright.sync_api import expect, sync_playwright

    documents = [
        {
            "id": "11111111-1111-4111-8111-111111111111",
            "name": "旅行计划.md",
            "relative_path": "旅行计划.md",
            "media_type": "text/markdown",
            "size": 20,
            "sha256": "a" * 64,
            "created_at": "2026-09-18T00:00:00Z",
            "updated_at": "2026-09-18T00:00:00Z",
        }
    ]
    statuses = [
        {
            "document_id": documents[0]["id"],
            "status": "pending",
            "indexed_characters": 0,
            "updated_at": None,
        }
    ]
    writes, errors, reads = [], [], []

    def api(route):
        path = urlsplit(route.request.url).path.removeprefix("/api")
        reads.append(path)
        if path.endswith("/stream"):
            route.fulfill(status=204)
            return
        payload = {}
        if path == "/auth/status":
            payload = {"enabled": True, "mode": "multi_user", "has_users": True}
        elif path == "/auth/refresh":
            payload = {"token": "test-only", "username": "library-test"}
        elif path == "/me":
            payload = {
                "user": {
                    "id": "test-user",
                    "username": "library-test",
                    "platform_role": "admin",
                    "status": "active",
                },
                "preferences": {"language": "zh", "timezone": "Asia/Shanghai"},
            }
        elif path in ("/agents", "/admin/agents"):
            payload = {
                "agents": [
                    {
                        "id": "default",
                        "name": "索引验收智能体",
                        "enabled": True,
                        "access_role": "owner",
                        "can_edit": True,
                    }
                ]
            }
        elif path == "/console/personal-library/documents":
            payload = documents
        elif path == "/console/personal-library/documents/page":
            assert route.request.headers["x-agent-id"] == "default"
            query = parse_qs(urlsplit(route.request.url).query)
            offset = int(query.get("offset", ["0"])[0])
            limit = int(query.get("limit", ["20"])[0])
            search = query.get("query", [""])[0].casefold()
            matches = [
                document
                for document in documents
                if search in document["relative_path"].casefold()
            ]
            payload = {
                "items": matches[offset : offset + limit],
                "total": len(matches),
            }
        elif path == "/console/personal-library/index":
            payload = statuses
        elif path == "/console/personal-library/index/rebuild":
            assert route.request.headers["x-agent-id"] == "default"
            assert route.request.post_data_json == {
                "document_ids": [documents[0]["id"]]
            }
            statuses[0].update(status="ready", indexed_characters=20)
            writes.append("rebuild")
            payload = statuses
        elif path == "/console/personal-library/documents/upload":
            assert route.request.headers["x-agent-id"] == "default"
            payload = {
                **documents[0],
                "id": "22222222-2222-4222-8222-222222222222",
                "name": "新资料.md",
                "relative_path": "新资料.md",
            }
            documents.append(payload)
            statuses.append(
                {
                    "document_id": payload["id"],
                    "status": "ready",
                    "indexed_characters": 20,
                    "updated_at": None,
                }
            )
            writes.append("upload")
        elif path in (
            "/frontend_plugin",
            "/slash/catalog",
            "/loops",
            "/chats",
            "/console/attachments",
        ):
            payload = []
        elif path == "/chats/page":
            payload = {"items": [], "has_more": False, "next_cursor": None}
        elif path == "/console/push-messages":
            payload = {"messages": [], "pending_approvals": []}
        elif path == "/console/inbox/events":
            payload = {"events": [], "total": 0, "unread_count": 0}
        elif path in ("/user-input/pending", "/runtime-status/current", "/plan/current"):
            payload = None
        elif path == "/model-catalog":
            payload = {"models": []}
        route.fulfill(
            status=200, content_type="application/json", body=json.dumps(payload)
        )

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            context.route("**/api/**", api)
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"{BASE_URL.rstrip('/')}/files", wait_until="networkidle")
            dismiss = page.get_by_text("我知道了", exact=True)
            if dismiss.is_visible():
                dismiss.click()
            page.get_by_role("tab", name="个人资料库", exact=True).click()
            panel = page.get_by_role("region", name="个人资料库", exact=True)
            expect(panel.get_by_text("待建立索引", exact=True)).to_be_visible()
            panel.get_by_role("button", name="重建索引", exact=True).click()
            expect(panel.get_by_text("可检索", exact=True)).to_have_count(1)
            page.get_by_label("上传文件", exact=True).set_input_files(
                {
                    "name": "新资料.md",
                    "mimeType": "text/markdown",
                    "buffer": "云南徒步旅行".encode(),
                }
            )
            expect(
                panel.get_by_role("button", name="新资料.md", exact=True)
            ).to_be_visible()
            expect(panel.get_by_text("可检索", exact=True)).to_have_count(2)
            other = context.new_page()
            other.goto("about:blank")
            other.bring_to_front()
            page.bring_to_front()
            for _ in range(3):
                page.get_by_role("tab", name="临时附件", exact=True).click()
                page.get_by_role("tab", name="个人资料库", exact=True).click()
                expect(
                    panel.get_by_role("button", name="旅行计划.md", exact=True)
                ).to_have_count(1)
                expect(panel.get_by_text("可检索", exact=True)).to_have_count(2)
            page.reload(wait_until="networkidle")
            page.get_by_role("tab", name="个人资料库", exact=True).click()
            expect(panel.get_by_text("可检索", exact=True)).to_have_count(2)
            page.get_by_text("收件箱", exact=True).first.click()
            page.wait_for_url("**/inbox")
            page.get_by_text("文件", exact=True).first.click()
            page.wait_for_url("**/files")
            page.get_by_role("tab", name="个人资料库", exact=True).click()
            expect(panel.get_by_text("可检索", exact=True)).to_have_count(2)
            assert writes == ["rebuild", "upload"]
            assert not errors, errors
        except Exception as exc:
            raise AssertionError(
                {
                    "errors": errors,
                    "requests": sorted(set(reads)),
                    "page": page.locator("body").inner_text()[:2500],
                }
            ) from exc
        finally:
            browser.close()
