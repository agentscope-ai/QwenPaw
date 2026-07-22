import { request } from "../request";
import type {
  CheckpointGcSettings,
  CheckpointGraphResponse,
  CheckpointStatus,
  GcRequest,
  GcResult,
  RestoreRequest,
  RestoreResult,
} from "../types/checkpoints";

const base = "/workspace/checkpoints";

export const checkpointsApi = {
  status: (signal?: AbortSignal) =>
    request<CheckpointStatus>(`${base}/status`, { signal }),

  graph: (limit = 500, signal?: AbortSignal) =>
    request<CheckpointGraphResponse>(`${base}/graph?limit=${limit}`, {
      signal,
    }),

  setAuto: (enabled: boolean) =>
    request<{ auto_enabled: boolean }>(`${base}/auto`, {
      method: "PATCH",
      body: JSON.stringify({ enabled }),
    }),

  snapshot: (body: {
    session_id: string;
    user_id: string;
    channel: string;
    name: string;
  }) =>
    request<{ ref: string; commit: string }>(`${base}/snapshot`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  previewRestore: (body: RestoreRequest) =>
    request<RestoreResult>(`${base}/restore/preview`, {
      method: "POST",
      body: JSON.stringify(body),
      timeout: 120_000,
    }),

  restore: (body: RestoreRequest) =>
    request<RestoreResult>(`${base}/restore`, {
      method: "POST",
      body: JSON.stringify(body),
      timeout: 120_000,
    }),

  previewGc: (body: GcRequest = {}) =>
    request<GcResult>(`${base}/gc/preview`, {
      method: "POST",
      body: JSON.stringify(body),
      timeout: 120_000,
    }),

  gc: (body: GcRequest = {}) =>
    request<GcResult>(`${base}/gc`, {
      method: "POST",
      body: JSON.stringify(body),
      timeout: 120_000,
    }),

  getGcSettings: () => request<CheckpointGcSettings>(`${base}/gc/settings`),

  updateGcSettings: (body: CheckpointGcSettings) =>
    request<CheckpointGcSettings>(`${base}/gc/settings`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  reset: () =>
    request<{ reset: boolean; auto_enabled: boolean }>(base, {
      method: "DELETE",
      timeout: 120_000,
    }),
};
