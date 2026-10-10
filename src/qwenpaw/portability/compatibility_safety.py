# -*- coding: utf-8 -*-
"""Small safety boundary shared by migration staging and materialization."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit, urlunsplit

_SECRET_NAME = re.compile(
    r"(?i)(?:api[-_]?key|access[-_]?token|auth(?:orization)?|cookie|"
    r"credential|license[-_]?key|pass(?:word|wd)?|private[-_]?key|"
    r"secret|token)",
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?:api[-_]?key|access[-_]?token|auth(?:orization)?|cookie|"
    r"credential|license[-_]?key|pass(?:word|wd)?|private[-_]?key|"
    r"secret|token)"
    r"\s*[:=]\s*[^\s,;]+",
)
_SECRET_VALUE = re.compile(
    r"(?i)\b(?:sk|gh[pousr]|glpat|xox[baprs]|pat)[-_][A-Za-z0-9_-]{12,}\b"
    r"|\bAKIA[0-9A-Z]{16}\b",
)
_SECRET_FLAG = re.compile(
    r"(?i)^(?:--?(?:api[-_]?key|key|license[-_]?key|password|passwd|pass|"
    r"secret|token|auth|credential)|-p)(?:=.+|.+)?$",
)
_URI_USERINFO = re.compile(r"(?i)(?:[a-z][a-z0-9+.-]*:)?//[^\s/@:]+:[^\s/@]+@")
_AUTH_HEADER = re.compile(
    r"(?i)^[A-Za-z0-9-]*(?:auth|token|key)[A-Za-z0-9-]*\s*:",
)
_WEBHOOK_PATH = re.compile(
    r"(?i)^https://(?:hooks\.slack\.com/services/|"
    r"(?:canary\.)?discord(?:app)?\.com/api/webhooks/|"
    r"api\.telegram\.org/bot)",
)


def bounded_plain_text(value: Any, limit: int) -> str:
    """Return bounded text without control characters."""
    return "".join(
        char
        for char in str(value or "")[:limit]
        if ord(char) >= 32 and ord(char) != 127
    ).strip()


def redact_sensitive_text(value: Any, *, limit: int = 32_000) -> str:
    """Return bounded text with common inline credentials removed."""
    text = str(value or "")[:limit]
    text = _SECRET_ASSIGNMENT.sub("<redacted>", text)
    text = _SECRET_VALUE.sub("<redacted>", text)
    text = _URI_USERINFO.sub("//<redacted>@", text)
    return text


def _argument_risk(arguments: Sequence[Any]) -> bool:
    values = [str(item) for item in arguments]
    for index, value in enumerate(values):
        stripped = value.strip()
        if (
            _SECRET_ASSIGNMENT.search(stripped)
            or _SECRET_VALUE.search(stripped)
            or _URI_USERINFO.search(stripped)
            or _AUTH_HEADER.search(stripped)
            or _WEBHOOK_PATH.search(stripped)
        ):
            return True
        if _SECRET_FLAG.match(stripped):
            return True
        if _SECRET_NAME.fullmatch(stripped.lstrip("-").replace("_", "-")):
            if index + 1 < len(values) and values[index + 1].strip():
                return True
    return False


def mcp_inline_secret_risks(
    command: Any,
    args: Any,
    url: Any = "",
    env: Any = None,
    headers: Any = None,
    cwd: Any = "",
) -> list[str]:
    """Identify locations that cannot be safely persisted as plain text."""
    risks: list[str] = []
    command_text = str(command or "")
    if (
        _SECRET_ASSIGNMENT.search(command_text)
        or _SECRET_VALUE.search(command_text)
        or _URI_USERINFO.search(command_text)
    ):
        risks.append("command")
    values = (
        args
        if isinstance(args, Sequence) and not isinstance(args, str)
        else []
    )
    if _argument_risk(values):
        risks.append("args")
    url_text = str(url or "")
    try:
        parsed = urlsplit(url_text)
    except ValueError:
        parsed = None
    if parsed is not None:
        if parsed.username or parsed.password:
            risks.append("url_userinfo")
        if parsed.query:
            risks.append("url_query")
        if parsed.fragment or _WEBHOOK_PATH.search(url_text):
            risks.append("url_path_or_fragment")
    elif url_text:
        risks.append("url")
    if _SECRET_ASSIGNMENT.search(str(cwd or "")) or _SECRET_VALUE.search(
        str(cwd or ""),
    ):
        risks.append("cwd")
    # Environment/header values are encrypted during materialization. Their
    # names are safe to expose; their values never enter the manifest.
    del env, headers
    return list(dict.fromkeys(risks))


def safe_url(value: Any) -> str:
    """Return a secret-free URL descriptor."""
    text = str(value or "")
    if not text:
        return ""
    risks = mcp_inline_secret_risks("", [], text)
    if "url_path_or_fragment" in risks:
        return "<redacted-unsafe-url>"
    try:
        parsed = urlsplit(text)
    except ValueError:
        return "<invalid-url>"
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    query = "<redacted>" if parsed.query else ""
    return urlunsplit((parsed.scheme, host + port, parsed.path, query, ""))


def secret_names(values: Any, *, prefix: str = "") -> list[str]:
    """Return only credential binding names, never values."""
    if not isinstance(values, Mapping):
        return []
    return sorted(
        f"{prefix}{key}" for key in values if _SECRET_NAME.search(str(key))
    )


__all__ = [
    "bounded_plain_text",
    "mcp_inline_secret_risks",
    "redact_sensitive_text",
    "safe_url",
    "secret_names",
]
