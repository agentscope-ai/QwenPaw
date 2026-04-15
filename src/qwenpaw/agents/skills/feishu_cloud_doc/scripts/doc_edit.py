#!/usr/bin/env python3
"""Edit a Feishu document: add, delete, or search-and-delete blocks.

Usage -- Add blocks:
    python scripts/doc_edit.py --doc-id DOC_ID --blocks-json '[...]'
    python scripts/doc_edit.py --doc-id DOC_ID --blocks-file blocks.json
    python scripts/doc_edit.py --doc-id DOC_ID --parent-block-id BLOCK_ID --blocks-json '[...]'

Usage -- Delete by block ID:
    python scripts/doc_edit.py --doc-id DOC_ID --action delete --block-id BLOCK_ID

Usage -- Delete by text content (searches all blocks, deletes those containing the text):
    python scripts/doc_edit.py --doc-id DOC_ID --action delete-by-text --text "content to remove"

Common block types:
  - type 2 (text):     {"block_type": 2, "text": {"elements": [{"text_run": {"content": "Hello"}}]}}
  - type 3 (heading1): {"block_type": 3, "heading1": {"elements": [{"text_run": {"content": "Title"}}]}}
  - type 4 (heading2): {"block_type": 4, "heading2": {"elements": [{"text_run": {"content": "Sub"}}]}}
  - type 9 (bullet):   {"block_type": 9, "bullet": {"elements": [{"text_run": {"content": "Item"}}]}}
  - type 10 (ordered):  {"block_type": 10, "ordered": {"elements": [{"text_run": {"content": "Step 1"}}]}}
  - type 12 (code):    {"block_type": 12, "code": {"elements": [{"text_run": {"content": "print(1)"}}], "style": {"language": 49}}}
  - type 14 (divider): {"block_type": 14}

Output: JSON with operation result.
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx

from feishu_auth import auth_headers, get_base_url


def _fetch_all_blocks(document_id: str) -> list[dict] | None:
    """Fetch all blocks of a document. Returns None on error."""
    base = get_base_url()
    url = f"{base}/open-apis/docx/v1/documents/{document_id}/blocks"
    all_blocks: list[dict] = []
    page_token = ""

    while True:
        params: dict = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token

        resp = httpx.get(url, headers=auth_headers(), params=params, timeout=30)
        data = resp.json()
        if data.get("code") != 0:
            return None

        all_blocks.extend(data.get("data", {}).get("items", []))
        page_token = data.get("data", {}).get("page_token", "")
        if not data.get("data", {}).get("has_more", False) or not page_token:
            break

    return all_blocks


def _extract_block_text(block: dict) -> str:
    """Extract plain text from a block's elements."""
    block_type = block.get("block_type", 0)
    type_key_map = {
        2: "text", 3: "heading1", 4: "heading2", 5: "heading3",
        6: "heading4", 7: "heading5", 8: "heading6",
        9: "bullet", 10: "ordered", 12: "code",
        15: "callout",
    }
    content_key = type_key_map.get(block_type, "")
    if not content_key:
        return ""

    content_obj = block.get(content_key, {})
    elements = content_obj.get("elements", [])
    parts = []
    for elem in elements:
        text_run = elem.get("text_run", {})
        if text_run:
            parts.append(text_run.get("content", ""))
    return "".join(parts)


def _batch_delete_children(
    document_id: str,
    parent_block_id: str,
    start_index: int,
    end_index: int,
) -> dict:
    """Delete children of a parent block by index range.

    Feishu API: DELETE /docx/v1/documents/{id}/blocks/{parent}/children/batch_delete
    start_index: inclusive, >= 0
    end_index: exclusive, >= 1
    """
    base = get_base_url()
    url = (
        f"{base}/open-apis/docx/v1/documents/{document_id}"
        f"/blocks/{parent_block_id}/children/batch_delete"
    )
    body = {"start_index": start_index, "end_index": end_index}
    resp = httpx.delete(url, headers=auth_headers(), json=body, timeout=30)
    data = resp.json()

    if data.get("code") != 0:
        return {
            "success": False,
            "error": data.get("msg", "unknown error"),
            "code": data.get("code"),
        }

    return {"success": True}


def add_blocks(
    document_id: str,
    blocks: list[dict],
    parent_block_id: str = "",
    index: int = -1,
) -> dict:
    """Add child blocks to a document or a specific parent block.

    If parent_block_id is empty, the document root block is used
    (which equals the document_id itself).
    """
    parent = parent_block_id or document_id
    base = get_base_url()
    url = (
        f"{base}/open-apis/docx/v1/documents/{document_id}"
        f"/blocks/{parent}/children"
    )

    body: dict = {"children": blocks}
    if index >= 0:
        body["index"] = index

    resp = httpx.post(url, headers=auth_headers(), json=body, timeout=30)
    data = resp.json()

    if data.get("code") != 0:
        return {
            "success": False,
            "error": data.get("msg", "unknown error"),
            "code": data.get("code"),
        }

    created = data.get("data", {}).get("children", [])
    return {
        "success": True,
        "document_id": document_id,
        "parent_block_id": parent,
        "created_count": len(created),
        "created_blocks": [
            {"block_id": b.get("block_id", ""), "block_type": b.get("block_type", 0)}
            for b in created
        ],
    }


