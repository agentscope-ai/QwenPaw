# -*- coding: utf-8 -*-
"""Explicit Host grants for the task dispatch surface.

Grants pin the complete descriptor (including permissions and effects) and
optionally constrain individual input values. Installing an App grants nothing.
The authenticated Host settings surface may update the signed-in operator's
grants. The PawApp SDK and task execution APIs expose no policy mutation.
"""

import asyncio
from pathlib import Path
from typing import Any, Iterable, Literal

from pydantic import Field

from ...utils.io_utils import write_text_atomic
from .contracts import (
    ActionDescriptor,
    CapabilityRisk,
    Contract,
    Identity,
    TaskScope,
    TaskStoreError,
)


class TaskGrant(Contract):
    scope: TaskScope
    action_id: Identity
    descriptor_digest: Identity
    input_values: dict[str, list[str]] = Field(default_factory=dict)


class TaskCapability(Contract):
    """A user-facing bundle of related public task actions.

    Capabilities are derived from the registered action descriptor for now;
    they are deliberately not persisted as a second authorization primitive.
    The action grants below remain the enforcement and descriptor-pinning
    layer, while this contract gives the Host a stable, higher-level policy
    surface for operators.
    """

    schema_version: Literal[1] = 1
    capability_id: Identity
    app_id: Identity
    label: str
    summary: str
    action_ids: tuple[Identity, ...] = ()
    permissions: tuple[Identity, ...] = ()
    effects: tuple[Identity, ...] = ()
    risk: CapabilityRisk


_CAPABILITY_LABELS = {
    "read": ("Read and inspect", "View information exposed by this App."),
    "project_mutation": (
        "Create and edit projects",
        "Create or update project content in this App.",
    ),
    "write": (
        "Create and update content",
        "Create or update content exposed by this App.",
    ),
    "media_generation": (
        "Generate media",
        "Use generation actions that may consume model or provider resources.",
    ),
}


def _capability_kind(action: ActionDescriptor) -> tuple[str, str]:
    """Map an action to a conservative, stable policy bundle.

    App-specific resource selectors stay in the action's Advanced constraints;
    ordinary creative parameters do not become access-control dimensions.
    """

    permissions = tuple(item.casefold() for item in action.permissions)
    effects = tuple(item.casefold() for item in action.effects)
    if any(
        permission.endswith(".generate")
        or ".generate." in permission
        for permission in permissions
    ):
        return "media_generation", "generation"
    if "project_mutation" in effects:
        return "project_mutation", "write"
    if any(
        permission.rsplit(".", 1)[-1]
        in {"create", "write", "update", "delete", "mutate"}
        for permission in permissions
        if "." in permission
    ):
        return "write", "write"
    if any(
        permission.rsplit(".", 1)[-1]
        in {"read", "list", "query", "get", "search"}
        for permission in permissions
        if "." in permission
    ):
        return "read", "read"
    return f"action:{action.action_id}", "other"


def _capability_fields(item):
    """Return action plus optional App-declared bundle metadata."""
    action = getattr(item, "action", item)
    return (
        action,
        getattr(item, "capability_id", None),
        getattr(item, "capability_label", None),
        getattr(item, "capability_summary", None),
        getattr(item, "capability_risk", None),
    )


