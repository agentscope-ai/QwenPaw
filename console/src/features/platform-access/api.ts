import { request } from "../../api/request";

export interface PlatformConnection {
  status:
    | "not_connected"
    | "authorization_pending"
    | "connected"
    | "recovery_required";
  platform_url: string | null;
  node_id: string | null;
  account_id: string | null;
  account_name: string | null;
  authorization_url: string | null;
  logged_in: boolean;
  transport_status: string;
}

export interface MobileLogin {
  request_id: string;
  url: string;
  expires_at: number;
}

export interface MobileLoginStatus {
  status: "created" | "claimed" | "approved" | "exchanged";
  verification_code: string | null;
  device_name: string | null;
  expires_at: number;
}

const base = "/remote-access/platform";
export const platformAccessApi = {
  status: () => request<PlatformConnection>(base),
  login: (name: string) =>
    request<PlatformConnection>(`${base}/login`, {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  logout: () => request(`${base}/logout`, { method: "POST", body: "{}" }),
  bind: () => request(`${base}/bind`, { method: "POST", body: "{}" }),
  disconnect: () =>
    request<{ remote_cleanup_confirmed: boolean }>(base, { method: "DELETE" }),
  mobile: () =>
    request<MobileLogin>(`${base}/mobile`, { method: "POST", body: "{}" }),
  mobileStatus: (id: string) =>
    request<MobileLoginStatus>(`${base}/mobile/${encodeURIComponent(id)}`),
  approve: (id: string, verification_code: string) =>
    request(`${base}/mobile/${encodeURIComponent(id)}/approve`, {
      method: "POST",
      body: JSON.stringify({ verification_code }),
    }),
  cancel: (id: string) =>
    request(`${base}/mobile/${encodeURIComponent(id)}`, { method: "DELETE" }),
};
