# -*- coding: utf-8 -*-
"""App-scoped setup checker and presentation registrations."""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from ..tasks.contracts import TaskScope
from .contracts import (
    ReadinessResult,
    SetupEntryDescriptor,
    SetupOpenAction,
    SetupRequest,
    SetupRequirement,
)

SetupChecker = Callable[
    [TaskScope, dict[str, Any]],
    Awaitable[ReadinessResult],
]
SetupOpener = Callable[[SetupRequest], Awaitable[SetupOpenAction]]


@dataclass(frozen=True)
class SetupCheckRegistration:
    requirement: SetupRequirement
    checker: SetupChecker

    def __post_init__(self) -> None:
        if not callable(self.checker):
            raise ValueError("setup checker must be callable")


@dataclass(frozen=True)
class SetupEntryRegistration:
    descriptor: SetupEntryDescriptor
    opener: SetupOpener

    def __post_init__(self) -> None:
        if not callable(self.opener):
            raise ValueError("setup opener must be callable")
