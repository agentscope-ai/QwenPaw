#!/usr/bin/env python3
"""Read a Feishu document's content.

Usage:
    python scripts/read_doc.py --doc-id DOC_ID [--format raw|blocks]

Output: JSON with document content.
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx

from feishu_auth import auth_headers, get_base_url


def get_raw_content(document_id: str) -> dict:
    """Get the plain-text content of a document."""
    base = get_base_url()
    url = f"{base}/open-apis/docx/v1/documents/{document_id}/raw_content"
    resp = httpx.get(url, headers=auth_headers(), timeout=30)
    data = resp.json()

    if data.get("code") != 0:
        return {
            "success": False,
            "error": data.get("msg", "unknown error"),
            "code": data.get("code"),
        }

    return {
        "success": True,
        "document_id": document_id,
        "content": data.get("data", {}).get("content", ""),
    }


def get_blocks(document_id: str) -> dict:
    """Get the block tree of a document."""
    base = get_base_url()
    url = f"{base}/open-apis/docx/v1/documents/{document_id}/blocks"
    all_blocks = []
    page_token = ""

    while True:
        params: dict = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token

        resp = httpx.get(
            url, headers=auth_headers(), params=params, timeout=30
        )
        data = resp.json()

        if data.get("code") != 0:
            return {
                "success": False,
                "error": data.get("msg", "unknown error"),
                "code": data.get("code"),
            }

        items = data.get("data", {}).get("items", [])
        all_blocks.extend(items)

        page_token = data.get("data", {}).get("page_token", "")
        has_more = data.get("data", {}).get("has_more", False)
        if not has_more or not page_token:
            break

    return {
        "success": True,
        "document_id": document_id,
        "block_count": len(all_blocks),
        "blocks": all_blocks,
    }


def get_document_info(document_id: str) -> dict:
    """Get document metadata (title, revision, etc.)."""
    base = get_base_url()
    url = f"{base}/open-apis/docx/v1/documents/{document_id}"
    resp = httpx.get(url, headers=auth_headers(), timeout=30)
    data = resp.json()

    if data.get("code") != 0:
        return {
            "success": False,
            "error": data.get("msg", "unknown error"),
            "code": data.get("code"),
        }

    doc = data.get("data", {}).get("document", {})
    return {
        "success": True,
        "document_id": doc.get("document_id", document_id),
        "title": doc.get("title", ""),
        "revision_id": doc.get("revision_id", 0),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Read a Feishu document")
    parser.add_argument("--doc-id", required=True, help="Document ID")
    parser.add_argument(
        "--format",
        choices=["raw", "blocks", "info"],
        default="raw",
        help="Output format: raw (plain text), blocks (block tree), info (metadata)",
    )
    args = parser.parse_args()

    if args.format == "raw":
        result = get_raw_content(args.doc_id)
    elif args.format == "blocks":
        result = get_blocks(args.doc_id)
    else:
        result = get_document_info(args.doc_id)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()
