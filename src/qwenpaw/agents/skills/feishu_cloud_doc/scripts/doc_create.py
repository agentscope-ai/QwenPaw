#!/usr/bin/env python3
"""Create a new Feishu document.

Usage:
    python scripts/doc_create.py --title "Meeting Notes"
    python scripts/doc_create.py --title "Notes" --folder FOLDER_TOKEN

Output: JSON with document_id, url, etc.
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx

from feishu_auth import auth_headers, get_base_url


def create_document(title: str, folder_token: str = "") -> dict:
    base = get_base_url()
    url = f"{base}/open-apis/docx/v1/documents"
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

    doc = data.get("data", {}).get("document", {})
    document_id = doc.get("document_id", "")
    doc_url = doc.get("url", "")
    if not doc_url and document_id:
        domain = "larksuite.com" if "larksuite" in base else "feishu.cn"
        doc_url = f"https://{domain}/docx/{document_id}"

    return {
        "success": True,
        "document_id": document_id,
        "title": doc.get("title", title),
        "url": doc_url,
        "revision_id": doc.get("revision_id", 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a Feishu document")
    parser.add_argument("--title", required=True, help="Document title")
    parser.add_argument("--folder", default="", help="Folder token (optional)")
    args = parser.parse_args()

    result = create_document(args.title, args.folder)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()
