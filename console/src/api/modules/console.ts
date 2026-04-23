import { request } from "../request";

export interface PushMessage {
  id: string;
  text: string;
}

export interface PendingApproval {
  request_id: string;
  session_id: string;
  root_session_id: string;
  agent_id: string;
  tool_name: string;
  severity: string;
  findings_count: number;
  findings_summary: string;
  tool_params: Record<string, unknown>;
  created_at: number;
  timeout_seconds: number;
}

export const consoleApi = {
  getPushMessages: (sessionId?: string) =>
    request<{ messages: PushMessage[]; pending_approvals: PendingApproval[] }>(
      sessionId
        ? `/console/push-messages?session_id=${sessionId}`
        : "/console/push-messages",
    ),
};
