import { request } from "../request";
import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";
import {
  DownloadCancelledError,
  downloadFileFromUrl,
} from "../../utils/downloadFileFromUrl";
import type {
  BackupMeta,
  BackupTrustMode,
  BackupDetail,
  BackupProgressEvent,
  BackupConflictResponse,
  CreateBackupRequest,
  RestoreBackupRequest,
  RestoreBackupResponse,
  DeleteBackupsResponse,
} from "../types/backup";

export const backupApi = {
  listBackups: () => request<BackupMeta[]>("/backups"),

  getBackup: (id: string) => request<BackupDetail>(`/backups/${id}`),

  createBackupStream: async (
    data: CreateBackupRequest,
    onEvent: (event: BackupProgressEvent) => void,
    signal?: AbortSignal,
  ): Promise<BackupMeta> => {
    const url = getApiUrl("/backups/stream");
    const res = await fetch(url, {
      method: "POST",
      headers: { ...buildAuthHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(data),
      signal,
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(text || `Request failed: ${res.status}`);
    }

    const reader = res.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let meta: BackupMeta | null = null;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split("\n\n");
      buffer = chunks.pop() ?? "";
      for (const chunk of chunks) {
        if (!chunk.startsWith("data: ")) continue;
        const event = JSON.parse(chunk.slice(6)) as BackupProgressEvent;
        onEvent(event);
        if (event.type === "done") meta = event.meta;
        if (event.type === "error") throw new Error(event.message);
      }
    }

    if (!meta) throw new Error("No completion event received");
    return meta;
  },

  restoreBackup: (id: string, data: RestoreBackupRequest) =>
    request<RestoreBackupResponse>(`/backups/${id}/restore`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  deleteBackups: (ids: string[]) =>
    request<DeleteBackupsResponse>("/backups/delete", {
      method: "POST",
      body: JSON.stringify({ ids }),
    }),

  exportBackup: async (id: string, name: string) => {
    const url = getApiUrl(`/backups/${id}/export`);

    try {
      await downloadFileFromUrl(url, `${name}.zip`, {
        headers: buildAuthHeaders(),
        errorMessage: "Export failed",
      });
    } catch (error) {
      if (error instanceof DownloadCancelledError) {
        return;
      }
      throw error;
    }
  },

  importBackup: async (
    file: File,
    options: { trustMode?: BackupTrustMode } = {},
  ): Promise<BackupMeta> => {
    const formData = new FormData();
    formData.append("file", file);
    if (options.trustMode) {
      formData.append("trust_mode", options.trustMode);
    }
    const url = getApiUrl("/backups/import");
    const res = await fetch(url, {
      method: "POST",
      headers: buildAuthHeaders(),
      body: formData,
    });
    if (res.status === 409) {
      const body: BackupConflictResponse = await res.json();
      const err = new Error("backup_conflict") as Error & {
        conflict: BackupConflictResponse;
      };
      err.conflict = body;
      throw err;
    }
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(text || `Import failed: ${res.status}`);
    }
    return res.json();
  },

  resolveImportConflict: async (pendingToken: string): Promise<BackupMeta> => {
    const formData = new FormData();
    formData.append("pending_token", pendingToken);
    const url = getApiUrl("/backups/import");
    const res = await fetch(url, {
      method: "POST",
      headers: buildAuthHeaders(),
      body: formData,
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(text || `Import failed: ${res.status}`);
    }
    return res.json();
  },
};
