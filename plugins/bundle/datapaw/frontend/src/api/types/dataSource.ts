/** Supported data source types (aligned with backend API). */
export type DataSourceType = "mysql" | "postgresql" | "odps";

export interface MysqlPostgresConfig {
  host?: string;
  port?: number;
  user?: string;
  password?: string;
  db?: string;
}

export interface OdpsConfig {
  endpoint?: string;
  project_name?: string;
  access_id?: string;
  access_key?: string;
  app_name?: string;
}

export type DataSourceConnectionConfig = MysqlPostgresConfig & OdpsConfig;

export interface DataSourceRecord {
  id: string;
  type: DataSourceType;
  name: string;
  config: DataSourceConnectionConfig;
  createdAt: string;
  updatedAt: string;
}

export interface DataSourceCreatePayload {
  type: DataSourceType;
  name: string;
  config: DataSourceConnectionConfig;
}

export interface DataSourceTestPayload {
  type: DataSourceType;
  config: DataSourceConnectionConfig;
}

export interface DataSourceTestResult {
  success: boolean;
  message: string;
  latencyMs?: number;
}

export interface DataSourceListResponse {
  items: DataSourceRecord[];
}

export interface DataSourceTypeInfo {
  type: DataSourceType;
  defaultPort?: number;
}

export interface DataSourceTypesResponse {
  items: DataSourceTypeInfo[];
}
