const days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

export function readSchedule(value: string) {
  const match = /^(\d{1,2}) (\d{1,2}) \* \* (\*|[a-z,]+)$/.exec(value.trim());
  if (!match || Number(match[1]) > 59 || Number(match[2]) > 23) return null;
  const selected = match[3] === "*" ? [] : match[3].split(",");
  if (selected.some((day) => !days.includes(day))) return null;
  return { minutes: Number(match[2]) * 60 + Number(match[1]), days: selected };
}

export function writeSchedule(minutes: number, selected: string[]) {
  const ordered = days.filter((day) => selected.includes(day));
  return `${minutes % 60} ${Math.floor(minutes / 60)} * * ${
    ordered.length ? ordered.join(",") : "*"
  }`;
}

export const scheduleDays = days;
