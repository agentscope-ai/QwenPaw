from ...rollback.service import SnapshotService
from .base import BaseControlCommandHandler, ControlContext


class UndoCommandHandler(BaseControlCommandHandler):
    """Reverts the last applied file operation in the workspace."""

    command_name = "/undo"

    async def handle(self, context: ControlContext) -> str:
        if not context.workspace:
            return "❌ /undo failed: No workspace attached."

        snapshot_svc = SnapshotService(context.workspace.workspace_dir)
        latest_applied = await snapshot_svc.get_latest_applied()

        if not latest_applied:
            return "⚠️ No rollback history available to undo."

        # Safety Check: Did the workspace diverge from the recorded 'after_hash'?
        current_hash = await snapshot_svc.track()
        if current_hash != latest_applied.after_hash:
            return (
                "❌ **Undo Blocked**\n"
                "The workspace has changed since the last agent operation. "
                "Undoing now might overwrite your manual changes. "
                "Please manually resolve or discard your changes before running `/undo`."
            )

        # Proceed with revert
        success = await snapshot_svc.revert(
            target_hash=latest_applied.before_hash, files=latest_applied.files
        )

        if not success:
            return "❌ /undo failed: Could not revert all files."

        # Mark entry as undone
        await snapshot_svc.mark_undone(latest_applied.id)

        file_list = "\n".join([f"- {f}" for f in latest_applied.files])
        return (
            f"✅ **Undo Successful**\n\n"
            f"Reverted {len(latest_applied.files)} file(s):\n{file_list}"
        )
