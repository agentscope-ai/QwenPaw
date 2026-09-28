import type { Dayjs } from "dayjs";
import type { TokenUsageRecord } from "@/api/types/tokenUsage";

export function buildActivity(
  records: TokenUsageRecord[],
  start: Dayjs,
  end: Dayjs,
) {
  const totals = new Map<string, number>();
  const models = new Map<string, number>();
  for (const row of records) {
    if (
      row.date < start.format("YYYY-MM-DD") ||
      row.date > end.format("YYYY-MM-DD")
    )
      continue;
    const value = row.prompt_tokens + row.completion_tokens;
    totals.set(row.date, (totals.get(row.date) ?? 0) + value);
    const key = `${row.provider_id}:${row.model}`;
    models.set(key, (models.get(key) ?? 0) + value);
  }
  const days: { date: string; value: number; inRange: boolean }[] = [];
  // Pad only for weekday alignment; out-of-range cells are not zero-usage days.
  let cursor = start.startOf("day").subtract((start.day() + 6) % 7, "day");
  const last = end.startOf("day").add(6 - ((end.day() + 6) % 7), "day");
  while (!cursor.isAfter(last, "day")) {
    const date = cursor.format("YYYY-MM-DD");
    days.push({
      date,
      value: totals.get(date) ?? 0,
      inRange: !cursor.isBefore(start, "day") && !cursor.isAfter(end, "day"),
    });
    cursor = cursor.add(1, "day");
  }
  return {
    days,
    models: [...models].sort((a, b) => b[1] - a[1]),
    max: Math.max(1, ...totals.values()),
  };
}
