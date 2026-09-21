# -*- coding: utf-8 -*-
"""Server-owned action registration and configuration readiness contracts."""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal, Protocol

from pydantic import model_validator

from .contracts import (
    ActionDescriptor,
    Contract,
    Identity,
    CapabilityRisk,
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


InputResolver = Callable[
    [TaskScope, dict[str, Any]],
    Awaitable[dict[str, Any]],
]


@dataclass(frozen=True)
class ActionRegistration:
    action: ActionDescriptor
    factory: Callable[[], ManagedTaskAdapter]
    settings_entry: str
    requirement_ids: tuple[Identity, ...] = ()
    deferred_requirement_ids: tuple[Identity, ...] = ()
    input_resolver: InputResolver | None = None
    exposure: Literal["host_public", "app_private"] = "host_public"
    capability_id: str | None = None
    capability_label: str | None = None
    capability_summary: str | None = None
    capability_risk: CapabilityRisk | None = None

    def __post_init__(self):
        if len(self.requirement_ids) != len(set(self.requirement_ids)):
            raise ValueError("action setup requirements must be unique")
        if len(self.deferred_requirement_ids) != len(
            set(self.deferred_requirement_ids),
        ):
            raise ValueError("deferred setup requirements must be unique")
        if set(self.requirement_ids) & set(self.deferred_requirement_ids):
            raise ValueError("setup requirements cannot be eager and deferred")
        if self.input_resolver is not None and not callable(
            self.input_resolver,
        ):
            raise ValueError("action input resolver must be callable")
        if self.exposure not in {"host_public", "app_private"}:
            raise ValueError("invalid action exposure")
        capability_metadata = (
            self.capability_label,
            self.capability_summary,
            self.capability_risk,
        )
        if self.capability_id is None and any(
            value is not None for value in capability_metadata
        ):
            raise ValueError(
                "capability metadata requires a capability id",
            )
        if self.capability_id is not None and not self.capability_id:
            raise ValueError("capability id must be non-empty")
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
