import { request } from "../request";

export interface NotificationRuleConfig {
  enabled: boolean;
  source_types: string[] | null;
  severities: string[] | null;
  event_types: string[] | null;
  agent_ids: string[] | null;
}

export interface NotificationSourceToggles {
  cron: boolean;
  heartbeat: boolean;
  memory: boolean;
  skill_autoupdate: boolean;
}

export interface NotificationConfig {
  enabled: boolean;
  sound: boolean;
  min_interval_seconds: number;
  sources: NotificationSourceToggles;
  agent_ids: string[] | null;
  rules: NotificationRuleConfig[];
}

export interface NotificationTestResponse {
  success: boolean;
  message: string;
}

export const notificationsApi = {
  getConfig: () => request<NotificationConfig>("/config/notifications"),

  updateConfig: (body: NotificationConfig) =>
    request<NotificationConfig>("/config/notifications", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  sendTest: () =>
    request<NotificationTestResponse>("/config/notifications/test", {
      method: "POST",
    }),
};
