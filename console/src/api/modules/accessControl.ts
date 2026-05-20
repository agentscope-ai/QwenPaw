import { request } from "../request";

export interface ACLData {
  /** user_id -> remark */
  whitelist: Record<string, string>;
  /** user_id -> remark */
  blacklist: Record<string, string>;
  pending: PendingEntry[];
}

export interface PendingEntry {
  user_id: string;
  channel: string;
  timestamp: number;
  first_message: string;
}

export interface ACLUserEntry {
  userId: string;
  remark: string;
}

export const accessControlApi = {
  getAclAll: () => request<Record<string, ACLData>>("/access-control"),

  getAclChannel: (channel: string) =>
    request<ACLData>(`/access-control/${channel}`),

  setAclWhitelist: (channel: string, userIds: string[]) =>
    request(`/access-control/${channel}/whitelist`, {
      method: "PUT",
      body: JSON.stringify({ user_ids: userIds }),
    }),

  addAclWhitelist: (channel: string, userId: string, remark: string = "") =>
    request(`/access-control/${channel}/whitelist/add`, {
      method: "POST",
      body: JSON.stringify({ user_id: userId, remark }),
    }),

  removeAclWhitelist: (channel: string, userId: string) =>
    request(`/access-control/${channel}/whitelist/remove`, {
      method: "POST",
      body: JSON.stringify({ user_id: userId }),
    }),

  setAclBlacklist: (channel: string, userIds: string[]) =>
    request(`/access-control/${channel}/blacklist`, {
      method: "PUT",
      body: JSON.stringify({ user_ids: userIds }),
    }),

  addAclBlacklist: (channel: string, userId: string, remark: string = "") =>
    request(`/access-control/${channel}/blacklist/add`, {
      method: "POST",
      body: JSON.stringify({ user_id: userId, remark }),
    }),

  removeAclBlacklist: (channel: string, userId: string) =>
    request(`/access-control/${channel}/blacklist/remove`, {
      method: "POST",
      body: JSON.stringify({ user_id: userId }),
    }),

  updateAclRemark: (channel: string, userId: string, remark: string) =>
    request(`/access-control/${channel}/remark`, {
      method: "POST",
      body: JSON.stringify({ user_id: userId, remark }),
    }),

  getAclAllPending: () =>
    request<PendingEntry[]>("/access-control/pending/all"),

  approveAclPending: (channel: string, userId: string, remark: string = "") =>
    request("/access-control/pending/approve", {
      method: "POST",
      body: JSON.stringify({ channel, user_id: userId, remark }),
    }),

  denyAclPending: (channel: string, userId: string, remark: string = "") =>
    request("/access-control/pending/deny", {
      method: "POST",
      body: JSON.stringify({ channel, user_id: userId, remark }),
    }),

  dismissAclPending: (channel: string, userId: string) =>
    request("/access-control/pending/dismiss", {
      method: "POST",
      body: JSON.stringify({ channel, user_id: userId }),
    }),
};
