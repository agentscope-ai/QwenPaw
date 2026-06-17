import { create } from "zustand";

const STORAGE_KEY = "qwenpaw_sidebar_mode";

export type SidebarMode = "simple" | "full";

interface SidebarModeState {
  mode: SidebarMode;
  toggleMode: () => void;
  setMode: (mode: SidebarMode) => void;
}

export const useSidebarModeStore = create<SidebarModeState>((set) => ({
  mode: (() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      return stored === "simple" ? "simple" : "full";
    } catch {
      return "full";
    }
  })(),

  toggleMode: () =>
    set((state) => {
      const next: SidebarMode = state.mode === "simple" ? "full" : "simple";
      try {
        if (next === "simple") {
          localStorage.setItem(STORAGE_KEY, "simple");
        } else {
          localStorage.removeItem(STORAGE_KEY);
        }
      } catch {
        // storage unavailable
      }
      return { mode: next };
    }),

  setMode: (mode: SidebarMode) => {
    try {
      if (mode === "simple") {
        localStorage.setItem(STORAGE_KEY, "simple");
      } else {
        localStorage.removeItem(STORAGE_KEY);
      }
    } catch {
      // storage unavailable
    }
    set({ mode });
  },
}));
