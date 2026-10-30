# -*- coding: utf-8 -*-
"""Lossless Markdown drafts interoperable with Platform's JsonML editor."""

import json
from typing import Any

from markdown_it import MarkdownIt

_MD = MarkdownIt("commonmark", {"html": False, "breaks": True})

# Inline void nodes need a text sibling so Platform's editor can place a
# cursor around them (mirrors the editor's own htmlToJsonML output).
_VOID_INLINE = {"img", "br"}


def draft_asl(content: str) -> str:
    """Parse Markdown into Platform JsonML so its editor renders rich nodes.

    Images and videos become real ``img`` inline nodes (Platform turns video
    URLs into players) instead of plain-text spans that showed the raw
    Markdown source as literal characters.
    """
    return json.dumps(_markdown_to_tree(content), ensure_ascii=False)


def _legacy_tree(content: str) -> list:
    """Old text-span format, kept to recognise drafts saved before parsing."""
    return [
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
    ]


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
        if tree == json.loads(draft_asl(text)) or tree == _legacy_tree(text):
            return text, True
        return _rich_markdown(tree), True
    except (TypeError, ValueError, KeyError, RecursionError):
        return text, False


def _markdown_to_tree(content: str) -> list:
    blocks, _ = _block_nodes(_MD.parse(content, {}), 0)
    return ["root", *blocks]


def _text_span(text: str, marks: Any = ()) -> list:
    attrs: dict[str, Any] = {"data-type": "text"}
    for mark in ("bold", "italic", "strike"):
        if mark in marks:
            attrs[mark] = True
    return ["span", attrs, ["span", {"data-type": "leaf"}, text]]


def _empty_text() -> list:
    return _text_span("")


def _plain_text(children: list) -> str:
    return "".join(child.content for child in children if child.type == "text")


def _normalize_inline(nodes: list) -> list:
    """Keep text nodes beside inline voids (img/br) for editor selection."""
    if not nodes:
        return [_empty_text()]
    out: list = []
    if nodes[0][0] in _VOID_INLINE:
        out.append(_empty_text())
    for index, node in enumerate(nodes):
        out.append(node)
        if node[0] in _VOID_INLINE:
            nxt = nodes[index + 1] if index + 1 < len(nodes) else None
            if nxt is None or nxt[0] in _VOID_INLINE:
                out.append(_empty_text())
    return out


def _inline_nodes(
    children: list,
    start: int = 0,
    marks: Any = None,
) -> tuple[list, int]:
    active = set() if marks is None else set(marks)
    nodes: list = []
    i = start
    while i < len(children):
        token = children[i]
        kind = token.type
        if kind == "link_close":
            return nodes, i
        if kind == "strong_open":
            active.add("bold")
        elif kind == "strong_close":
            active.discard("bold")
        elif kind == "em_open":
            active.add("italic")
        elif kind == "em_close":
            active.discard("italic")
        elif kind == "s_open":
            active.add("strike")
        elif kind == "s_close":
            active.discard("strike")
        elif kind == "text":
            if token.content:
                nodes.append(_text_span(token.content, active))
        elif kind == "code_inline":
            nodes.append(["inlineCode", {}, _text_span(token.content)])
        elif kind in ("softbreak", "hardbreak"):
            nodes.append(["br", {}, _empty_text()])
        elif kind == "image":
            src = token.attrGet("src") or ""
            alt = _plain_text(token.children or [])
            nodes.append(["img", {"src": src, "alt": alt}, _empty_text()])
        elif kind == "link_open":
            href = token.attrGet("href") or ""
            inner, j = _inline_nodes(children, i + 1, active)
            nodes.append(["a", {"href": href}, *inner])
            i = j
        i += 1
    return nodes, i


def _paragraph(children: list) -> list:
    inline, _ = _inline_nodes(children)
    return ["p", *_normalize_inline(inline)]


def _list_items(tokens: list, start: int) -> tuple[list, int]:
    items: list = []
    i = start
    while i < len(tokens):
        token = tokens[i]
        if token.type in ("bullet_list_close", "ordered_list_close"):
            return items, i
        if token.type == "list_item_open":
            inner, j = _block_nodes(tokens, i + 1)
            children: list = []
            for node in inner:
                # Lift tight-list paragraph content directly into the li.
                if node[0] == "p":
                    children.extend(node[1:])
                else:
                    children.append(node)
            items.append(["li", {}, *_normalize_inline(children)])
            i = j + 1
        else:
            i += 1
    return items, i


def _block_nodes(tokens: list, start: int = 0) -> tuple[list, int]:
    nodes: list = []
    i = start
    while i < len(tokens):
        token = tokens[i]
        kind = token.type
        if kind in (
            "paragraph_close",
            "heading_close",
            "blockquote_close",
            "bullet_list_close",
            "ordered_list_close",
            "list_item_close",
        ):
            return nodes, i
        if kind == "paragraph_open":
            nodes.append(_paragraph(tokens[i + 1].children))
            i += 3
        elif kind == "heading_open":
            inline, _ = _inline_nodes(tokens[i + 1].children)
            nodes.append([token.tag, {}, *_normalize_inline(inline)])
            i += 3
        elif kind in ("bullet_list_open", "ordered_list_open"):
            tag = "ul" if kind == "bullet_list_open" else "ol"
            items, j = _list_items(tokens, i + 1)
            nodes.append([tag, {}, *items])
            i = j + 1
        elif kind == "blockquote_open":
            inner, j = _block_nodes(tokens, i + 1)
            nodes.append(["blockquote", {}, *inner])
            i = j + 1
        elif kind in ("fence", "code_block"):
            info = (token.info or "").strip()
            syntax = info.split()[0] if info else "plaintext"
            nodes.append(
                [
                    "code",
                    {"code": token.content.rstrip("\n"), "syntax": syntax},
                ],
            )
            i += 1
        elif kind == "hr":
            nodes.append(["hr"])
            i += 1
        else:
            i += 1
    return nodes, i


def _escape_url(url: str) -> str:
    """Escape parens so a Markdown link destination stays intact.

    Both '(' and ')' are escaped: escaping only ')' would leave a balanced
    URL such as ``Foo_(bar)`` with an unmatched '(' that CommonMark rejects.
    """
    return url.replace("(", "\\(").replace(")", "\\)")


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
        return f"[{content}]({_escape_url(attrs['href'])})"
    if tag == "img":
        return f"![{attrs.get('alt', '')}]({_escape_url(attrs['src'])})"
    if tag == "inlineCode":
        return f"`{content}`"
    if tag == "code":
        syntax = attrs.get("syntax") or ""
        fence = "" if syntax in ("", "plaintext") else syntax
        return f"```{fence}\n{attrs.get('code', '')}\n```\n\n"
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
