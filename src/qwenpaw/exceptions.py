# -*- coding: utf-8 -*-
"""QwenPaw exception definitions and converters."""

from typing import Any, Dict, Optional


# ==================== Base Exceptions ====================


class AppBaseException(Exception):
    """Top-level base for QwenPaw application exceptions.

    Accepts ``error_code`` / ``detail`` / arbitrary kwargs so that
    handlers can build structured HTTP error responses.
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


class ConfigurationException(AppBaseException):
    """Invalid or missing configuration."""

    def __init__(
        self,
        message: str | None = None,
        *,
        config_key: str | None = None,
        **kwargs: Any,
    ) -> None:
        self.config_key = config_key
        super().__init__(message=message, **kwargs)


class AgentRuntimeErrorException(AppBaseException):
    """Base for runtime/model errors carrying ``error_code`` + ``details``."""

    def __init__(
        self,
        error_code: str | None = None,
        message: str | None = None,
        details: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self.details = details or {}
        super().__init__(message=message, error_code=error_code, **kwargs)


class ModelExecutionException(AgentRuntimeErrorException):
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


class ModelTimeoutException(AgentRuntimeErrorException):
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


class UnauthorizedModelAccessException(AgentRuntimeErrorException):
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


class ModelQuotaExceededException(AgentRuntimeErrorException):
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


class ModelContextLengthExceededException(AgentRuntimeErrorException):
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


class UnknownAgentException(AgentRuntimeErrorException):
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


class ExternalServiceException(AgentRuntimeErrorException):
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


class ModelNotFoundException(AgentRuntimeErrorException):
    """Provider does not host the requested model."""

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


class RateLimitExceededException(AgentRuntimeErrorException):
    """Local rate limiter (semaphore/token bucket) timed out.

    Distinct from :class:`ModelQuotaExceededException`, which represents a
    429 from the provider.
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


class AgentException(AppBaseException):
    """Catch-all for control-flow errors raised by the runner
    (task cancellation, etc.)."""


# ==================== QwenPaw Business Exceptions ====================


class ProviderError(AgentRuntimeErrorException):
    """Exception raised when there's an error with a model provider."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__("PROVIDER_ERROR", message, details)


class ModelFormatterError(AgentRuntimeErrorException):
    """Exception raised when there's an error with model message formatting."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__("MODEL_FORMATTER_ERROR", message, details)


class SystemCommandException(AgentRuntimeErrorException):
    """Exception raised when there's an error with system command execution."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__("SYSTEM_COMMAND_ERROR", message, details)


class ChannelError(ExternalServiceException):
    """Exception raised for channel communication errors."""

    def __init__(
        self,
        channel_name: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize channel error."""
        # Add channel_name to details for better debugging
        if details is None:
            details = {}
        details["channel"] = channel_name

        # Call parent with service_name set to channel_name
        super().__init__(
            service_name=channel_name,
            message=message,
            details=details,
        )


class AgentStateError(AgentRuntimeErrorException):
    """Exception raised for agent state and session errors."""

    def __init__(
        self,
        session_id: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        if details is None:
            details = {}
        # Add session_id to details for better debugging
        details["session_id"] = session_id
        super().__init__("AGENT_STATE_ERROR", message, details)


class SkillsError(AgentRuntimeErrorException):
    """Exception raised for skills management errors."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__("SKILLS_ERROR", message, details)


# ==================== LLM API Exception Converter ====================


def _is_model_related_error(exc: Exception) -> bool:
    """Check if exception is likely related to LLM model execution.

    Args:
        exc: Exception to check

    Returns:
        True if likely a model-related error, False otherwise
    """
    # Check exception type name
    exc_type_name = type(exc).__name__.lower()

    # Common LLM provider exception names
    model_exception_types = [
        "api",
        "model",
        "openai",
        "anthropic",
        "completion",
        "chat",
        "generation",
        "inference",
        "llm",
    ]

    if any(keyword in exc_type_name for keyword in model_exception_types):
        return True

    # Check if has status_code attribute (typical for API errors)
    if hasattr(exc, "status_code"):
        return True

    # Check error message for model-related keywords
    error_msg = str(exc).lower()
    model_keywords = [
        "api",
        "model",
        "token",
        "completion",
        "chat",
        "openai",
        "anthropic",
        "rate limit",
        "quota",
        "context length",
        "authentication",
        "unauthorized",
        "forbidden",
        "timeout",
        "timed out",
    ]

    if any(keyword in error_msg for keyword in model_keywords):
        return True

    return False


def convert_model_exception(  # pylint: disable=too-many-return-statements
    exc: Exception,
    model_name: Optional[str] = None,
) -> AgentRuntimeErrorException:
    """Wrap a model SDK exception in :class:`AgentRuntimeErrorException`.

    Args:
        exc: Original exception
        model_name: Name of the model (optional, defaults to "unknown")

    Returns:
        AgentRuntimeErrorException with original details preserved
    """
    # Build details with original exception info
    details = {
        "original_error_type": type(exc).__name__,
        "original_error_message": str(exc),
    }

    # Level 0: Check if this is a model-related error
    if not _is_model_related_error(exc):
        # Non-model error: wrap as UnknownAgentException
        return UnknownAgentException(
            original_exception=exc,
            details=details,
        )

    # Pydantic ValidationError indicates a malformed request payload (wrong
    # parameter name/type), not an auth/quota issue.  Route it to the generic
    # model execution exception so the underlying message reaches the user
    # instead of being masked as "Unauthorized access".
    if type(exc).__name__ == "ValidationError" and (
        type(exc).__module__.startswith("pydantic")
    ):
        model = model_name or "unknown"
        details["model_name"] = model
        return ModelExecutionException(model, details=details)

    # Extract information for model errors
    status_code = getattr(exc, "status_code", None)
    error_message = str(exc).lower()
    model = model_name or "unknown"
    details["model_name"] = model

    if status_code is not None:
        details["status_code"] = status_code

    # Level 1: Status code mapping (most reliable)
    if status_code in (401, 403):
        return UnauthorizedModelAccessException(model, details=details)

    if status_code == 429:
        return ModelQuotaExceededException(model, details=details)

    # Level 2: Keyword mapping
    if any(
        kw in error_message
        for kw in [
            "unauthorized",
            "authentication",
            "api key",
            "invalid key",
            "forbidden",
        ]
    ):
        return UnauthorizedModelAccessException(model, details=details)

    if any(
        kw in error_message
        for kw in [
            "rate limit",
            "quota",
            "too many requests",
        ]
    ):
        return ModelQuotaExceededException(model, details=details)

    if any(
        kw in error_message
        for kw in [
            "timeout",
            "timed out",
            "deadline exceeded",
        ]
    ):
        return ModelTimeoutException(model, timeout=60, details=details)

    if any(
        kw in error_message
        for kw in [
            "context",
            "maximum context",
            "context window",
            "too many tokens",
        ]
    ):
        return ModelContextLengthExceededException(model, details=details)

    # Level 3: Model-related default catch-all
    return ModelExecutionException(model, details=details)
