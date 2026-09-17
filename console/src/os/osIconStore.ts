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

export type IconLayout = "free" | "name" | "type";

interface OsIconStore {
  positions: Record<string, IconPos>;
  layout: IconLayout;
  setPosition: (id: string, x: number, y: number) => void;
  setLayout: (layout: IconLayout) => void;
  arrange: (ids: readonly string[], viewportH: number) => void;
  reflowToViewport: (ids: readonly string[], viewportH: number) => void;
  /** Transactional cleanup: drop positions for confirmed-removed apps. */
  purge: (ids: ReadonlySet<string>) => void;
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
      layout: "free",
      setPosition: (id, x, y) =>
        set((s) => ({ positions: { ...s.positions, [id]: { x, y } } })),
      setLayout: (layout) => set({ layout }),
      arrange: (ids, viewportH) =>
        set((state) => {
          const positions = { ...state.positions };
          ids.forEach((id, index) => {
            positions[id] = defaultIconPos(index, viewportH);
          });
          return { positions };
        }),
      reflowToViewport: (ids, viewportH) =>
        set((state) => {
          if (state.layout !== "free") return {};
          const positions = { ...state.positions };
          let changed = false;
          ids.forEach((id, index) => {
            const next = defaultIconPos(index, viewportH);
            const current = state.positions[id];
            if (current?.x !== next.x || current?.y !== next.y) {
              positions[id] = next;
              changed = true;
            }
          });
          if (!changed) {
            return {};
          }
          return { positions };
        }),
      purge: (ids) =>
        set((s) => {
          if (![...ids].some((id) => id in s.positions)) return {};
          const positions = { ...s.positions };
          for (const id of ids) delete positions[id];
          return { positions };
        }),
      reset: () => set({ positions: {}, layout: "free" }),
    }),
    { name: "qwenpaw.os.iconPositions" },
  ),
);
