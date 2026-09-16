# -*- coding: utf-8 -*-
"""Server-owned action registration and configuration readiness contracts."""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal, Protocol

from pydantic import model_validator

from .contracts import (
    ActionDescriptor,
    Contract,
    Identity,
    TaskScope,
    TaskOrigin,
)
from .coordinator import TaskAdapter


class Readiness(Contract):
    state: Literal["ready", "blocked"]
    reason: Identity | None = None

    @model_validator(mode="after")
    def validate_reason(self):
        if (self.state == "blocked") != (self.reason is not None):
            raise ValueError("only blocked readiness has a reason")
        return self


class ManagedTaskAdapter(TaskAdapter, Protocol):
    async def readiness(
        self,
        scope: TaskScope,
        inputs: dict[str, Any],
    ) -> Readiness:
        ...

    async def aclose(self) -> None:
        ...


@dataclass(frozen=True)
class ActionRegistration:
    action: ActionDescriptor
    factory: Callable[[], ManagedTaskAdapter]
    settings_entry: str
    requirement_ids: tuple[Identity, ...] = ()

    def __post_init__(self):
        if len(self.requirement_ids) != len(set(self.requirement_ids)):
            raise ValueError("action setup requirements must be unique")
        # Local App settings only: never accept an adapter-supplied redirect.
        prefix = f"/apps/{self.action.app_id}"
        if (
            self.settings_entry != prefix
            and not self.settings_entry.startswith(
                prefix + "/",
            )
        ):
            raise ValueError("settings entry must belong to the App")
        if any(c in self.settings_entry for c in ("\\", "?", "#", "%")):
            raise ValueError("settings entry must be a local App path")
        if ".." in self.settings_entry.split("/"):
            raise ValueError("settings entry cannot traverse paths")


AuthorizeOrigin = Callable[[TaskScope, TaskOrigin], Awaitable[None]]
