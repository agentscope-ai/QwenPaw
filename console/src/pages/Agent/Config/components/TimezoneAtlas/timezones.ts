/** IANA's Etc/GMT identifiers use the opposite sign to UTC offsets. */
export function fixedTimezone(minutes: number) {
  if (minutes === 0) return "UTC";
  const hours = minutes / 60;
  return `Etc/GMT${hours > 0 ? "-" : "+"}${Math.abs(hours)}`;
}

export function timezoneOffset(zone: string, date: Date) {
  const text =
    new Intl.DateTimeFormat("en", {
      timeZone: zone,
      timeZoneName: "shortOffset",
    })
      .formatToParts(date)
      .find((part) => part.type === "timeZoneName")?.value || "GMT";
  const match = text.match(/GMT([+-])(\d+)(?::(\d+))?/);
  return match
    ? (Number(match[2]) * 60 + Number(match[3] || 0)) *
        (match[1] === "-" ? -1 : 1)
    : 0;
}

export function offsetLabel(minutes: number) {
  const absolute = Math.abs(minutes);
  return `UTC${minutes >= 0 ? "+" : "−"}${String(
    Math.floor(absolute / 60),
  ).padStart(2, "0")}:${String(absolute % 60).padStart(2, "0")}`;
}

export function timezoneName(
  zone: string,
  language: string,
  beijingLabel: string,
  date = new Date(),
) {
  if (zone === "Asia/Shanghai") return beijingLabel;
  if (zone === "UTC" || zone.startsWith("Etc/GMT")) {
    return offsetLabel(timezoneOffset(zone, date));
  }
  return (
    new Intl.DateTimeFormat(language, {
      timeZone: zone,
      timeZoneName: "longGeneric",
    })
      .formatToParts(date)
      .find((part) => part.type === "timeZoneName")?.value || zone
  );
}
