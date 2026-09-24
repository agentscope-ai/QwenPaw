# -*- coding: utf-8 -*-
"""Failures that must never silently select another storage backend."""


class StorageError(RuntimeError):
    """Base storage failure."""


class StorageIdentityError(StorageError):
    """The namespace belongs to another deployment or dataset."""


class StorageMaintenanceError(StorageError):
    """Writes are fenced while the dataset is being migrated."""


class MigrationConflictError(StorageError):
    """The target changed or replacement has not been confirmed."""
