# -*- coding: utf-8 -*-
# pylint: disable=redefined-builtin
"""Custom exception hierarchy for structured error handling."""

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


def redact_url(url: str) -> str:
    """Strip credential query parameters before exposing a URL in errors."""
    base, sep, query = url.partition("?")
    if not sep:
        return url
    kept = [
        kv
        for kv in query.split("&")
        if not kv.lower().startswith(("key=", "token=", "api_key="))
    ]
    return f"{base}?{'&'.join(kept)}" if kept else base


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
    ):
        super().__init__(message, code="MODEL_ERROR", status_code=502)
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
