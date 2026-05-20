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
  getAllACLs: () => request<Record<string, ACLData>>("/access-control"),

  getChannelACL: (channel: string) =>
    request<ACLData>(`/access-control/${channel}`),

  setWhitelist: (channel: string, userIds: string[]) =>
    request(`/access-control/${channel}/whitelist`, {
      method: "PUT",
      body: JSON.stringify({ user_ids: userIds }),
    }),

  addToWhitelist: (channel: string, userId: string, remark: string = "") =>
    request(`/access-control/${channel}/whitelist/add`, {
      method: "POST",
      body: JSON.stringify({ user_id: userId, remark }),
    }),

  removeFromWhitelist: (channel: string, userId: string) =>
    request(`/access-control/${channel}/whitelist/remove`, {
      method: "POST",
      body: JSON.stringify({ user_id: userId }),
    }),

  setBlacklist: (channel: string, userIds: string[]) =>
    request(`/access-control/${channel}/blacklist`, {
      method: "PUT",
      body: JSON.stringify({ user_ids: userIds }),
    }),

  addToBlacklist: (channel: string, userId: string, remark: string = "") =>
    request(`/access-control/${channel}/blacklist/add`, {
      method: "POST",
      body: JSON.stringify({ user_id: userId, remark }),
    }),

  removeFromBlacklist: (channel: string, userId: string) =>
    request(`/access-control/${channel}/blacklist/remove`, {
      method: "POST",
      body: JSON.stringify({ user_id: userId }),
    }),

  updateRemark: (channel: string, userId: string, remark: string) =>
    request(`/access-control/${channel}/remark`, {
      method: "POST",
      body: JSON.stringify({ user_id: userId, remark }),
    }),

  getAllPending: () =>
    request<PendingEntry[]>("/access-control/pending/all"),

  approvePending: (channel: string, userId: string, remark: string = "") =>
    request("/access-control/pending/approve", {
      method: "POST",
      body: JSON.stringify({ channel, user_id: userId, remark }),
    }),

  denyPending: (channel: string, userId: string, remark: string = "") =>
    request("/access-control/pending/deny", {
      method: "POST",
      body: JSON.stringify({ channel, user_id: userId, remark }),
    }),

  dismissPending: (channel: string, userId: string) =>
    request("/access-control/pending/dismiss", {
      method: "POST",
      body: JSON.stringify({ channel, user_id: userId }),
    }),
};
