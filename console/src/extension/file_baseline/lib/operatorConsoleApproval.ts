import type { PendingApproval } from "../../../api/modules/console";

/** Matches ``operator_console_session_id`` in extension/file_baseline/operator_write.py */
export const OPERATOR_CONSOLE_SESSION_PREFIX = "persona-console:";

/** Console operator saves (skills, workspace md, coding mode) — not agent chat sessions. */
export function isOperatorConsoleApproval(approval: PendingApproval): boolean {
  if (approval.tool_name === "operator_console_save") {
    return true;
  }
  return Boolean(
    approval.root_session_id?.startsWith(OPERATOR_CONSOLE_SESSION_PREFIX),
  );
}

export function filterOperatorConsoleApprovals(
  approvals: PendingApproval[],
): PendingApproval[] {
  return approvals
    .filter(isOperatorConsoleApproval)
    .slice()
    .sort((a, b) => a.created_at - b.created_at);
}
