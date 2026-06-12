# -*- coding: utf-8 -*-
"""Driver subsystem errors."""

from __future__ import annotations


class DriverError(Exception):
    """Base class for Driver subsystem errors."""


class DriverCardError(DriverError):
    """DriverCard parse, validation, or persistence failed."""


class DriverNotFoundError(DriverError):
    def __init__(self, name: str) -> None:
        super().__init__(f"Driver not found: {name}")
        self.name = name


class UnsupportedProtocolError(DriverError):
    def __init__(self, protocol: str) -> None:
        super().__init__(f"Unsupported driver protocol: {protocol}")
        self.protocol = protocol


class UnsupportedCredentialKindError(DriverError):
    def __init__(self, kind: str) -> None:
        super().__init__(f"Unsupported credential kind: {kind}")
        self.kind = kind


class DriverCredentialProviderError(DriverError):
    """Credential provider registry/factory failed."""


class CredentialNotFoundError(DriverError):
    def __init__(self, ref: str) -> None:
        super().__init__(f"Credential not found: {ref}")
        self.ref = ref


class PermissionDeniedError(DriverError):
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
            f"- Subject: `{self.subject}`\n"
            f"- Reason: {self.reason}\n\n"
            "This denial applies only to the current tool call under the "
            "policy observed at execution time."
        )

    def to_result(self) -> dict[str, str | bool]:
        return {
            "ok": False,
            "type": "driver_policy_denied",
            "driver_id": self.driver_name,
            "subject": self.subject,
            "operation": self.operation,
            "message": self.to_user_message(),
        }


class ApprovalRequiredError(DriverError):
    """Raised when policy returns ask but no approval requester is wired."""


class OAuthRequiredError(DriverError):
    def __init__(self, ref: str) -> None:
        super().__init__(f"OAuth authorization required for credential: {ref}")
        self.ref = ref
