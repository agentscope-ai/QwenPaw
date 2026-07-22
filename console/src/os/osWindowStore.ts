/**
 * osWindowStore.ts — Window Manager state for the Desktop OS PoC.
 *
 * Mirrors the prototype's WindowManager (open/close/focus/minimize/maximize/
 * drag/resize) but as a Zustand store so React windows subscribe reactively.
 * One window per app id (route id) — opening an already-open app focuses it,
 * matching the prototype behaviour and avoiding global-store instance clashes.
 *
 * Window layouts (current space + saved spaces) persist to localStorage so
 * desktops survive reloads; transient UI flags (launcher, mission control)
 * always start closed.
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { computeSnapRect, type SnapZone } from "./snap";

export interface OsRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface OsWindow extends OsRect {
  /** Route id, e.g. "core.skills". Unique per open window. */
  id: string;
  z: number;
  minimized: boolean;
  maximized: boolean;
  /** Saved geometry to restore from a maximized state. */
  prev?: OsRect;
}

/** Snapshot of a single space's window layout (saved while inactive). */
interface SavedSpace {
  windows: Record<string, OsWindow>;
  order: string[];
  activeId: string | null;
  zCounter: number;
}

interface OsStore {
  // ── Active space (mirrors the current space so window components read these
  //    fields directly and stay agnostic of the multi-space machinery). ──────
  windows: Record<string, OsWindow>;
  /** Open order — drives the taskbar item sequence. */
  order: string[];
  activeId: string | null;
  zCounter: number;
  launcherOpen: boolean;

  // ── Spaces (macOS-style): one space per agent/workspace id. ───────────────
  /** Current space id (== selected agent id). */
  spaceId: string;
  /** Saved window layouts for inactive spaces. */
  saved: Record<string, SavedSpace>;
  missionControlOpen: boolean;

  open: (id: string, size?: { w: number; h: number }) => void;
  close: (id: string) => void;
  focus: (id: string) => void;
  minimize: (id: string) => void;
  /** Taskbar click: restore+focus, or minimize when already active. */
  toggleFromTaskbar: (id: string) => void;
  toggleMaximize: (id: string) => void;
  /** Snap a window to a screen edge (left/right half) or maximize it. */
  snap: (id: string, zone: SnapZone) => void;
  move: (id: string, x: number, y: number) => void;
  resize: (id: string, rect: Partial<OsRect>) => void;
  setLauncher: (open: boolean) => void;
  /** Swap the whole desktop to another space (like a full-screen app switch). */
  switchSpace: (id: string) => void;
  setMissionControl: (open: boolean) => void;
}

const BASE_Z = 100;
const CASCADE = 28;

