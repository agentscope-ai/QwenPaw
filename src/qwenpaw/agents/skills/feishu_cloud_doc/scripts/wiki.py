#!/usr/bin/env python3
"""Manage Feishu Wiki (Knowledge Base) spaces and nodes.

Usage:
    python scripts/wiki.py list-spaces
    python scripts/wiki.py create-space --name "Engineering Wiki" [--description "..."]
    python scripts/wiki.py list-nodes --space-id SPACE_ID [--parent-node-token TOKEN]
    python scripts/wiki.py get-node --space-id SPACE_ID --node-token TOKEN
    python scripts/wiki.py create-node --space-id SPACE_ID --obj-type docx --title "Page Title" [--parent-node-token TOKEN]
    python scripts/wiki.py move-node --space-id SPACE_ID --node-token TOKEN --target-parent-token PARENT

Output: JSON with operation result.
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx

from feishu_auth import auth_headers, get_base_url


def list_spaces(page_size: int = 50, page_token: str = "") -> dict:
    """List all wiki spaces the app can access."""
    base = get_base_url()
    url = f"{base}/open-apis/wiki/v2/spaces"
    params: dict = {"page_size": min(page_size, 50)}
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

    result_data = data.get("data", {})
    items = result_data.get("items", [])
    return {
        "success": True,
        "has_more": result_data.get("has_more", False),
        "page_token": result_data.get("page_token", ""),
        "space_count": len(items),
        "spaces": [
            {
                "space_id": s.get("space_id", ""),
                "name": s.get("name", ""),
                "description": s.get("description", ""),
                "space_type": s.get("space_type", ""),
                "visibility": s.get("visibility", ""),
            }
            for s in items
        ],
    }


def create_space(name: str, description: str = "") -> dict:
    """Create a new wiki space."""
    base = get_base_url()
    url = f"{base}/open-apis/wiki/v2/spaces"
    body: dict = {"name": name}
    if description:
        body["description"] = description

    resp = httpx.post(url, headers=auth_headers(), json=body, timeout=30)
    data = resp.json()

    if data.get("code") != 0:
        return {
            "success": False,
            "error": data.get("msg", "unknown error"),
            "code": data.get("code"),
        }

    space = data.get("data", {}).get("space", {})
    return {
        "success": True,
        "space_id": space.get("space_id", ""),
        "name": space.get("name", name),
        "description": space.get("description", ""),
    }


def list_nodes(
    space_id: str,
    parent_node_token: str = "",
    page_size: int = 50,
    page_token: str = "",
) -> dict:
    """List child nodes of a wiki space or parent node."""
    base = get_base_url()
    url = f"{base}/open-apis/wiki/v2/spaces/{space_id}/nodes"
    params: dict = {"page_size": min(page_size, 50)}
    if parent_node_token:
        params["parent_node_token"] = parent_node_token
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

    result_data = data.get("data", {})
    items = result_data.get("items", [])
    return {
        "success": True,
        "space_id": space_id,
        "has_more": result_data.get("has_more", False),
        "page_token": result_data.get("page_token", ""),
        "node_count": len(items),
        "nodes": [
            {
                "node_token": n.get("node_token", ""),
                "obj_token": n.get("obj_token", ""),
                "obj_type": n.get("obj_type", ""),
                "title": n.get("title", ""),
                "has_child": n.get("has_child", False),
                "parent_node_token": n.get("parent_node_token", ""),
                "node_create_time": n.get("node_create_time", ""),
            }
            for n in items
        ],
    }


def get_node(space_id: str, node_token: str) -> dict:
    """Get information about a specific wiki node."""
    base = get_base_url()
    url = f"{base}/open-apis/wiki/v2/spaces/get_node"
    params = {"token": node_token}

    resp = httpx.get(url, headers=auth_headers(), params=params, timeout=30)
    data = resp.json()

    if data.get("code") != 0:
        return {
            "success": False,
            "error": data.get("msg", "unknown error"),
            "code": data.get("code"),
        }

    node = data.get("data", {}).get("node", {})
    return {
        "success": True,
        "space_id": node.get("space_id", space_id),
        "node_token": node.get("node_token", node_token),
        "obj_token": node.get("obj_token", ""),
        "obj_type": node.get("obj_type", ""),
        "title": node.get("title", ""),
        "has_child": node.get("has_child", False),
        "parent_node_token": node.get("parent_node_token", ""),
        "node_create_time": node.get("node_create_time", ""),
        "obj_create_time": node.get("obj_create_time", ""),
        "obj_edit_time": node.get("obj_edit_time", ""),
        "creator": node.get("creator", ""),
        "owner": node.get("owner", ""),
    }


def create_node(
    space_id: str,
    obj_type: str,
    title: str,
    parent_node_token: str = "",
) -> dict:
    """Create a new node in a wiki space.

    obj_type: "docx" (document), "sheet" (spreadsheet), "bitable" (multi-table),
              "mindnote" (mind map), "slides" (slides)
    """
    base = get_base_url()
    url = f"{base}/open-apis/wiki/v2/spaces/{space_id}/nodes"
    body: dict = {
        "obj_type": obj_type,
        "title": title,
    }
    if parent_node_token:
        body["parent_node_token"] = parent_node_token

    resp = httpx.post(url, headers=auth_headers(), json=body, timeout=30)
    data = resp.json()

    if data.get("code") != 0:
        return {
            "success": False,
            "error": data.get("msg", "unknown error"),
            "code": data.get("code"),
        }

    node = data.get("data", {}).get("node", {})
    node_token = node.get("node_token", "")
    obj_token = node.get("obj_token", "")

    result: dict = {
        "success": True,
        "space_id": space_id,
        "node_token": node_token,
        "obj_token": obj_token,
        "obj_type": node.get("obj_type", obj_type),
        "title": node.get("title", title),
    }

    if obj_token:
        domain = "larksuite.com" if "larksuite" in base else "feishu.cn"
        if obj_type == "docx":
            result["url"] = f"https://{domain}/docx/{obj_token}"
        elif obj_type == "sheet":
            result["url"] = f"https://{domain}/sheets/{obj_token}"
        elif obj_type == "bitable":
            result["url"] = f"https://{domain}/base/{obj_token}"

    return result


def move_node(
    space_id: str,
    node_token: str,
    target_parent_token: str,
) -> dict:
    """Move a node to a new parent within the same space."""
    base = get_base_url()
    url = (
        f"{base}/open-apis/wiki/v2/spaces/{space_id}"
        f"/nodes/{node_token}/move"
    )
    body = {"target_parent_token": target_parent_token}

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
        "space_id": space_id,
        "node_token": node_token,
        "target_parent_token": target_parent_token,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage Feishu Wiki")
    sub = parser.add_subparsers(dest="command", required=True)

    list_spaces_p = sub.add_parser("list-spaces", help="List wiki spaces")
    list_spaces_p.add_argument("--page-size", type=int, default=50)
    list_spaces_p.add_argument("--page-token", default="")

    create_space_p = sub.add_parser("create-space", help="Create a wiki space")
    create_space_p.add_argument("--name", required=True)
    create_space_p.add_argument("--description", default="")

    list_nodes_p = sub.add_parser("list-nodes", help="List nodes in a space")
    list_nodes_p.add_argument("--space-id", required=True)
    list_nodes_p.add_argument("--parent-node-token", default="")
    list_nodes_p.add_argument("--page-size", type=int, default=50)
    list_nodes_p.add_argument("--page-token", default="")

    get_node_p = sub.add_parser("get-node", help="Get node info")
    get_node_p.add_argument("--space-id", required=True)
    get_node_p.add_argument("--node-token", required=True)

    create_node_p = sub.add_parser("create-node", help="Create a node")
    create_node_p.add_argument("--space-id", required=True)
    create_node_p.add_argument("--obj-type", required=True, choices=["docx", "sheet", "bitable", "mindnote", "slides"])
    create_node_p.add_argument("--title", required=True)
    create_node_p.add_argument("--parent-node-token", default="")

    move_node_p = sub.add_parser("move-node", help="Move a node")
    move_node_p.add_argument("--space-id", required=True)
    move_node_p.add_argument("--node-token", required=True)
    move_node_p.add_argument("--target-parent-token", required=True)

    args = parser.parse_args()

    if args.command == "list-spaces":
        result = list_spaces(args.page_size, args.page_token)
    elif args.command == "create-space":
        result = create_space(args.name, args.description)
    elif args.command == "list-nodes":
        result = list_nodes(args.space_id, args.parent_node_token, args.page_size, args.page_token)
    elif args.command == "get-node":
        result = get_node(args.space_id, args.node_token)
    elif args.command == "create-node":
        result = create_node(args.space_id, args.obj_type, args.title, args.parent_node_token)
    elif args.command == "move-node":
        result = move_node(args.space_id, args.node_token, args.target_parent_token)
    else:
        result = {"success": False, "error": f"Unknown command: {args.command}"}

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()
