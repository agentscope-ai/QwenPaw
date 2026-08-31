# -*- coding: utf-8 -*-
"""Tool adapter for the transactional patch primitive."""

from __future__ import annotations

from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolChunk

from ...config.context import (
    get_current_project_dir,
    get_current_workspace_dir,
)
from ...constant import WORKING_DIR
from ...patching import PatchError, apply_patch_document, parse_patch
from ...runtime.tool_registry import tool_descriptor

_MAX_PATCH_BYTES = 1024 * 1024


@tool_descriptor(
    requires_sandbox=("file_write",),
    async_execution=True,
    tool_type="file",
    target_param="patch",
    policy_name="ApplyPatch",
    ui_description="Apply a contextual multi-file patch",
    ui_icon="🩹",
)
async def apply_patch(patch: str) -> ToolChunk:
    """Apply a context-validated multi-file patch as one transaction.

    The patch must use ``*** Begin Patch`` / ``*** End Patch`` with
    ``Add File``, ``Delete File``, ``Update File`` and optional ``Move to``
    sections. Any conflict leaves every target unchanged.
    """
    try:
        if (
            isinstance(patch, str)
            and len(patch.encode("utf-8")) > _MAX_PATCH_BYTES
        ):
            raise PatchError(
                "patch_too_large",
                "Patch exceeds the 1 MiB input limit",
            )
        document = parse_patch(patch)
        root = (
            get_current_project_dir()
            or get_current_workspace_dir()
            or WORKING_DIR
        )
        result = await apply_patch_document(root, document)
    except PatchError as exc:
        metadata = {
            "status": "conflict" if exc.conflicts else "error",
            "error_code": exc.code,
            "conflicts": [conflict.as_dict() for conflict in exc.conflicts],
            "rolled_back": exc.rolled_back,
            "rollback_errors": list(exc.rollback_errors),
        }
        details = ""
        if exc.conflicts:
            details = "\n" + "\n".join(
                f"- {item.message}" for item in exc.conflicts
            )
        return ToolChunk(
            is_last=True,
            state=ToolResultState.ERROR,
            content=[
                TextBlock(type="text", text=f"Patch failed: {exc}{details}"),
            ],
            metadata=metadata,
        )
    except Exception as exc:  # noqa: BLE001
        return ToolChunk(
            is_last=True,
            state=ToolResultState.ERROR,
            content=[TextBlock(type="text", text=f"Patch failed: {exc}")],
            metadata={"status": "error", "error_code": "unexpected_error"},
        )
    return ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS,
        content=[
            TextBlock(
                type="text",
                text=(
                    f"Applied patch to {len(result.files)} file(s); "
                    f"{result.hunks_applied} hunk(s) applied."
                ),
            ),
        ],
        metadata={
            "status": result.status,
            "files": list(result.files),
            "hunks_applied": result.hunks_applied,
            "conflicts": [],
            "rolled_back": False,
        },
    )
