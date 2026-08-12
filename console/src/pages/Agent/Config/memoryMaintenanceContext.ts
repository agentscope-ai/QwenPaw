import { createContext, useContext } from "react";
import type { ReMeRuntimeStatus } from "./useReMeRuntimeStatus";

export interface MemoryMaintenanceState {
  needsReindex: boolean;
  setNeedsReindex: (value: boolean) => void;
  reindexing: boolean;
  setReindexing: (value: boolean) => void;
  openMemorySettings: () => void;
  runtimeStatus: ReMeRuntimeStatus;
  checkMemoryStatus: () => Promise<void>;
  configRevision: number;
}

export const MemoryMaintenanceContext = createContext<MemoryMaintenanceState>({
  needsReindex: false,
  setNeedsReindex: () => {},
  reindexing: false,
  setReindexing: () => {},
  openMemorySettings: () => {},
  runtimeStatus: { type: "unknown" },
  checkMemoryStatus: async () => {},
  configRevision: 0,
});

export function useMemoryMaintenance() {
  return useContext(MemoryMaintenanceContext);
}
