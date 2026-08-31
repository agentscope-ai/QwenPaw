import { afterEach, describe, expect, it } from "vitest";
import dayjs from "dayjs";
import "dayjs/locale/zh-cn";
import { getCalendarDays, getCalendarWeekLabels } from "./calendar";

describe("calendar layout", () => {
  afterEach(() => {
    dayjs.locale("en");
  });

  it("always uses Sunday as the first column in the Chinese locale", () => {
    dayjs.locale("zh-cn");
    const calendarDays = getCalendarDays(dayjs("2026-08-27"));

    expect(calendarDays[0].day()).toBe(0);
    expect(getCalendarWeekLabels(calendarDays)[0]).toBe("日");
  });

  it("places 2026-08-27 under Thursday in the Chinese locale", () => {
    dayjs.locale("zh-cn");
    const targetDate = dayjs("2026-08-27");
    const calendarDays = getCalendarDays(targetDate);
    const targetColumn =
      calendarDays.findIndex((day) => day.isSame(targetDate, "day")) % 7;

    expect(getCalendarWeekLabels(calendarDays)[targetColumn]).toBe(
      targetDate.format("dd"),
    );
  });
});
