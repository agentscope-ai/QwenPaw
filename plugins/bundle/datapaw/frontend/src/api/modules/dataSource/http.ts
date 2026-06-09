import { request } from "../../request";
import type {
  DataSourceCreatePayload,
  DataSourceListResponse,
  DataSourceRecord,
  DataSourceTestPayload,
  DataSourceTestResult,
} from "../../types/dataSource";

const BASE = "/datapaw/data-sources";

export const httpDataSourceApi = {
  list: () => request<DataSourceListResponse>(BASE),

  create: (payload: DataSourceCreatePayload) =>
    request<DataSourceRecord>(BASE, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  testConnection: (payload: DataSourceTestPayload) =>
    request<DataSourceTestResult>(`${BASE}/test`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  remove: (id: string) =>
    request<void>(`${BASE}/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
};
