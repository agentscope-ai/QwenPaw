import type { DataSourceType } from "../../../api/types/dataSource";

export type { DataSourceType };

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
