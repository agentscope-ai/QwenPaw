import { getApiToken, getApiUrl } from "../config";

export type AuthMode = "legacy" | "multi_user";

export interface AuthUser {
  id: string;
  username: string;
  platform_role: "admin" | "member";
  status: "active" | "disabled";
  display_name?: string | null;
  email?: string | null;
  phone?: string | null;
  department?: string | null;
  job_title?: string | null;
  remark?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  last_login_at?: string | null;
}

export type UserProfileInput = Pick<
  AuthUser,
  | "username"
  | "display_name"
  | "email"
  | "phone"
  | "department"
  | "job_title"
  | "remark"
>;

export interface AuthSession {
  id: string;
  client_info: Record<string, string>;
  created_at?: string;
  last_seen_at?: string | null;
  expires_at?: string;
  revoked_at?: string | null;
}

export interface LoginResponse {
  token: string;
  username: string;
  user?: AuthUser;
  session?: AuthSession;
  access_expires_at?: string;
  message?: string;
}

export interface AuthStatusResponse {
  enabled: boolean;
  has_users: boolean;
  mode?: AuthMode;
}

export interface MeResponse {
  user: AuthUser;
  preferences: { language: string; timezone: string };
}

function bearerHeaders(): Record<string, string> {
  const token = getApiToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function detailError(res: Response, fallback: string): Promise<Error> {
  const err = await res.json().catch(() => ({}));
  return new Error(err.detail || fallback);
}

export const authApi = {
  login: async (username: string, password: string): Promise<LoginResponse> => {
    const res = await fetch(getApiUrl("/auth/login"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Login failed");
    }
    return res.json();
  },

  register: async (
    username: string,
    password: string,
  ): Promise<LoginResponse> => {
    const res = await fetch(getApiUrl("/auth/register"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Registration failed");
    }
    return res.json();
  },

  getStatus: async (): Promise<AuthStatusResponse> => {
    const res = await fetch(getApiUrl("/auth/status"));
    if (!res.ok) throw new Error("Failed to check auth status");
    return res.json();
  },

  verify: async (): Promise<{ valid: boolean; username: string }> => {
    const res = await fetch(getApiUrl("/auth/verify"), {
      headers: bearerHeaders(),
    });
    if (!res.ok) throw await detailError(res, "Verification failed");
    return res.json();
  },

  refresh: async (): Promise<LoginResponse> => {
    const res = await fetch(getApiUrl("/auth/refresh"), {
      method: "POST",
      credentials: "include",
    });
    if (!res.ok) throw await detailError(res, "Session expired");
    return res.json();
  },

  logout: async (): Promise<{ revoked: boolean }> => {
    const res = await fetch(getApiUrl("/auth/logout"), {
      method: "POST",
      credentials: "include",
      headers: bearerHeaders(),
    });
    if (!res.ok) throw await detailError(res, "Logout failed");
    return res.json();
  },

  getMe: async (): Promise<MeResponse> => {
    const res = await fetch(getApiUrl("/me"), {
      headers: bearerHeaders(),
      credentials: "include",
    });
    if (!res.ok) throw await detailError(res, "Failed to load account");
    return res.json();
  },

  updatePreferences: async (
    language: string,
    timezone: string,
  ): Promise<{ language: string; timezone: string }> => {
    const res = await fetch(getApiUrl("/me/preferences"), {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...bearerHeaders() },
      credentials: "include",
      body: JSON.stringify({ language, timezone }),
    });
    if (!res.ok) throw await detailError(res, "Preference update failed");
    return res.json();
  },

  listSessions: async (): Promise<AuthSession[]> => {
    const res = await fetch(getApiUrl("/auth/sessions"), {
      headers: bearerHeaders(),
      credentials: "include",
    });
    if (!res.ok) throw await detailError(res, "Failed to load sessions");
    return res.json();
  },

  revokeAllSessions: async (): Promise<{
    revoked: boolean;
    revoked_sessions: number;
  }> => {
    const res = await fetch(getApiUrl("/auth/revoke-all-tokens"), {
      method: "POST",
      headers: bearerHeaders(),
      credentials: "include",
    });
    if (!res.ok) throw await detailError(res, "Session revocation failed");
    return res.json();
  },

  updateLegacyProfile: async (
    currentPassword: string,
    newUsername?: string,
    newPassword?: string,
  ): Promise<LoginResponse> => {
    const token = getApiToken();
    const res = await fetch(getApiUrl("/auth/update-profile"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        current_password: currentPassword,
        new_username: newUsername || null,
        new_password: newPassword || null,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Update failed");
    }
    return res.json();
  },

  updateProfile: async (
    profile: UserProfileInput,
  ): Promise<{ user: AuthUser }> => {
    const res = await fetch(getApiUrl("/me/profile"), {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...bearerHeaders() },
      credentials: "include",
      body: JSON.stringify(profile),
    });
    if (!res.ok) throw await detailError(res, "Profile update failed");
    return res.json();
  },

  changePassword: async (
    currentPassword: string,
    newPassword: string,
  ): Promise<{ revoked_sessions: number }> => {
    const res = await fetch(getApiUrl("/me/change-password"), {
      method: "POST",
      headers: { "Content-Type": "application/json", ...bearerHeaders() },
      credentials: "include",
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
      }),
    });
    if (!res.ok) throw await detailError(res, "Password update failed");
    return res.json();
  },
};
