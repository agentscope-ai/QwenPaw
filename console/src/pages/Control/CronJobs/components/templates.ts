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
  share_session: true,
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
    taskType?: "text" | "agent";
    textContent?: string;
    agentPrompt?: string;
    runAt?: dayjs.Dayjs;
    repeatEnabled: boolean;
    repeatEveryDays?: number;
    repeatEndType?: "never" | "until" | "count";
    repeatUntil?: dayjs.Dayjs;
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
    const onceRunAt = options.runAt ?? dayjs("2026-01-01T09:00:00");
    return {
      name: "",
      enabled: true,
      save_result_to_inbox: true,
      scheduleType: "once",
      onceRunAt,
      onceRepeatEnabled: options.repeatEnabled,
      onceRepeatEveryDays: options.repeatEveryDays ?? 1,
      onceRepeatEndType: options.repeatEndType ?? "never",
      onceRepeatUntil: options.repeatUntil ?? null,
      onceRepeatCount: options.repeatCount ?? 2,
      schedule: {
        type: "once",
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
    "once_text_birthday_reminder",
    "cronJobs.templates.onceTextBirthdayReminder.title",
    "cronJobs.templates.onceTextBirthdayReminder.description",
    "cronJobs.templates.onceTextBirthdayReminder.frequency",
    {
      taskType: "text",
      textContent: "xx在1月1日过生日，别忘了送上祝福～",
      runAt: dayjs("2026-01-01T09:00:00"),
      repeatEnabled: false,
    },
    ["personal", "reminder", "calendar"],
  ),
  createScheduledTemplate(
    "once_agent_business_trip_prep",
    "cronJobs.templates.onceAgentBusinessTripPrep.title",
    "cronJobs.templates.onceAgentBusinessTripPrep.description",
    "cronJobs.templates.onceAgentBusinessTripPrep.frequency",
    {
      taskType: "agent",
      agentPrompt:
        "我明天要出差，请查询目的地天气，并给出穿衣、携带物品和行程准备建议。",
      runAt: dayjs("2026-01-01T20:00:00"),
      repeatEnabled: false,
    },
    ["personal", "reminder", "calendar"],
  ),
  createScheduledTemplate(
    "repeat_count_text_medicine_reminder",
    "cronJobs.templates.repeatCountTextMedicineReminder.title",
    "cronJobs.templates.repeatCountTextMedicineReminder.description",
    "cronJobs.templates.repeatCountTextMedicineReminder.frequency",
    {
      taskType: "text",
      textContent: "注意身体，别忘记吃药哦。",
      runAt: dayjs("2026-01-01T09:00:00"),
      repeatEnabled: true,
      repeatEveryDays: 1,
      repeatEndType: "count",
      repeatCount: 14,
    },
    ["personal", "reminder", "calendar"],
  ),
  createScheduledTemplate(
    "repeat_count_agent_diet_plan",
    "cronJobs.templates.repeatCountAgentDietPlan.title",
    "cronJobs.templates.repeatCountAgentDietPlan.description",
    "cronJobs.templates.repeatCountAgentDietPlan.frequency",
    {
      taskType: "agent",
      agentPrompt: "我最近在增肌，请为我生成今天的饮食建议。",
      runAt: dayjs("2026-01-01T08:00:00"),
      repeatEnabled: true,
      repeatEveryDays: 1,
      repeatEndType: "count",
      repeatCount: 14,
    },
    ["personal", "reminder", "calendar"],
  ),
  createScheduledTemplate(
    "repeat_until_text_weekly_meeting",
    "cronJobs.templates.repeatUntilTextWeeklyMeeting.title",
    "cronJobs.templates.repeatUntilTextWeeklyMeeting.description",
    "cronJobs.templates.repeatUntilTextWeeklyMeeting.frequency",
    {
      taskType: "text",
      textContent: "15分钟后周会开始。",
      runAt: dayjs("2026-01-02T08:45:00"),
      repeatEnabled: true,
      repeatEveryDays: 7,
      repeatEndType: "until",
      repeatUntil: dayjs("2026-03-01T23:59:00"),
    },
    ["team", "reminder", "calendar"],
  ),
  createScheduledTemplate(
    "repeat_until_agent_weekly_summary",
    "cronJobs.templates.repeatUntilAgentWeeklySummary.title",
    "cronJobs.templates.repeatUntilAgentWeeklySummary.description",
    "cronJobs.templates.repeatUntilAgentWeeklySummary.frequency",
    {
      taskType: "agent",
      agentPrompt:
        "请基于最近一周的 memory，生成本周工作总结，供周会前快速回顾。",
      runAt: dayjs("2026-01-02T08:30:00"),
      repeatEnabled: true,
      repeatEveryDays: 7,
      repeatEndType: "until",
      repeatUntil: dayjs("2026-03-01T23:59:00"),
    },
    ["team", "calendar"],
  ),
];
