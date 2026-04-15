# -*- coding: utf-8 -*-
"""Handler for /redo command."""

from ...rollback.service import SnapshotService
from .base import BaseControlCommandHandler, ControlContext


class RedoCommandHandler(BaseControlCommandHandler):
    """Reapplies the last undone file operation in the workspace."""

    command_name = "/redo"

    async def handle(self, context: ControlContext) -> str:
        if not context.workspace:
            return "❌ /redo failed: No workspace attached."

        snapshot_svc = SnapshotService(context.workspace.workspace_dir)
        status, entry = await snapshot_svc.redo_latest()
        if status == "empty" or entry is None:
            return "⚠️ No undone rollback history available to redo."
        if status == "diverged":
            return (
                "❌ **Redo Blocked**\n"
                "The workspace has changed since the last agent operation. "
                "Redoing now might overwrite your manual changes. "
                "Please manually resolve or discard your changes before "
                "running `/redo`."
            )
        if status == "failed":
            return "❌ /redo failed: Could not re-apply all files."
        file_list = "\n".join(f"- {path}" for path in entry.files)
        return (
            f"✅ **Redo Successful**\n\n"
            f"Re-applied {len(entry.files)} file(s):\n{file_list}"
        )
