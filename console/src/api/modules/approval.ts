import { request } from "../request";

export interface PendingApproval {
  request_id: string;
  session_id: string;
  user_id: string;
  channel: string;
  tool_name: string;
  status: string;
  created_at: number;
  result_summary: string;
  findings_count: number;
  extra: Record<string, unknown>;
}

export const approvalApi = {
  getPendingApproval: (sessionId: string) =>
    request<PendingApproval | null>(
      `/approvals/pending?session_id=${encodeURIComponent(sessionId)}`,
    ),

  approveRequest: (requestId: string) =>
    request<PendingApproval>(`/approvals/${encodeURIComponent(requestId)}/approve`, {
      method: "POST",
    }),

  denyRequest: (requestId: string) =>
    request<PendingApproval>(`/approvals/${encodeURIComponent(requestId)}/deny`, {
      method: "POST",
    }),
};
