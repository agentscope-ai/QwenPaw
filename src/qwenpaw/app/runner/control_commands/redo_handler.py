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
        latest_undone = await snapshot_svc.get_latest_undone()

        if not latest_undone:
            return "⚠️ No undone rollback history available to redo."

        # Safety check: avoid overwriting out-of-band workspace changes.
        current_hash = await snapshot_svc.track()
        if current_hash != latest_undone.before_hash:
            return (
                "❌ **Redo Blocked**\n"
                "The workspace has changed since the last agent operation. "
                "Redoing now might overwrite your manual changes. "
                "Please manually resolve or discard your changes before "
                "running `/redo`."
            )

        # Proceed with redo (applying the 'after_hash' state)
        success = await snapshot_svc.revert(
            target_hash=latest_undone.after_hash,
            files=latest_undone.files,
        )

        if not success:
            return "❌ /redo failed: Could not re-apply all files."

        # Mark entry as applied
        await snapshot_svc.mark_applied(latest_undone.id)

        file_list = "\n".join([f"- {f}" for f in latest_undone.files])
        return (
            f"✅ **Redo Successful**\n\n"
            f"Re-applied {len(latest_undone.files)} file(s):\n{file_list}"
        )
