import { request } from "../request";

export type StorageMode = "legacy" | "postgres";
export type ActiveRepository = StorageMode | "mixed";

export type MigrationLockState =
  | "not_applicable"
  | "not_configured"
  | "locked"
  | "unknown";

export interface DomainCutoverStatus {
  domain: string;
  migration_validated: boolean;
  legacy_writes_frozen: boolean;
  postgres_writes_open: boolean;
  read_repository: StorageMode;
  write_repository: StorageMode;
}

export interface StorageStatus {
  status: "legacy" | "disconnected" | "ready";
  connected: boolean;
  schema_version: string | null;
  expected_schema_version: string;
  schema_ready: boolean;
  storage_mode: StorageMode;
  active_repository: ActiveRepository;
  migration_lock_state: MigrationLockState;
  domains: DomainCutoverStatus[];
  error_code: string | null;
}

export const systemStatusApi = {
  getStorageStatus: () =>
    request<StorageStatus>("/system/storage-status", {
      method: "GET",
    }),
};
