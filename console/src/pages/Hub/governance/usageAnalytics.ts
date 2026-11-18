import type { UsageDetailRow } from "../../../api/modules/hubGovernance";

export const usageFields = [
  "requests",
  "charged",
  "actual",
  "reserved",
  "conservative",
  "failures",
] as const;
export type UsageTotals = Pick<UsageDetailRow, (typeof usageFields)[number]>;
export type UsageGroup = UsageTotals & {
  key: string;
  label: string;
  members: number;
  models: number;
};
export function groupUsage(
  rows: UsageDetailRow[],
  dimension: "user_id" | "model_id" | "date",
): UsageGroup[] {
  const groups = new Map<
    string,
    { row: UsageGroup; users: Set<string>; models: Set<string> }
  >();
  for (const item of rows) {
    const key = item[dimension];
    if (!groups.has(key))
      groups.set(key, {
        row: {
          key,
          label:
            dimension === "user_id"
              ? item.username
              : dimension === "model_id"
              ? item.model_name
              : item.date,
          requests: 0,
          charged: 0,
          actual: 0,
          reserved: 0,
          conservative: 0,
          failures: 0,
          members: 0,
          models: 0,
        },
        users: new Set(),
        models: new Set(),
      });
    const group = groups.get(key)!;
    for (const field of usageFields) group.row[field] += item[field];
    group.users.add(item.user_id);
    group.models.add(item.model_id);
    group.row.members = group.users.size;
    group.row.models = group.models.size;
  }
  return [...groups.values()]
    .map((group) => group.row)
    .sort((a, b) => b.charged - a.charged || a.key.localeCompare(b.key));
}
