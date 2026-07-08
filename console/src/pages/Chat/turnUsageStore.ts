import { create } from "zustand";
import type { TurnUsageSnapshot } from "./turnUsage";

interface TurnUsageStore {
  snapshot: TurnUsageSnapshot | null;
  setSnapshot: (snapshot: TurnUsageSnapshot | null) => void;
}

export const useTurnUsageStore = create<TurnUsageStore>((set) => ({
  snapshot: null,
  setSnapshot: (snapshot) => set({ snapshot }),
}));
