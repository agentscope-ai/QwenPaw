import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";
import "dayjs/locale/zh-cn";
import "dayjs/locale/ja";
import "dayjs/locale/ru";

dayjs.extend(relativeTime);

const LOCALE_MAP: Record<string, string> = {
  en: "en",
  zh: "zh-cn",
  ja: "ja",
  ru: "ru",
};

export const formatFileSize = (bytes: number): string => {
  if (bytes === 0) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
};

export const formatTimeAgo = (
  timestamp: number | string,
  locale: string = "en",
): string => {
  const time =
    typeof timestamp === "string" ? new Date(timestamp).getTime() : timestamp;
  if (isNaN(time)) {
    return "-";
  }

  const dayjsLocale = LOCALE_MAP[locale] || "en";
  return dayjs(time).locale(dayjsLocale).fromNow();
};

export const isDailyMemoryFile = (filename: string): boolean => {
  return /^\d{4}-\d{2}-\d{2}\.md$/.test(filename);
};