def build_task_capabilities(
    actions: Iterable[ActionDescriptor],
) -> tuple[TaskCapability, ...]:
    """Build public policy bundles without changing descriptor digests."""

    grouped: dict[tuple[str, str], list[tuple]] = {}
    for item in actions:
        action, capability_id, _, _, _ = _capability_fields(item)
        kind, _ = _capability_kind(action)
        grouped.setdefault((action.app_id, capability_id or kind), []).append(
            _capability_fields(item),
        )

    capabilities = []
    for (app_id, capability_id), members in sorted(grouped.items()):
        first_action, _, declared_label, declared_summary, declared_risk = (
            members[0]
        )
        _, inferred_risk = _capability_kind(first_action)
        risk = declared_risk or inferred_risk
        if capability_id in _CAPABILITY_LABELS:
            label, summary = _CAPABILITY_LABELS[capability_id]
        elif declared_label or declared_summary:
            label = declared_label or first_action.summary
            summary = declared_summary or (
                "A specific App capability exposed to the Main Chat agent."
            )
        else:
            label = first_action.summary
            summary = "A specific App action exposed to the Main Chat agent."
        permissions = tuple(
            dict.fromkeys(
                permission
                for action, _, _, _, _ in members
                for permission in action.permissions
            ),
        )
        effects = tuple(
            dict.fromkeys(
                effect
                for action, _, _, _, _ in members
                for effect in action.effects
            ),
        )
        capabilities.append(
            TaskCapability(
                capability_id=capability_id,
                app_id=app_id,
                label=label,
                summary=summary,
                action_ids=tuple(
                    sorted(action.action_id for action, _, _, _, _ in members)
                ),
                permissions=permissions,
                effects=effects,
                risk=risk,
            ),
        )
    return tuple(capabilities)


class TaskPolicy(Contract):
    version: Literal[1] = 1
    revision: int = Field(default=0, ge=0)
    grants: tuple[TaskGrant, ...] = ()


class FileTaskPolicy:
    def __init__(self, path: Path):
        self.path = path
        self._write_lock = asyncio.Lock()

    def _read_sync(self) -> TaskPolicy:
        try:
            return TaskPolicy.model_validate_json(self.path.read_text())
        except FileNotFoundError:
            return TaskPolicy()
        except (OSError, ValueError):
            raise TaskStoreError("task_policy_unavailable") from None

    async def read(self) -> TaskPolicy:
        """Read one complete policy snapshot, failing closed on corruption."""
        return await asyncio.to_thread(self._read_sync)

    async def set_grant(
        self,
        grant: TaskGrant,
        *,
        enabled: bool,
        expected_revision: int,
    ) -> TaskPolicy:
        """Replace one scope/action grant at an expected revision."""
        return await self.set_grants(
            (grant,),
            enabled=enabled,
            expected_revision=expected_revision,
        )

    async def set_grants(
        self,
        grants: Iterable[TaskGrant],
        *,
        enabled: bool,
        expected_revision: int,
    ) -> TaskPolicy:
        """Atomically replace a set of scope/action grants.

        A capability toggle uses this method so a bundle cannot be left
        half-enabled if the process is interrupted between individual writes.
        """
        async with self._write_lock:
            current = await asyncio.to_thread(self._read_sync)
            if current.revision != expected_revision:
                raise TaskStoreError("task_policy_conflict")
            replacements = tuple(grants)
            grants = [
                item
                for item in current.grants
                if not any(
                    item.scope == replacement.scope
                    and item.action_id == replacement.action_id
                    for replacement in replacements
                )
            ]
            if enabled:
                grants.extend(replacements)
            grants.sort(
                key=lambda item: (
                    item.scope.principal_id,
                    item.scope.workspace_id,
                    item.scope.app_id,
                    item.action_id,
                ),
            )
            updated = TaskPolicy(
                revision=current.revision + 1,
                grants=tuple(grants),
            )
            await asyncio.to_thread(
                write_text_atomic,
                self.path,
                updated.model_dump_json(indent=2) + "\n",
            )
            return updated

    async def check(
        self,
        scope: TaskScope,
        action: ActionDescriptor,
        inputs: dict[str, Any] | None = None,
    ) -> None:
        policy = await self.read()
        for grant in policy.grants:
            if (
                grant.scope == scope
                and grant.action_id == action.action_id
                and grant.descriptor_digest == action.descriptor_digest
                and (
                    inputs is None
                    or all(
                        isinstance(inputs.get(key), str)
                        and inputs[key] in values
                        for key, values in grant.input_values.items()
                    )
                )
            ):
                return
        raise TaskStoreError("action_forbidden")
