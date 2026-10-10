import type { Dayjs } from "dayjs";

export function getCalendarDays(calendarMonth: Dayjs): Dayjs[] {
  const monthStart = calendarMonth.startOf("month");
  const calendarStart = monthStart.subtract(monthStart.day(), "day");
  return Array.from({ length: 42 }, (_, index) =>
    calendarStart.add(index, "day"),
  );
}

export function getCalendarWeekLabels(calendarDays: Dayjs[]): string[] {
  return calendarDays.slice(0, 7).map((day) => day.format("dd"));
}
