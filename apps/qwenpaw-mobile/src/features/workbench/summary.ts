export function summarizeModulePayload(payload: unknown): string {
  if (Array.isArray(payload)) return `${payload.length} 项`;
  if (payload && typeof payload === "object") {
    const keys = Object.keys(payload);
    if (keys.length === 1) {
      const value = (payload as Record<string, unknown>)[keys[0]];
      if (Array.isArray(value)) return `${value.length} 项`;
    }
    return `${keys.length} 个配置字段`;
  }
  return "已同步";
}

export interface ModuleSnapshotItem {
  id: string;
  title: string;
  subtitle?: string;
}

const TITLE_KEYS = ["name", "title", "id", "key", "provider_id", "session_id"];
const SUBTITLE_KEYS = ["description", "status", "type", "channel", "enabled"];

export function moduleSnapshotItems(payload: unknown): ModuleSnapshotItem[] {
  const collection = extractCollection(payload);
  if (collection) {
    return collection.slice(0, 100).map((value, index) => (
      snapshotItem(value, index)
    ));
  }
  if (!payload || typeof payload !== "object") return [];
  return Object.entries(payload as Record<string, unknown>)
    .filter(([key]) => !isSensitiveKey(key))
    .slice(0, 100)
    .map(([key, value]) => ({
      id: key,
      title: humanize(key),
      subtitle: summarizeValue(value),
    }));
}

function extractCollection(payload: unknown): unknown[] | null {
  if (Array.isArray(payload)) return payload;
  if (!payload || typeof payload !== "object") return null;
  const values = Object.values(payload);
  if (values.length === 1 && Array.isArray(values[0])) return values[0];
  return null;
}

function snapshotItem(value: unknown, index: number): ModuleSnapshotItem {
  if (!value || typeof value !== "object") {
    return { id: String(index), title: String(value) };
  }
  const record = value as Record<string, unknown>;
  const titleKey = TITLE_KEYS.find((key) => typeof record[key] === "string");
  const subtitleKey = SUBTITLE_KEYS.find((key) => (
    typeof record[key] === "string" || typeof record[key] === "boolean"
  ));
  const title = titleKey ? String(record[titleKey]) : `项目 ${index + 1}`;
  const subtitle = subtitleKey
    ? `${humanize(subtitleKey)} · ${summarizeValue(record[subtitleKey])}`
    : undefined;
  return { id: `${title}-${index}`, title, subtitle };
}

function summarizeValue(value: unknown): string {
  if (typeof value === "boolean") return value ? "已启用" : "已停用";
  if (typeof value === "string" || typeof value === "number") {
    return String(value);
  }
  if (Array.isArray(value)) return `${value.length} 项`;
  if (value && typeof value === "object") {
    return `${Object.keys(value).length} 个配置字段`;
  }
  return "未设置";
}

function isSensitiveKey(key: string): boolean {
  return /password|secret|token|credential|api.?key|value/i.test(key);
}

function humanize(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => (
    letter.toUpperCase()
  ));
}
