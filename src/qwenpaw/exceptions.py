# -*- coding: utf-8 -*-
"""CoPaw exception definitions and converters."""

from typing import Any, Dict, Optional

from agentscope_runtime.engine.schemas.exception import (
    AgentRuntimeErrorException,
    ModelExecutionException,
    ModelTimeoutException,
    UnauthorizedModelAccessException,
    ModelQuotaExceededException,
    ModelContextLengthExceededException,
    UnknownAgentException,
    ExternalServiceException,
)


# ==================== CoPaw Business Exceptions ====================


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
    """Convert exceptions to agentscope_runtime exceptions.

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
