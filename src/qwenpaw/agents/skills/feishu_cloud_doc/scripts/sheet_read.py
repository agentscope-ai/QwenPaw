#!/usr/bin/env python3
"""Read data from a Feishu spreadsheet.

Usage:
    python scripts/read_sheet.py --token TOKEN --range "Sheet1!A1:D10"
    python scripts/read_sheet.py --token TOKEN --info
    python scripts/read_sheet.py --token TOKEN --list-sheets

Output: JSON with cell values or sheet metadata.
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx

from feishu_auth import auth_headers, get_base_url


def get_spreadsheet_info(token: str) -> dict:
    """Get spreadsheet metadata."""
    base = get_base_url()
    url = f"{base}/open-apis/sheets/v3/spreadsheets/{token}"
    resp = httpx.get(url, headers=auth_headers(), timeout=30)
    data = resp.json()

    if data.get("code") != 0:
        return {
            "success": False,
            "error": data.get("msg", "unknown error"),
            "code": data.get("code"),
        }

    sheet = data.get("data", {}).get("spreadsheet", {})
    return {
        "success": True,
        "spreadsheet_token": sheet.get("spreadsheet_token", token),
        "title": sheet.get("title", ""),
    }


def list_sheets(token: str) -> dict:
    """List all worksheets in a spreadsheet."""
    base = get_base_url()
    url = f"{base}/open-apis/sheets/v3/spreadsheets/{token}/sheets/query"
    resp = httpx.get(url, headers=auth_headers(), timeout=30)
    data = resp.json()

    if data.get("code") != 0:
        return {
            "success": False,
            "error": data.get("msg", "unknown error"),
            "code": data.get("code"),
        }

    sheets = data.get("data", {}).get("sheets", [])
    return {
        "success": True,
        "spreadsheet_token": token,
        "sheet_count": len(sheets),
        "sheets": [
            {
                "sheet_id": s.get("sheet_id", ""),
                "title": s.get("title", ""),
                "index": s.get("index", 0),
                "row_count": s.get("grid_properties", {}).get("row_count", 0),
                "column_count": s.get("grid_properties", {}).get("column_count", 0),
            }
            for s in sheets
        ],
    }


def read_range(token: str, range_str: str) -> dict:
    """Read a range of cells from a spreadsheet.

    Range format: "SheetName!A1:D10" or "sheet_id!A1:D10"
    """
    base = get_base_url()
    url = f"{base}/open-apis/sheets/v2/spreadsheets/{token}/values/{range_str}"
    params = {
        "valueRenderOption": "ToString",
        "dateTimeRenderOption": "FormattedString",
    }
    resp = httpx.get(url, headers=auth_headers(), params=params, timeout=30)
    data = resp.json()

    if data.get("code") != 0:
        return {
            "success": False,
            "error": data.get("msg", "unknown error"),
            "code": data.get("code"),
        }

    value_range = data.get("data", {}).get("valueRange", {})
    return {
        "success": True,
        "spreadsheet_token": token,
        "range": value_range.get("range", range_str),
        "revision": data.get("data", {}).get("revision", 0),
        "values": value_range.get("values", []),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Read a Feishu spreadsheet")
    parser.add_argument("--token", required=True, help="Spreadsheet token")
    parser.add_argument("--range", default="", help="Cell range (e.g. Sheet1!A1:D10)")
    parser.add_argument("--info", action="store_true", help="Get spreadsheet metadata")
    parser.add_argument("--list-sheets", action="store_true", help="List all worksheets")
    args = parser.parse_args()

    if args.info:
        result = get_spreadsheet_info(args.token)
    elif args.list_sheets:
        result = list_sheets(args.token)
    elif args.range:
        result = read_range(args.token, args.range)
    else:
        print(json.dumps({"success": False, "error": "Specify --range, --info, or --list-sheets"}))
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()
