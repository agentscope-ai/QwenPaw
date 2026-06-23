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


class HookCycleError(AgentRuntimeErrorException):
    """Raised when ``before``/``after`` constraints contain a cycle."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__("HOOK_CYCLE_ERROR", message, details)


class SkillConflictError(SkillsError):
    """Raised when an import or save operation hits a renameable conflict."""

    def __init__(self, detail: Dict[str, Any]) -> None:
        super().__init__(
            message=str(detail.get("message") or "Skill conflict"),
            details=detail,
        )
        self.detail = detail


class SkillImportCancelled(SkillsError):
    """Raised when a skill import task is cancelled by user."""

    def __init__(
        self,
        message: str = "Skill import cancelled by user",
    ) -> None:
        super().__init__(message=message)


class SkillScanError(SkillsError):
    """Raised when a skill fails a security scan and blocking is enabled."""

    def __init__(self, result: Any) -> None:
        self.result = result
        findings = getattr(result, "findings", [])
        skill_name = getattr(result, "skill_name", "unknown")
        max_severity = getattr(result, "max_severity", None)
        max_sev_str = (
            getattr(max_severity, "value", "UNKNOWN")
            if max_severity
            else "UNKNOWN"
        )

        def _loc(f: Any) -> str:
            ln = getattr(f, "line_number", None)
            fp = getattr(f, "file_path", "")
            return f"({fp}:{ln})" if ln is not None else f"({fp})"

        findings_summary = "; ".join(
            f"[{f.severity.value}] {f.title} {_loc(f)}" for f in findings[:5]
        )
        truncated = (
            f" (and {len(findings) - 5} more)" if len(findings) > 5 else ""
        )
        msg = (
            f"Security scan of skill '{skill_name}' found "
            f"{len(findings)} issue(s) "
            f"(max severity: {max_sev_str}): "
            f"{findings_summary}{truncated}"
        )
        super().__init__(message=msg)


# ==================== Command Execution Exceptions ====================


class CommandExecutionError(AgentRuntimeErrorException):
    """Raised when a shell command exits with a non-zero return code."""

    def __init__(
        self,
        command: "Any",
        message: str,
        *,
        returncode: Optional[int] = None,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self.command = (
            list(command) if not isinstance(command, list) else command
        )
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(
            "COMMAND_EXECUTION_ERROR",
            message,
            details={
                "command": self.command,
                "returncode": returncode,
                "stdout": stdout[:500] if stdout else "",
                "stderr": stderr[:500] if stderr else "",
            },
        )


class ProcessLaunchError(AgentRuntimeErrorException):
    """Raised when a subprocess cannot be started."""

    def __init__(
        self,
        command: "Any",
        message: str,
    ) -> None:
        self.command = (
            list(command) if not isinstance(command, list) else command
        )
        super().__init__(
            "PROCESS_LAUNCH_ERROR",
            message,
            details={"command": self.command},
        )


# ==================== Sandbox / Security Exceptions ====================


class SandboxViolationError(AppBaseException):
    """Raised when a tool call violates sandbox boundaries."""

    def __init__(self, message: str = "Sandbox violation") -> None:
        super().__init__(message=message, error_code="SANDBOX_VIOLATION")


# ==================== Channel Exceptions ====================


class QQApiError(ChannelError):
    """HTTP error returned by QQ Bot API."""

    def __init__(self, path: str, status: int, data: Any) -> None:
        self.path = path
        self.status = status
        self.data = data
        super().__init__(
            channel_name="qq",
            message=f"QQ API error: {path} returned {status}",
            details={"path": path, "status": status, "data": data},
        )


# ==================== ACP Exceptions ====================


class ACPError(ExternalServiceException):
    """Base for Agent Communication Protocol errors."""

    def __init__(self, message: str, *, agent: Optional[str] = None) -> None:
        self.agent = agent
        super().__init__(
            service_name="acp",
            message=message,
            details={"agent": agent} if agent else None,
        )


class ACPConfigurationError(ACPError):
    """ACP configuration is missing or invalid."""


class ACPTransportError(ACPError):
    """ACP transport-level failure (network, connection)."""


class ACPProtocolError(ACPError):
    """ACP protocol violation (malformed message, unexpected state)."""


class ACPSessionError(ACPError):
    """ACP session error (not found, expired, invalid state)."""


# ==================== Backup Exceptions ====================


class BackupConflictError(AppBaseException):
    """Raised when an imported backup's ID already exists on disk."""

    def __init__(self, existing_meta: Any) -> None:
        self.existing_meta = existing_meta
        meta_id = getattr(existing_meta, "id", "unknown")
        super().__init__(
            message=f"backup_conflict: {meta_id}",
            error_code="BACKUP_CONFLICT",
        )


