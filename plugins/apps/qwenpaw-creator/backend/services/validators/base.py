# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    message: str
    target_ref: str | None = None


@dataclass(frozen=True, slots=True)
class ValidationReport:
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.issues

    def require_valid(self) -> None:
        if self.issues:
            detail = "; ".join(
                f"{item.code}: {item.message}" for item in self.issues
            )
            raise ValueError(detail)

    @classmethod
    def from_iterable(
        cls,
        issues: Iterable[ValidationIssue],
    ) -> "ValidationReport":
        return cls(tuple(issues))
