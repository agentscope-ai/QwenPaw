import type {
  DataSourceCreatePayload,
  DataSourceListResponse,
  DataSourceRecord,
  DataSourceTestPayload,
  DataSourceTestResult,
} from "../../types/dataSource";

const STORAGE_KEY = "qwenpaw_data_source_records_v3";

const DEFAULT_RECORDS: DataSourceRecord[] = [
  {
    id: "mysql-user-db",
    type: "mysql",
    name: "用户库",
    config: {
      host: "127.0.0.1",
      port: 3306,
      user: "root",
      password: "se********345",
      db: "user_db",
    },
    createdAt: "2026-01-01T00:00:00.000Z",
    updatedAt: "2026-01-01T00:00:00.000Z",
  },
  {
    id: "pg-analytics",
    type: "postgresql",
    name: "分析库",
    config: {
      host: "127.0.0.1",
      port: 5432,
      user: "postgres",
      password: "se********345",
      db: "analytics_warehouse",
    },
    createdAt: "2026-01-02T00:00:00.000Z",
    updatedAt: "2026-01-02T00:00:00.000Z",
  },
];

function readRecords(): DataSourceRecord[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [...DEFAULT_RECORDS];
    const parsed = JSON.parse(raw) as DataSourceRecord[];
    return Array.isArray(parsed) ? parsed : [...DEFAULT_RECORDS];
  } catch {
    return [...DEFAULT_RECORDS];
  }
}

function writeRecords(items: DataSourceRecord[]): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
}

function validateConfig(payload: DataSourceTestPayload): string | null {
  if (payload.type === "odps") {
    if (!payload.config.endpoint?.trim()) return "endpointRequired";
    if (!payload.config.project_name?.trim()) return "projectNameRequired";
    if (!payload.config.access_id?.trim()) return "accessIdRequired";
    if (!payload.config.access_key?.trim()) return "accessKeyRequired";
    if (!payload.config.app_name?.trim()) return "appNameRequired";
    return null;
  }

  if (!payload.config.host?.trim()) return "hostRequired";
  if (!payload.config.port) return "portRequired";
  if (!payload.config.user?.trim()) return "userRequired";
  if (!payload.config.password?.trim()) return "passwordRequired";
  if (!payload.config.db?.trim()) return "dbRequired";
  return null;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export const mockDataSourceApi = {
  list: async (): Promise<DataSourceListResponse> => {
    await sleep(200);
    return { items: readRecords() };
  },

  create: async (payload: DataSourceCreatePayload): Promise<DataSourceRecord> => {
    await sleep(300);
    if (!payload.name?.trim()) {
      throw new Error("nameRequired");
    }

    const items = readRecords();
    if (items.some((item) => item.name === payload.name.trim())) {
      throw new Error("nameConflict");
    }

    const errorKey = validateConfig(payload);
    if (errorKey) {
      throw new Error(errorKey);
    }

    const now = new Date().toISOString();
    const record: DataSourceRecord = {
      id: `${payload.type}-${Date.now()}`,
      type: payload.type,
      name: payload.name.trim(),
      config: { ...payload.config },
      createdAt: now,
      updatedAt: now,
    };

    writeRecords([record, ...items]);
    return record;
  },

  testConnection: async (
    payload: DataSourceTestPayload,
  ): Promise<DataSourceTestResult> => {
    const started = Date.now();
    await sleep(800);

    const errorKey = validateConfig(payload);
    if (errorKey) {
      return {
        success: false,
        message: errorKey,
        latencyMs: Date.now() - started,
      };
    }

    if (payload.config.password?.toLowerCase() === "fail") {
      return {
        success: false,
        message: "connectionRejected",
        latencyMs: Date.now() - started,
      };
    }

    return {
      success: true,
      message: "connectionOk",
      latencyMs: Date.now() - started,
    };
  },

  remove: async (id: string): Promise<void> => {
    await sleep(200);
    const items = readRecords();
    if (!items.some((item) => item.id === id)) {
      throw new Error("notFound");
    }
    writeRecords(items.filter((item) => item.id !== id));
  },
};
