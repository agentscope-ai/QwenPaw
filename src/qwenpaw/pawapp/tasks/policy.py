# -*- coding: utf-8 -*-
"""Explicit Host grants for the experimental task dispatch surface.

Grants pin the complete descriptor (including permissions and effects) and
optionally constrain individual input values. Installing an App grants nothing.
The Host operator owns this file; public APIs cannot write it.
"""

import asyncio
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

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
    grants: tuple[TaskGrant, ...] = ()


class FileTaskPolicy:
    def __init__(self, path: Path):
        self.path = path

    async def check(
        self,
        scope: TaskScope,
        action: ActionDescriptor,
        inputs: dict[str, Any] | None = None,
    ) -> None:
        def read():
            try:
                return TaskPolicy.model_validate_json(self.path.read_text())
            except FileNotFoundError:
                return TaskPolicy()
            except (OSError, ValueError):
                raise TaskStoreError("task_policy_unavailable") from None

        policy = await asyncio.to_thread(read)
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
