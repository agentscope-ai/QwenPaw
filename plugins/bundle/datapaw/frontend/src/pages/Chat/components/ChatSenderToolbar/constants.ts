export type DataSourceId = "stockstar" | "amap" | "yingmi" | "hackernews";

export interface DataSourceOption {
  id: DataSourceId;
  labelKey: string;
  /** Simple brand accent for the icon badge */
  accent: string;
  /** Short label shown inside the icon badge */
  badge: string;
}

export const DATA_SOURCE_OPTIONS: DataSourceOption[] = [
  {
    id: "stockstar",
    labelKey: "chat.dataSource.stockstar",
    accent: "#7c3aed",
    badge: "★",
  },
  {
    id: "amap",
    labelKey: "chat.dataSource.amap",
    accent: "#2563eb",
    badge: "📍",
  },
  {
    id: "yingmi",
    labelKey: "chat.dataSource.yingmi",
    accent: "#16a34a",
    badge: "¥",
  },
  {
    id: "hackernews",
    labelKey: "chat.dataSource.hackernews",
    accent: "#ea580c",
    badge: "Y",
  },
];

export const DATA_SOURCE_STORAGE_PREFIX = "qwenpaw_data_source_";
