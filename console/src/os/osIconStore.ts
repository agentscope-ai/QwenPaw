/**
 * osIconStore.ts — Persisted desktop icon positions (per route id).
 *
 * Icons without a stored position fall back to `defaultIconPos`, which lays
 * them out column-major (top-to-bottom, then next column), mirroring the old
 * CSS grid. Positions persist to localStorage so reorders survive reloads.
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { MENUBAR_H, DOCK_H } from "./useOsStyles";

export interface IconPos {
  x: number;
  y: number;
}

interface OsIconStore {
  positions: Record<string, IconPos>;
  setPosition: (id: string, x: number, y: number) => void;
  /** Drop stored positions for apps no longer in the registry. */
  prune: (validIds: ReadonlySet<string>) => void;
  reset: () => void;
}

const CELL_H = 104;
const CELL_W = 96;
const ORIGIN_X = 20;
const ORIGIN_Y = MENUBAR_H + 8 + 20;

/** Column-major fallback layout for icons without a stored position. */
export function defaultIconPos(index: number, viewportH: number): IconPos {
  const usableH = Math.max(CELL_H, viewportH - ORIGIN_Y - DOCK_H);
  const perCol = Math.max(1, Math.floor(usableH / CELL_H));
  const col = Math.floor(index / perCol);
  const row = index % perCol;
  return { x: ORIGIN_X + col * CELL_W, y: ORIGIN_Y + row * CELL_H };
}

export const useOsIcons = create<OsIconStore>()(
  persist(
    (set) => ({
      positions: {},
      setPosition: (id, x, y) =>
        set((s) => ({ positions: { ...s.positions, [id]: { x, y } } })),
      prune: (validIds) =>
        set((s) => {
          const positions: Record<string, IconPos> = {};
          let changed = false;
          for (const [id, pos] of Object.entries(s.positions)) {
            if (validIds.has(id)) positions[id] = pos;
            else changed = true;
          }
          return changed ? { positions } : {};
        }),
      reset: () => set({ positions: {} }),
    }),
    { name: "qwenpaw.os.iconPositions" },
  ),
);
