import { creatorRequest, jsonBody } from "./client";

export interface ProjectStorageProfile {
  projectId: string;
  baselineAt: string | null;
  historyKeptAt: string | null;
  reclaimConfirmedAt: string | null;
  pendingReclaimBytes: number;
  taskWorkBytes: number;
  taskWorkLegacyBytes: number;
  taskWorkReclaimableBytes: number;
  transactionsBytes: number;
  transactionsLegacyBytes: number;
  orphanBytes: number;
}

export interface StorageTotals {
  taskWorkBytes: number;
  taskWorkLegacyBytes: number;
  taskWorkReclaimableBytes: number;
  transactionsBytes: number;
  transactionsLegacyBytes: number;
  orphanBytes: number;
}

export interface StorageProfile {
  dataRoot: string;
  generatedAt: string;
  scratchReleaseEnabled: boolean;
  releasedFiles: number;
  releasedBytes: number;
  elisionBackupBytes: number;
  totals: StorageTotals;
  projects: ProjectStorageProfile[];
}

export interface HistoryReclaimResult {
  projectId: string;
  historyKept: boolean;
  removedTransactions: number;
  transactionBytes: number;
  releasedFiles: number;
  releasedBytes: number;
  confirmedAt: string | null;
}

export function getStorageProfile(): Promise<StorageProfile> {
  return creatorRequest<StorageProfile>("/storage/profile");
}

export function confirmProjectReclaim(
  projectId: string,
): Promise<HistoryReclaimResult> {
  return creatorRequest<HistoryReclaimResult>(
    `/storage/projects/${encodeURIComponent(projectId)}/reclaim-history`,
    { method: "POST", body: jsonBody({ confirm: true }) },
  );
}
