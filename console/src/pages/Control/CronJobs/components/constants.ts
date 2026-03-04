import dayjs from "dayjs";

export const TIMEZONE_OPTIONS = [
  { value: "UTC", label: "UTC" },
  { value: "Asia/Shanghai", label: "Asia/Shanghai (UTC+8)" },
  { value: "Asia/Tokyo", label: "Asia/Tokyo (UTC+9)" },
  { value: "Asia/Seoul", label: "Asia/Seoul (UTC+9)" },
  { value: "Asia/Hong_Kong", label: "Asia/Hong_Kong (UTC+8)" },
  { value: "Asia/Singapore", label: "Asia/Singapore (UTC+8)" },
  { value: "Asia/Dubai", label: "Asia/Dubai (UTC+4)" },
  { value: "Europe/London", label: "Europe/London (UTC+0)" },
  { value: "Europe/Paris", label: "Europe/Paris (UTC+1)" },
  { value: "Europe/Berlin", label: "Europe/Berlin (UTC+1)" },
  { value: "Europe/Moscow", label: "Europe/Moscow (UTC+3)" },
  { value: "America/New_York", label: "America/New_York (UTC-5)" },
  { value: "America/Chicago", label: "America/Chicago (UTC-6)" },
  { value: "America/Denver", label: "America/Denver (UTC-7)" },
  { value: "America/Los_Angeles", label: "America/Los_Angeles (UTC-8)" },
  { value: "America/Toronto", label: "America/Toronto (UTC-5)" },
  { value: "Australia/Sydney", label: "Australia/Sydney (UTC+10)" },
  { value: "Australia/Melbourne", label: "Australia/Melbourne (UTC+10)" },
  { value: "Pacific/Auckland", label: "Pacific/Auckland (UTC+12)" },
];

export const DEFAULT_FORM_VALUES = {
  enabled: false,
  schedule: {
    type: "cron" as const,
    cron: "0 9 * * *",
    timezone: "UTC",
  },
  cronType: "daily",
  cronTime: dayjs().hour(9).minute(0),
  task_type: "agent" as const,
  dispatch: {
    type: "channel" as const,
    channel: "console",
    target: {
      user_id: "",
      session_id: "",
    },
    mode: "final" as const,
  },
  runtime: {
    max_concurrency: 1,
    timeout_seconds: 120,
    misfire_grace_seconds: 60,
  },
};
