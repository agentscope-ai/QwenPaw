import { request } from "../request";

export interface NotificationRuleConfig {
  enabled: boolean;
  source_types: string[] | null;
  severities: string[] | null;
  event_types: string[] | null;
  agent_ids: string[] | null;
}

export interface NotificationSourceToggles {
  approval: boolean;
  cron_text: boolean;
  cron_agent: boolean;
  heartbeat: boolean;
  memory: boolean;
  skill_autoupdate: boolean;
}

export interface NotificationConfig {
  enabled: boolean;
  sound: boolean;
  min_interval_seconds: number;
  sources: NotificationSourceToggles;
  language: string;
  agent_ids: string[] | null;
  rules: NotificationRuleConfig[];
}

export interface NotificationTestResponse {
  success: boolean;
  message: string;
}

export interface SourceKeyEntry {
  key: keyof NotificationSourceToggles | "_label";
  labelKey: string;
  hintKey?: string;
  indent?: boolean;
  isLabel?: boolean;
}

export const NOTIFICATION_SOURCE_KEYS: SourceKeyEntry[] = [
  { key: "approval", labelKey: "notifications.sourceApproval" },
  { key: "_label", labelKey: "notifications.sourceCron", isLabel: true },
  {
    key: "cron_text",
    labelKey: "notifications.sourceCronText",
    hintKey: "notifications.sourceCronTextHint",
    indent: true,
  },
  {
    key: "cron_agent",
    labelKey: "notifications.sourceCronAgent",
    hintKey: "notifications.sourceCronAgentHint",
    indent: true,
  },
  { key: "heartbeat", labelKey: "notifications.sourceHeartbeat" },
  { key: "memory", labelKey: "notifications.sourceMemory" },
  { key: "skill_autoupdate", labelKey: "notifications.sourceSkillUpdate" },
];

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
