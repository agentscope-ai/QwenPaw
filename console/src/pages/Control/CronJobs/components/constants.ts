import dayjs from "dayjs";

export const DEFAULT_FORM_VALUES = {
  enabled: false,
  save_result_to_inbox: true,
  scheduleType: "cron" as const,
  schedule: {
    type: "cron" as const,
    cron: "0 9 * * *",
    timezone: "UTC",
  },
  onceRunAt: dayjs().add(1, "hour"),
  onceRepeatEnabled: false,
  onceRepeatEveryDays: 1,
  onceRepeatEndType: "never" as const,
  onceRepeatUntil: dayjs().add(7, "day"),
  onceRepeatCount: 2,
  cronType: "daily",
  cronTime: dayjs().hour(9).minute(0),
  task_type: "agent" as const,
  request: {
    input: "",
    session_id: "",
    user_id: "",
  },
  text: "",
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
    share_session: true,
    max_concurrency: 1,
    timeout_seconds: 120,
    misfire_grace_seconds: 60,
  },
};
