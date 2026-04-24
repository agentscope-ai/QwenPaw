import dayjs from "dayjs";

export type CronTemplateCategory = "cron" | "once";
export type CronTemplateTag = "personal" | "team" | "reminder" | "calendar";

export interface CronTemplateDefinition {
  id: string;
  category: CronTemplateCategory;
  titleKey: string;
  descriptionKey: string;
  frequencyKey: string;
  source: "builtin";
  tags: CronTemplateTag[];
  showInCalendarRecommended: boolean;
  toFormValues: (timezone: string) => Record<string, unknown>;
}

// Phase 1: built-in templates only.
// Phase 2: merge user-saved templates into this collection at runtime.

const buildDispatch = () => ({
  type: "channel" as const,
  channel: "console",
  target: {
    user_id: "default",
    session_id: "cron_job",
  },
  mode: "final" as const,
});

const buildRuntime = () => ({
  max_concurrency: 1,
  timeout_seconds: 120,
  misfire_grace_seconds: 60,
});

const createCustomCronTemplate = (
  id: string,
  titleKey: string,
  descriptionKey: string,
  frequencyKey: string,
  cronCustom: string,
  options: {
    taskType?: "text" | "agent";
    textContent?: string;
    agentPrompt?: string;
  },
  tags: CronTemplateTag[],
): CronTemplateDefinition => ({
  id,
  category: "cron",
  titleKey,
  descriptionKey,
  frequencyKey,
  source: "builtin",
  tags,
  showInCalendarRecommended: true,
  toFormValues: (timezone) => ({
    name: "",
    enabled: true,
    scheduleType: "cron",
    cronType: "custom",
    cronCustom,
    schedule: {
      type: "cron",
      timezone,
    },
    task_type: options.taskType || "text",
    text: options.taskType === "agent" ? "" : options.textContent || "",
    request:
      options.taskType === "agent"
        ? {
            input: JSON.stringify(
              [
                {
                  role: "user",
                  content: [
                    {
                      type: "text",
                      text: options.agentPrompt || "",
                    },
                  ],
                },
              ],
              null,
              2,
            ),
            session_id: "",
            user_id: "",
          }
        : undefined,
    dispatch: buildDispatch(),
    runtime: buildRuntime(),
    meta: {
      template_id: id,
      template_source: "builtin",
      show_in_calendar: true,
    },
  }),
});

const createScheduledTemplate = (
  id: string,
  titleKey: string,
  descriptionKey: string,
  frequencyKey: string,
  options: {
    repeatEnabled: boolean;
    repeatEveryDays?: number;
    repeatEndType?: "never" | "until" | "count";
    repeatUntilDaysFromNow?: number;
    repeatCount?: number;
  },
  tags: CronTemplateTag[],
): CronTemplateDefinition => ({
  id,
  category: "once",
  titleKey,
  descriptionKey,
  frequencyKey,
  source: "builtin",
  tags,
  showInCalendarRecommended: true,
  toFormValues: (timezone) => {
    const onceRunAt = dayjs().add(1, "hour");
    const onceRepeatUntil =
      options.repeatUntilDaysFromNow !== undefined
        ? onceRunAt.add(options.repeatUntilDaysFromNow, "day")
        : null;
    return {
      name: "",
      enabled: true,
      scheduleType: "once",
      onceRunAt,
      onceRepeatEnabled: options.repeatEnabled,
      onceRepeatEveryDays: options.repeatEveryDays ?? 1,
      onceRepeatEndType: options.repeatEndType ?? "never",
      onceRepeatUntil,
      onceRepeatCount: options.repeatCount ?? 2,
      schedule: {
        type: "once",
        timezone,
      },
      task_type: "text",
      text: "",
      dispatch: buildDispatch(),
      runtime: buildRuntime(),
      meta: {
        template_id: id,
        template_source: "builtin",
        show_in_calendar: true,
      },
    };
  },
});

