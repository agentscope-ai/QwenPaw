import { request } from "../request";

export interface MailUserInfo {
  remark: string;
  display_name: string;
}

export interface MailPendingEntry {
  sender_address: string;
  agent_id: string;
  display_name: string;
  subject: string;
  body_preview: string;
  timestamp: number;
  remark: string;
}

export interface MailACLUserEntry {
  agent_id: string;
  address: string;
  display_name: string;
  remark: string;
}

export interface MailACLData {
  whitelist: Record<string, MailUserInfo>;
  blacklist: Record<string, MailUserInfo>;
  pending: MailPendingEntry[];
}

export const mailAccessControlApi = {
  getMailAclAll: () =>
    request<Record<string, MailACLData>>("/mail-access-control"),

  getMailAgents: () =>
    request<{ agents: string[] }>("/mail-access-control/agents"),

  getMailPendingAll: () =>
    request<MailPendingEntry[]>("/mail-access-control/pending/all"),

  getMailPendingCount: () =>
    request<{ count: number }>("/mail-access-control/pending/count"),

  approveMailPending: (
    entries: { agent_id: string; address: string; remark?: string }[],
  ) =>
    request("/mail-access-control/pending/approve", {
      method: "POST",
      body: JSON.stringify({ entries }),
    }),

  denyMailPending: (
    entries: { agent_id: string; address: string; remark?: string }[],
  ) =>
    request("/mail-access-control/pending/deny", {
      method: "POST",
      body: JSON.stringify({ entries }),
    }),

  dismissMailPending: (entries: { agent_id: string; address: string }[]) =>
    request("/mail-access-control/pending/dismiss", {
      method: "POST",
      body: JSON.stringify({ entries }),
    }),

  updateMailPendingRemark: (
    agent_id: string,
    address: string,
    remark: string,
  ) =>
    request("/mail-access-control/pending/remark", {
      method: "POST",
      body: JSON.stringify({ agent_id, address, remark }),
    }),

  addMailWhitelist: (
    entries: {
      agent_id: string;
      address: string;
      remark?: string;
      display_name?: string;
    }[],
  ) =>
    request("/mail-access-control/whitelist/add", {
      method: "POST",
      body: JSON.stringify({ entries }),
    }),

  removeMailWhitelist: (entries: { agent_id: string; address: string }[]) =>
    request("/mail-access-control/whitelist/remove", {
      method: "POST",
      body: JSON.stringify({ entries }),
    }),

  addMailBlacklist: (
    entries: {
      agent_id: string;
      address: string;
      remark?: string;
      display_name?: string;
    }[],
  ) =>
    request("/mail-access-control/blacklist/add", {
      method: "POST",
      body: JSON.stringify({ entries }),
    }),

  removeMailBlacklist: (entries: { agent_id: string; address: string }[]) =>
    request("/mail-access-control/blacklist/remove", {
      method: "POST",
      body: JSON.stringify({ entries }),
    }),

  updateMailRemark: (agent_id: string, address: string, remark: string) =>
    request("/mail-access-control/remark", {
      method: "POST",
      body: JSON.stringify({ agent_id, address, remark }),
    }),
};
