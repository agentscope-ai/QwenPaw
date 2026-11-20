# -*- coding: utf-8 -*-
"""Driver subsystem errors."""

from __future__ import annotations

from ssl import SSLCertVerificationError
from typing import Any

from httpx import HTTPStatusError

from ..exceptions import (
    AgentRuntimeErrorException,
    AppBaseException,
    ConfigurationException,
)


def driver_error_diagnostic(error: BaseException) -> str:
    """Summarize failure codes and locations without exception payloads."""
    details = []
    pending = [error]
    seen = set()
    while pending and len(seen) < 8:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        detail = type(current).__name__
        if isinstance(current, HTTPStatusError):
            detail += f" (HTTP {current.response.status_code})"
        elif isinstance(current, SSLCertVerificationError):
            code = getattr(current, "verify_code", None)
            if isinstance(code, int):
                detail += f" (verify_code={code})"
        elif isinstance(current, OSError) and isinstance(current.errno, int):
            detail += f" (errno={current.errno})"
        tb = current.__traceback__
        if tb is not None:
            while tb.tb_next is not None:
                tb = tb.tb_next
            filename = tb.tb_frame.f_code.co_filename.replace("\\", "/")
            detail += f" at {filename.rsplit('/', 1)[-1]!r}:{tb.tb_lineno}"
        details.append(detail)
        if isinstance(current, BaseExceptionGroup):
            pending.extend(reversed(current.exceptions[:8]))
        cause = current.__cause__
        if cause is None and not current.__suppress_context__:
            cause = current.__context__
        if cause is not None:
            pending.append(cause)
    return " / ".join(details)


class DriverError(AppBaseException):
    """Base class for Driver subsystem errors."""


class DriverConfigurationError(ConfigurationException, DriverError):
    """Driver configuration, declaration, or registry setup failed."""

    def __init__(
        self,
        message: str | None = None,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("error_code", "DRIVER_CONFIGURATION_ERROR")
        super().__init__(message=message, **kwargs)


class DriverRuntimeError(AgentRuntimeErrorException, DriverError):
    """Driver runtime operation failed."""

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            error_code="DRIVER_RUNTIME_ERROR",
            message=message,
            details=details,
            **kwargs,
        )


class DriverCardError(DriverConfigurationError):
    """DriverCard parse, validation, or persistence failed."""


class DriverNotFoundError(DriverRuntimeError):
    def __init__(self, name: str) -> None:
        super().__init__(f"Driver not found: {name}")
        self.name = name


class UnsupportedProtocolError(DriverConfigurationError):
    def __init__(self, protocol: str) -> None:
        super().__init__(f"Unsupported driver protocol: {protocol}")
        self.protocol = protocol


class UnsupportedCredentialKindError(DriverConfigurationError):
    def __init__(self, kind: str) -> None:
        super().__init__(f"Unsupported credential kind: {kind}")
        self.kind = kind


class DriverCredentialProviderError(DriverConfigurationError):
    """Credential provider registry/factory failed."""


class CredentialNotFoundError(DriverRuntimeError):
    def __init__(self, ref: str) -> None:
        super().__init__(f"Credential not found: {ref}")
        self.ref = ref


class PermissionDeniedError(DriverRuntimeError):
    def __init__(self, driver_name: str, subject: str) -> None:
        super().__init__(f"Permission denied: {subject} -> {driver_name}")
        self.driver_name = driver_name
        self.subject = subject


class DriverPermissionDeniedError(PermissionDeniedError):
    def __init__(
        self,
        driver_name: str,
        subject: str,
        operation: str,
        reason: str = "",
    ) -> None:
        super().__init__(driver_name, subject)
        self.operation = operation
        self.reason = reason or "Driver policy denied the request."

    def to_user_message(self) -> str:
        return (
            "Driver policy denied the request.\n\n"
            f"- Driver: `{self.driver_name}`\n"
            f"- Operation: `{self.operation}`\n"
            f"- Reason: {self.reason}\n\n"
            "This denial applies only to the current tool call under the "
            "policy observed at execution time."
        )

    def to_result(self) -> dict[str, str | bool]:
        return {
            "ok": False,
            "type": "driver_policy_denied",
            "driver_id": self.driver_name,
            "operation": self.operation,
            "message": self.to_user_message(),
        }


class ApprovalRequiredError(DriverRuntimeError):
    """Raised when policy returns ask but no approval requester is wired."""


class OAuthRequiredError(DriverRuntimeError):
    def __init__(self, ref: str) -> None:
        super().__init__(f"OAuth authorization required for credential: {ref}")
        self.ref = ref
