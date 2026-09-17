# -*- coding: utf-8 -*-
"""供应商配置的 API 安全投影。"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .provider import ProviderInfo

_SENSITIVE_KEY = re.compile(
    r"(?:api[_-]?key|auth(?:orization)?|token|secret|password|cookie|credential"
    r"|(?:^|[_-])(?:key|sig|signature)(?:$|[_-]))",
    re.IGNORECASE,
)
_MASKED_SECRET = re.compile(r"^[^*]*\*{3,}$")
_PUBLIC_PROVIDER_NAMES = {
    "qwenpaw-local": "WeldonAgent Local",
    "copaw-local": "WeldonAgent Local",
}


class SensitiveListEditError(ValueError):
    """无法安全合并没有稳定元素标识的敏感列表。"""


def is_masked_secret(value: str) -> bool:
    """判断输入是否为旧版界面回传的掩码占位符。"""
    return bool(_MASKED_SECRET.fullmatch(value.strip()))


def _collect_sensitive(value: Any, *, sensitive: bool = False) -> set[str]:
    secrets: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            secrets.update(
                _collect_sensitive(
                    item,
                    sensitive=sensitive or bool(_SENSITIVE_KEY.search(str(key))),
                )
            )
    elif isinstance(value, (list, tuple)):
        for item in value:
            secrets.update(_collect_sensitive(item, sensitive=sensitive))
    elif sensitive and isinstance(value, str) and value:
        secrets.add(value)
    return secrets


def _redact_known_secrets(value: str, secrets: set[str]) -> str:
    result = value
    for secret in sorted(secrets, key=len, reverse=True):
        result = result.replace(secret, "[redacted]")
    return result


def _sanitize_url(value: str, secrets: set[str]) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return value
    if not parsed.scheme or not parsed.netloc:
        return value
    hostname = parsed.hostname or ""
    if ":" in hostname:
        hostname = f"[{hostname}]"
    try:
        port = parsed.port
    except ValueError:
        return "[redacted-url]"
    if port is not None:
        hostname = f"{hostname}:{port}"
    query = urlencode(
        [
            (
                key,
                "[redacted]"
                if _SENSITIVE_KEY.search(key)
                else _redact_known_secrets(item, secrets),
            )
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        ]
    )
    return urlunsplit((parsed.scheme, hostname, parsed.path, query, ""))


def _sanitize(value: Any, secrets: set[str]) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _sanitize(item, secrets)
            for key, item in value.items()
            if not _SENSITIVE_KEY.search(str(key))
        }
    if isinstance(value, list):
        return [_sanitize(item, secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize(item, secrets) for item in value)
    if isinstance(value, str):
        sanitized_url = _sanitize_url(value, secrets)
        return _redact_known_secrets(sanitized_url, secrets)
    return value


def preserve_sensitive_values(
    existing: Any,
    submitted: Any,
    *,
    _known_secrets: set[str] | None = None,
) -> Any:
    """将未显式提交的敏感嵌套值从现有配置合并回新配置。"""
    known_secrets = _known_secrets or _collect_sensitive(existing)
    if isinstance(existing, list) and isinstance(submitted, list):
        projected = _sanitize(existing, known_secrets)
        if projected != existing:
            if submitted == projected:
                return existing
            raise SensitiveListEditError
        return submitted
    if not isinstance(existing, dict) or not isinstance(submitted, dict):
        return submitted
    result = dict(submitted)
    for key, value in existing.items():
        if _SENSITIVE_KEY.search(str(key)):
            result.setdefault(key, value)
        elif key in result:
            result[key] = preserve_sensitive_values(
                value,
                result[key],
                _known_secrets=known_secrets,
            )
    return result


def project_provider_info(provider: ProviderInfo) -> ProviderInfo:
    """复制并脱敏供应商信息，不修改运行时供应商实例。"""
    payload = provider.model_dump()
    payload["name"] = _PUBLIC_PROVIDER_NAMES.get(provider.id, provider.name)
    secrets = _collect_sensitive(payload)
    payload["api_key_configured"] = bool(provider.api_key)
    payload["api_key"] = ""
    payload["base_url"] = _redact_known_secrets(
        _sanitize_url(provider.base_url, secrets),
        secrets,
    )
    payload["custom_headers"] = _sanitize(provider.custom_headers, secrets)
    payload["generate_kwargs"] = _sanitize(provider.generate_kwargs, secrets)
    payload["meta"] = _sanitize(provider.meta, secrets)
    return ProviderInfo.model_validate(payload)


def sanitize_provider_error(_message: object) -> str:
    """管理接口只返回稳定错误，不透传供应商或连接层消息。"""
    return "Provider operation failed"
