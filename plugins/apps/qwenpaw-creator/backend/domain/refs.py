# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Parsers for runtime target locators and persistent workspace references."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import quote, unquote, urlparse

from .errors import ValidationError


_TARGET_RE = re.compile(
    r"^(project|timeline|element|shot|asset|asset-import|analysis):([^/\\]+)$",
)
_ARTIFACT_TARGET_RE = re.compile(r"^artifact:([^\\]+)$")
_WORKSPACE_SCHEMES = frozenset(
    {"project", "asset", "artifact", "analysis"},
)


@dataclass(frozen=True, slots=True)
class TargetRef:
    kind: str
    identifier: str


def parse_target_ref(value: str) -> TargetRef:
    raw = (value or "").strip()
    match = _TARGET_RE.fullmatch(raw)
    if match is not None:
        if ".." in match.group(2):
            raise ValidationError(f"非法 target ref: {value!r}")
        return TargetRef(match.group(1), match.group(2))

    artifact_match = _ARTIFACT_TARGET_RE.fullmatch(raw)
    if artifact_match is None:
        raise ValidationError(f"非法 target ref: {value!r}")
    identifier = artifact_match.group(1)
    if (
        ".." in identifier
        or identifier.startswith("/")
        or identifier.endswith("/")
        or "//" in identifier
        or any(part in {"", ".", ".."} for part in identifier.split("/"))
    ):
        raise ValidationError(f"非法 target ref: {value!r}")
    return TargetRef("artifact", identifier)


def validate_workspace_ref(value: str) -> str:
    raw = (value or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme not in _WORKSPACE_SCHEMES or not parsed.netloc:
        raise ValidationError(f"非法 workspace ref: {value!r}")
    if ".." in unquote(parsed.path):
        raise ValidationError(f"非法 workspace ref 路径: {value!r}")
    return raw


def safe_relative_path(value: str) -> str:
    original = (value or "").replace("\\", "/")
    if original.startswith("/"):
        raise ValidationError(f"非法 workspace path: {value!r}")
    raw = original.strip("/")
    path = PurePosixPath(raw)
    if (
        not raw
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValidationError(f"非法 workspace path: {value!r}")
    return path.as_posix()


def workspace_asset_ref(asset_id: str, version_id: str) -> str:
    return f"asset://{quote(asset_id, safe='')}@{quote(version_id, safe='')}"


def workspace_artifact_ref(slot_id: str, version_id: str) -> str:
    return f"artifact://{quote(slot_id, safe='')}@{quote(version_id, safe='')}"
