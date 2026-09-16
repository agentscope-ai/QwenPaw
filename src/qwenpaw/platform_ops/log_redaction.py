# -*- coding: utf-8 -*-
"""管理员日志响应的集中脱敏规则。"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

REDACTED = "[REDACTED]"
REDACTED_PATH = "[REDACTED_PATH]"

_HEADER_PATTERN = re.compile(
    r"(?i)\b(authorization|proxy-authorization|cookie|set-cookie)"
    r"\s*[:=]\s*[^\r\n|]+"
)
_SENSITIVE_ASSIGNMENT_PATTERN = re.compile(
    r"(?ix)"
    r"(?P<prefix>"
    r"[\"']?"
    r"(?:[a-z][a-z0-9_-]*[_-])?"
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password|credential)"
    r"[\"']?\s*[:=]\s*"
    r")"
    r"(?P<quote>[\"']?)"
    r"(?P<value>[^\s,;}\]\"']+)"
    r"(?P=quote)"
)
_BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_COMMON_TOKEN_PATTERN = re.compile(
    r"(?x)"
    r"(?:sk-(?:proj-)?[A-Za-z0-9_-]{16,})"
    r"|(?:gh[pousr]_[A-Za-z0-9]{16,})"
    r"|(?:xox[baprs]-[A-Za-z0-9-]{12,})"
    r"|(?:eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})"
)
_USER_IDENTIFIER_PATTERN = re.compile(
    r"(?ix)"
    r"(?P<prefix>[\"']?"
    r"(?:owner_user_id|platform_user_id|recipient_user_id|created_by|user_id)"
    r"[\"']?\s*[:=]\s*[\"']?)"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
_WINDOWS_PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(?:[A-Za-z]:[\\/]|\\\\)[^\s<>|\"']+"
)
_POSIX_PATH_PATTERN = re.compile(
    r"(?<![:A-Za-z0-9_])"
    r"/(?:home|Users|root|tmp|var|etc|opt|srv|mnt|private|Volumes)"
    r"(?:/[^\s<>|\"'?]+)+"
)
_SENSITIVE_FIELD_PARTS = (
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "user_id",
    "external_subject_id",
)


def _redact_header(match: re.Match[str]) -> str:
    return f"{match.group(1)}: {REDACTED}"


def _redact_assignment(match: re.Match[str]) -> str:
    quote = match.group("quote")
    return f"{match.group('prefix')}{quote}{REDACTED}{quote}"


def redact_log_text(text: str, *, secret_values: Iterable[str] = ()) -> str:
    """移除日志响应中的凭据和宿主绝对路径。"""
    redacted = text
    for value in sorted(
        {str(item) for item in secret_values if len(str(item)) >= 4},
        key=len,
        reverse=True,
    ):
        redacted = redacted.replace(value, REDACTED)
    redacted = _HEADER_PATTERN.sub(_redact_header, redacted)
    redacted = _SENSITIVE_ASSIGNMENT_PATTERN.sub(_redact_assignment, redacted)
    redacted = _BEARER_PATTERN.sub(f"Bearer {REDACTED}", redacted)
    redacted = _COMMON_TOKEN_PATTERN.sub(REDACTED, redacted)
    redacted = _USER_IDENTIFIER_PATTERN.sub(
        lambda match: f"{match.group('prefix')}{REDACTED}",
        redacted,
    )
    redacted = _WINDOWS_PATH_PATTERN.sub(REDACTED_PATH, redacted)
    return _POSIX_PATH_PATTERN.sub(REDACTED_PATH, redacted)


def redact_diagnostic_value(value: Any) -> Any:
    """递归清理诊断快照中的凭据、宿主路径和身份标识。"""
    if isinstance(value, Mapping):
        redacted = {}
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            redacted[str(key)] = (
                REDACTED
                if any(part in normalized for part in _SENSITIVE_FIELD_PARTS)
                else redact_diagnostic_value(item)
            )
        return redacted
    if isinstance(value, (list, tuple)):
        return [redact_diagnostic_value(item) for item in value]
    if isinstance(value, str):
        return redact_log_text(value)
    return value
