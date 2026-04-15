#!/usr/bin/env python3
"""Create and manage Feishu Bitable (multi-dimensional tables).

Usage:
    python scripts/bitable_manage.py create --name "Tracker"
    python scripts/bitable_manage.py add-table --app-token TOKEN --table-name "Tasks"
    python scripts/bitable_manage.py list-tables --app-token TOKEN
    python scripts/bitable_manage.py list-fields --app-token TOKEN --table-id TABLE_ID
    python scripts/bitable_manage.py add-field --app-token TOKEN --table-id TID --field-name "Status" --field-type 3

Output: JSON with operation result.
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx

from feishu_auth import auth_headers, get_base_url


def create_bitable(name: str, folder_token: str = "") -> dict:
    """Create a new Bitable app."""
    base = get_base_url()
    url = f"{base}/open-apis/bitable/v1/apps"
    body: dict = {"name": name}
    if folder_token:
        body["folder_token"] = folder_token

    resp = httpx.post(url, headers=auth_headers(), json=body, timeout=30)
    data = resp.json()

    if data.get("code") != 0:
        return {
            "success": False,
            "error": data.get("msg", "unknown error"),
            "code": data.get("code"),
        }

    app = data.get("data", {}).get("app", {})
    app_token = app.get("app_token", "")
    app_url = app.get("url", "")
    if not app_url and app_token:
        domain = "larksuite.com" if "larksuite" in base else "feishu.cn"
        app_url = f"https://{domain}/base/{app_token}"

    return {
        "success": True,
        "app_token": app_token,
        "name": app.get("name", name),
        "url": app_url,
    }


def add_table(app_token: str, table_name: str) -> dict:
    """Add a data table to a Bitable app."""
    base = get_base_url()
    url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables"
    body = {"table": {"name": table_name}}

    resp = httpx.post(url, headers=auth_headers(), json=body, timeout=30)
    data = resp.json()

    if data.get("code") != 0:
        return {
            "success": False,
            "error": data.get("msg", "unknown error"),
            "code": data.get("code"),
        }

    return {
        "success": True,
        "app_token": app_token,
        "table_id": data.get("data", {}).get("table_id", ""),
    }


def list_tables(app_token: str) -> dict:
    """List all tables in a Bitable app."""
    base = get_base_url()
    url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables"

    resp = httpx.get(url, headers=auth_headers(), timeout=30)
    data = resp.json()

    if data.get("code") != 0:
        return {
            "success": False,
            "error": data.get("msg", "unknown error"),
            "code": data.get("code"),
        }

    items = data.get("data", {}).get("items", [])
    return {
        "success": True,
        "app_token": app_token,
        "table_count": len(items),
        "tables": [
            {
                "table_id": t.get("table_id", ""),
                "name": t.get("name", ""),
                "revision": t.get("revision", 0),
            }
            for t in items
        ],
    }


def list_fields(app_token: str, table_id: str) -> dict:
    """List all fields in a table."""
    base = get_base_url()
    url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields"

    all_fields = []
    page_token = ""
    while True:
        params: dict = {"page_size": 100}
        if page_token:
            params["page_token"] = page_token

        resp = httpx.get(url, headers=auth_headers(), params=params, timeout=30)
        data = resp.json()

        if data.get("code") != 0:
            return {
                "success": False,
                "error": data.get("msg", "unknown error"),
                "code": data.get("code"),
            }

        items = data.get("data", {}).get("items", [])
        all_fields.extend(items)

        page_token = data.get("data", {}).get("page_token", "")
        has_more = data.get("data", {}).get("has_more", False)
        if not has_more or not page_token:
            break

    return {
        "success": True,
        "app_token": app_token,
        "table_id": table_id,
        "field_count": len(all_fields),
        "fields": [
            {
                "field_id": f.get("field_id", ""),
                "field_name": f.get("field_name", ""),
                "type": f.get("type", 0),
                "is_primary": f.get("is_primary", False),
            }
            for f in all_fields
        ],
    }


def add_field(
    app_token: str,
    table_id: str,
    field_name: str,
    field_type: int,
) -> dict:
    """Add a field to a table."""
    base = get_base_url()
    url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields"
    body = {"field_name": field_name, "type": field_type}

    resp = httpx.post(url, headers=auth_headers(), json=body, timeout=30)
    data = resp.json()

    if data.get("code") != 0:
        return {
            "success": False,
            "error": data.get("msg", "unknown error"),
            "code": data.get("code"),
        }

    field = data.get("data", {}).get("field", {})
    return {
        "success": True,
        "app_token": app_token,
        "table_id": table_id,
        "field_id": field.get("field_id", ""),
        "field_name": field.get("field_name", field_name),
        "type": field.get("type", field_type),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage Feishu Bitable")
    sub = parser.add_subparsers(dest="command", required=True)

    create_p = sub.add_parser("create", help="Create a new Bitable")
    create_p.add_argument("--name", required=True, help="Bitable name")
    create_p.add_argument("--folder", default="", help="Folder token")

    add_table_p = sub.add_parser("add-table", help="Add a table")
    add_table_p.add_argument("--app-token", required=True)
    add_table_p.add_argument("--table-name", required=True)

    list_tables_p = sub.add_parser("list-tables", help="List tables")
    list_tables_p.add_argument("--app-token", required=True)

    list_fields_p = sub.add_parser("list-fields", help="List fields")
    list_fields_p.add_argument("--app-token", required=True)
    list_fields_p.add_argument("--table-id", required=True)

    add_field_p = sub.add_parser("add-field", help="Add a field")
    add_field_p.add_argument("--app-token", required=True)
    add_field_p.add_argument("--table-id", required=True)
    add_field_p.add_argument("--field-name", required=True)
    add_field_p.add_argument("--field-type", type=int, required=True)

    args = parser.parse_args()

    if args.command == "create":
        result = create_bitable(args.name, args.folder)
    elif args.command == "add-table":
        result = add_table(args.app_token, args.table_name)
    elif args.command == "list-tables":
        result = list_tables(args.app_token)
    elif args.command == "list-fields":
        result = list_fields(args.app_token, args.table_id)
    elif args.command == "add-field":
        result = add_field(args.app_token, args.table_id, args.field_name, args.field_type)
    else:
        result = {"success": False, "error": f"Unknown command: {args.command}"}

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()
