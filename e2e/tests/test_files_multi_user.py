# -*- coding: utf-8 -*-
"""Task 6.2: two-user browser acceptance for private runtime files."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, expect

from config.settings import config


def _credentials(prefix: str) -> tuple[str, str]:
    username = os.getenv(f"QWENPAW_E2E_{prefix}_USERNAME", "").strip()
    password = os.getenv(f"QWENPAW_E2E_{prefix}_PASSWORD", "").strip()
    if not username or not password:
        pytest.skip(f"Missing QWENPAW_E2E_{prefix}_USERNAME/PASSWORD")
    return username, password


def _login(page: Page, username: str, password: str) -> None:
    page.goto(f"{config.base_url}/login?redirect=%2Ffiles")
    inputs = page.locator("input")
    expect(inputs).to_have_count(2)
    inputs.nth(0).fill(username)
    inputs.nth(1).fill(password)
    page.locator("form button[type='submit']").click()
    page.wait_for_url(lambda url: "/login" not in url, timeout=15_000)


def _select_agent(page: Page, agent_id: str) -> None:
    page.evaluate(
        "agentId => localStorage.setItem('qwenpaw-last-used-agent', agentId)",
        agent_id,
    )
    page.evaluate("sessionStorage.clear()")
    page.reload(wait_until="networkidle")


def _write_and_read_runtime_file(
    page: Page,
    *,
    username: str,
    password: str,
    agent_id: str,
    path: str,
    content: str,
) -> dict[str, object]:
    return page.evaluate(
        """
        async ({ username, password, agentId, path, content }) => {
          const loginResponse = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password }),
          });
          if (!loginResponse.ok) throw new Error('login_failed');
          const { token } = await loginResponse.json();
          const headers = {
            Authorization: `Bearer ${token}`,
            'Content-Type': 'application/json',
            'X-Agent-Id': agentId,
          };
          const query = new URLSearchParams({ path, root: 'project' });
          const writeResponse = await fetch(
            `/api/workspace/file-content?${query}`,
            { method: 'PUT', headers, body: JSON.stringify({ content }) },
          );
          const readResponse = await fetch(
            `/api/workspace/file-content?${query}`,
            { headers },
          );
          const agentWorkspaceWrite = await fetch(
            `/api/workspace/file-content?${new URLSearchParams({
              path: 'task-6-2-agent-config-denied.md',
              root: 'workspace',
            })}`,
            { method: 'PUT', headers, body: JSON.stringify({ content }) },
          );
          const directoryResponse = await fetch(
            '/api/workspace/project-directory',
            { headers },
          );
          return {
            writeStatus: writeResponse.status,
            readStatus: readResponse.status,
            readBody: await readResponse.json(),
            agentWorkspaceWriteStatus: agentWorkspaceWrite.status,
            directoryStatus: directoryResponse.status,
            directory: await directoryResponse.json(),
          };
        }
        """,
        {
            "username": username,
            "password": password,
            "agentId": agent_id,
            "path": path,
            "content": content,
        },
    )


def _upload_chat_attachment(
    page: Page,
    *,
    username: str,
    password: str,
    agent_id: str,
    content: str,
) -> dict[str, object]:
    """Upload through the real chat endpoint and inspect the runtime tree."""
    return page.evaluate(
        """
        async ({ username, password, agentId, content }) => {
          const loginResponse = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password }),
          });
          if (!loginResponse.ok) throw new Error('login_failed');
          const { token } = await loginResponse.json();
          const headers = {
            Authorization: `Bearer ${token}`,
            'X-Agent-Id': agentId,
          };
          const form = new FormData();
          form.append(
            'file',
            new Blob([content], { type: 'text/plain' }),
            'task-6-2-r-attachment.txt',
          );
          const uploadResponse = await fetch('/api/console/upload', {
            method: 'POST',
            headers,
            body: form,
          });
          const upload = await uploadResponse.json();
          const treeResponse = await fetch(
            '/api/workspace/tree?root=project&path=media&limit=200',
            { headers },
          );
          return {
            uploadStatus: uploadResponse.status,
            upload,
            treeStatus: treeResponse.status,
            tree: await treeResponse.json(),
          };
        }
        """,
        {
            "username": username,
            "password": password,
            "agentId": agent_id,
            "content": content,
        },
    )


def _download_attachment_as(
    page: Page,
    *,
    username: str,
    password: str,
    agent_id: str,
    attachment_url: str,
) -> int:
    return page.evaluate(
        """
        async ({ username, password, agentId, attachmentUrl }) => {
          const loginResponse = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password }),
          });
          if (!loginResponse.ok) throw new Error('login_failed');
          const { token } = await loginResponse.json();
          const response = await fetch(attachmentUrl, {
            headers: {
              Authorization: `Bearer ${token}`,
              'X-Agent-Id': agentId,
            },
          });
          return response.status;
        }
        """,
        {
            "username": username,
            "password": password,
            "agentId": agent_id,
            "attachmentUrl": attachment_url,
        },
    )


@pytest.mark.integration
@pytest.mark.files
def test_two_users_keep_same_named_runtime_files_isolated(
    browser: Browser,
    tmp_path: Path,
) -> None:
    """Two use-only users must get writable, mutually isolated roots."""
    user_a = _credentials("USER_A")
    user_b = _credentials("USER_B")
    agent_id = os.getenv("QWENPAW_E2E_PUBLIC_AGENT", "default")
    evidence_dir = Path(
        os.getenv("QWENPAW_E2E_EVIDENCE_DIR", str(tmp_path)),
    ).resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    path = "task-6-2-same-name.md"

    context_a = browser.new_context()
    context_b = browser.new_context()
    try:
        page_a = context_a.new_page()
        page_b = context_b.new_page()
        _login(page_a, *user_a)
        _login(page_b, *user_b)
        _select_agent(page_a, agent_id)
        _select_agent(page_b, agent_id)

        for label in ("临时附件", "个人资料库", "产物", "Agent 配置", "记忆"):
            expect(page_a.get_by_role("tab", name=label, exact=True)).to_be_visible()
            expect(page_b.get_by_role("tab", name=label, exact=True)).to_be_visible()
        expect(page_a.get_by_role("tab", name="档案", exact=True)).to_have_count(0)
        expect(page_b.get_by_role("tab", name="知识库", exact=True)).to_have_count(0)
        expect(page_a.get_by_role("button", name="Agent 项目目录")).to_have_count(0)
        expect(page_b.get_by_role("button", name="Agent 项目目录")).to_have_count(0)

        result_a = _write_and_read_runtime_file(
            page_a,
            username=user_a[0],
            password=user_a[1],
            agent_id=agent_id,
            path=path,
            content="user-a-runtime",
        )
        result_b = _write_and_read_runtime_file(
            page_b,
            username=user_b[0],
            password=user_b[1],
            agent_id=agent_id,
            path=path,
            content="user-b-runtime",
        )

        assert result_a["writeStatus"] == result_a["readStatus"] == 200
        assert result_b["writeStatus"] == result_b["readStatus"] == 200
        assert result_a["readBody"]["content"] == "user-a-runtime"
        assert result_b["readBody"]["content"] == "user-b-runtime"
        assert result_a["agentWorkspaceWriteStatus"] == 403
        assert result_b["agentWorkspaceWriteStatus"] == 403
        assert result_a["directoryStatus"] == result_b["directoryStatus"] == 200
        assert result_a["directory"]["project_kind"] == "user_runtime"
        assert result_b["directory"]["project_kind"] == "user_runtime"
        assert result_a["directory"]["path"] != result_b["directory"]["path"]

        page_a.screenshot(
            path=str(evidence_dir / "task-6-2-user-a-runtime.png"),
            full_page=True,
        )
        page_b.screenshot(
            path=str(evidence_dir / "task-6-2-user-b-runtime.png"),
            full_page=True,
        )
    finally:
        context_b.close()
        context_a.close()


@pytest.mark.integration
@pytest.mark.files
def test_chat_uploads_follow_each_users_runtime_workspace(
    browser: Browser,
) -> None:
    """Chat uploads must appear below each caller's private runtime root."""
    user_a = _credentials("USER_A")
    user_b = _credentials("USER_B")
    agent_id = os.getenv("QWENPAW_E2E_PUBLIC_AGENT", "default")
    context_a = browser.new_context()
    context_b = browser.new_context()
    try:
        page_a = context_a.new_page()
        page_b = context_b.new_page()
        page_a.goto(f"{config.base_url}/login", wait_until="domcontentloaded")
        page_b.goto(f"{config.base_url}/login", wait_until="domcontentloaded")

        upload_a = _upload_chat_attachment(
            page_a,
            username=user_a[0],
            password=user_a[1],
            agent_id=agent_id,
            content="user-a-attachment",
        )
        upload_b = _upload_chat_attachment(
            page_b,
            username=user_b[0],
            password=user_b[1],
            agent_id=agent_id,
            content="user-b-attachment",
        )

        assert upload_a["uploadStatus"] == upload_a["treeStatus"] == 200
        assert upload_b["uploadStatus"] == upload_b["treeStatus"] == 200
        url_a = str(upload_a["upload"]["url"])
        url_b = str(upload_b["upload"]["url"])
        assert url_a.startswith("/api/console/attachments/")
        assert url_b.startswith("/api/console/attachments/")
        assert url_a != url_b
        assert upload_a["tree"]["entries"]
        assert upload_b["tree"]["entries"]
        assert (
            _download_attachment_as(
                page_a,
                username=user_a[0],
                password=user_a[1],
                agent_id=agent_id,
                attachment_url=url_a,
            )
            == 200
        )
        assert (
            _download_attachment_as(
                page_b,
                username=user_b[0],
                password=user_b[1],
                agent_id=agent_id,
                attachment_url=url_a,
            )
            == 404
        )
    finally:
        context_b.close()
        context_a.close()
