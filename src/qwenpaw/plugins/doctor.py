# -*- coding: utf-8 -*-
"""Read-only checks shared by consumers of the doctor contract."""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .extensions import ExtensionPoint


@dataclass(frozen=True)
class DoctorContext:
    """The same configuration and target used by core doctor checks."""

    config: dict[str, Any] | None
    raw_config: dict[str, Any] | None
    base_url: str
    timeout: float
    deep: bool


@dataclass(frozen=True)
class DoctorSpec:
    """Return informational notes without starting a provider or channel."""

    id: str
    check: Callable[[DoctorContext], list[str] | Awaitable[list[str]]]

    def __post_init__(self):
        if not callable(self.check):
            raise ValueError("DoctorSpec.check must be callable")


DOCTOR = ExtensionPoint("qwenpaw.doctor", DoctorSpec)
