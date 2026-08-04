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
import {
  persist,
  createJSONStorage,
  type StateStorage,
} from "zustand/middleware";
import { computeSnapRect, type SnapZone } from "./snap";
import { resolveAppDef } from "./osAppRegistry";
import { clampRectToViewport } from "./windowGeometry";

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

  open: (
    id: string,
    size?: { w: number; h: number; minW?: number; minH?: number },
  ) => void;
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
  /**
   * Re-clamp every window (active space, saved spaces and maximize/snap
   * restore rects) to the current viewport work area. Called after
   * hydration and on viewport resize so persisted layouts never restore
   * off-screen (monitor switch, DPI change, smaller browser window).
   */
  clampToViewport: () => void;
  /**
   * Transactional cleanup: drop state for the given app ids (confirmed
   * uninstalled) in the active space and every saved space, pruning
   * order/activeId accordingly. Never derives deletions from snapshots.
   */
  purgeApps: (ids: ReadonlySet<string>) => void;
  /**
   * Transactional cleanup: drop the saved layout of one deleted agent's
   * Space. When it is the displayed space, the active layout is cleared so
   * a later space switch cannot resurrect it.
   */
  purgeSpace: (spaceId: string) => void;
}

const BASE_Z = 100;
const CASCADE = 28;

/** Debounce delay for persisted writes (one write per gesture burst). */
const PERSIST_DEBOUNCE_MS = 250;

/**
 * localStorage adapter that debounces writes. Drag/resize gestures update
 * the store on every pointermove; persisting each update would run
 * synchronous storage IO on the hot path and drop frames. Writes collapse
 * into a single setItem after the burst ends; a pending write flushes on
 * pagehide so the final geometry survives an immediate reload. Reads stay
 * synchronous so hydration behaviour is unchanged.
 */
function createDebouncedStorage(delayMs: number): StateStorage {
  let timer: ReturnType<typeof setTimeout> | null = null;
  let pending: { name: string; value: string } | null = null;
  const flush = () => {
    if (timer !== null) clearTimeout(timer);
    timer = null;
    if (!pending) return;
    const { name, value } = pending;
    pending = null;
    if (typeof window === "undefined") return;
    window.localStorage.setItem(name, value);
  };
  if (typeof window !== "undefined") {
    window.addEventListener("pagehide", flush);
  }
  return {
    getItem: (name) => window.localStorage.getItem(name),
    setItem: (name, value) => {
      pending = { name, value };
      if (timer !== null) clearTimeout(timer);
      timer = setTimeout(flush, delayMs);
    },
    removeItem: (name) => {
      if (pending?.name === name) {
        if (timer !== null) clearTimeout(timer);
        timer = null;
        pending = null;
      }
      window.localStorage.removeItem(name);
    },
  };
}

const debouncedLocalStorage = createDebouncedStorage(PERSIST_DEBOUNCE_MS);

/** Re-clamp a window (and its restore rect) to the given viewport. */
function clampWindow(win: OsWindow, vw: number, vh: number): OsWindow {
  const def = resolveAppDef(win.id);
  const limits = { minW: def?.minW, minH: def?.minH };
  return {
    ...win,
    ...clampRectToViewport(win, limits, vw, vh),
    prev: win.prev ? clampRectToViewport(win.prev, limits, vw, vh) : undefined,
  };
}

