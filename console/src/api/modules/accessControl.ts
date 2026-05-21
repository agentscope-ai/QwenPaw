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
  remark: string;
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

  /**
   * Unified pending action API - works for both single and batch operations.
   * Pass an array of entries (1 or more).
   */
  approveAclPending: (
    entries: { channel: string; user_id: string; remark?: string }[]
  ) =>
    request("/access-control/pending/approve", {
      method: "POST",
      body: JSON.stringify({ entries }),
    }),

  denyAclPending: (
    entries: { channel: string; user_id: string; remark?: string }[]
  ) =>
    request("/access-control/pending/deny", {
      method: "POST",
      body: JSON.stringify({ entries }),
    }),

  dismissAclPending: (entries: { channel: string; user_id: string }[]) =>
    request("/access-control/pending/dismiss", {
      method: "POST",
      body: JSON.stringify({ entries }),
    }),

  updatePendingRemark: (channel: string, userId: string, remark: string) =>
    request("/access-control/pending/remark", {
      method: "POST",
      body: JSON.stringify({ channel, user_id: userId, remark }),
    }),
};