export const useOsWindows = create<OsStore>()(
  persist(
    (set, get) => ({
      windows: {},
      order: [],
      activeId: null,
      zCounter: BASE_Z,
      launcherOpen: false,
      spaceId: "default",
      saved: {},
      missionControlOpen: false,

      open: (id, size) => {
        const state = get();
        if (state.windows[id]) {
          // Already open — restore if minimized, then focus.
          set((s) => ({
            windows: {
              ...s.windows,
              [id]: { ...s.windows[id], minimized: false },
            },
          }));
          get().focus(id);
          return;
        }
        const count = state.order.length;
        const w = size?.w ?? 820;
        const h = size?.h ?? 580;
        const z = state.zCounter + 1;
        const win: OsWindow = {
          id,
          x: 80 + count * CASCADE,
          y: 60 + count * CASCADE,
          w,
          h,
          z,
          minimized: false,
          maximized: false,
        };
        set((s) => ({
          windows: { ...s.windows, [id]: win },
          order: [...s.order, id],
          activeId: id,
          zCounter: z,
          launcherOpen: false,
        }));
      },

      close: (id) =>
        set((s) => {
          const next = { ...s.windows };
          delete next[id];
          const order = s.order.filter((x) => x !== id);
          return {
            windows: next,
            order,
            activeId:
              s.activeId === id ? order[order.length - 1] ?? null : s.activeId,
          };
        }),

      focus: (id) =>
        set((s) => {
          const win = s.windows[id];
          if (!win) return {};
          const z = s.zCounter + 1;
          return {
            windows: { ...s.windows, [id]: { ...win, z, minimized: false } },
            zCounter: z,
            activeId: id,
          };
        }),

      minimize: (id) =>
        set((s) => {
          const win = s.windows[id];
          if (!win) return {};
          return {
            windows: { ...s.windows, [id]: { ...win, minimized: true } },
            activeId: s.activeId === id ? null : s.activeId,
          };
        }),

      toggleFromTaskbar: (id) => {
        const s = get();
        const win = s.windows[id];
        if (!win) return;
        if (win.minimized) {
          get().focus(id);
        } else if (s.activeId === id) {
          get().minimize(id);
        } else {
          get().focus(id);
        }
      },

      toggleMaximize: (id) =>
        set((s) => {
          const win = s.windows[id];
          if (!win) return {};
          if (win.maximized) {
            const prev = win.prev ?? { x: 80, y: 60, w: 820, h: 580 };
            return {
              windows: {
                ...s.windows,
                [id]: { ...win, ...prev, maximized: false, prev: undefined },
              },
            };
          }
          return {
            windows: {
              ...s.windows,
              [id]: {
                ...win,
                maximized: true,
                prev: { x: win.x, y: win.y, w: win.w, h: win.h },
              },
            },
          };
        }),

      move: (id, x, y) =>
        set((s) => {
          const win = s.windows[id];
          if (!win) return {};
          return { windows: { ...s.windows, [id]: { ...win, x, y } } };
        }),

      resize: (id, rect) =>
        set((s) => {
          const win = s.windows[id];
          if (!win) return {};
          return { windows: { ...s.windows, [id]: { ...win, ...rect } } };
        }),

      snap: (id, zone) =>
        set((s) => {
          const win = s.windows[id];
          if (!win) return {};
          const prev = win.prev ?? { x: win.x, y: win.y, w: win.w, h: win.h };
          if (zone === "maximize") {
            return {
              windows: {
                ...s.windows,
                [id]: { ...win, maximized: true, prev },
              },
            };
          }
          const rect = computeSnapRect(
            zone,
            window.innerWidth,
            window.innerHeight,
          );
          return {
            windows: {
              ...s.windows,
              [id]: { ...win, ...rect, maximized: false, prev },
            },
          };
        }),

      setLauncher: (open) => set({ launcherOpen: open }),

      switchSpace: (id) =>
        set((s) => {
          if (id === s.spaceId) return { missionControlOpen: false };
          // Save the current space, then load (or create) the target space.
          const saved: Record<string, SavedSpace> = {
            ...s.saved,
            [s.spaceId]: {
              windows: s.windows,
              order: s.order,
              activeId: s.activeId,
              zCounter: s.zCounter,
            },
          };
          const target = saved[id] ?? {
            windows: {},
            order: [],
            activeId: null,
            zCounter: BASE_Z,
          };
          delete saved[id];
          return {
            saved,
            spaceId: id,
            windows: target.windows,
            order: target.order,
            activeId: target.activeId,
            zCounter: target.zCounter,
            launcherOpen: false,
            missionControlOpen: false,
          };
        }),

      setMissionControl: (open) => set({ missionControlOpen: open }),
    }),
    {
      name: "qwenpaw-os-windows",
      version: 1,
      // Persist only the window layouts (current space + saved spaces);
      // transient overlays (launcher, mission control) always start closed.
      partialize: (s) => ({
        windows: s.windows,
        order: s.order,
        activeId: s.activeId,
        zCounter: s.zCounter,
        spaceId: s.spaceId,
        saved: s.saved,
      }),
    },
  ),
);
