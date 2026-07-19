import { create } from "zustand";
import type { TurnUsageSnapshot } from "./turnUsage";

interface TurnUsageStore {
  snapshot: TurnUsageSnapshot | null;
  setSnapshot: (snapshot: TurnUsageSnapshot | null) => void;
  /** Current agent active model's effective context window (from ModelSelector). */
  activeMaxInputLength: number | null;
  setActiveMaxInputLength: (maxInputLength: number | null) => void;
}

export const useTurnUsageStore = create<TurnUsageStore>((set) => ({
  snapshot: null,
  setSnapshot: (snapshot) => set({ snapshot }),
  activeMaxInputLength: null,
  setActiveMaxInputLength: (activeMaxInputLength) =>
    set({ activeMaxInputLength }),
}));
