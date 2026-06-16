"""演示脚本 — 依次调用 forum_list_posts 与 hr_get_employee（employeeQwenpaw Token）。

阶段 A（agentgateway-rbac.yaml）：两次调用均成功。
阶段 B（downgrade-employee.ps1 后）：forum 成功，hr 被网关拒绝并写入错误日志。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URL = "http://localhost:3000/mcp"
TOKEN_FILE = ROOT / "jwt" / "employeeQwenpaw.key"
FORUM_TOOL = "forum_list_posts"
HR_TOOL = "hr_get_employee"

# AgentGateway 对 DELETE 会话返回 202，mcp 库会误报 "Session termination failed: 202"。
# 关闭时 SSE 流与客户端竞态也会打出 ClosedResourceError 堆栈——均在业务成功后发生，可忽略。
_SUPPRESS_MCP_TRANSPORT_NOISE = True


def _configure_logging() -> None:
    if not _SUPPRESS_MCP_TRANSPORT_NOISE:
        return
    for name in ("mcp", "mcp.client", "mcp.client.streamable_http"):
        logging.getLogger(name).setLevel(logging.CRITICAL)


def read_token(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _flatten_exceptions(exc: BaseException) -> list[BaseException]:
    if isinstance(exc, BaseExceptionGroup):
        return list(exc.exceptions)
    return [exc]


def _is_gateway_block(exc: BaseException) -> bool:
    parts = [str(exc)]
    for sub in _flatten_exceptions(exc):
        parts.append(str(sub))
    combined = " ".join(parts)
    return any(k in combined for k in ("Unknown tool", "400", "403", "401", "Forbidden"))


def _tool_result_text(result) -> str:
    if result.content:
        parts = []
        for block in result.content:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
            else:
                parts.append(str(block))
        return "\n".join(parts) if parts else str(result)
    return str(result)


def _print_section(title: str) -> None:
    print()
    print("-" * 64)
    print(title)
    print("-" * 64)


async def _call_one_tool(
    url: str,
    headers: dict[str, str],
    tool_name: str,
    arguments: dict,
) -> object:
    """单次短连接调用一个工具，避免长会话关闭时的 SSE 竞态噪声。"""
    timeout = httpx.Timeout(connect=30.0, read=120.0, write=30.0, pool=30.0)
    async with httpx.AsyncClient(headers=headers, timeout=timeout) as http_client:
        async with streamable_http_client(
            url,
            http_client=http_client,
            terminate_on_close=False,
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await session.call_tool(tool_name, arguments=arguments)


async def run(url: str, token_path: Path, forum_limit: int) -> int:
    _configure_logging()

    token = read_token(token_path)
    headers = {"Authorization": f"Bearer {token}"}

    print("=" * 64)
    print("employeeQwenpaw — forum_list_posts + hr_get_employee")
    print(f"Gateway : {url}")
    print(f"Token   : {token_path.name}（演示期间不更换）")
    print("=" * 64)

    forum_ok = False
    hr_ok = False
    hr_blocked = False

    _print_section(f"1/2 调用 {FORUM_TOOL}")
    try:
        forum_result = await _call_one_tool(
            url,
            headers,
            FORUM_TOOL,
            {"limit": forum_limit},
        )
        forum_ok = True
        print("[OK] 调用成功")
        print(_tool_result_text(forum_result))
    except BaseException as exc:
        print("[FAIL] 调用失败")
        for sub in _flatten_exceptions(exc):
            print(f"  {sub}")
        return 1

    _print_section(f"2/2 调用 {HR_TOOL}")
    try:
        hr_result = await _call_one_tool(url, headers, HR_TOOL, {})
        hr_ok = True
        print("[OK] 调用成功（阶段 A 预期）")
        print(_tool_result_text(hr_result))
    except BaseException as exc:
        if _is_gateway_block(exc):
            hr_blocked = True
            print("[BLOCKED] 网关拒绝（阶段 B 预期）")
            for sub in _flatten_exceptions(exc):
                print(f"  {sub}")
            print("\n说明: 同一 Token 在网关降权后无法访问 HR；")
            print("      AgentGateway 会记录 error 日志，watcher 可上报 Security Center。")
        else:
            print("[ERROR] 意外失败")
            for sub in _flatten_exceptions(exc):
                print(f"  {sub}")
            return 1

    print()
    print("=" * 64)
    print("结果摘要")
    print(f"  {FORUM_TOOL}: {'成功' if forum_ok else '失败'}")
    if hr_ok:
        print(f"  {HR_TOOL}: 成功（当前为网关阶段 A）")
        return 0
    if hr_blocked:
        print(f"  {HR_TOOL}: 被拒绝（当前为网关阶段 B）")
        return 0
    print(f"  {HR_TOOL}: 失败")
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Call forum_list_posts then hr_get_employee with employeeQwenpaw token.",
    )
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--token", type=Path, default=TOKEN_FILE)
    parser.add_argument("--limit", type=int, default=5, help="forum_list_posts limit")
    args = parser.parse_args()

    if not args.token.is_file():
        print(f"Token 不存在: {args.token}", file=sys.stderr)
        sys.exit(2)

    sys.exit(asyncio.run(run(args.url, args.token, args.limit)))


if __name__ == "__main__":
    main()
