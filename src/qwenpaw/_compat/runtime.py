# -*- coding: utf-8 -*-
"""Shim for symbols previously exported by ``agentscope_runtime``.

The ``agentscope-runtime`` package was folded into ``agentscope`` 2.0
(see ``agentscope.app`` for the FastAPI factory and ``agentscope.app._schema``
for request/response schemas).  However, the new schemas are not drop-in
equivalents of the old ones — ``AgentRequest`` was OpenAI-style while
``ChatRequest`` is a much smaller envelope, and ``Message`` (a server-side
streaming response wrapper) has no direct counterpart at all.

To unblock the migration we expose plain-Python stand-ins here so the
codebase keeps importing; each call site will be revisited as part of the
2.0 channel/runner rewrite.

TODO(as2-migration): delete this module once every caller has been ported
to ``agentscope.app._schema`` / ``agentscope.event`` / ``agentscope.message``.
"""
from __future__ import annotations

from typing import Any


class AppBaseException(Exception):  # pragma: no cover - migration shim
    """Stand-in for ``agentscope_runtime.engine.schemas.exception.AppBaseException``.

    Accepts arbitrary kwargs to match the original constructor surface
    (the runtime version carried ``error_code`` / ``detail`` / ``message``
    fields used for HTTP error responses).
    """

    def __init__(
        self,
        message: str | None = None,
        **kwargs: Any,
    ) -> None:
        self.message = message
        self.error_code = kwargs.pop("error_code", None)
        self.detail = kwargs.pop("detail", None)
        for key, value in kwargs.items():
            setattr(self, key, value)
        super().__init__(message or "")


class ConfigurationException(AppBaseException):  # pragma: no cover
    """Stand-in for ``ConfigurationException``.

    Original signature was ``ConfigurationException(config_key=..., message=...)``;
    we keep ``config_key`` as an attribute and forward ``message`` to the
    base class so ``str(exc)`` still surfaces a useful message.
    """

    def __init__(
        self,
        message: str | None = None,
        *,
        config_key: str | None = None,
        **kwargs: Any,
    ) -> None:
        self.config_key = config_key
        super().__init__(message=message, **kwargs)


# ---------------------------------------------------------------------------
# Agent runtime / model exception stubs.
# Used by ``qwenpaw.exceptions`` to wrap upstream LLM and runtime errors.
# Constructor signatures mirror the agentscope-runtime originals so that
# call sites keep type-checking and ``str(exc)`` stays useful.
# ---------------------------------------------------------------------------


class AgentRuntimeErrorException(AppBaseException):  # pragma: no cover
    """Stand-in for the runtime's ``AgentRuntimeErrorException``.

    Original signature is roughly ``(error_code, message, details=None)``.
    """

    def __init__(
        self,
        error_code: str | None = None,
        message: str | None = None,
        details: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self.details = details or {}
        super().__init__(message=message, error_code=error_code, **kwargs)


class ModelExecutionException(AgentRuntimeErrorException):  # pragma: no cover
    """Generic model execution failure (e.g. provider returned 5xx)."""

    def __init__(
        self,
        model: str,
        details: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self.model = model
        super().__init__(
            error_code="MODEL_EXECUTION_ERROR",
            message=f"Model '{model}' execution failed",
            details=details,
            **kwargs,
        )


class ModelTimeoutException(AgentRuntimeErrorException):  # pragma: no cover
    """LLM request exceeded the configured timeout."""

    def __init__(
        self,
        model: str,
        timeout: float | int | None = None,
        details: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self.model = model
        self.timeout = timeout
        super().__init__(
            error_code="MODEL_TIMEOUT",
            message=f"Model '{model}' timed out after {timeout}s",
            details=details,
            **kwargs,
        )


class UnauthorizedModelAccessException(  # pragma: no cover
    AgentRuntimeErrorException,
):
    """401/403 from the LLM provider."""

    def __init__(
        self,
        model: str,
        details: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self.model = model
        super().__init__(
            error_code="UNAUTHORIZED_MODEL_ACCESS",
            message=f"Unauthorized access to model '{model}'",
            details=details,
            **kwargs,
        )


class ModelQuotaExceededException(  # pragma: no cover
    AgentRuntimeErrorException,
):
    """429/quota exceeded from the LLM provider."""

    def __init__(
        self,
        model: str,
        details: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self.model = model
        super().__init__(
            error_code="MODEL_QUOTA_EXCEEDED",
            message=f"Quota exceeded for model '{model}'",
            details=details,
            **kwargs,
        )


class ModelContextLengthExceededException(  # pragma: no cover
    AgentRuntimeErrorException,
):
    """Prompt exceeded the model's context window."""

    def __init__(
        self,
        model: str,
        details: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self.model = model
        super().__init__(
            error_code="MODEL_CONTEXT_LENGTH_EXCEEDED",
            message=f"Context length exceeded for model '{model}'",
            details=details,
            **kwargs,
        )


class UnknownAgentException(AgentRuntimeErrorException):  # pragma: no cover
    """Catch-all when an upstream error cannot be classified."""

    def __init__(
        self,
        original_exception: Exception | None = None,
        details: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self.original_exception = original_exception
        msg = (
            str(original_exception)
            if original_exception is not None
            else "Unknown agent error"
        )
        super().__init__(
            error_code="UNKNOWN_AGENT_ERROR",
            message=msg,
            details=details,
            **kwargs,
        )


class ExternalServiceException(AgentRuntimeErrorException):  # pragma: no cover
    """Error talking to an external dependency (e.g. a channel)."""

    def __init__(
        self,
        service_name: str | None = None,
        message: str | None = None,
        details: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self.service_name = service_name
        super().__init__(
            error_code="EXTERNAL_SERVICE_ERROR",
            message=message or f"External service '{service_name}' error",
            details=details,
            **kwargs,
        )


class ModelNotFoundException(AgentRuntimeErrorException):  # pragma: no cover
    """Provider does not host the requested model.

    Original signature was ``(model_name, details=None)`` — preserved here
    because qwenpaw's provider manager calls it with those kwargs.
    """

    def __init__(
        self,
        model_name: str,
        details: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self.model_name = model_name
        super().__init__(
            error_code="MODEL_NOT_FOUND",
            message=f"Model '{model_name}' not found",
            details=details,
            **kwargs,
        )


class RateLimitExceededException(AgentRuntimeErrorException):  # pragma: no cover
    """Local rate limiter (semaphore/token bucket) timed out.

    Distinct from :class:`ModelQuotaExceededException`, which represents a
    429 from the provider.  Subclassed by qwenpaw's internal acquire-timeout
    error in ``retry_chat_model``.
    """

    def __init__(
        self,
        message: str | None = None,
        details: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            error_code="RATE_LIMIT_EXCEEDED",
            message=message or "Rate limit exceeded",
            details=details,
            **kwargs,
        )


class AgentException(AppBaseException):  # pragma: no cover
    """Catch-all for control-flow errors raised by qwenpaw's runner
    (task cancellation, etc.).  Not a model error — sits alongside the
    other ``AppBaseException`` subclasses rather than under
    ``AgentRuntimeErrorException`` so the runner's ``except AppBaseException``
    block still catches it.
    """
