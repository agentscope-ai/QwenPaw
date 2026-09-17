# -*- coding: utf-8 -*-
"""Task 13.1 多用户全角色、逐页和关键操作验收。

该文件故意支持直接执行，避免加载旧 E2E ``conftest.py`` 的单用户种子。
所有写操作只使用本次创建的唯一 Agent；出现任何失败时立即停止并保留现场。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import asyncpg
import requests
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright


BASE_URL = os.getenv("QWENPAW_BASE_URL", "http://127.0.0.1:18089").rstrip("/")
SCHEMA = os.getenv("QWENPAW_DATABASE_SCHEMA", "qwenpaw_task21_acceptance")
DATABASE_URL = os.getenv("QWENPAW_DATABASE_URL", "").strip()
RUN_ID = os.getenv("QWENPAW_TASK131_RUN_ID", datetime.now().strftime("%Y%m%d-%H%M%S"))
AGENT_ID = f"task131-{RUN_ID.lower()}"
EVIDENCE_DIR = Path(
    os.getenv("QWENPAW_TASK131_EVIDENCE_DIR", f"tmp/task-13-1-{RUN_ID}"),
).resolve()

GENERAL_ROUTES = (
    "/chat",
    "/inbox",
    "/apps",
    "/channels",
    "/sessions",
    "/cron-jobs",
    "/heartbeat",
    "/files",
    "/skills",
    "/tools",
    "/mcp",
    "/agent-config",
    "/agent-stats",
    "/checkpoints",
    "/agents",
    "/token-usage",
)
USER_ROUTES = (
    "/chat",
    "/inbox",
    "/apps",
    "/sessions",
    "/files",
    "/agent-config",
    "/agent-stats",
    "/checkpoints",
    "/agents",
    "/token-usage",
)
ADMIN_ROUTES = (
    "/models",
    "/admin/users",
    "/admin/publications",
    "/skill-pool",
    "/environments",
    "/offload-policy",
    "/security",
    "/system-status",
    "/migration-preview",
    "/voice-transcription",
    "/debug",
    "/backups",
    "/plugin-manager",
)


def _credential(name: str, fallback: str = "") -> str:
    value = os.getenv(name, fallback).strip()
    if not value:
        raise RuntimeError(f"缺少验收凭据环境变量：{name}")
    return value


def _assert_status(response: requests.Response, expected: int | set[int]) -> None:
    allowed = {expected} if isinstance(expected, int) else expected
    if response.status_code not in allowed:
        body = response.text[:600]
        raise AssertionError(
            f"{response.request.method} {response.url} => {response.status_code}, "
            f"期望 {sorted(allowed)}，响应：{body}",
        )


@dataclass
class Evidence:
    checks: list[dict[str, Any]] = field(default_factory=list)
    pages: list[dict[str, Any]] = field(default_factory=list)
    request_ids: list[dict[str, str]] = field(default_factory=list)
    database: dict[str, Any] = field(default_factory=dict)

    def check(self, subject: str, operation: str, detail: Any = None) -> None:
        self.checks.append(
            {"subject": subject, "operation": operation, "detail": detail, "ok": True},
        )

    def write(self, *, status: str, error: str | None = None) -> Path:
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        target = EVIDENCE_DIR / "report.json"
        target.write_text(
            json.dumps(
                {
                    "task": "13.1",
                    "status": status,
                    "run_id": RUN_ID,
                    "agent_id": AGENT_ID,
                    "base_url": BASE_URL,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "error": error,
                    "checks": self.checks,
                    "pages": self.pages,
                    "request_ids": self.request_ids,
                    "database": self.database,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        return target


class ApiIdentity:
    def __init__(self, subject: str, username: str, password: str, evidence: Evidence):
        self.subject = subject
        self.username = username
        self._password = password
        self.evidence = evidence
        self.session = requests.Session()
        response = self.session.post(
            f"{BASE_URL}/api/auth/login",
            json={"username": username, "password": password},
            timeout=20,
        )
        _assert_status(response, 200)
        payload = response.json()
        self.token = str(payload["token"])
        me = self.request("GET", "/api/me", expected=200).json()["user"]
        self.user_id = str(me["id"])
        self.platform_role = str(me["platform_role"])

    def request(
        self,
        method: str,
        path: str,
        *,
        agent_id: str | None = None,
        expected: int | set[int] = 200,
        json_body: Any = None,
        files: Any = None,
        extra_headers: dict[str, str] | None = None,
        stream: bool = False,
        timeout: int = 30,
    ) -> requests.Response:
        request_id = f"task131-{self.subject}-{uuid4().hex[:16]}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "X-Request-ID": request_id,
        }
        if agent_id:
            headers["X-Agent-Id"] = agent_id
        if extra_headers:
            headers.update(extra_headers)
        response = self.session.request(
            method,
            f"{BASE_URL}{path}",
            headers=headers,
            json=json_body,
            files=files,
            stream=stream,
            timeout=timeout,
        )
        self.evidence.request_ids.append(
            {
                "subject": self.subject,
                "operation": f"{method.upper()} {path}",
                "request_id": request_id,
                "status": str(response.status_code),
            },
        )
        _assert_status(response, expected)
        return response


def _login_page(context: BrowserContext, username: str, password: str) -> Page:
    page = context.new_page()
    page.goto(f"{BASE_URL}/login?redirect=%2Fchat", wait_until="domcontentloaded")
    inputs = page.locator("input")
    inputs.nth(1).wait_for(state="visible", timeout=15_000)
    if inputs.count() != 2:
        raise AssertionError("登录页未呈现用户名和密码输入框")
    inputs.nth(0).fill(username)
    inputs.nth(1).fill(password)
    page.locator("form button[type='submit']").click()
    page.wait_for_url(lambda value: "/login" not in value, timeout=20_000)
    return page


def _select_agent(page: Page, agent_id: str) -> None:
    page.evaluate(
        """
        agentId => {
          const userId = localStorage.getItem('qwenpaw_authenticated_user_id');
          if (!userId) throw new Error('authenticated_user_id_missing');
          const suffix = `:user:${userId}`;
          const state = JSON.stringify({ state: { selectedAgent: agentId }, version: 0 });
          localStorage.setItem(`qwenpaw-last-used-agent${suffix}`, agentId);
          localStorage.setItem(`qwenpaw-agent-storage${suffix}`, state);
          sessionStorage.setItem(`qwenpaw-agent-storage${suffix}`, state);
        }
        """,
        agent_id,
    )
    page.reload(wait_until="domcontentloaded")


def _route_name(route: str) -> str:
    return "root" if route == "/" else route.strip("/").replace("/", "-")


def _capture_pages(
    page: Page,
    *,
    subject: str,
    routes: tuple[str, ...],
    evidence: Evidence,
    expected_redirect: str | None = None,
) -> None:
    directory = EVIDENCE_DIR / "screenshots" / subject
    directory.mkdir(parents=True, exist_ok=True)
    for route in routes:
        page.goto(f"{BASE_URL}{route}", wait_until="domcontentloaded", timeout=25_000)
        target = directory / f"{_route_name(route)}.png"
        body = ""
        stable_samples = 0
        for _ in range(40):
            page.wait_for_timeout(500)
            body = str(
                page.evaluate("document.body ? document.body.innerText : ''"),
            )
            stable_samples = stable_samples + 1 if body.strip() else 0
            if stable_samples >= 3:
                break
        page.screenshot(path=str(target), full_page=True)
        if not body.strip():
            raise AssertionError(f"{subject} {route} 页面为空")
        if "Something went wrong" in body or "ChunkLoadError" in body:
            raise AssertionError(f"{subject} {route} 出现前端致命错误")
        if expected_redirect and expected_redirect not in page.url:
            raise AssertionError(
                f"{subject} {route} 未重定向到 {expected_redirect}，实际 {page.url}",
            )
        evidence.pages.append(
            {
                "subject": subject,
                "route": route,
                "final_url": page.url,
                "screenshot": str(target),
                "body_chars": len(body),
                "ok": True,
            },
        )


def _profile(identity: ApiIdentity, agent_id: str) -> dict[str, Any]:
    return identity.request("GET", f"/api/agents/{agent_id}", expected=200).json()


def _update_description(
    identity: ApiIdentity,
    agent_id: str,
    description: str,
    *,
    governance: bool = False,
) -> None:
    if governance:
        path = f"/api/admin/agents/{agent_id}/config"
        profile = identity.request("GET", path, expected=200).json()
    else:
        path = f"/api/agents/{agent_id}"
        profile = _profile(identity, agent_id)
    profile["description"] = description
    identity.request("PUT", path, json_body=profile, expected=200)


def _exercise_sse(identity: ApiIdentity, evidence: Evidence) -> None:
    response = identity.request(
        "GET",
        f"/api/agents/{AGENT_ID}/runtime-status/stream",
        agent_id=AGENT_ID,
        expected=200,
        stream=True,
        timeout=10,
    )
    try:
        first = next(
            line.decode("utf-8")
            for line in response.iter_lines(chunk_size=1)
            if line
        )
        if '"type": "connected"' not in first:
            raise AssertionError(f"SSE 首事件异常：{first[:200]}")
    finally:
        response.close()
    evidence.check(identity.subject, "SSE connected", first)


async def _database_snapshot(request_ids: list[str]) -> dict[str, Any]:
    if not DATABASE_URL:
        return {"skipped": "QWENPAW_DATABASE_URL 未设置"}
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", SCHEMA):
        raise RuntimeError("QWENPAW_DATABASE_SCHEMA 非法")
    dsn = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)
    connection = await asyncpg.connect(dsn)
    try:
        agent = await connection.fetchrow(
            f'''SELECT a.id, a.name, a.status, a.visibility, a.config_version,
                       owner.username AS owner_username
                FROM "{SCHEMA}".agents a
                JOIN "{SCHEMA}".users owner ON owner.id = a.owner_user_id
                WHERE a.name = $1
                ORDER BY a.created_at DESC LIMIT 1''',
            f"Task 13.1 {RUN_ID}",
        )
        if agent is None:
            raise AssertionError("数据库中未找到 Task 13.1 Agent")
        agent_uuid = agent["id"]
        members = await connection.fetch(
            f'''SELECT u.username, am.role, am.revoked_at
                FROM "{SCHEMA}".agent_members am
                JOIN "{SCHEMA}".users u ON u.id = am.user_id
                WHERE am.agent_id = $1 ORDER BY u.username''',
            agent_uuid,
        )
        conversations = await connection.fetch(
            f'''SELECT c.id, c.title, c.status, u.username AS owner_username
                FROM "{SCHEMA}".conversations c
                JOIN "{SCHEMA}".users u ON u.id = c.owner_user_id
                WHERE c.agent_id = $1 ORDER BY c.created_at''',
            agent_uuid,
        )
        audits = await connection.fetch(
            f'''SELECT action, result, request_id, source, redacted_detail
                FROM "{SCHEMA}".audit_logs
                WHERE resource_id = $1 OR request_id = ANY($2::text[])
                ORDER BY created_at''',
            agent_uuid,
            request_ids,
        )
        return {
            "agent": dict(agent),
            "members": [dict(row) for row in members],
            "conversations": [dict(row) for row in conversations],
            "audit_logs": [dict(row) for row in audits],
        }
    finally:
        await connection.close()


def _create_chat(owner: ApiIdentity, name: str) -> str:
    response = owner.request(
        "POST",
        f"/api/agents/{AGENT_ID}/chats",
        agent_id=AGENT_ID,
        expected=200,
        json_body={
            "name": name,
            "session_id": f"task131-{uuid4()}",
            "user_id": "untrusted-client-value",
            "channel": "console",
            "meta": {"task": "13.1", "run_id": RUN_ID},
        },
    )
    return str(response.json()["id"])


def run(*, allow_destructive_cleanup: bool, headless: bool) -> Path:
    if not allow_destructive_cleanup:
        raise RuntimeError(
            "完整验收包含撤销成员、批量删除测试会话和软删除测试 Agent；"
            "必须显式传入 --allow-destructive-cleanup",
        )
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    evidence = Evidence()
    admin_user = _credential("QWENPAW_E2E_ADMIN_USERNAME", "admin-task21")
    admin_password = _credential("QWENPAW_E2E_ADMIN_PASSWORD")
    owner_user = _credential("QWENPAW_E2E_OWNER_USERNAME", "task42-user")
    owner_password = _credential("QWENPAW_E2E_OWNER_PASSWORD")
    member_user = _credential("QWENPAW_E2E_MEMBER_USERNAME", "task62-user-b")
    member_password = _credential("QWENPAW_E2E_MEMBER_PASSWORD")

    try:
        admin = ApiIdentity("admin-normal", admin_user, admin_password, evidence)
        owner = ApiIdentity("owner", owner_user, owner_password, evidence)
        member = ApiIdentity("collaborator", member_user, member_password, evidence)
        evidence.check("authentication", "three independent identities")

        admin.request("GET", "/api/admin/agents", expected=200)
        owner_agents = owner.request("GET", "/api/agents", expected=200).json()[
            "agents"
        ]
        member.request("GET", "/api/agents", expected=200)
        active_model = next(
            (
                row["active_model"]
                for row in owner_agents
                if row.get("access_role") == "owner"
                and row.get("active_model", {}).get("provider_id")
                and row.get("active_model", {}).get("model")
            ),
            None,
        )
        if active_model is None:
            raise AssertionError("owner 没有可复用的非敏感活动模型槽")

        owner.request(
            "POST",
            "/api/agents",
            expected=201,
            json_body={
                "id": AGENT_ID,
                "name": f"Task 13.1 {RUN_ID}",
                "description": "Task 13.1 owner-created acceptance agent",
                "language": "zh",
                "skill_names": [],
                "active_model": active_model,
            },
        )
        for _ in range(30):
            response = owner.request(
                "GET",
                f"/api/agents/{AGENT_ID}",
                expected={200, 409, 503},
            )
            if response.status_code == 200:
                break
            time.sleep(0.3)
        else:
            raise AssertionError("临时 Agent 未在预期时间内就绪")
        evidence.check("owner", "create/detail", AGENT_ID)

        _update_description(owner, AGENT_ID, "Task 13.1 owner update")
        evidence.check("owner", "edit")
        _update_description(
            admin,
            AGENT_ID,
            "Task 13.1 explicit admin governance update",
            governance=True,
        )
        evidence.check("admin-governance", "explicit config read/update")

        users = admin.request("GET", "/api/admin/users", expected=200).json()
        member_row = next(row for row in users if row["username"] == member_user)
        owner.request(
            "PUT",
            f"/api/agents/{AGENT_ID}/members/{member_row['id']}",
            json_body={"role": "collaborator"},
            expected=200,
        )
        member.request("GET", f"/api/agents/{AGENT_ID}", expected=200)
        _update_description(member, AGENT_ID, "Task 13.1 collaborator update")
        evidence.check("collaborator", "detail/edit")

        chat_ids = [
            _create_chat(owner, f"Task 13.1 batch A {RUN_ID}"),
            _create_chat(owner, f"Task 13.1 batch B {RUN_ID}"),
        ]
        batch = owner.request(
            "POST",
            f"/api/agents/{AGENT_ID}/chats/actions/batch-archive",
            agent_id=AGENT_ID,
            json_body={"chat_ids": chat_ids},
            expected=200,
        ).json()
        if set(batch["succeeded"]) != set(chat_ids) or batch["failed"]:
            raise AssertionError(f"批量归档异常：{batch}")
        owner.request(
            "POST",
            f"/api/agents/{AGENT_ID}/chats/actions/batch-unarchive",
            agent_id=AGENT_ID,
            json_body={"chat_ids": chat_ids},
            expected=200,
        )
        evidence.check("owner", "batch archive/unarchive", chat_ids)

        upload_name = f"task-13-1-{RUN_ID}.txt"
        upload_content = f"Task 13.1 upload {RUN_ID}".encode()
        upload_path = f"/api/agents/{AGENT_ID}/workspace/file-upload?root=project&path="
        owner.request(
            "POST",
            upload_path,
            agent_id=AGENT_ID,
            files={"files": (upload_name, upload_content, "text/plain")},
            expected=200,
        )
        owner.request(
            "POST",
            upload_path,
            agent_id=AGENT_ID,
            files={"files": (upload_name, b"must-not-overwrite", "text/plain")},
            expected=409,
        )
        download = owner.request(
            "GET",
            f"/api/agents/{AGENT_ID}/workspace/file-download"
            f"?root=project&path={upload_name}",
            agent_id=AGENT_ID,
            expected=200,
        )
        if download.content != upload_content:
            raise AssertionError("上传冲突后原文件内容发生变化")
        evidence.check("owner", "upload/download/conflict rollback", upload_name)
        _exercise_sse(owner, evidence)

        for identity in (owner, member):
            identity.request(
                "GET",
                "/api/approval/list",
                expected=200,
            )
            identity.request(
                "POST",
                "/api/approval/approve",
                json_body={
                    "request_id": str(uuid4()),
                    "session_id": "task131-missing",
                },
                expected=404,
            )
        evidence.check("approval", "user-bound list and safe missing-request failure")

        with sync_playwright() as playwright:
            executable = os.getenv("QWENPAW_E2E_BROWSER_EXECUTABLE", "").strip()
            launch_options: dict[str, Any] = {"headless": headless}
            if executable:
                executable_path = Path(executable).expanduser().resolve()
                if not executable_path.is_file():
                    raise RuntimeError(
                        "QWENPAW_E2E_BROWSER_EXECUTABLE 不存在："
                        f"{executable_path}",
                    )
                launch_options["executable_path"] = str(executable_path)
            browser: Browser = playwright.chromium.launch(**launch_options)
            try:
                admin_context = browser.new_context(viewport={"width": 1600, "height": 1000})
                owner_context = browser.new_context(viewport={"width": 1600, "height": 1000})
                member_context = browser.new_context(viewport={"width": 1600, "height": 1000})
                anonymous_context = browser.new_context(viewport={"width": 1600, "height": 1000})
                admin_page = _login_page(admin_context, admin_user, admin_password)
                owner_page = _login_page(owner_context, owner_user, owner_password)
                member_page = _login_page(member_context, member_user, member_password)
                _select_agent(admin_page, "default")
                _select_agent(owner_page, AGENT_ID)
                _select_agent(member_page, AGENT_ID)
                _capture_pages(
                    admin_page,
                    subject="admin-normal",
                    routes=GENERAL_ROUTES + ADMIN_ROUTES,
                    evidence=evidence,
                )
                _capture_pages(
                    admin_page,
                    subject="admin-governance",
                    routes=("/agents", "/agent-config"),
                    evidence=evidence,
                )
                _capture_pages(
                    owner_page,
                    subject="owner",
                    routes=GENERAL_ROUTES,
                    evidence=evidence,
                )
                _capture_pages(
                    member_page,
                    subject="collaborator",
                    routes=GENERAL_ROUTES,
                    evidence=evidence,
                )

                owner.request(
                    "PUT",
                    f"/api/agents/{AGENT_ID}/members/{member_row['id']}",
                    json_body={"role": "user"},
                    expected=200,
                )
                member.subject = "user"
                member.request("GET", f"/api/agents/{AGENT_ID}", expected=403)
                member.request(
                    "GET",
                    "/api/approval/list",
                    expected=200,
                )
                _capture_pages(
                    member_page,
                    subject="user",
                    routes=USER_ROUTES,
                    evidence=evidence,
                )
                evidence.check("user", "use/read paths; full config denied")

                owner.request(
                    "DELETE",
                    f"/api/agents/{AGENT_ID}/members/{member_row['id']}",
                    expected=200,
                )
                member.subject = "unauthorized"
                member.request("GET", f"/api/agents/{AGENT_ID}", expected=403)
                member.request(
                    "GET",
                    f"/api/agents/{AGENT_ID}/chats",
                    agent_id=AGENT_ID,
                    expected=403,
                )
                _capture_pages(
                    member_page,
                    subject="unauthorized",
                    routes=("/chat", "/files", "/agent-config", "/sessions"),
                    evidence=evidence,
                )
                anonymous_page = anonymous_context.new_page()
                _capture_pages(
                    anonymous_page,
                    subject="anonymous",
                    routes=("/chat", "/agents", "/admin/users"),
                    evidence=evidence,
                    expected_redirect="/login",
                )
            finally:
                browser.close()

        evidence.database["before_cleanup"] = asyncio.run(
            _database_snapshot([row["request_id"] for row in evidence.request_ids]),
        )
        owner.request(
            "POST",
            f"/api/agents/{AGENT_ID}/chats/batch-delete",
            agent_id=AGENT_ID,
            json_body=chat_ids,
            expected=200,
        )
        deleted = owner.request(
            "DELETE",
            f"/api/agents/{AGENT_ID}",
            expected=200,
        ).json()
        if not deleted.get("soft_deleted"):
            raise AssertionError(f"多用户 Agent 删除未走软删除：{deleted}")
        evidence.check("owner", "batch delete and agent soft delete")
        after_cleanup = asyncio.run(
            _database_snapshot([row["request_id"] for row in evidence.request_ids]),
        )
        evidence.database["after_cleanup"] = after_cleanup
        if after_cleanup["agent"]["status"] != "deleted":
            raise AssertionError("Agent 软删除未同步到 PostgreSQL")
        if any(
            row["status"] != "deleted"
            for row in after_cleanup["conversations"]
        ):
            raise AssertionError("会话删除未同步到 PostgreSQL")
        return evidence.write(status="passed")
    except BaseException as exc:
        report = evidence.write(status="failed", error=f"{type(exc).__name__}: {exc}")
        print(f"验收失败，现场已保留：{report}", file=sys.stderr)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-destructive-cleanup",
        action="store_true",
        help="允许撤销临时成员、批量删除临时会话和软删除临时 Agent",
    )
    parser.add_argument("--headed", action="store_true", help="显示浏览器窗口")
    args = parser.parse_args()
    report = run(
        allow_destructive_cleanup=args.allow_destructive_cleanup,
        headless=not args.headed,
    )
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