class BackupValidationError(AppBaseException):
    """Raised for user-actionable backup validation failures."""

    def __init__(
        self,
        code: str,
        message: str,
        details: Optional[Dict[str, object]] = None,
    ) -> None:
        self.code = code
        self.details = details
        super().__init__(
            message=message,
            error_code=f"BACKUP_VALIDATION_{code}",
        )


# ==================== Misc Runtime Exceptions ====================


class PrdValidationError(AppBaseException):
    """Raised when prd.json does not conform to the expected schema."""

    def __init__(self, message: str = "PRD validation failed") -> None:
        super().__init__(message=message, error_code="PRD_VALIDATION_ERROR")


class RestartInProgressError(AgentStateError):
    """Raised when /daemon restart is invoked while another restart runs."""

    def __init__(self, message: str = "Restart already in progress") -> None:
        super().__init__(
            session_id="",
            message=message,
        )


class DirectUrlDownloadRejectedError(AgentRuntimeErrorException):
    """Raised when direct URL download cannot be proven small enough."""

    def __init__(
        self,
        reason: str,
        content_length: Optional[int] = None,
        status: Optional[int] = None,
    ) -> None:
        self.content_length = content_length
        self.status = status
        super().__init__(
            "DIRECT_URL_DOWNLOAD_REJECTED",
            reason,
            details={
                "content_length": content_length,
                "status": status,
            },
        )


class LspError(AgentRuntimeErrorException):
    """Raised when the LSP server returns a JSON-RPC error or dies."""

    def __init__(self, message: str = "LSP error") -> None:
        super().__init__("LSP_ERROR", message)


# ==================== LLM API Exception Converter ====================

_ERROR_SUMMARY_MAX_LEN = 200


def _extract_error_summary(exc: Exception) -> str:
    """Extract a short, user-friendly summary from an API exception.

    Tries the provider's structured error message first, then
    falls back to the first meaningful line of ``str(exc)``.
    """
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error", body)
        if isinstance(err, dict):
            msg = err.get("message")
            if msg and isinstance(msg, str):
                return msg[:_ERROR_SUMMARY_MAX_LEN]

    raw = str(exc)
    for line in raw.splitlines():
        first_line = line.strip()
        if first_line:
            return first_line[:_ERROR_SUMMARY_MAX_LEN]
    return raw.strip()[:_ERROR_SUMMARY_MAX_LEN]


def _append_error_detail(
    converted: "AgentRuntimeErrorException",
    exc: Exception,
) -> "AgentRuntimeErrorException":
    """Append original error summary to *converted*.message."""
    summary = _extract_error_summary(exc)
    if summary:
        converted.message = f"{converted.message}. Reason: {summary}"
    return converted


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
        return _append_error_detail(
            ModelExecutionException(model, details=details),
            exc,
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
        return _append_error_detail(
            UnauthorizedModelAccessException(model, details=details),
            exc,
        )

    if status_code == 429:
        return _append_error_detail(
            ModelQuotaExceededException(model, details=details),
            exc,
        )

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
        return _append_error_detail(
            UnauthorizedModelAccessException(
                model,
                details=details,
            ),
            exc,
        )

    if any(
        kw in error_message
        for kw in [
            "rate limit",
            "quota",
            "too many requests",
        ]
    ):
        return _append_error_detail(
            ModelQuotaExceededException(model, details=details),
            exc,
        )

    if any(
        kw in error_message
        for kw in [
            "timeout",
            "timed out",
            "deadline exceeded",
        ]
    ):
        return _append_error_detail(
            ModelTimeoutException(
                model,
                timeout=60,
                details=details,
            ),
            exc,
        )

    if any(
        kw in error_message
        for kw in [
            "context",
            "maximum context",
            "context window",
            "too many tokens",
        ]
    ):
        return _append_error_detail(
            ModelContextLengthExceededException(
                model,
                details=details,
            ),
            exc,
        )

    # Level 3: Model-related default catch-all
    return _append_error_detail(
        ModelExecutionException(model, details=details),
        exc,
    )
