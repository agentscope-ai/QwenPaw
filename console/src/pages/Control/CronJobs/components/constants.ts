import dayjs from "dayjs";

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
  execution: {
    session: {
      mode: "dispatch" as const,
    },
  },
  sessionStrategy: "dispatch" as const,
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
