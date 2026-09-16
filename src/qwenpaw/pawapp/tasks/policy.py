# -*- coding: utf-8 -*-
"""Explicit Host grants for the task dispatch surface.

Grants pin the complete descriptor (including permissions and effects) and
optionally constrain individual input values. Installing an App grants nothing.
The authenticated Host settings surface may update the signed-in operator's
grants. The PawApp SDK and task execution APIs expose no policy mutation.
"""

import asyncio
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from ...utils.io_utils import write_text_atomic
from .contracts import (
    ActionDescriptor,
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
        async with self._write_lock:
            current = await asyncio.to_thread(self._read_sync)
            if current.revision != expected_revision:
                raise TaskStoreError("task_policy_conflict")
            grants = [
                item
                for item in current.grants
                if not (
                    item.scope == grant.scope
                    and item.action_id == grant.action_id
                )
            ]
            if enabled:
                grants.append(grant)
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
