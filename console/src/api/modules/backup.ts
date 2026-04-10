import { request } from "../request";

export interface BackupConfigData {
  enabled: boolean;
  schedule: string;
  retention_days: number;
  max_backups: number;
  include_types: string[];
}

export interface BackupEntry {
  backup_path: string;
  timestamp: string;
  size_bytes: number;
  asset_count: number;
  success: boolean;
}

export interface BackupListResponse {
  backups: BackupEntry[];
}

export interface ExportResponse {
  zip_path: string;
  asset_count: number;
  total_size_bytes: number;
}

export interface ImportResponse {
  imported: string[];
  skipped: string[];
  conflicts_count: number;
  errors: string[];
}

export const backupApi = {
  getConfig: () => request<BackupConfigData>("/backup/config"),

  updateConfig: (body: Partial<BackupConfigData>) =>
    request<BackupConfigData>("/backup/config", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  listBackups: () => request<BackupListResponse>("/backup/list"),

  exportAssets: (body: {
    types?: string[];
    output_path?: string;
  }) =>
    request<ExportResponse>("/backup/export", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  importAssets: (body: {
    zip_path: string;
    strategy?: string;
    types?: string[];
  }) =>
    request<ImportResponse>("/backup/import", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  restore: (body: { backup_name: string; strategy?: string }) =>
    request<ImportResponse>("/backup/restore", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
