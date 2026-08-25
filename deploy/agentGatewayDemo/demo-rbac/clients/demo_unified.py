"""Unified-gateway demo assertions.

Phases:
  open      — anonymous direct calls to Forum/HR/Finance must succeed
  bypass    — direct calls after lock-down must be rejected
  no-token  — gateway without JWT must be rejected
  forged    — gateway with a badly signed JWT must be rejected
  valid     — gateway with employeeQwenpaw JWT must list and call tools
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from mcp import ClientSession

ROOT = Path(__file__).resolve().parents[1]
TOKEN_FILE = ROOT / "jwt" / "employeeQwenpaw.key"
HR_URL = "http://127.0.0.1:9001/mcp"
FORUM_URL = "http://127.0.0.1:9002/mcp"
FINANCE_URL = "http://127.0.0.1:9003/mcp"
GATEWAY_URL = "http://localhost:3000/mcp"

EXPECTED_GATEWAY_TOOLS = {
    "forum_list_posts",
    "forum_create_post",
    "forum_delete_post",
    "hr_get_employee",
    "hr_update_employee",
    "finance_get_department_budget",
    "finance_submit_expense",
}


def _import_streamable_client():
    from mcp.client import streamable_http as module

    if hasattr(module, "streamablehttp_client"):
        return module.streamablehttp_client, "legacy"
    return module.streamable_http_client, "modern"


def read_token(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def make_forged_token() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    return jwt.encode(
        {
            "iss": "agentgateway.dev",
            "aud": "test.agentgateway.dev",
            "exp": 1893456000,
            "sub": "forgedAgent",
        },
        key,
        algorithm="ES256",
        headers={"typ": "JWT"},
    )


def mask_secret(text: str) -> str:
    text = re.sub(r"id_card=\d+", "id_card=***********", text)
    text = re.sub(r"phone=\d+", "phone=***********", text)
    text = re.sub(r"(budget_cny=)\d+", r"\1***", text)
    text = re.sub(r"(spent_cny=)\d+", r"\1***", text)
    text = re.sub(r"(remaining_cny=)\d+", r"\1***", text)
    text = re.sub(r"(amount_cny=)\d+", r"\1***", text)
    return text


def _flatten(exc: BaseException) -> list[BaseException]:
    found: list[BaseException] = [exc]
    if isinstance(exc, BaseExceptionGroup):
        for sub in exc.exceptions:
            found.extend(_flatten(sub))
    cause = getattr(exc, "__cause__", None)
    if isinstance(cause, BaseException):
        found.extend(_flatten(cause))
    return found


def is_auth_block(exc: BaseException) -> bool:
    parts: list[str] = []
    for sub in _flatten(exc):
        parts.append(str(sub))
        code = getattr(sub, "code", None)
        if code in {-32000, -32600, -32603, 401, 403, 400}:
            return True
        status = getattr(sub, "status_code", None) or getattr(getattr(sub, "response", None), "status_code", None)
        if status in {401, 403, 400}:
            return True
    combined = " ".join(parts).lower()
    hints = (
        "401",
        "403",
        "400",
        "unauthorized",
        "forbidden",
        "invalid token",
        "jwt",
        "unknown tool",
        "missing or invalid gateway token",
        "no bearer token",
        "authentication failure",
        "upstream error",
        "server returned an error response",
    )
    return any(h in combined for h in hints)


def http_status(url: str, headers: dict[str, str] | None = None) -> int:
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        url,
        method="POST",
        data=b"{}",
        headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return int(resp.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)


def tool_text(result) -> str:
    if not result.content:
        return str(result)
    chunks = []
    for block in result.content:
        text = getattr(block, "text", None)
        chunks.append(text if text else str(block))
    return "\n".join(chunks)


@asynccontextmanager
async def open_session(url: str, headers: dict[str, str] | None = None):
    import httpx

    client_fn, flavor = _import_streamable_client()
    if flavor == "legacy":
        async with client_fn(url, headers=headers or {}) as (read, write, *_):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session
        return

    timeout = httpx.Timeout(connect=15.0, read=60.0, write=15.0, pool=15.0)
    async with httpx.AsyncClient(headers=headers or {}, timeout=timeout) as http_client:
        async with client_fn(url, http_client=http_client, terminate_on_close=False) as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session


async def expect_success(url: str, tool: str, arguments: dict | None = None, headers=None) -> str:
    async with open_session(url, headers) as session:
        result = await session.call_tool(tool, arguments=arguments or {})
        text = mask_secret(tool_text(result))
        print(f"  [OK] {url}  {tool}")
        preview = text.splitlines()[:3]
        for line in preview:
            print(f"       {line}")
        if len(text.splitlines()) > 3:
            print("       ...")
        return text


async def expect_denied(url: str, headers=None, label: str = "") -> None:
    title = label or url
    status = http_status(url, headers)
    if status in {401, 403}:
        print(f"  [BLOCKED] {title}  http.status={status}")
        return
    try:
        async with open_session(url, headers) as session:
            tools = [t.name for t in (await session.list_tools()).tools]
            print(f"  [FAIL] {title}  handshake succeeded, tools={tools}")
            raise AssertionError(f"expected deny: {title}")
    except AssertionError:
        raise
    except BaseException as exc:
        if is_auth_block(exc):
            print(f"  [BLOCKED] {title}")
            return
        print(f"  [ERROR] {title}: {exc}")
        raise


async def phase_open() -> int:
    print("角色: anonymousAgent（无 Token，直连三个 MCP）")
    await expect_success(FORUM_URL, "list_posts", {"limit": 3})
    await expect_success(HR_URL, "get_employee", {})
    await expect_success(FINANCE_URL, "get_department_budget", {})
    await expect_success(
        FORUM_URL,
        "create_post",
        {"title": "open-demo", "content": "no auth required", "author": "anonymousAgent"},
    )
    await expect_success(
        FINANCE_URL,
        "submit_expense",
        {"department_id": "D-SALES", "amount_cny": 88, "purpose": "open-demo"},
    )
    print("\n[OK] 三个入口均可匿名读写 — 入口、身份、策略、审计全部缺失")
    return 0


async def phase_bypass() -> int:
    print("角色: anonymousAgent（绕过网关，直连已上锁的后端）")
    await expect_denied(HR_URL, label="HR :9001")
    await expect_denied(FORUM_URL, label="Forum :9002")
    await expect_denied(FINANCE_URL, label="Finance :9003")
    print("\n[OK] 后端只接受网关内部凭证，直连被拒绝")
    return 0


async def phase_no_token() -> int:
    print("角色: anonymousAgent（经网关，无 Authorization）")
    await expect_denied(GATEWAY_URL, label="Gateway :3000 no token")
    print("\n[OK] 网关 strict JWT：无 Token 不能进入统一入口")
    return 0


async def phase_forged() -> int:
    print("角色: forgedAgent（经网关，伪造 JWT）")
    headers = {"Authorization": f"Bearer {make_forged_token()}"}
    await expect_denied(GATEWAY_URL, headers=headers, label="Gateway :3000 forged token")
    print("\n[OK] 网关校验签名/issuer/audience，不是“有 Bearer 就放行”")
    return 0


async def phase_valid() -> int:
    token = read_token(TOKEN_FILE)
    headers = {"Authorization": f"Bearer {token}"}
    print("角色: employeeQwenpaw（经网关，合法 JWT）")
    print(f"Token file: {TOKEN_FILE.name}  (value not printed)")

    async with open_session(GATEWAY_URL, headers) as session:
        tools = {t.name for t in (await session.list_tools()).tools}
        print(f"\n[List Tools] 可见 {len(tools)} 个工具:")
        for name in sorted(tools):
            print(f"  - {name}")
        if tools != EXPECTED_GATEWAY_TOOLS:
            print(f"\n[WARN] 预期 {sorted(EXPECTED_GATEWAY_TOOLS)}，实际 {sorted(tools)}")
            if not EXPECTED_GATEWAY_TOOLS.issubset(tools):
                return 1
        else:
            print("\n[OK] 三个 MCP 已聚合到单一入口")

        for tool, args in (
            ("forum_list_posts", {"limit": 3}),
            ("hr_get_employee", {}),
            ("finance_get_department_budget", {}),
        ):
            result = await session.call_tool(tool, arguments=args)
            print(f"  [OK] {tool}")
            preview = mask_secret(tool_text(result)).splitlines()[:2]
            for line in preview:
                print(f"       {line}")

    print("\n[OK] 一个地址 + 一个合法 Token 即可访问论坛/人事/财务")
    return 0


PHASES = {
    "open": phase_open,
    "bypass": phase_bypass,
    "no-token": phase_no_token,
    "forged": phase_forged,
    "valid": phase_valid,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Unified AgentGateway demo assertions")
    parser.add_argument("--phase", required=True, choices=sorted(PHASES))
    args = parser.parse_args()

    print("=" * 64)
    print(f"Unified gateway demo — phase {args.phase}")
    print("=" * 64)
    try:
        code = asyncio.run(PHASES[args.phase]())
    except AssertionError as exc:
        print(f"\n[FAIL] {exc}")
        code = 1
    except BaseException as exc:
        print(f"\n[FAIL] {exc}")
        code = 1
    sys.exit(code)


if __name__ == "__main__":
    main()
