# -*- coding: utf-8 -*-
"""Deterministic patch operations over one Project document.

``patch_project`` moves bracket depth off the model: instead of hand-
writing one deep nested document (where LLM bracket-balance errors grow
with depth x length), the model emits a flat list of small operations and
the Runtime assembles the document. Errors name the exact op index and
path so one turn is enough to fix a bad call.

Supported operations:

- ``add``     — set an object member, append to a list with ``-``, or
                insert at a list index (parent must exist)
- ``replace`` — overwrite an existing object member or list index
- ``remove``  — delete an existing object member or list index
- ``upsert_entity`` — domain op for ``EntityCollection`` nodes: writes
                ``items[id]`` and appends ``id`` to ``order`` when absent,
                so the items/order invariant cannot be half-updated
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .commit import is_protected_pointer
from .json_pointer import split_pointer


class PatchOpError(ValueError):
    """One invalid patch operation, addressed by index and path."""

    def __init__(self, index: int, message: str) -> None:
        super().__init__(f"ops[{index}]: {message}")
        self.index = index


_ALLOWED_OPS = frozenset({"add", "replace", "remove", "upsert_entity"})


def apply_patch_ops(
    document: dict[str, Any],
    ops: list[Mapping[str, Any]],
) -> None:
    """Apply every operation to *document* in place, or raise PatchOpError.

    The caller owns atomicity: apply to a throwaway candidate and discard
    it when this raises.
    """

    if not ops:
        raise PatchOpError(0, "ops 不能为空")
    for index, op in enumerate(ops):
        if not isinstance(op, Mapping):
            raise PatchOpError(index, "每个 op 必须是 object")
        kind = str(op.get("op") or "")
        if kind not in _ALLOWED_OPS:
            raise PatchOpError(
                index,
                f"不支持的 op 类型 {kind!r}；可用：add/replace/remove/" "upsert_entity",
            )
        if kind == "upsert_entity":
            _apply_upsert_entity(document, index, op)
        else:
            _apply_pointer_op(document, index, kind, op)


def _normalize_pointer(index: int, pointer: str, *, label: str) -> str:
    """Accept dotted paths as a lossless alias for JSON Pointers.

    Models habitually write ``visual.entities`` (jq/JS muscle memory).
    When the value has no slash at all, converting dots to ``/`` is an
    unambiguous, information-preserving rewrite — refusing it only costs a
    retry turn. Anything already pointer-shaped passes through untouched.
    """

    if not pointer:
        raise PatchOpError(index, f"{label} 不能为空")
    if pointer.startswith("/"):
        return pointer
    if "/" not in pointer:
        return "/" + pointer.replace(".", "/")
    raise PatchOpError(
        index,
        f"{label} 必须是 RFC 6901 JSON Pointer（如 /visual/entities），"
        f"收到：{pointer!r}",
    )


def _resolve_parent(
    document: dict[str, Any],
    index: int,
    pointer: str,
    *,
    label: str = "path",
) -> tuple[Any, str]:
    pointer = _normalize_pointer(index, pointer, label=label)
    if is_protected_pointer(pointer):
        raise PatchOpError(
            index,
            f"{label} {pointer!r} 是 Runtime 保护字段，禁止修改",
        )
    tokens = split_pointer(pointer)
    if not tokens:
        raise PatchOpError(index, f"{label} 不能指向 Project 根")
    node: Any = document
    for depth, token in enumerate(tokens[:-1]):
        if isinstance(node, dict):
            if token not in node:
                missing = "/" + "/".join(tokens[: depth + 1])
                raise PatchOpError(
                    index,
                    f"path 的父级不存在：{missing}（先用 add 创建父级）",
                )
            node = node[token]
        elif isinstance(node, list):
            position = _list_index(index, token, len(node), insert=False)
            node = node[position]
        else:
            missing = "/" + "/".join(tokens[: depth + 1])
            raise PatchOpError(
                index,
                f"path 中 {missing} 不是对象或数组，无法继续下钻",
            )
    return node, tokens[-1]


def _list_index(
    index: int,
    token: str,
    length: int,
    *,
    insert: bool,
) -> int:
    if not token.isdigit():
        raise PatchOpError(index, f"数组下标必须是数字：{token!r}")
    position = int(token)
    limit = length if insert else length - 1
    if position > limit:
        raise PatchOpError(
            index,
            f"数组下标越界：{position}（长度 {length}）",
        )
    return position


def _apply_pointer_op(
    document: dict[str, Any],
    index: int,
    kind: str,
    op: Mapping[str, Any],
) -> None:
    pointer = str(op.get("path") or "")
    parent, leaf = _resolve_parent(document, index, pointer)
    if kind in {"add", "replace"} and "value" not in op:
        raise PatchOpError(index, f"{kind} 需要 value 字段")
    if isinstance(parent, dict):
        _apply_dict_op(parent, index, kind, op, pointer, leaf)
        return
    if isinstance(parent, list):
        _apply_list_op(parent, index, kind, op, leaf)
        return
    raise PatchOpError(index, f"path 的父级不是对象或数组：{pointer}")


def _apply_dict_op(
    parent: dict[str, Any],
    index: int,
    kind: str,
    op: Mapping[str, Any],
    pointer: str,
    leaf: str,
) -> None:
    exists = leaf in parent
    if kind == "add":
        parent[leaf] = op["value"]
    elif kind == "replace":
        if not exists:
            raise PatchOpError(
                index,
                f"replace 目标不存在：{pointer}（新增请用 add）",
            )
        parent[leaf] = op["value"]
    else:  # remove
        if not exists:
            raise PatchOpError(index, f"remove 目标不存在：{pointer}")
        del parent[leaf]


def _apply_list_op(
    parent: list[Any],
    index: int,
    kind: str,
    op: Mapping[str, Any],
    leaf: str,
) -> None:
    if kind == "add":
        if leaf == "-":
            parent.append(op["value"])
        else:
            position = _list_index(index, leaf, len(parent), insert=True)
            parent.insert(position, op["value"])
    elif kind == "replace":
        position = _list_index(index, leaf, len(parent), insert=False)
        parent[position] = op["value"]
    else:  # remove
        position = _list_index(index, leaf, len(parent), insert=False)
        del parent[position]


def _apply_upsert_entity(
    document: dict[str, Any],
    index: int,
    op: Mapping[str, Any],
) -> None:
    collection_pointer = str(op.get("collection") or "")
    entity_id = str(op.get("id") or "")
    if not collection_pointer:
        raise PatchOpError(index, "upsert_entity 需要 collection 字段")
    if not entity_id:
        raise PatchOpError(index, "upsert_entity 需要 id 字段")
    if "value" not in op or not isinstance(op["value"], Mapping):
        raise PatchOpError(index, "upsert_entity 的 value 必须是 object")
    parent, leaf = _resolve_parent(
        document,
        index,
        collection_pointer,
        label="collection",
    )
    if isinstance(parent, dict) and leaf in parent:
        collection = parent[leaf]
    else:
        raise PatchOpError(
            index,
            f"collection 不存在：{collection_pointer}",
        )
    if not (
        isinstance(collection, dict)
        and isinstance(collection.get("items"), dict)
        and isinstance(collection.get("order"), list)
    ):
        raise PatchOpError(
            index,
            f"collection {collection_pointer} 不是 EntityCollection"
            "（需要 items+order）",
        )
    # The identity field inside value must equal the key; the Project
    # schema's collection-identity validator reports any mismatch, so the
    # op itself stays agnostic of the field name.
    collection["items"][entity_id] = dict(op["value"])
    if entity_id not in collection["order"]:
        collection["order"].append(entity_id)


__all__ = ["PatchOpError", "apply_patch_ops"]
