import { create } from "zustand";
import type { TurnUsageSnapshot } from "./turnUsage";

interface TurnUsageStore {
  snapshot: TurnUsageSnapshot | null;
  setSnapshot: (snapshot: TurnUsageSnapshot | null) => void;
  /** Tokens still in-window after `/compact`; ring shows growth above this. */
  contextBaselineTokens: number;
  setContextBaseline: (tokens: number) => void;
  /** Current agent active model's effective context window (from ModelSelector). */
  activeMaxInputLength: number | null;
  setActiveMaxInputLength: (maxInputLength: number | null) => void;
}

export const useTurnUsageStore = create<TurnUsageStore>((set) => ({
  snapshot: null,
  setSnapshot: (snapshot) =>
    set(
      snapshot === null
        ? { snapshot: null, contextBaselineTokens: 0 }
        : { snapshot },
    ),
  contextBaselineTokens: 0,
  setContextBaseline: (contextBaselineTokens) => set({ contextBaselineTokens }),
  activeMaxInputLength: null,
  setActiveMaxInputLength: (activeMaxInputLength) =>
    set({ activeMaxInputLength }),
}));
