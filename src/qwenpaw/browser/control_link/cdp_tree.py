# -*- coding: utf-8 -*-
"""Shared pure CDP accessibility/DOM tree projection helpers."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Mapping, Sequence

from ..errors import BrowserError, ErrorCause, ErrorCategory

_ATTR_WHITELIST = frozenset(
    {
        "href",
        "src",
        "alt",
        "type",
        "placeholder",
        "name",
        "value",
        "data-testid",
        "id",
    },
)
_EXCLUDED_TAGS = frozenset({"SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE"})
_TEXT_NODE_TYPE = 3


def _s(strings: Sequence[object], index: object) -> str:
    """Safely look up a DOMSnapshot string-table entry."""
    if not isinstance(index, int) or index < 0 or index >= len(strings):
        return ""
    return str(strings[index])


def _text_by_backend(snap: Mapping[str, Any]) -> dict[int, str]:
    """Assign each visible DOM text node to its nearest backend ancestor."""
    strings = snap.get("strings") or []
    if not isinstance(strings, Sequence):
        return {}
    text_by_backend: dict[int, list[str]] = {}

    for document in snap.get("documents") or []:
        if not isinstance(document, Mapping):
            continue
        nodes = document.get("nodes") or {}
        layout = document.get("layout") or {}
        if not isinstance(nodes, Mapping) or not isinstance(layout, Mapping):
            continue
        parent_indices = nodes.get("parentIndex") or []
        node_types = nodes.get("nodeType") or []
        node_names = nodes.get("nodeName") or []
        node_values = nodes.get("nodeValue") or []
        backend_ids = nodes.get("backendNodeId") or []
        node_count = len(parent_indices)
        children: list[list[int]] = [[] for _ in range(node_count)]
        roots: list[int] = []
        for index, parent in enumerate(parent_indices):
            if isinstance(parent, int) and 0 <= parent < node_count:
                children[parent].append(index)
            else:
                roots.append(index)
        visible = {
            index
            for index in layout.get("nodeIndex") or []
            if isinstance(index, int) and 0 <= index < node_count
        }
        stack: list[tuple[int, int | None, bool]] = [
            (root, None, False) for root in reversed(roots)
        ]
        while stack:
            index, owner, excluded = stack.pop()
            backend_id = (
                backend_ids[index] if index < len(backend_ids) else None
            )
            if isinstance(backend_id, int) and backend_id > 0:
                owner = backend_id
            node_name = _s(
                strings,
                node_names[index] if index < len(node_names) else None,
            ).upper()
            excluded = excluded or node_name in _EXCLUDED_TAGS
            node_type = node_types[index] if index < len(node_types) else None
            if (
                not excluded
                and node_type == _TEXT_NODE_TYPE
                and index in visible
                and owner is not None
            ):
                text = " ".join(
                    _s(
                        strings,
                        node_values[index]
                        if index < len(node_values)
                        else None,
                    ).split(),
                )
                if text:
                    text_by_backend.setdefault(owner, []).append(text)
            stack.extend(
                (child, owner, excluded) for child in reversed(children[index])
            )

    return {
        backend_id: " ".join(texts)
        for backend_id, texts in text_by_backend.items()
    }


def dom_attrs_by_backend(snap: Mapping[str, Any]) -> dict[int, dict[str, str]]:
    documents = snap.get("documents") or []
    if not documents:
        return {}
    nodes, strings = documents[0].get("nodes") or {}, snap.get("strings") or []
    backend_ids, attributes = (
        nodes.get("backendNodeId") or [],
        nodes.get("attributes") or [],
    )
    result: dict[int, dict[str, str]] = {}
    for index, backend_id in enumerate(backend_ids):
        attrs: dict[str, str] = {}
        raw = attributes[index] if index < len(attributes) else []
        for name_index, value_index in zip(raw[::2], raw[1::2]):
            name = str(strings[name_index])
            if name in _ATTR_WHITELIST:
                attrs[name] = str(strings[value_index])
        if attrs.get("type") == "password" and "value" in attrs:
            attrs["value"] = "***"
        if attrs:
            result[int(backend_id)] = attrs
    return result


def ax_states(node: Mapping[str, Any]) -> list[str]:
    states = []
    for property_ in node.get("properties") or []:
        name, value = str(property_.get("name", "")), property_.get(
            "value",
            {},
        ).get("value")
        if value is True:
            states.append(name)
        elif value not in (None, False, ""):
            states.append(f"{name}={value}")
    return states


def merge_ax_dom(
    nodes: list[Mapping[str, Any]],
    snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    """Build an AX tree enriched by attributes and visible DOM text."""
    attrs_by_backend = dom_attrs_by_backend(snapshot)
    text_by_backend = _text_by_backend(snapshot)
    by_id = {str(node["nodeId"]): node for node in nodes if "nodeId" in node}
    children = {
        str(child) for node in nodes for child in node.get("childIds") or []
    }
    root_id = next(
        (node_id for node_id in by_id if node_id not in children),
        "",
    )

    def build(node_id: str) -> dict[str, Any]:
        node = by_id[node_id]
        name = str(node.get("name", {}).get("value", ""))
        backend_node_id = int(node.get("backendDOMNodeId", -1))
        text = text_by_backend.get(backend_node_id, "") or name
        children = [
            build(str(child))
            for child in node.get("childIds") or []
            if str(child) in by_id
        ]
        children = [
            child
            for child in children
            if not (
                child["role"] == "InlineTextBox"
                and child["text"]
                and child["text"] in text
            )
        ]
        return {
            "role": str(node.get("role", {}).get("value", "")),
            "name": name,
            "states": ax_states(node),
            "attrs": dict(
                attrs_by_backend.get(
                    backend_node_id,
                    {},
                ),
            ),
            "text": text,
            "children": children,
        }

    return build(root_id) if root_id else {}


@dataclass(frozen=True)
class ResolverNode:
    role: str
    name: str
    backend_node_id: int
    node_id: str
    child_ids: tuple[str, ...]
    states: tuple[str, ...]
    attrs: Mapping[str, str]


def capture_resolver_nodes(
    ax_nodes: Sequence[Mapping[str, Any]],
) -> list[ResolverNode]:
    return [
        ResolverNode(
            str(node.get("role", {}).get("value", "")),
            str(node.get("name", {}).get("value", "")),
            int(node.get("backendDOMNodeId", -1)),
            str(node.get("nodeId", "")),
            tuple(str(child) for child in node.get("childIds") or []),
            tuple(ax_states(node)),
            {},
        )
        for node in ax_nodes
        if "backendDOMNodeId" in node
    ]


def resolve_spec(
    nodes: Sequence[ResolverNode],
    spec: Sequence[Any],
) -> list[ResolverNode]:
    """Resolve an AX-tree spec.

    DEPRECATED for locator chain resolution: use injected engine.js through
    ``CdpVerbsMixin``. This remains available for the snapshot/AX-tree path.
    """
    candidates = list(nodes)
    for step in spec:
        method, args, kwargs = step.method, step.args, dict(step.kwargs)
        if method == "get_by_role":
            candidates = [
                node
                for node in candidates
                if node.role == str(args[0])
                and (
                    not kwargs.get("name") or str(kwargs["name"]) in node.name
                )
            ]
        elif method in {"get_by_text", "get_by_label"}:
            candidates = [
                node for node in candidates if str(args[0]) in node.name
            ]
        elif method == "get_by_placeholder":
            candidates = [
                node
                for node in candidates
                if str(args[0]) in node.attrs.get("placeholder", "")
            ]
        elif method == "filter":
            text = str(kwargs.get("has_text", ""))
            candidates = [
                node for node in candidates if not text or text in node.name
            ]
        elif method == "nth":
            candidates = candidates[int(args[0]) : int(args[0]) + 1]
        elif method == "first":
            candidates = candidates[:1]
        elif method == "last":
            candidates = candidates[-1:]
        elif method == "locator":
            selector = str(args[0])
            id_match = re.fullmatch(r"#([A-Za-z_][\w-]*)", selector)
            test_id_match = re.fullmatch(
                r'\[data-testid="([A-Za-z_][\w-]*)"\]',
                selector,
            )
            if id_match:
                candidates = [
                    node
                    for node in candidates
                    if node.attrs.get("id") == id_match.group(1)
                ]
            elif test_id_match:
                candidates = [
                    node
                    for node in candidates
                    if node.attrs.get("data-testid") == test_id_match.group(1)
                ]
            else:
                raise ValueError(
                    "CSS locator is resolved by the Chrome adapter",
                )
    return candidates


def _format_spec(spec: object) -> str:
    """Render a replayable locator spec as SDK-shaped Python."""
    if not isinstance(spec, Sequence) or isinstance(spec, (str, bytes)):
        return str(spec)
    rendered = ""
    for step in spec:
        method = getattr(step, "method", "")
        args = tuple(getattr(step, "args", ()))
        kwargs = dict(getattr(step, "kwargs", ()))
        if method in {
            "get_by_role",
            "get_by_text",
            "get_by_label",
            "get_by_placeholder",
            "locator",
        }:
            arguments = [json.dumps(arg, ensure_ascii=False) for arg in args]
            arguments.extend(
                f"{key}={json.dumps(value, ensure_ascii=False)}"
                for key, value in kwargs.items()
            )
            call = f"{method}({', '.join(arguments)})"
            rendered = f"{rendered}.{call}" if rendered else call
        elif method == "nth" and args:
            rendered += f".nth({args[0]})"
        elif method in {"first", "last"}:
            rendered += f".{method}()"
        else:
            return str(spec)
    return rendered or str(spec)


def _candidate_attrs(candidate: ResolverNode) -> str:
    """Keep candidate summaries focused on locator-distinguishing attrs."""
    parts = [
        f"{key}={value}"
        for key in ("id", "data-testid")
        if (value := candidate.attrs.get(key))
    ]
    return f" [{', '.join(parts)}]" if parts else ""


def _candidate_aka(
    candidate: ResolverNode,
    candidates: Sequence[ResolverNode],
) -> str:
    """Return the narrowest locator that identifies *candidate* here."""
    name_matches = [
        node
        for node in candidates
        if node.role == candidate.role and candidate.name in node.name
    ]
    if candidate.name and len(name_matches) == 1:
        return (
            "get_by_role("
            f"{json.dumps(candidate.role, ensure_ascii=False)}, "
            f"name={json.dumps(candidate.name, ensure_ascii=False)})"
        )
    for key in ("id", "data-testid"):
        value = str(candidate.attrs.get(key, ""))
        if (
            value
            and len(value) <= 80
            and re.fullmatch(
                r"[A-Za-z_][\w-]*",
                value,
            )
        ):
            if key == "id":
                return f'locator("#{value}")'
            return f"locator('[data-testid=\"{value}\"]')"
    same_role_name = [
        node
        for node in candidates
        if node.role == candidate.role and node.name == candidate.name
    ]
    index = same_role_name.index(candidate)
    if candidate.name:
        return (
            "get_by_role("
            f"{json.dumps(candidate.role, ensure_ascii=False)}, "
            f"name={json.dumps(candidate.name, ensure_ascii=False)})"
            f".nth({index})"
        )
    role_index = [
        node for node in candidates if node.role == candidate.role
    ].index(candidate)
    return (
        "get_by_role("
        f"{json.dumps(candidate.role, ensure_ascii=False)}).nth({role_index})"
    )


def _locator_error(
    candidates: Sequence[ResolverNode],
    spec: object,
) -> BrowserError:
    """Build a recoverable strict-locator teaching error."""
    rendered_spec = _format_spec(spec)
    if not candidates:
        message = (
            f"strict locator matched 0 elements: {rendered_spec}\n"
            "Narrow it: check .count() first, loosen name= to a substring, "
            "or re-snapshot() before trying again."
        )
    else:
        lines = [
            "strict locator matched "
            f"{len(candidates)} elements (need exactly 1): {rendered_spec}",
        ]
        for index, candidate in enumerate(candidates[:10], start=1):
            lines.append(
                f"  {index}) {candidate.role} "
                f"{json.dumps(candidate.name, ensure_ascii=False)}"
                f"{_candidate_attrs(candidate)} aka "
                f"{_candidate_aka(candidate, candidates)}",
            )
        if len(candidates) > 10:
            lines.append(f"  ... and {len(candidates) - 10} more")
        lines.append(
            "Narrow it: use an exact name=, add .filter(has_text=...), or "
            "pick one with .nth(i); check .count() first when unsure.",
        )
        message = "\n".join(lines)
    return BrowserError(
        category=ErrorCategory.RETRYABLE,
        cause=ErrorCause.LOCATE_FAILED,
        suggested_action="",
        reason=message,
        detail=message,
    )


def single_or_teach(
    candidates: Sequence[ResolverNode],
    spec: object,
) -> ResolverNode:
    if len(candidates) != 1:
        raise _locator_error(candidates, spec)
    return candidates[0]
