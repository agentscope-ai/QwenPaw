import type {
  DataSourceType,
  DataSourceTypeInfo,
} from "../../../api/types/dataSource";

export type { DataSourceType };

/** Supported types for the add-data-source form (static, no API). */
export const SUPPORTED_DATA_SOURCE_TYPES: DataSourceTypeInfo[] = [
  { type: "mysql" },
  { type: "postgresql" },
  { type: "odps" },
];

export const DATA_CONNECTION_TYPE_META: Record<
  DataSourceType,
  { labelKey: string; accent: string; badge: string }
> = {
  mysql: {
    labelKey: "dataConnection.types.mysql",
    accent: "#2563eb",
    badge: "SQL",
  },
  postgresql: {
    labelKey: "dataConnection.types.postgresql",
    accent: "#0d9488",
    badge: "PG",
  },
  odps: {
    labelKey: "dataConnection.types.odps",
    accent: "#7c3aed",
    badge: "ODPS",
  },
};
