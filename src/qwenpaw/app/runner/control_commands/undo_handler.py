# -*- coding: utf-8 -*-
"""Handler for /undo command."""

from ...rollback.service import SnapshotService
from .base import BaseControlCommandHandler, ControlContext


class UndoCommandHandler(BaseControlCommandHandler):
    """Reverts the last applied file operation in the workspace."""

    command_name = "/undo"

    async def handle(self, context: ControlContext) -> str:
        if not context.workspace:
            return "❌ /undo failed: No workspace attached."

        snapshot_svc = SnapshotService(context.workspace.workspace_dir)
        status, entry = await snapshot_svc.undo_latest()
        if status == "empty" or entry is None:
            return "⚠️ No rollback history available to undo."
        if status == "diverged":
            return (
                "❌ **Undo Blocked**\n"
                "The workspace has changed since the last agent operation. "
                "Undoing now might overwrite your manual changes. "
                "Please manually resolve or discard your changes before "
                "running `/undo`."
            )
        if status == "failed":
            return "❌ /undo failed: Could not revert all files."
        file_list = "\n".join(f"- {path}" for path in entry.files)
        return (
            f"✅ **Undo Successful**\n\n"
            f"Reverted {len(entry.files)} file(s):\n{file_list}"
        )
