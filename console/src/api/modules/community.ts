import { request } from "../request";
import type { InstallationOrigin } from "../types/community";

export interface CommunityConnectionStatus {
  status:
    | "not_configured"
    | "disconnected"
    | "authorizing"
    | "connected"
    | "expired"
    | "unsupported_remote";
  account?: { id: string; display_name: string; avatar_url?: string };
  message_types?: string[];
  sync_enabled: boolean;
  messages_enabled: boolean;
  last_success_at?: number | null;
  last_error?: string | null;
  authorization?: {
    flow_id: string;
    authorize_url: string;
    expires_at: number;
  };
  configured?: boolean;
  local_login_supported?: boolean;
  connection_available?: boolean;
}

const connectionPath = "/community/connection";
export const communityConnectionApi = {
  status: (signal?: AbortSignal) =>
    request<CommunityConnectionStatus>(connectionPath, { signal }),
  start: () =>
    request<{ flow_id: string; authorize_url: string; expires_at: number }>(
      `${connectionPath}/start`,
      { method: "POST" },
    ),
  cancel: (flowId: string) =>
    request(`${connectionPath}/authorization/${encodeURIComponent(flowId)}`, {
      method: "DELETE",
    }),
  disconnect: () => request(connectionPath, { method: "DELETE" }),
  setSync: (enabled: boolean) =>
    request(`${connectionPath}/sync`, {
      method: "PATCH",
      body: JSON.stringify({ enabled }),
    }),
  setMessageTypes: (message_types: string[]) =>
    request(`${connectionPath}/sync`, {
      method: "PATCH",
      body: JSON.stringify({ message_types }),
    }),
  sync: () => request(`${connectionPath}/sync`, { method: "POST" }),
};

export function resolveCommunityFeedbackLink(
  origin: InstallationOrigin,
  signal?: AbortSignal,
): Promise<{ url: string }> {
  return request("/community/feedback-link", {
    method: "POST",
    body: JSON.stringify({ origin }),
    signal,
  });
}
