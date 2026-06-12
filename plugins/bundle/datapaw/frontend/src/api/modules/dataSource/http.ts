import { request } from "../../request";
import type {
  DataSourceCreatePayload,
  DataSourceListResponse,
  DataSourceRecord,
  DataSourceTestPayload,
  DataSourceTestResult,
  DataSourceTypeInfo,
  DataSourceTypesResponse,
} from "../../types/dataSource";

const BASE = "/datapaw/data-sources";

function normalizeRecord(raw: Record<string, unknown>): DataSourceRecord {
  return {
    id: String(raw.id ?? ""),
    type: raw.type as DataSourceRecord["type"],
    name: String(raw.name ?? ""),
    config: (raw.config as DataSourceRecord["config"]) ?? {},
    createdAt: String(raw.createdAt ?? raw.created_at ?? ""),
    updatedAt: String(raw.updatedAt ?? raw.updated_at ?? ""),
  };
}

function normalizeListResponse(raw: unknown): DataSourceListResponse {
  if (Array.isArray(raw)) {
    return { items: raw.map((item) => normalizeRecord(item as Record<string, unknown>)) };
  }
  const body = (raw ?? {}) as Record<string, unknown>;
  const items = Array.isArray(body.items) ? body.items : [];
  return {
    items: items.map((item) => normalizeRecord(item as Record<string, unknown>)),
  };
}

function normalizeTypesResponse(raw: unknown): DataSourceTypesResponse {
  const body = (raw ?? {}) as Record<string, unknown>;
  const items = Array.isArray(body.items) ? body.items : [];
  return {
    items: items.map((item) => {
      const row = item as Record<string, unknown>;
      const info: DataSourceTypeInfo = {
        type: row.type as DataSourceTypeInfo["type"],
      };
      const defaultPort = row.defaultPort ?? row.default_port;
      if (defaultPort !== undefined && defaultPort !== null) {
        info.defaultPort = Number(defaultPort);
      }
      return info;
    }),
  };
}

/** POST /test always returns 200 with { success, message, latencyMs }. */
function normalizeTestResult(raw: unknown): DataSourceTestResult {
  const body = (raw ?? {}) as Record<string, unknown>;
  const latency = body.latencyMs ?? body.latency_ms;
  return {
    success: Boolean(body.success),
    message: String(body.message ?? ""),
    latencyMs:
      latency === undefined || latency === null ? undefined : Number(latency),
  };
}

export const httpDataSourceApi = {
  list: async () => normalizeListResponse(await request(BASE)),

  listTypes: async () =>
    normalizeTypesResponse(await request(`${BASE}/types`)),

  create: async (payload: DataSourceCreatePayload) =>
    normalizeRecord(
      (await request(BASE, {
        method: "POST",
        body: JSON.stringify(payload),
      })) as Record<string, unknown>,
    ),

  testConnection: async (payload: DataSourceTestPayload) =>
    normalizeTestResult(
      await request(`${BASE}/test`, {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    ),

  remove: (id: string) =>
    request<void>(`${BASE}/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
};
