#!/usr/bin/env python3
"""Read and write records in a Feishu Bitable table.

Usage:
    python scripts/records.py list --app-token TOKEN --table-id TABLE_ID [--page-size 20]
    python scripts/records.py get --app-token TOKEN --table-id TABLE_ID --record-id REC_ID
    python scripts/records.py create --app-token TOKEN --table-id TABLE_ID --fields-json '{"fldXXX": "value"}'
    python scripts/records.py batch-create --app-token TOKEN --table-id TABLE_ID --records-json '[{"fields": {...}}, ...]'
    python scripts/records.py update --app-token TOKEN --table-id TABLE_ID --record-id REC_ID --fields-json '{"fldXXX": "new"}'
    python scripts/records.py delete --app-token TOKEN --table-id TABLE_ID --record-id REC_ID

Output: JSON with operation result.
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx

from feishu_auth import auth_headers, get_base_url


def list_records(
    app_token: str,
    table_id: str,
    page_size: int = 20,
    page_token: str = "",
    filter_str: str = "",
    sort_str: str = "",
) -> dict:
    """List records in a table with pagination."""
    base = get_base_url()
    url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    params: dict = {"page_size": min(page_size, 500)}
    if page_token:
        params["page_token"] = page_token
    if filter_str:
        params["filter"] = filter_str
    if sort_str:
        params["sort"] = sort_str

    resp = httpx.get(url, headers=auth_headers(), params=params, timeout=30)
    data = resp.json()

    if data.get("code") != 0:
        return {
            "success": False,
            "error": data.get("msg", "unknown error"),
            "code": data.get("code"),
        }

    result_data = data.get("data", {})
    items = result_data.get("items", [])
    return {
        "success": True,
        "app_token": app_token,
        "table_id": table_id,
        "total": result_data.get("total", len(items)),
        "has_more": result_data.get("has_more", False),
        "page_token": result_data.get("page_token", ""),
        "record_count": len(items),
        "records": [
            {
                "record_id": r.get("record_id", ""),
                "fields": r.get("fields", {}),
            }
            for r in items
        ],
    }


def get_record(app_token: str, table_id: str, record_id: str) -> dict:
    """Get a single record by ID."""
    base = get_base_url()
    url = (
        f"{base}/open-apis/bitable/v1/apps/{app_token}"
        f"/tables/{table_id}/records/{record_id}"
    )
    resp = httpx.get(url, headers=auth_headers(), timeout=30)
    data = resp.json()

    if data.get("code") != 0:
        return {
            "success": False,
            "error": data.get("msg", "unknown error"),
            "code": data.get("code"),
        }

    record = data.get("data", {}).get("record", {})
    return {
        "success": True,
        "record_id": record.get("record_id", record_id),
        "fields": record.get("fields", {}),
    }


def create_record(app_token: str, table_id: str, fields: dict) -> dict:
    """Create a single record."""
    base = get_base_url()
    url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    body = {"fields": fields}

    resp = httpx.post(url, headers=auth_headers(), json=body, timeout=30)
    data = resp.json()

    if data.get("code") != 0:
        return {
            "success": False,
            "error": data.get("msg", "unknown error"),
            "code": data.get("code"),
        }

    record = data.get("data", {}).get("record", {})
    return {
        "success": True,
        "record_id": record.get("record_id", ""),
        "fields": record.get("fields", {}),
    }


def batch_create_records(
    app_token: str, table_id: str, records: list[dict]
) -> dict:
    """Batch create records (max 500 per call)."""
    base = get_base_url()
    url = (
        f"{base}/open-apis/bitable/v1/apps/{app_token}"
        f"/tables/{table_id}/records/batch_create"
    )
    body = {"records": records}

    resp = httpx.post(url, headers=auth_headers(), json=body, timeout=60)
    data = resp.json()

    if data.get("code") != 0:
        return {
            "success": False,
            "error": data.get("msg", "unknown error"),
            "code": data.get("code"),
        }

    created = data.get("data", {}).get("records", [])
    return {
        "success": True,
        "created_count": len(created),
        "record_ids": [r.get("record_id", "") for r in created],
    }


def update_record(
    app_token: str, table_id: str, record_id: str, fields: dict
) -> dict:
    """Update a single record."""
    base = get_base_url()
    url = (
        f"{base}/open-apis/bitable/v1/apps/{app_token}"
        f"/tables/{table_id}/records/{record_id}"
    )
    body = {"fields": fields}

    resp = httpx.put(url, headers=auth_headers(), json=body, timeout=30)
    data = resp.json()

    if data.get("code") != 0:
        return {
            "success": False,
            "error": data.get("msg", "unknown error"),
            "code": data.get("code"),
        }

    record = data.get("data", {}).get("record", {})
    return {
        "success": True,
        "record_id": record.get("record_id", record_id),
        "fields": record.get("fields", {}),
    }


def delete_record(app_token: str, table_id: str, record_id: str) -> dict:
    """Delete a single record."""
    base = get_base_url()
    url = (
        f"{base}/open-apis/bitable/v1/apps/{app_token}"
        f"/tables/{table_id}/records/{record_id}"
    )
    resp = httpx.delete(url, headers=auth_headers(), timeout=30)
    data = resp.json()

    if data.get("code") != 0:
        return {
            "success": False,
            "error": data.get("msg", "unknown error"),
            "code": data.get("code"),
        }

    return {
        "success": True,
        "deleted": True,
        "record_id": record_id,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage Bitable records")
    sub = parser.add_subparsers(dest="command", required=True)

    list_p = sub.add_parser("list", help="List records")
    list_p.add_argument("--app-token", required=True)
    list_p.add_argument("--table-id", required=True)
    list_p.add_argument("--page-size", type=int, default=20)
    list_p.add_argument("--page-token", default="")
    list_p.add_argument("--filter", default="", dest="filter_str")
    list_p.add_argument("--sort", default="", dest="sort_str")

    get_p = sub.add_parser("get", help="Get a record")
    get_p.add_argument("--app-token", required=True)
    get_p.add_argument("--table-id", required=True)
    get_p.add_argument("--record-id", required=True)

    create_p = sub.add_parser("create", help="Create a record")
    create_p.add_argument("--app-token", required=True)
    create_p.add_argument("--table-id", required=True)
    create_p.add_argument("--fields-json", required=True)

    batch_p = sub.add_parser("batch-create", help="Batch create records")
    batch_p.add_argument("--app-token", required=True)
    batch_p.add_argument("--table-id", required=True)
    batch_p.add_argument("--records-json", default="")
    batch_p.add_argument("--records-file", default="")

    update_p = sub.add_parser("update", help="Update a record")
    update_p.add_argument("--app-token", required=True)
    update_p.add_argument("--table-id", required=True)
    update_p.add_argument("--record-id", required=True)
    update_p.add_argument("--fields-json", required=True)

    delete_p = sub.add_parser("delete", help="Delete a record")
    delete_p.add_argument("--app-token", required=True)
    delete_p.add_argument("--table-id", required=True)
    delete_p.add_argument("--record-id", required=True)

    args = parser.parse_args()

    if args.command == "list":
        result = list_records(
            args.app_token,
            args.table_id,
            args.page_size,
            args.page_token,
            args.filter_str,
            args.sort_str,
        )
    elif args.command == "get":
        result = get_record(args.app_token, args.table_id, args.record_id)
    elif args.command == "create":
        fields = json.loads(args.fields_json)
        result = create_record(args.app_token, args.table_id, fields)
    elif args.command == "batch-create":
        if args.records_file:
            with open(args.records_file, encoding="utf-8") as fh:
                records = json.load(fh)
        elif args.records_json:
            records = json.loads(args.records_json)
        else:
            print(json.dumps({"success": False, "error": "Provide --records-json or --records-file"}))
            sys.exit(1)
        result = batch_create_records(args.app_token, args.table_id, records)
    elif args.command == "update":
        fields = json.loads(args.fields_json)
        result = update_record(args.app_token, args.table_id, args.record_id, fields)
    elif args.command == "delete":
        result = delete_record(args.app_token, args.table_id, args.record_id)
    else:
        result = {"success": False, "error": f"Unknown command: {args.command}"}

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()
