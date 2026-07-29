# -*- coding: utf-8 -*-
# pylint: disable=redefined-builtin
"""Custom exception hierarchy for structured error handling."""


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
