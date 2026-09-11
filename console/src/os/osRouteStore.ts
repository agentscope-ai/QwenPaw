/**
 * osRouteStore.ts — Cross-window navigation channel for the Desktop OS.
 *
 * Each OS window runs an isolated MemoryRouter, so intra-app navigation stays
 * inside the window. To navigate ACROSS apps (e.g. a session row opening the
 * Chat window, or Chat opening the Models settings pane) we cannot use the
 * window's own router. This store is the bridge: `openApp` opens/focuses the
 * target window via osWindowStore and posts the desired sub-path (with a
 * bumped nonce). The target window's bridge subscribes to its own entry and
 * navigates its local router whenever the nonce changes.
 */
import { create } from "zustand";
import { useOsWindows } from "./osWindowStore";
import { SETTINGS_APP_ID, SETTINGS_ROUTE_IDS } from "./osRouteMap";

/** A pending deep-link for a given window (route id). */
export interface RouteTarget {
  /** Full sub-path to navigate to inside the window's router. */
  path: string;
  /** Monotonic counter so repeated same-path targets still fire. */
  nonce: number;
}

interface OsRouteStore {
  /** routeId -> pending deep-link target. */
  targets: Record<string, RouteTarget>;
  /** Open/focus an app window and deep-link its router to `path`. */
  openApp: (routeId: string, path?: string) => void;
  /**
   * Route a cross-app navigation intent. Settings routes open the System
   * Settings window (selecting the pane); everything else opens the app whose
   * route id is given. Returns true when handled.
   */
  navigateTo: (routeId: string, path: string) => void;
  /** Transactional cleanup: drop deep-links for confirmed-removed apps. */
  purge: (ids: ReadonlySet<string>) => void;
}

export const useOsRoute = create<OsRouteStore>((set) => ({
  targets: {},

  openApp: (routeId, path) => {
    if (path !== undefined) {
      set((s) => ({
        targets: {
          ...s.targets,
          [routeId]: {
            path,
            nonce: (s.targets[routeId]?.nonce ?? 0) + 1,
          },
        },
      }));
    }
    useOsWindows.getState().open(routeId);
  },

  navigateTo: (routeId, path) => {
    if (SETTINGS_ROUTE_IDS.has(routeId)) {
      // Settings routes live inside the aggregate System Settings window; the
      // "path" for that window is the target pane's route id.
      set((s) => ({
        targets: {
          ...s.targets,
          [SETTINGS_APP_ID]: {
            path: routeId,
            nonce: (s.targets[SETTINGS_APP_ID]?.nonce ?? 0) + 1,
          },
        },
      }));
      useOsWindows.getState().open(SETTINGS_APP_ID);
      return;
    }
    set((s) => ({
      targets: {
        ...s.targets,
        [routeId]: {
          path,
          nonce: (s.targets[routeId]?.nonce ?? 0) + 1,
        },
      },
    }));
    useOsWindows.getState().open(routeId);
  },

  purge: (ids) =>
    set((s) => {
      if (![...ids].some((id) => id in s.targets)) return s;
      const targets = { ...s.targets };
      for (const id of ids) delete targets[id];
      return { targets };
    }),
}));
