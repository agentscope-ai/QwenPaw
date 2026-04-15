#!/usr/bin/env python3
"""Create a new Feishu spreadsheet.

Usage:
    python scripts/sheet_create.py --title "Sales Data"
    python scripts/sheet_create.py --title "Data" --folder FOLDER_TOKEN

Output: JSON with spreadsheet_token, url, etc.
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx

from feishu_auth import auth_headers, get_base_url


def create_spreadsheet(title: str, folder_token: str = "") -> dict:
    base = get_base_url()
    url = f"{base}/open-apis/sheets/v3/spreadsheets"
    body: dict = {"title": title}
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

    sheet = data.get("data", {}).get("spreadsheet", {})
    token = sheet.get("spreadsheet_token", "")
    sheet_url = sheet.get("url", "")
    if not sheet_url and token:
        domain = "larksuite.com" if "larksuite" in base else "feishu.cn"
        sheet_url = f"https://{domain}/sheets/{token}"

    return {
        "success": True,
        "spreadsheet_token": token,
        "title": sheet.get("title", title),
        "url": sheet_url,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a Feishu spreadsheet")
    parser.add_argument("--title", required=True, help="Spreadsheet title")
    parser.add_argument("--folder", default="", help="Folder token (optional)")
    args = parser.parse_args()

    result = create_spreadsheet(args.title, args.folder)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()