function clampWindows(
  wins: Record<string, OsWindow> | undefined,
  vw: number,
  vh: number,
): Record<string, OsWindow> {
  const next: Record<string, OsWindow> = {};
  for (const [id, win] of Object.entries(wins ?? {})) {
    next[id] = clampWindow(win, vw, vh);
  }
  return next;
}

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
        // Resolve geometry from the app manifest so every entry point
        // (Dock, Launcher, desktop icons, cross-app navigation) opens the
        // same app with the same size; the explicit `size` argument only
        // overrides it. Then clamp to the visible desktop area.
        const def = resolveAppDef(id);
        const rect = clampRectToViewport(
          {
            x: 80 + count * CASCADE,
            y: 60 + count * CASCADE,
            w: size?.w ?? def?.defaultW ?? 820,
            h: size?.h ?? def?.defaultH ?? 580,
          },
          {
            minW: size?.minW ?? def?.minW,
            minH: size?.minH ?? def?.minH,
          },
          window.innerWidth,
          window.innerHeight,
        );
        const z = state.zCounter + 1;
        const win: OsWindow = {
          id,
          ...rect,
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
          // Empty desktops are not snapshotted — this keeps purged (deleted
          // agent) spaces from being re-created by the switch itself.
          const saved: Record<string, SavedSpace> = { ...s.saved };
          if (s.order.length > 0) {
            saved[s.spaceId] = {
              windows: s.windows,
              order: s.order,
              activeId: s.activeId,
              zCounter: s.zCounter,
            };
          } else {
            delete saved[s.spaceId];
          }
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

      clampToViewport: () =>
        set((s) => {
          const vw = window.innerWidth;
          const vh = window.innerHeight;
          const saved: Record<string, SavedSpace> = {};
          for (const [sid, space] of Object.entries(s.saved)) {
            saved[sid] = {
              ...space,
              windows: clampWindows(space.windows, vw, vh),
            };
          }
          return { windows: clampWindows(s.windows, vw, vh), saved };
        }),

      purgeApps: (ids) =>
        set((s) => {
          const prune = (
            space: SavedSpace,
          ): { space: SavedSpace; changed: boolean } => {
            // Guard against persisted states where windows/order diverge.
            const present = new Set(
              [...space.order, ...Object.keys(space.windows)].filter((id) =>
                ids.has(id),
              ),
            );
            if (present.size === 0) return { space, changed: false };
            const windows = { ...space.windows };
            for (const id of present) delete windows[id];
            const order = space.order.filter((id) => !ids.has(id));
            const activeId =
              space.activeId !== null && !ids.has(space.activeId)
                ? space.activeId
                : order[order.length - 1] ?? null;
            return {
              space: { ...space, windows, order, activeId },
              changed: true,
            };
          };

          const active = prune({
            windows: s.windows,
            order: s.order,
            activeId: s.activeId,
            zCounter: s.zCounter,
          });
          const saved: Record<string, SavedSpace> = {};
          let savedChanged = false;
          for (const [sid, space] of Object.entries(s.saved)) {
            const next = prune(space);
            saved[sid] = next.space;
            savedChanged = savedChanged || next.changed;
          }
          if (!active.changed && !savedChanged) return {};
          return {
            windows: active.space.windows,
            order: active.space.order,
            activeId: active.space.activeId,
            saved: savedChanged ? saved : s.saved,
          };
        }),

      purgeSpace: (spaceId) =>
        set((s) => {
          const next: Partial<OsStore> = {};
          if (spaceId in s.saved) {
            const saved = { ...s.saved };
            delete saved[spaceId];
            next.saved = saved;
          }
          if (spaceId === s.spaceId) {
            // The deleted agent's space is on screen: clear the layout so a
            // later switchSpace snapshots nothing for it.
            next.windows = {};
            next.order = [];
            next.activeId = null;
          }
          return next;
        }),
    }),
    {
      name: "qwenpaw-os-windows",
      version: 3,
      // Debounced storage: keep synchronous localStorage writes off the
      // drag/resize hot path (see createDebouncedStorage above).
      storage: createJSONStorage(() => debouncedLocalStorage),
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
      // Normalize layouts stored by older versions: clamp the full rect
      // (position + size + restore rect) to the current viewport, not just
      // the per-app minimums.
      migrate: (persisted) => {
        const st = (persisted ?? {}) as Partial<OsStore>;
        const vw = window.innerWidth;
        const vh = window.innerHeight;
        const saved: Record<string, SavedSpace> = {};
        for (const [sid, space] of Object.entries(st.saved ?? {})) {
          saved[sid] = {
            ...space,
            windows: clampWindows(space.windows, vw, vh),
          };
        }
        return {
          ...st,
          windows: clampWindows(st.windows, vw, vh),
          saved,
        } as OsStore;
      },
      // migrate only runs on version bumps; same-version layouts can still
      // go stale (display/DPI changed since last visit), so re-clamp after
      // every hydration too.
      onRehydrateStorage: () => (state) => {
        state?.clampToViewport();
      },
    },
  ),
);
