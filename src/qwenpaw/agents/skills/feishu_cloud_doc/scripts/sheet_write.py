#!/usr/bin/env python3
"""Write data to a Feishu spreadsheet.

Usage:
    python scripts/write_sheet.py --token TOKEN --range "Sheet1!A1:B2" --values-json '[["Name","Score"],["Alice",95]]'
    python scripts/write_sheet.py --token TOKEN --range "Sheet1!A1" --append --values-json '[["Bob",88]]'
    python scripts/write_sheet.py --token TOKEN --add-sheet --sheet-title "New Sheet"

Output: JSON with operation result.
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx

from feishu_auth import auth_headers, get_base_url


def write_range(token: str, range_str: str, values: list[list]) -> dict:
    """Write values to a specific range."""
    base = get_base_url()
    url = f"{base}/open-apis/sheets/v2/spreadsheets/{token}/values"
    body = {
        "valueRange": {
            "range": range_str,
            "values": values,
        }
    }
    resp = httpx.put(url, headers=auth_headers(), json=body, timeout=30)
    data = resp.json()

    if data.get("code") != 0:
        return {
            "success": False,
            "error": data.get("msg", "unknown error"),
            "code": data.get("code"),
        }

    return {
        "success": True,
        "spreadsheet_token": token,
        "range": range_str,
        "updated_cells": data.get("data", {}).get("updatedCells", 0),
        "updated_rows": data.get("data", {}).get("updatedRows", 0),
        "updated_columns": data.get("data", {}).get("updatedColumns", 0),
    }


def append_data(token: str, range_str: str, values: list[list]) -> dict:
    """Append values after the last row in a range."""
    base = get_base_url()
    url = f"{base}/open-apis/sheets/v2/spreadsheets/{token}/values_append"
    params = {"insertDataOption": "INSERT_ROWS"}
    body = {
        "valueRange": {
            "range": range_str,
            "values": values,
        }
    }
    resp = httpx.post(
        url, headers=auth_headers(), params=params, json=body, timeout=30
    )
    data = resp.json()

    if data.get("code") != 0:
        return {
            "success": False,
            "error": data.get("msg", "unknown error"),
            "code": data.get("code"),
        }

    updates = data.get("data", {}).get("updates", {})
    return {
        "success": True,
        "spreadsheet_token": token,
        "updated_range": updates.get("updatedRange", ""),
        "updated_rows": updates.get("updatedRows", 0),
        "updated_cells": updates.get("updatedCells", 0),
    }


def add_sheet(token: str, title: str, index: int = -1) -> dict:
    """Add a new worksheet to the spreadsheet."""
    base = get_base_url()
    url = f"{base}/open-apis/sheets/v2/spreadsheets/{token}/sheets_batch_update"
    add_req: dict = {"properties": {"title": title}}
    if index >= 0:
        add_req["properties"]["index"] = index
    body = {"requests": [{"addSheet": add_req}]}

    resp = httpx.post(url, headers=auth_headers(), json=body, timeout=30)
    data = resp.json()

    if data.get("code") != 0:
        return {
            "success": False,
            "error": data.get("msg", "unknown error"),
            "code": data.get("code"),
        }

    replies = data.get("data", {}).get("replies", [])
    sheet_info = replies[0].get("addSheet", {}).get("properties", {}) if replies else {}
    return {
        "success": True,
        "spreadsheet_token": token,
        "sheet_id": sheet_info.get("sheetId", ""),
        "title": sheet_info.get("title", title),
        "index": sheet_info.get("index", 0),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Write to a Feishu spreadsheet")
    parser.add_argument("--token", required=True, help="Spreadsheet token")
    parser.add_argument("--range", default="", help="Cell range (e.g. Sheet1!A1:B2)")
    parser.add_argument("--values-json", default="", help="JSON 2D array of values")
    parser.add_argument("--values-file", default="", help="Path to JSON file with values")
    parser.add_argument("--append", action="store_true", help="Append after last row instead of overwrite")
    parser.add_argument("--add-sheet", action="store_true", help="Add a new worksheet")
    parser.add_argument("--sheet-title", default="", help="Title for new worksheet")
    parser.add_argument("--sheet-index", type=int, default=-1, help="Index for new worksheet")
    args = parser.parse_args()

    if args.add_sheet:
        if not args.sheet_title:
            print(json.dumps({"success": False, "error": "--sheet-title required with --add-sheet"}))
            sys.exit(1)
        result = add_sheet(args.token, args.sheet_title, args.sheet_index)
    else:
        if not args.range:
            print(json.dumps({"success": False, "error": "--range required for read/write"}))
            sys.exit(1)

        values: list[list] = []
        if args.values_file:
            with open(args.values_file, encoding="utf-8") as fh:
                values = json.load(fh)
        elif args.values_json:
            values = json.loads(args.values_json)
        else:
            print(json.dumps({"success": False, "error": "Provide --values-json or --values-file"}))
            sys.exit(1)

        if args.append:
            result = append_data(args.token, args.range, values)
        else:
            result = write_range(args.token, args.range, values)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()
