/** Supported data source types for connection forms and list display. */
export type DataSourceType = "csv" | "mysql" | "postgresql" | "api";

export interface DataSourceConnectionConfig {
  host?: string;
  port?: number;
  user?: string;
  password?: string;
  db?: string;
  /** CSV file path or URL */
  filePath?: string;
}

export interface DataSourceRecord {
  id: string;
  type: DataSourceType;
  /** Display name, usually the database or file identifier */
  name: string;
  config: DataSourceConnectionConfig;
  createdAt: string;
}

export interface DataSourceCreatePayload {
  type: DataSourceType;
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
