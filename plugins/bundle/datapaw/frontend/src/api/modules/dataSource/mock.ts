import type {
  DataSourceCreatePayload,
  DataSourceListResponse,
  DataSourceRecord,
  DataSourceTestPayload,
  DataSourceTestResult,
} from "../../types/dataSource";

const STORAGE_KEY = "qwenpaw_data_source_records_v2";

const DEFAULT_RECORDS: DataSourceRecord[] = [
  {
    id: "mysql-user-db",
    type: "mysql",
    name: "user_db",
    config: {
      host: "127.0.0.1",
      port: 3306,
      user: "root",
      db: "user_db",
    },
    createdAt: "2026-01-01T00:00:00.000Z",
  },
  {
    id: "pg-analytics",
    type: "postgresql",
    name: "analytics_warehouse",
    config: {
      host: "127.0.0.1",
      port: 5432,
      user: "postgres",
      db: "analytics_warehouse",
    },
    createdAt: "2026-01-02T00:00:00.000Z",
  },
  {
    id: "api-crm",
    type: "api",
    name: "crm_events",
    config: {
      host: "https://api.example.com",
    },
    createdAt: "2026-01-03T00:00:00.000Z",
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

function resolveName(payload: DataSourceCreatePayload): string {
  if (payload.type === "csv") {
    const path = payload.config.filePath?.trim() || "";
    const segments = path.split(/[/\\]/);
    return segments[segments.length - 1] || path || "csv_source";
  }
  return payload.config.db?.trim() || `${payload.type}_source`;
}

function validateConfig(payload: DataSourceTestPayload): string | null {
  if (payload.type === "csv") {
    if (!payload.config.filePath?.trim()) {
      return "filePathRequired";
    }
    return null;
  }

  if (!payload.config.host?.trim()) return "hostRequired";
  if (!payload.config.port) return "portRequired";
  if (!payload.config.user?.trim()) return "userRequired";
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
    const errorKey = validateConfig(payload);
    if (errorKey) {
      throw new Error(errorKey);
    }

    const record: DataSourceRecord = {
      id: `${payload.type}-${Date.now()}`,
      type: payload.type,
      name: resolveName(payload),
      config: { ...payload.config },
      createdAt: new Date().toISOString(),
    };

    const items = [record, ...readRecords()];
    writeRecords(items);
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
    writeRecords(readRecords().filter((item) => item.id !== id));
  },
};