export const CRON_TEMPLATES: CronTemplateDefinition[] = [
  createCustomCronTemplate(
    "daily_tech_news_brief",
    "cronJobs.templates.dailyTechNewsBrief.title",
    "cronJobs.templates.dailyTechNewsBrief.description",
    "cronJobs.templates.dailyTechNewsBrief.frequency",
    "30 9 * * 1-5",
    {
      taskType: "agent",
      agentPrompt:
        "整理今天最值得关注的科技新闻，输出 5-8 条。每条包含：新闻标题、核心进展、为什么值得关注。最后补充一句今日科技趋势判断。",
    },
    ["personal", "reminder", "calendar"],
  ),
  createCustomCronTemplate(
    "weekend_relaxation_reminder",
    "cronJobs.templates.weekendRelaxationReminder.title",
    "cronJobs.templates.weekendRelaxationReminder.description",
    "cronJobs.templates.weekendRelaxationReminder.frequency",
    "0 10 * * 6,0",
    {
      taskType: "agent",
      agentPrompt:
        "推荐最近热度高、口碑好的电影，给出 5 部。每部包含：类型、一句话看点、适合人群；如果有公开信息，请补充上映/平台情况。",
    },
    ["team", "reminder", "calendar"],
  ),
  createCustomCronTemplate(
    "pomodoro_break_reminder",
    "cronJobs.templates.pomodoroBreakReminder.title",
    "cronJobs.templates.pomodoroBreakReminder.description",
    "cronJobs.templates.pomodoroBreakReminder.frequency",
    "*/25 9-17 * * 1-5",
    {
      textContent:
        "持续工作25分钟啦，起来活动一下，喝口水，顺便看看远处放松眼睛～",
    },
    ["personal", "reminder", "calendar"],
  ),
  createCustomCronTemplate(
    "pet_care_reminder",
    "cronJobs.templates.petCareReminder.title",
    "cronJobs.templates.petCareReminder.description",
    "cronJobs.templates.petCareReminder.frequency",
    "0 20 15 * *",
    {
      textContent: "小提醒：今天记得给毛孩子安排驱虫/疫苗检查喔～",
    },
    ["personal", "reminder", "calendar"],
  ),
  createScheduledTemplate(
    "one_time_reminder",
    "cronJobs.templates.oneTimeReminder.title",
    "cronJobs.templates.oneTimeReminder.description",
    "cronJobs.templates.oneTimeReminder.frequency",
    {
      repeatEnabled: false,
    },
    ["personal", "reminder", "calendar"],
  ),
  createScheduledTemplate(
    "n_day_checkin",
    "cronJobs.templates.nDayCheckin.title",
    "cronJobs.templates.nDayCheckin.description",
    "cronJobs.templates.nDayCheckin.frequency",
    {
      repeatEnabled: true,
      repeatEveryDays: 1,
      repeatEndType: "count",
      repeatCount: 7,
    },
    ["personal", "reminder", "calendar"],
  ),
  createScheduledTemplate(
    "daily_until_deadline",
    "cronJobs.templates.dailyUntilDeadline.title",
    "cronJobs.templates.dailyUntilDeadline.description",
    "cronJobs.templates.dailyUntilDeadline.frequency",
    {
      repeatEnabled: true,
      repeatEveryDays: 1,
      repeatEndType: "until",
      repeatUntilDaysFromNow: 14,
    },
    ["team", "reminder", "calendar"],
  ),
  createScheduledTemplate(
    "release_countdown",
    "cronJobs.templates.releaseCountdown.title",
    "cronJobs.templates.releaseCountdown.description",
    "cronJobs.templates.releaseCountdown.frequency",
    {
      repeatEnabled: true,
      repeatEveryDays: 1,
      repeatEndType: "until",
      repeatUntilDaysFromNow: 10,
    },
    ["team", "reminder", "calendar"],
  ),
  createScheduledTemplate(
    "training_cycle",
    "cronJobs.templates.trainingCycle.title",
    "cronJobs.templates.trainingCycle.description",
    "cronJobs.templates.trainingCycle.frequency",
    {
      repeatEnabled: true,
      repeatEveryDays: 7,
      repeatEndType: "count",
      repeatCount: 6,
    },
    ["team", "calendar"],
  ),
  createScheduledTemplate(
    "sprint_cadence",
    "cronJobs.templates.sprintCadence.title",
    "cronJobs.templates.sprintCadence.description",
    "cronJobs.templates.sprintCadence.frequency",
    {
      repeatEnabled: true,
      repeatEveryDays: 2,
      repeatEndType: "count",
      repeatCount: 10,
    },
    ["team", "calendar"],
  ),
];
