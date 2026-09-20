import { createContext, useContext } from "react";
import type {
  ReMeDiagnosticsStatus,
  ReMeRuntimeStatus,
} from "./useReMeRuntimeStatus";

export interface MemoryMaintenanceState {
  needsReindex: boolean;
  setNeedsReindex: (value: boolean) => void;
  reindexing: boolean;
  setReindexing: (value: boolean) => void;
  persistedEmbeddingFingerprint?: string;
  setPersistedEmbeddingFingerprint?: (value: string) => void;
  openMemorySettings: () => void;
  runtimeStatus: ReMeRuntimeStatus;
  diagnosticsStatus: ReMeDiagnosticsStatus;
  checkMemoryStatus: (includeDiagnostics?: boolean) => Promise<void>;
}

export const MemoryMaintenanceContext = createContext<MemoryMaintenanceState>({
  needsReindex: false,
  setNeedsReindex: () => {},
  reindexing: false,
  setReindexing: () => {},
  persistedEmbeddingFingerprint: undefined,
  setPersistedEmbeddingFingerprint: () => {},
  openMemorySettings: () => {},
  runtimeStatus: { type: "unknown" },
  diagnosticsStatus: { type: "unknown" },
  checkMemoryStatus: async () => {},
});

export function useMemoryMaintenance() {
  return useContext(MemoryMaintenanceContext);
}
