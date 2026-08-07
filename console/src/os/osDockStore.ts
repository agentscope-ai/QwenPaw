/** Persisted Dock shortcuts for the Desktop OS shell. */
import { create } from "zustand";
import { persist } from "zustand/middleware";

export const DEFAULT_DOCK_APPS = ["core.chat", "core.inbox", "os.store"];

interface OsDockStore {
  pinned: string[];
  pin: (id: string, index?: number) => void;
  unpin: (id: string) => void;
  move: (id: string, beforeId?: string) => void;
  purge: (ids: ReadonlySet<string>) => void;
  reset: () => void;
}

export function normalizeDockApps(ids: unknown): string[] {
  if (!Array.isArray(ids)) return [...DEFAULT_DOCK_APPS];
  return [...new Set(ids.filter((id): id is string => typeof id === "string"))];
}

export const useOsDock = create<OsDockStore>()(
  persist(
    (set) => ({
      pinned: [...DEFAULT_DOCK_APPS],
      pin: (id, index) =>
        set((state) => {
          if (state.pinned.includes(id)) return {};
          const next = [...state.pinned];
          const at = Math.max(0, Math.min(index ?? next.length, next.length));
          next.splice(at, 0, id);
          return { pinned: normalizeDockApps(next) };
        }),
      unpin: (id) =>
        set((state) => ({
          pinned: state.pinned.filter((item) => item !== id),
        })),
      move: (id, beforeId) =>
        set((state) => {
          if (!state.pinned.includes(id) || id === beforeId) return {};
          const next = state.pinned.filter((item) => item !== id);
          const at = beforeId ? next.indexOf(beforeId) : next.length;
          next.splice(at < 0 ? next.length : at, 0, id);
          return { pinned: normalizeDockApps(next) };
        }),
      purge: (ids) =>
        set((state) => ({
          pinned: state.pinned.filter((id) => !ids.has(id)),
        })),
      reset: () => set({ pinned: [...DEFAULT_DOCK_APPS] }),
    }),
    {
      name: "qwenpaw.os.dock",
      merge: (persisted, current) => {
        const stored = persisted as Partial<OsDockStore> | undefined;
        return {
          ...current,
          pinned: normalizeDockApps(stored?.pinned),
        };
      },
    },
  ),
);
