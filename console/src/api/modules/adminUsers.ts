import { request } from "@/api/request";

export interface AdminUser {
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

export type AdminUserProfileInput = Pick<
  AdminUser,
  | "username"
  | "display_name"
  | "email"
  | "phone"
  | "department"
  | "job_title"
  | "remark"
>;

export interface CreateAdminUserRequest {
  username: string;
  password: string;
  platform_role: "admin" | "member";
}

const userPath = (userId: string) =>
  `/admin/users/${encodeURIComponent(userId)}`;

export const adminUsersApi = {
  list: () => request<AdminUser[]>("/admin/users"),
  create: (body: CreateAdminUserRequest) =>
    request<AdminUser>("/admin/users", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  setStatus: (userId: string, status: AdminUser["status"]) =>
    request<{ user: AdminUser; revoked_sessions: number }>(
      `${userPath(userId)}/status`,
      {
        method: "PATCH",
        body: JSON.stringify({ status }),
      },
    ),
  setRole: (userId: string, platformRole: AdminUser["platform_role"]) =>
    request<AdminUser>(`${userPath(userId)}/role`, {
      method: "PATCH",
      body: JSON.stringify({ platform_role: platformRole }),
    }),
  revokeSessions: (userId: string) =>
    request<{ revoked_sessions: number }>(
      `${userPath(userId)}/revoke-sessions`,
      { method: "POST" },
    ),
  updateProfile: (userId: string, body: AdminUserProfileInput) =>
    request<AdminUser>(`${userPath(userId)}/profile`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  resetPassword: (userId: string, newPassword: string) =>
    request<{ revoked_sessions: number }>(
      `${userPath(userId)}/reset-password`,
      {
        method: "POST",
        body: JSON.stringify({ new_password: newPassword }),
      },
    ),
};
