# -*- coding: utf-8 -*-
# pylint: disable=redefined-builtin
"""Custom exception hierarchy for structured error handling."""

import re
from urllib.parse import unquote

UPSTREAM_STATUS_HINTS = {
    400: "请求被上游拒绝（参数或请求体不合法），请检查模型名称与协议是否匹配",
    401: "鉴权失败：API Key 缺失或无效，请在模型配置中核对 API Key",
    403: "权限不足：API Key 有效但无该模型/接口权限，或账户欠费",
    404: "未找到模型或端点：请检查 Base URL 和模型名称是否正确",
    429: "上游限流或额度耗尽，请稍后重试或检查账户额度",
}


def upstream_status_hint(status_code: int) -> str:
    """Human-readable diagnosis for a gateway HTTP status, or ``""``."""
    return UPSTREAM_STATUS_HINTS.get(status_code, "")


# Query parameters that carry a credential or a pre-signed grant.  Object
# storage vendors put the whole authorization into the URL query string
# (Aliyun OSS ``OSSAccessKeyId``/``Signature``, AWS S3 ``X-Amz-*``), so a
# signed URL leaked into an error message is a usable grant (issue #8592).
_SECRET_QUERY_NAMES = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "key",
        "ossaccesskeyid",
        "security-token",
        "sig",
        "signature",
        "token",
        "x-amz-credential",
        "x-amz-security-token",
        "x-amz-signature",
        "x-oss-credential",
        "x-oss-security-token",
        "x-oss-signature",
    },
)

_URL_IN_TEXT = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)


def _redact_query(query: str) -> str:
    """The query string with credential/grant parameters removed."""
    return "&".join(
        kv
        for kv in query.split("&")
        if unquote(kv.partition("=")[0]).strip().casefold()
        not in _SECRET_QUERY_NAMES
    )


def redact_url(url: str) -> str:
    """Strip credential and signature query parameters from a URL.

    Signature parameters are matched case-insensitively and regardless of
    encoding, because both OSS and S3 accept mixed spellings.  A fragment
    is scrubbed too: OAuth-style redirects carry the token after ``#``.
    """
    base, sep, rest = url.partition("?")
    if not sep:
        head, hash_sep, fragment = url.partition("#")
        if not hash_sep:
            return url
        redacted = _redact_query(fragment)
        return f"{head}#{redacted}" if redacted else head
    query, hash_sep, fragment = rest.partition("#")
    kept = _redact_query(query)
    redacted = f"{base}?{kept}" if kept else base
    return f"{redacted}#{fragment}" if hash_sep else redacted


def redact_urls(text: str) -> str:
    """Redact every embedded URL's credentials in free-form error text."""
    if not text:
        return text
    return _URL_IN_TEXT.sub(
        lambda match: redact_url(match.group(0)),
        text,
    )


class AppError(Exception):
    """Base application exception with error code and HTTP status."""

    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_ERROR",
        status_code: int = 500,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class AgentError(AppError):
    def __init__(self, message: str, agent_name: str = ""):
        super().__init__(message, code="AGENT_ERROR", status_code=500)
        self.agent_name = agent_name


class ModelError(AppError):
    def __init__(
        self,
        message: str,
        model_name: str = "",
        retryable: bool = True,
        code: str = "MODEL_ERROR",
    ):
        super().__init__(message, code=code, status_code=502)
        self.model_name = model_name
        # Permanent errors (e.g. upstream 4xx client errors) should be
        # marked non-retryable so pollers and other callers can fail fast
        # instead of waiting until timeout.
        self.retryable = retryable


class ValidationError(AppError):
    def __init__(self, message: str):
        super().__init__(message, code="VALIDATION_ERROR", status_code=422)


class TimeoutError(AppError):
    def __init__(self, message: str, operation: str = ""):
        super().__init__(message, code="TIMEOUT_ERROR", status_code=504)
        self.operation = operation
