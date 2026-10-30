import { buildChatPath } from "../utils/sessionRoute";

export interface ApprovalNotificationTarget {
  requestId?: string;
  rootSessionId?: string;
  agentId?: string;
}

export function buildApprovalNavigationPath(
  target?: ApprovalNotificationTarget,
): string {
  const rootSessionId = target?.rootSessionId?.trim();
  if (!rootSessionId) return "/inbox?tab=approvals";

  const requestId = target?.requestId?.trim();
  const params = new URLSearchParams();
  if (requestId) params.set("approval", requestId);
  const agentId = target?.agentId?.trim();
  if (agentId) params.set("agent", agentId);
  const query = params.toString() ? `?${params.toString()}` : "";
  return `${buildChatPath(rootSessionId)}${query}`;
}
