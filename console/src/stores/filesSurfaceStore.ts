import { create } from "zustand";
import {
  CLOSED_FILES_DRAWER,
  filesDrawerReducer,
} from "../features/files-workspace/filesDrawerState";
import type {
  FilesDrawerEvent,
  FilesDrawerState,
} from "../features/files-workspace/types";

interface FilesSurfaceState {
  sessionDrawers: Record<string, FilesDrawerState>;
  dispatchSession: (scopeKey: string, event: FilesDrawerEvent) => void;
  migrateSession: (fromScopeKey: string, toScopeKey: string) => void;
  removeSession: (scopeKey: string) => void;
}

export const useFilesSurfaceStore = create<FilesSurfaceState>((set) => ({
  sessionDrawers: {},

  dispatchSession: (scopeKey, event) =>
    set((state) => ({
      sessionDrawers: {
        ...state.sessionDrawers,
        [scopeKey]: filesDrawerReducer(
          state.sessionDrawers[scopeKey] ?? CLOSED_FILES_DRAWER,
          event,
        ),
      },
    })),

  migrateSession: (fromScopeKey, toScopeKey) =>
    set((state) => {
      if (fromScopeKey === toScopeKey) return state;
      const current = state.sessionDrawers[fromScopeKey];
      if (!current) return state;
      const next = { ...state.sessionDrawers };
      delete next[fromScopeKey];
      next[toScopeKey] = current;
      return { sessionDrawers: next };
    }),

  removeSession: (scopeKey) =>
    set((state) => {
      if (!(scopeKey in state.sessionDrawers)) return state;
      const next = { ...state.sessionDrawers };
      delete next[scopeKey];
      return { sessionDrawers: next };
    }),
}));

export function useSessionFilesDrawer(scopeKey: string): FilesDrawerState {
  return useFilesSurfaceStore(
    (state) => state.sessionDrawers[scopeKey] ?? CLOSED_FILES_DRAWER,
  );
}
