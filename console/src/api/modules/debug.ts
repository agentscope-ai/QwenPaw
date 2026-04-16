import { request } from "../request";

export interface BackendDebugLogsResponse {
  path: string;
  exists: boolean;
  lines: number;
  updated_at: number | null;
  size: number;
  content: string;
}

export const debugApi = {
  getBackendLogs: (lines = 200) =>
    request<BackendDebugLogsResponse>(
      `/console/debug/backend-logs?lines=${lines}`,
    ),
};
