import { create } from "zustand";

interface TerminalSurfaceState {
  openSessions: Record<string, true>;
  setSessionOpen: (scopeKey: string, open: boolean) => void;
  toggleSession: (scopeKey: string) => void;
  migrateSession: (fromScopeKey: string, toScopeKey: string) => void;
  removeSession: (scopeKey: string) => void;
}

export const useTerminalSurfaceStore = create<TerminalSurfaceState>((set) => ({
  openSessions: {},

  setSessionOpen: (scopeKey, open) =>
    set((state) => {
      const currentlyOpen = state.openSessions[scopeKey] === true;
      if (currentlyOpen === open) return state;
      const next = { ...state.openSessions };
      if (open) next[scopeKey] = true;
      else delete next[scopeKey];
      return { openSessions: next };
    }),

  toggleSession: (scopeKey) =>
    set((state) => {
      const next = { ...state.openSessions };
      if (next[scopeKey]) delete next[scopeKey];
      else next[scopeKey] = true;
      return { openSessions: next };
    }),

  migrateSession: (fromScopeKey, toScopeKey) =>
    set((state) => {
      if (fromScopeKey === toScopeKey || !state.openSessions[fromScopeKey]) {
        return state;
      }
      const next = { ...state.openSessions };
      delete next[fromScopeKey];
      next[toScopeKey] = true;
      return { openSessions: next };
    }),

  removeSession: (scopeKey) =>
    set((state) => {
      if (!state.openSessions[scopeKey]) return state;
      const next = { ...state.openSessions };
      delete next[scopeKey];
      return { openSessions: next };
    }),
}));

export function useSessionTerminalOpen(scopeKey: string): boolean {
  return useTerminalSurfaceStore(
    (state) => state.openSessions[scopeKey] === true,
  );
}
