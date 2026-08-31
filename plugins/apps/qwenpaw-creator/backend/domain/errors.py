# -*- coding: utf-8 -*-
"""Typed domain failures mapped to structured HTTP errors by the API layer."""

from __future__ import annotations


class CreatorError(Exception):
    status_code = 400
    code = "CREATOR_ERROR"
    retryable = False

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(CreatorError):
    status_code = 404
    code = "NOT_FOUND"


class ConflictError(CreatorError):
    status_code = 409
    code = "CONFLICT"
    retryable = True


class ReviewPendingError(ConflictError):
    """Normal pause while a generated artifact awaits user review."""

    code = "WAITING_REVIEW"
    retryable = False


class PhaseConflictError(ConflictError):
    code = "PHASE_CONFLICT"


class CasConflictError(ConflictError):
    code = "CAS_CONFLICT"


class PermissionDeniedError(CreatorError):
    status_code = 403
    code = "PERMISSION_DENIED"


class ValidationError(CreatorError):
    status_code = 422
    code = "VALIDATION_ERROR"


class BadRequestError(CreatorError):
    status_code = 400
    code = "BAD_REQUEST"


class StorageIntegrityError(CreatorError):
    status_code = 503
    code = "STORAGE_INTEGRITY_ERROR"


class RuntimeBusyError(CreatorError):
    """A short Runtime transition could not acquire its coordination lock."""

    status_code = 503
    code = "RUNTIME_LOCK_TIMEOUT"
    retryable = True
