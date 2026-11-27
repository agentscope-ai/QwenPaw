import { request } from "../request";

export interface CommandCheckResponse {
  is_control_command: boolean;
  command_token: string | null;
}

export interface ApprovalCommandResponse {
  success: boolean;
  message: string;
}

export const commandsApi = {
  isApprovalPending: async (requestId: string, rootSessionId?: string) => {
    const query = rootSessionId
      ? `?${new URLSearchParams({ session_id: rootSessionId })}`
      : "";
    const { pending_approvals } = await request<{
      pending_approvals: Array<{ request_id: string }>;
    }>(`/approval/list${query}`, { cache: "no-store" });
    return pending_approvals.some(
      (approval) => approval.request_id === requestId,
    );
  },

  /** Check if text is a system control command */
  checkCommand: async (text: string): Promise<boolean> => {
    const response = await request<CommandCheckResponse>("/commands/check", {
      method: "POST",
      body: JSON.stringify({ text }),
    });
    return response.is_control_command;
  },

  /** Send approval command (approve or deny) */
  sendApprovalCommand: async (
    action: "approve" | "deny",
    requestId: string,
    sessionId: string,
    reason?: string,
    scope?: "exact" | "similar",
  ): Promise<ApprovalCommandResponse> => {
    console.log(
      `[commandsApi] Sending ${action} for request:`,
      requestId,
      "session:",
      sessionId,
      "reason:",
      reason,
      "scope:",
      scope,
    );

    // Use dedicated approval API endpoint (bypasses chat/session system)
    const response = await request<ApprovalCommandResponse>(
      `/approval/${action}`,
      {
        method: "POST",
        body: JSON.stringify({
          request_id: requestId,
          session_id: sessionId,
          reason: reason || undefined,
          // scope only meaningful for approve; omitted on deny.
          scope: action === "approve" ? scope : undefined,
        }),
      },
    );
    if (!response.success) {
      throw new Error(response.message);
    }
    return response;
  },
};