def delete_block(document_id: str, block_id: str) -> dict:
    """Delete a specific block from a document by its block_id.

    Finds the block's parent, determines the child index, then calls
    batch_delete on the parent with the correct index range.
    """
    all_blocks = _fetch_all_blocks(document_id)
    if all_blocks is None:
        return {
            "success": False,
            "error": "Failed to fetch document blocks",
        }

    parent_block_id = ""
    child_index = -1
    for block in all_blocks:
        children_ids = block.get("children", [])
        if block_id in children_ids:
            parent_block_id = block.get("block_id", "")
            child_index = children_ids.index(block_id)
            break

    if not parent_block_id or child_index < 0:
        return {
            "success": False,
            "error": f"Block {block_id} not found in any parent's children list",
        }

    result = _batch_delete_children(
        document_id, parent_block_id, child_index, child_index + 1
    )
    if not result.get("success"):
        return result

    return {
        "success": True,
        "document_id": document_id,
        "deleted_block_id": block_id,
        "parent_block_id": parent_block_id,
        "deleted_index": child_index,
    }


def delete_by_text(document_id: str, search_text: str, match_exact: bool = False) -> dict:
    """Delete all blocks whose text content contains (or exactly matches) the search text.

    Steps:
    1. Fetch all blocks
    2. Find blocks whose text contains search_text
    3. Group by parent and delete via batch_delete (in reverse index order to avoid shifting)
    """
    all_blocks = _fetch_all_blocks(document_id)
    if all_blocks is None:
        return {
            "success": False,
            "error": "Failed to fetch document blocks",
        }

    matching_block_ids: list[str] = []
    for block in all_blocks:
        block_text = _extract_block_text(block)
        if not block_text:
            continue
        if match_exact:
            if block_text.strip() == search_text.strip():
                matching_block_ids.append(block.get("block_id", ""))
        else:
            if search_text in block_text:
                matching_block_ids.append(block.get("block_id", ""))

    if not matching_block_ids:
        return {
            "success": False,
            "error": f"No blocks found containing text: {search_text!r}",
            "searched_block_count": len(all_blocks),
        }

    parent_to_indices: dict[str, list[int]] = {}
    for block in all_blocks:
        children_ids = block.get("children", [])
        parent_id = block.get("block_id", "")
        for idx, child_id in enumerate(children_ids):
            if child_id in matching_block_ids:
                parent_to_indices.setdefault(parent_id, []).append(idx)

    deleted_blocks: list[dict] = []
    errors: list[str] = []

    for parent_id, indices in parent_to_indices.items():
        sorted_indices = sorted(indices, reverse=True)
        for idx in sorted_indices:
            result = _batch_delete_children(document_id, parent_id, idx, idx + 1)
            if result.get("success"):
                deleted_blocks.append({"parent_id": parent_id, "index": idx})
            else:
                errors.append(
                    f"Failed to delete index {idx} from parent {parent_id}: "
                    f"{result.get('error', 'unknown')}"
                )

    return {
        "success": len(deleted_blocks) > 0,
        "document_id": document_id,
        "search_text": search_text,
        "matched_count": len(matching_block_ids),
        "deleted_count": len(deleted_blocks),
        "deleted_blocks": deleted_blocks,
        "errors": errors if errors else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Edit a Feishu document")
    parser.add_argument("--doc-id", required=True, help="Document ID")
    parser.add_argument(
        "--parent-block-id",
        default="",
        help="Parent block ID (default: document root)",
    )
    parser.add_argument(
        "--blocks-json",
        default="",
        help="JSON array of block objects to add",
    )
    parser.add_argument(
        "--blocks-file",
        default="",
        help="Path to JSON file containing block array",
    )
    parser.add_argument(
        "--index",
        type=int,
        default=-1,
        help="Insert position (-1 = append at end)",
    )
    parser.add_argument(
        "--action",
        choices=["add", "delete", "delete-by-text"],
        default="add",
        help="Action: add blocks, delete by block ID, or delete by text content",
    )
    parser.add_argument(
        "--block-id",
        default="",
        help="Block ID to delete (for --action delete)",
    )
    parser.add_argument(
        "--text",
        default="",
        help="Text to search and delete (for --action delete-by-text)",
    )
    parser.add_argument(
        "--exact",
        action="store_true",
        help="Require exact text match instead of substring (for --action delete-by-text)",
    )
    args = parser.parse_args()

    if args.action == "delete":
        if not args.block_id:
            print(json.dumps({"success": False, "error": "--block-id required for delete"}))
            sys.exit(1)
        result = delete_block(args.doc_id, args.block_id)
    elif args.action == "delete-by-text":
        if not args.text:
            print(json.dumps({"success": False, "error": "--text required for delete-by-text"}))
            sys.exit(1)
        result = delete_by_text(args.doc_id, args.text, match_exact=args.exact)
    else:
        blocks_data: list[dict] = []
        if args.blocks_file:
            with open(args.blocks_file, encoding="utf-8") as fh:
                blocks_data = json.load(fh)
        elif args.blocks_json:
            blocks_data = json.loads(args.blocks_json)
        else:
            print(json.dumps({"success": False, "error": "Provide --blocks-json or --blocks-file"}))
            sys.exit(1)

        if not isinstance(blocks_data, list):
            blocks_data = [blocks_data]

        result = add_blocks(
            args.doc_id,
            blocks_data,
            parent_block_id=args.parent_block_id,
            index=args.index,
        )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()
