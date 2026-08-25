"""MCP 人事服务 — 员工 PII（演示用）。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

COMMON = Path(__file__).resolve().parents[1] / "mcp-common"
if str(COMMON) not in sys.path:
    sys.path.insert(0, str(COMMON))

from gateway_auth import add_auth_args, create_mcp_server, resolve_gateway_token, run_mcp_http

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9001
DEFAULT_PATH = "/mcp"
DATA_FILE = Path(__file__).resolve().parent / "employees.json"


def load_employees() -> dict[str, dict]:
    if DATA_FILE.is_file():
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return {}


def save_employees(data: dict[str, dict]) -> None:
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def format_employee(employee_id: str, record: dict) -> str:
    return (
        f"employee_id={employee_id} | "
        f"name={record['name']} | "
        f"phone={record['phone']} | "
        f"id_card={record['id_card']}"
    )


def register_handlers(mcp) -> None:
    @mcp.tool()
    def get_employee(employee_id: str = "") -> str:
        """读取员工信息（姓名、电话、身份证号码）。不传 employee_id 时返回全部员工。"""
        employees = load_employees()
        if not employee_id or not employee_id.strip():
            if not employees:
                return "（暂无员工记录）"
            lines = [
                format_employee(emp_id, record)
                for emp_id, record in sorted(employees.items())
            ]
            return "\n".join(lines)
        emp_id = employee_id.strip()
        record = employees.get(emp_id)
        if record is None:
            return f"未找到员工: {emp_id}"
        return format_employee(emp_id, record)

    @mcp.tool()
    def update_employee(
        employee_id: str,
        name: str | None = None,
        phone: str | None = None,
        id_card: str | None = None,
    ) -> str:
        """修改员工信息（演示用敏感写操作）。"""
        employees = load_employees()
        if employee_id not in employees:
            return f"未找到员工: {employee_id}"
        record = employees[employee_id]
        if name is not None:
            record["name"] = name
        if phone is not None:
            record["phone"] = phone
        if id_card is not None:
            record["id_card"] = id_card
        employees[employee_id] = record
        save_employees(employees)
        return f"已更新员工 {employee_id}: {record}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="HR MCP Server")
    parser.add_argument("--host", default=os.getenv("MCP_HR_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.getenv("MCP_HR_PORT", str(DEFAULT_PORT))))
    parser.add_argument("--path", default=os.getenv("MCP_HR_PATH", DEFAULT_PATH))
    add_auth_args(parser, "HR_GATEWAY_TOKEN")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    mcp = create_mcp_server("HR MCP Server", args.host, args.port, args.path)
    register_handlers(mcp)
    url = f"http://{args.host}:{args.port}{args.path}"
    print("HR MCP Server (人事 / PII)")
    print(f"  URL: {url}")
    print("  工具: get_employee, update_employee")
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
