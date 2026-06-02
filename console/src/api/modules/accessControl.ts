import { request } from "../request";

export interface UserInfo {
  remark: string;
  username: string;
}

export interface ACLData {
  whitelist: Record<string, UserInfo>;
  blacklist: Record<string, UserInfo>;
  pending: PendingEntry[];
}

export interface PendingEntry {
  user_id: string;
  channel: string;
  timestamp: number;
  first_message: string;
  remark: string;
  username: string;
}

export interface ACLUserEntry {
  userId: string;
  remark: string;
  username: string;
}

export const accessControlApi = {
  getAclAll: () => request<Record<string, ACLData>>("/access-control"),

  getAclChannel: (channel: string) =>
    request<ACLData>(`/access-control/${channel}`),

  /**
   * Unified whitelist/blacklist/remark APIs - work for both single and batch.
   * Pass an array of entries (1 or more).
   */
  addAclWhitelist: (
    entries: {
      channel: string;
      user_id: string;
      remark?: string;
      username?: string;
    }[],
  ) =>
    request("/access-control/whitelist/add", {
      method: "POST",
      body: JSON.stringify({ entries }),
    }),

  removeAclWhitelist: (entries: { channel: string; user_id: string }[]) =>
    request("/access-control/whitelist/remove", {
      method: "POST",
      body: JSON.stringify({ entries }),
    }),

  addAclBlacklist: (
    entries: {
      channel: string;
      user_id: string;
      remark?: string;
      username?: string;
    }[],
  ) =>
    request("/access-control/blacklist/add", {
      method: "POST",
      body: JSON.stringify({ entries }),
    }),

  removeAclBlacklist: (entries: { channel: string; user_id: string }[]) =>
    request("/access-control/blacklist/remove", {
      method: "POST",
      body: JSON.stringify({ entries }),
    }),

  updateAclRemark: (channel: string, userId: string, remark: string) =>
    request("/access-control/remark", {
      method: "POST",
      body: JSON.stringify({ channel, user_id: userId, remark }),
    }),

  getAclAllPending: () =>
    request<PendingEntry[]>("/access-control/pending/all"),

  /**
   * Unified pending action API - works for both single and batch operations.
   * Pass an array of entries (1 or more).
   */
  approveAclPending: (
    entries: { channel: string; user_id: string; remark?: string }[],
  ) =>
    request("/access-control/pending/approve", {
      method: "POST",
      body: JSON.stringify({ entries }),
    }),

  denyAclPending: (
    entries: { channel: string; user_id: string; remark?: string }[],
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

  updateUsername: (channel: string, userId: string, username: string) =>
    request("/access-control/username", {
      method: "POST",
      body: JSON.stringify({ channel, user_id: userId, username }),
    }),
};
