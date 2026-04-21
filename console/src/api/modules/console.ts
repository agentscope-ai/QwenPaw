import { request } from "../request";

export interface PushMessage {
  id: string;
  text: string;
}

export interface PendingApproval {
  request_id: string;
  tool_name: string;
  operation_preview: string;
  result_summary: string;
  findings_count: number;
  created_at: number;
}

export const consoleApi = {
  getPushMessages: () =>
    request<{ messages: PushMessage[] }>("/console/push-messages"),
  getPendingApproval: (sessionId: string) =>
    request<PendingApproval>(
      `/console/approvals/pending?session_id=${encodeURIComponent(sessionId)}`,
    ),
  runApprovalAction: (payload: {
    session_id: string;
    action: "approve" | "deny";
    request_id?: string;
    user_id?: string;
    channel?: string;
  }) =>
    request<{ ok: boolean; reason?: string }>("/console/approvals/action", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};
