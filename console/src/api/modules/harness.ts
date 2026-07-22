import { request } from "../request";

export interface HarnessProvider {
  id: "codex" | "claude" | "qoder";
  name: string;
  available: boolean;
  coming_soon: boolean;
  installed: boolean;
  authenticated: boolean;
  account: {
    type?: string;
    email?: string | null;
    planType?: string;
  } | null;
  error: string | null;
}

export interface HarnessLogin {
  type: string;
  loginId: string;
  authUrl?: string;
  verificationUrl?: string;
  userCode?: string;
}

export const harnessApi = {
  list: () =>
    request<{ providers: HarnessProvider[] }>("/harnesses", {
      timeout: 60_000,
    }),
  loginCodex: (deviceCode = false) =>
    request<HarnessLogin>("/harnesses/codex/login", {
      method: "POST",
      body: JSON.stringify({ device_code: deviceCode }),
      timeout: 60_000,
    }),
  logoutCodex: () =>
    request<{ ok: boolean }>("/harnesses/codex/logout", {
      method: "POST",
    }),
};
