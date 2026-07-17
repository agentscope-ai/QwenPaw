import { request } from "../request";
import type {
  CheckpointGraphResponse,
  CheckpointStatus,
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

  previewGc: () =>
    request<GcResult>(`${base}/gc/preview`, {
      method: "POST",
      body: "{}",
      timeout: 120_000,
    }),

  gc: () =>
    request<GcResult>(`${base}/gc`, {
      method: "POST",
      body: "{}",
      timeout: 120_000,
    }),

  reset: () =>
    request<{ reset: boolean; auto_enabled: boolean }>(base, {
      method: "DELETE",
      timeout: 120_000,
    }),
};
