import { getTimeZones } from "@vvo/tzdb";

const TIMEZONE_ID_SET = new Set([
  "America/Los_Angeles",
  "America/Denver",
  "America/Chicago",
  "America/New_York",
  "America/Toronto",
  "UTC",
  "Europe/London",
  "Europe/Paris",
  "Europe/Berlin",
  "Europe/Moscow",
  "Asia/Dubai",
  "Asia/Shanghai",
  "Asia/Hong_Kong",
  "Asia/Singapore",
  "Asia/Tokyo",
  "Asia/Seoul",
  "Australia/Sydney",
  "Australia/Melbourne",
  "Pacific/Auckland",
]);

export interface TimezoneOption {
  value: string; // for timezone id
  label: string; // for display text
}

function getLocalizedName(tzName: string, lang: string): string {
  const locale = { zh: "zh-CN", en: "en", ru: "ru", ja: "ja" }[lang] || "en";
  try {
    const parts = new Intl.DateTimeFormat(locale, {
      timeZone: tzName,
      timeZoneName: "long",
    }).formatToParts(new Date());
    return parts.find((p) => p.type === "timeZoneName")?.value || tzName;
  } catch {
    return tzName;
  }
}

export function getTimezoneOptions(lang: string = "en"): TimezoneOption[] {
  return getTimeZones({ includeUtc: true })
    .filter(
      (tz) =>
        TIMEZONE_ID_SET.has(tz.name) ||
        (tz.name === "Etc/UTC" && TIMEZONE_ID_SET.has("UTC")),
    )
    .sort((a, b) => a.currentTimeOffsetInMinutes - b.currentTimeOffsetInMinutes)
    .map((tz) => {
      const value = tz.name === "Etc/UTC" ? "UTC" : tz.name;
      return {
        value,
        label: `${getLocalizedName(tz.name, lang)} (${
          tz.currentTimeFormat.split(" ")[0]
        }, ${value})`,
      };
    });
}
