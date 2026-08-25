"""MCP 财务服务 — 部门预算与报销（演示用虚构数据）。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

COMMON = Path(__file__).resolve().parents[1] / "mcp-common"
if str(COMMON) not in sys.path:
    sys.path.insert(0, str(COMMON))

from gateway_auth import add_auth_args, create_mcp_server, resolve_gateway_token, run_mcp_http

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9003
DEFAULT_PATH = "/mcp"
BUDGET_FILE = Path(__file__).resolve().parent / "budgets.json"
EXPENSE_FILE = Path(__file__).resolve().parent / "expenses.json"


def load_budgets() -> dict[str, dict]:
    if BUDGET_FILE.is_file():
        return json.loads(BUDGET_FILE.read_text(encoding="utf-8"))
    return {}


def load_expenses() -> list[dict]:
    if EXPENSE_FILE.is_file():
        return json.loads(EXPENSE_FILE.read_text(encoding="utf-8"))
    return []


def save_expenses(items: list[dict]) -> None:
    EXPENSE_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def format_budget(dept_id: str, record: dict) -> str:
    remaining = record["budget_cny"] - record["spent_cny"]
    return (
        f"department_id={dept_id} | "
        f"name={record['name']} | "
        f"budget_cny={record['budget_cny']} | "
        f"spent_cny={record['spent_cny']} | "
        f"remaining_cny={remaining}"
    )


def register_handlers(mcp) -> None:
    @mcp.tool()
    def get_department_budget(department_id: str = "") -> str:
        """读取部门年度预算（演示用虚构数据）。不传 department_id 时返回全部部门。"""
        budgets = load_budgets()
        if not department_id or not department_id.strip():
            if not budgets:
                return "（暂无预算记录）"
            return "\n".join(
                format_budget(dept_id, record)
                for dept_id, record in sorted(budgets.items())
            )
        dept_id = department_id.strip()
        record = budgets.get(dept_id)
        if record is None:
            return f"未找到部门: {dept_id}"
        return format_budget(dept_id, record)

    @mcp.tool()
    def submit_expense(department_id: str, amount_cny: int, purpose: str) -> str:
        """提交报销单（演示用写操作，不校验真实审批）。"""
        budgets = load_budgets()
        if department_id not in budgets:
            return f"未找到部门: {department_id}"
        items = load_expenses()
        expense_id = f"X{len(items) + 1:04d}"
        items.append(
            {
                "id": expense_id,
                "department_id": department_id,
                "amount_cny": amount_cny,
                "purpose": purpose,
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }
        )
        save_expenses(items)
        return (
            f"已提交报销 id={expense_id} department={department_id} "
            f"amount_cny={amount_cny} purpose={purpose}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Finance MCP Server")
    parser.add_argument("--host", default=os.getenv("MCP_FINANCE_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.getenv("MCP_FINANCE_PORT", str(DEFAULT_PORT))))
    parser.add_argument("--path", default=os.getenv("MCP_FINANCE_PATH", DEFAULT_PATH))
    add_auth_args(parser, "FINANCE_GATEWAY_TOKEN")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    mcp = create_mcp_server("Finance MCP Server", args.host, args.port, args.path)
    register_handlers(mcp)
    url = f"http://{args.host}:{args.port}{args.path}"
    print("Finance MCP Server (财务 / 预算)")
    print(f"  URL: {url}")
    print("  工具: get_department_budget, submit_expense")
    run_mcp_http(
        mcp,
        host=args.host,
        port=args.port,
        path=args.path,
        auth_mode=args.auth_mode,
        gateway_token=resolve_gateway_token(args.gateway_token_env),
        header_name=args.gateway_token_header,
    )


if __name__ == "__main__":
    main()
