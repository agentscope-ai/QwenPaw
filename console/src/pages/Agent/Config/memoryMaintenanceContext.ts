import { createContext, useContext } from "react";

export interface MemoryMaintenanceState {
  needsReindex: boolean;
  setNeedsReindex: (value: boolean) => void;
  openMemorySettings: () => void;
}

export const MemoryMaintenanceContext = createContext<MemoryMaintenanceState>({
  needsReindex: false,
  setNeedsReindex: () => {},
  openMemorySettings: () => {},
});

export function useMemoryMaintenance() {
  return useContext(MemoryMaintenanceContext);
}
