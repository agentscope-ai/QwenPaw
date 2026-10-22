# -*- coding: utf-8 -*-
"""Lossless Markdown drafts interoperable with Platform's JsonML editor."""

import json
from typing import Any


def draft_asl(content: str) -> str:
    """Use Platform's textToJsonML structure so its editor can restore text."""
    return json.dumps(
        [
            "root",
            *[
                [
                    "p",
                    [
                        "span",
                        {"data-type": "text"},
                        ["span", {"data-type": "leaf"}, line],
                    ],
                ]
                for line in content.split("\n")
            ],
        ],
        ensure_ascii=False,
    )


def draft_content(post: dict[str, Any]) -> tuple[str, bool]:
    """Restore Markdown exactly; leave unsupported rich documents intact.

    Platform's body_text is plain text for native rich articles, so using it
    unconditionally would silently discard links, images and formatting.
    """
    text = post.get("body_text") or ""
    raw = post.get("body_asl")
    if post.get("article_type") == "question" or not raw:
        return text, True
    try:
        tree = json.loads(raw) if isinstance(raw, str) else raw
        if tree == json.loads(draft_asl(text)):
            return text, True
        return _rich_markdown(tree), True
    except (TypeError, ValueError, KeyError, RecursionError):
        return text, False


# One explicit branch per supported JsonML node; unknown nodes fail closed.
# pylint: disable=too-many-return-statements,too-many-branches
def _rich_markdown(node: Any) -> str:
    """Convert common Platform JsonML nodes; fail closed for custom embeds."""
    if isinstance(node, str):
        return node
    if not isinstance(node, list) or not node:
        raise ValueError("unsupported_asl")
    tag = node[0]
    attrs = node[1] if len(node) > 1 and isinstance(node[1], dict) else {}
    children = node[2:] if attrs else node[1:]
    if len(node) > 1 and isinstance(node[1], dict):
        children = node[2:]
    content = "".join(_rich_markdown(child) for child in children)
    if tag == "root":
        return content.rstrip()
    if tag == "span":
        if any(
            key not in {"data-type", "bold", "italic", "strike"}
            for key in attrs
        ):
            raise ValueError("unsupported_asl_marks")
        for key, marker in (("bold", "**"), ("italic", "_"), ("strike", "~~")):
            if attrs.get(key):
                content = f"{marker}{content}{marker}"
        return content
    if tag == "p":
        return content + "\n\n"
    if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        return "#" * int(tag[1]) + " " + content + "\n\n"
    if tag == "a":
        return f"[{content}]({attrs['href']})"
    if tag == "img":
        return f"![{attrs.get('alt', '')}]({attrs['src']})\n\n"
    if tag == "blockquote":
        return (
            "\n".join("> " + line for line in content.strip().splitlines())
            + "\n\n"
        )
    if tag == "li":
        return content.strip() + "\n"
    if tag in {"ul", "ol"}:
        items = [_rich_markdown(child).strip() for child in children]
        return (
            "\n".join(
                (f"{index}. " if tag == "ol" else "- ")
                + item.replace("\n", "\n  ")
                for index, item in enumerate(items, 1)
            )
            + "\n\n"
        )
    if tag == "br":
        return "  \n"
    if tag == "hr":
        return "\n---\n\n"
    raise ValueError("unsupported_asl_node")
