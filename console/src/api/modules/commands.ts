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
  ): Promise<ApprovalCommandResponse> => {
    console.log(
      `[commandsApi] Sending ${action} for request:`,
      requestId,
      "session:",
      sessionId,
      "reason:",
      reason,
    );

    // Use dedicated approval API endpoint (bypasses chat/session system)
    return request<ApprovalCommandResponse>(`/approval/${action}`, {
      method: "POST",
      body: JSON.stringify({
        request_id: requestId,
        session_id: sessionId,
        reason: reason || undefined,
      }),
    });
  },
};
