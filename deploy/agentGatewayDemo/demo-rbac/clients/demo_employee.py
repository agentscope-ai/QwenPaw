"""RBAC 演示 Client — employeeQwenpaw（换岗前管理员 / 换岗后网关降权）。"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URL = "http://localhost:3000/mcp"
TOKEN_FILE = ROOT / "jwt" / "employeeQwenpaw.key"
FORUM_READ_TOOL = "forum_list_posts"
FORUM_WRITE_TOOL = "forum_create_post"
SENSITIVE_TOOL = "hr_get_employee"
ADMIN_TOOLS = {
    FORUM_READ_TOOL,
    FORUM_WRITE_TOOL,
    "forum_delete_post",
    "hr_get_employee",
    "hr_update_employee",
}
DOWNGRADED_TOOLS = {FORUM_READ_TOOL, FORUM_WRITE_TOOL}


def read_token(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _is_gateway_block(exc: BaseException) -> bool:
    parts: list[str] = [str(exc)]
    if isinstance(exc, BaseExceptionGroup):
        parts.extend(str(e) for e in exc.exceptions)
    combined = " ".join(parts)
    return any(k in combined for k in ("Unknown tool", "400", "403", "401", "Forbidden"))


async def run(url: str, token_path: Path, phase: str) -> int:
    headers = {"Authorization": f"Bearer {read_token(token_path)}"}
    is_admin_phase = phase == "admin"
    expected_tools = ADMIN_TOOLS if is_admin_phase else DOWNGRADED_TOOLS

    print("=" * 64)
    if is_admin_phase:
        print("角色: employeeQwenpaw（换岗前 — 管理员 Token，网关阶段 A）")
    else:
        print("角色: employeeQwenpaw（换岗后 — 同一 Token，网关策略已降权）")
    print(f"Gateway: {url}")
    print("=" * 64)

    try:
        async with streamablehttp_client(url, headers=headers) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                print("\n[OK] JWT 认证通过，MCP 握手完成（Token 未更换）")

                tools = {t.name for t in (await session.list_tools()).tools}
                print(f"\n[List Tools] 可见 {len(tools)} 个工具:")
                for name in sorted(tools):
                    print(f"  - {name}")

                if tools == expected_tools:
                    print(f"\n[OK] RBAC 符合预期: {sorted(expected_tools)}")
                else:
                    print(f"\n[WARN] 预期 {sorted(expected_tools)}，实际 {sorted(tools)}")
                    if is_admin_phase:
                        print("  提示: 执行 restore-employee-admin.ps1 或 start-all.ps1 -Restart")

                print(f"\n[合法] 调用 {FORUM_READ_TOOL}")
                ok = await session.call_tool(FORUM_READ_TOOL, arguments={"limit": 5})
                print(ok.content[0].text if ok.content else ok)

                print(f"\n[合法] 调用 {FORUM_WRITE_TOOL}")
                post = await session.call_tool(
                    FORUM_WRITE_TOOL,
                    arguments={
                        "author": "employeeQwenpaw",
                        "title": "RBAC demo post",
                        "content": "Same token before/after gateway downgrade demo.",
                    },
                )
                print(post.content[0].text if post.content else post)

                if is_admin_phase:
                    print(f"\n[合法] 管理员权限调用 {SENSITIVE_TOOL}")
                    hr = await session.call_tool(SENSITIVE_TOOL, arguments={})
                    text = hr.content[0].text if hr.content else str(hr)
                    print(text[:400] + ("..." if len(text) > 400 else ""))
                    return 0

                print(f"\n[攻击] 换岗后仍用原管理员 Token 窃取 PII → {SENSITIVE_TOOL}")
                print("  （员工本地备份的 Token 未失效，但网关策略已收紧）")
                blocked = False
                try:
                    await session.call_tool(SENSITIVE_TOOL, arguments={})
                    print("  [FAIL] 未被拦截，敏感工具返回了数据")
                    return 1
                except BaseException as exc:
                    if _is_gateway_block(exc):
                        blocked = True
                        print("  [BLOCKED] 网关拦截（HTTP/JSON-RPC 拒绝）")
                        print("  拦截原因: 网关按 jwt.sub 降权 — employeeQwenpaw 无 hr 工具权限")
                    else:
                        print(f"  [ERROR] 意外失败: {exc}")
                        return 1

                return 0 if blocked else 1
    except BaseException as exc:
        if not is_admin_phase and _is_gateway_block(exc):
            print("\n[BLOCKED] 网关拦截（会话层）")
            return 0
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--token", type=Path, default=TOKEN_FILE)
    parser.add_argument(
        "--phase",
        choices=("admin", "downgraded"),
        default="downgraded",
        help="admin=换岗前(5 tools); downgraded=换岗后(2 tools + HR attack)",
    )
    args = parser.parse_args()
    if not args.token.is_file():
        print(f"Token 不存在: {args.token}", file=sys.stderr)
        sys.exit(2)
    sys.exit(asyncio.run(run(args.url, args.token, args.phase)))


if __name__ == "__main__":
    main()
