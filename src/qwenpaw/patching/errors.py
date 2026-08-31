# -*- coding: utf-8 -*-
"""Stable patch errors with machine-readable conflict details."""

from __future__ import annotations

from .models import PatchConflict


class PatchError(ValueError):
    """A parse, validation or commit error that is safe to show to callers."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        conflicts: tuple[PatchConflict, ...] = (),
        rolled_back: bool = False,
        rollback_errors: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.conflicts = conflicts
        self.rolled_back = rolled_back
        self.rollback_errors = rollback_errors
