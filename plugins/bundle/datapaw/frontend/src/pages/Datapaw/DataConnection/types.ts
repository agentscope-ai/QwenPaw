import type { DataSourceType } from "../../../api/types/dataSource";

export type { DataSourceType };

/** Types available on the add-data-source form */
export const FORM_DATA_SOURCE_TYPES: DataSourceType[] = [
  "csv",
  "mysql",
  "postgresql",
];

export const DATA_CONNECTION_TYPE_META: Record<
  DataSourceType,
  { labelKey: string; accent: string; badge: string }
> = {
  csv: {
    labelKey: "dataConnection.types.csv",
    accent: "#6366f1",
    badge: "CSV",
  },
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
  api: {
    labelKey: "dataConnection.types.api",
    accent: "#ea580c",
    badge: "API",
  },
};

export const DEFAULT_PORTS: Partial<Record<DataSourceType, number>> = {
  mysql: 3306,
  postgresql: 5432,
};
