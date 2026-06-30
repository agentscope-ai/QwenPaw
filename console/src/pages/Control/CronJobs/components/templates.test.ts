import { describe, it, expect } from "vitest";
import { CRON_TEMPLATES } from "./templates";

describe("CRON_TEMPLATES", () => {
  it("is an array with 10 items", () => {
    expect(Array.isArray(CRON_TEMPLATES)).toBe(true);
    expect(CRON_TEMPLATES).toHaveLength(10);
  });

  it("every template has all required fields", () => {
    const requiredFields = [
      "id",
      "category",
      "titleKey",
      "descriptionKey",
      "frequencyKey",
      "source",
      "tags",
      "showInCalendarRecommended",
      "toFormValues",
    ] as const;

    for (const template of CRON_TEMPLATES) {
      for (const field of requiredFields) {
        expect(
          template,
          `template "${template.id}" missing field "${field}"`,
        ).toHaveProperty(field);
      }
    }
  });

  it('every template\'s source is "builtin"', () => {
    for (const template of CRON_TEMPLATES) {
      expect(template.source, `template "${template.id}" source`).toBe(
        "builtin",
      );
    }
  });

  it("toFormValues('UTC') on a cron template returns scheduleType 'cron' and schedule.timezone 'UTC'", () => {
    // CRON_TEMPLATES[0] = daily_tech_news_brief, category: "cron"
    const cronTemplate = CRON_TEMPLATES[0];
    expect(cronTemplate.category).toBe("cron");

    const values = cronTemplate.toFormValues("UTC") as Record<string, unknown>;
    expect(values.scheduleType).toBe("cron");
    expect((values.schedule as Record<string, unknown>).timezone).toBe("UTC");
  });

  it("toFormValues('America/New_York') on an once template returns scheduleType 'once' and schedule.timezone 'America/New_York'", () => {
    // CRON_TEMPLATES[4] = once_text_birthday_reminder, category: "once"
    const onceTemplate = CRON_TEMPLATES[4];
    expect(onceTemplate.category).toBe("once");

    const values = onceTemplate.toFormValues("America/New_York") as Record<
      string,
      unknown
    >;
    expect(values.scheduleType).toBe("once");
    expect((values.schedule as Record<string, unknown>).timezone).toBe(
      "America/New_York",
    );
  });

  it("agent-type template has task_type 'agent' and a request object; text-type has a different task_type and a text string", () => {
    // CRON_TEMPLATES[0] = daily_tech_news_brief, agent type
    const agentValues = CRON_TEMPLATES[0].toFormValues("UTC") as Record<
      string,
      unknown
    >;
    expect(agentValues.task_type).toBe("agent");
    expect(agentValues.request).toBeDefined();
    expect(typeof agentValues.request).toBe("object");

    // CRON_TEMPLATES[2] = pomodoro_break_reminder, text type
    const textValues = CRON_TEMPLATES[2].toFormValues("UTC") as Record<
      string,
      unknown
    >;
    expect(textValues.task_type).not.toBe("agent");
    expect(typeof textValues.text).toBe("string");
  });
});
