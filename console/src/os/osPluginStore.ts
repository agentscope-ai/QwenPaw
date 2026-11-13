/**
 * osPluginStore.ts — Simulated plugin/app management state for the OS PoC.
 *
 * Tracks which apps are "installed" on the desktop. This mimics a plugin
 * manager: the App Store window installs/uninstalls entries here, and the
 * desktop / launcher render only installed apps. Persisted to localStorage so
 * the layout survives reloads.
 *
 * The App Store itself is a system app and is never in this list — it is
 * always available (see osApps STORE_APP).
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { OS_APPS } from "./osApps";

interface PluginStore {
  /** Route ids currently installed on the desktop. */
  installed: string[];
  install: (id: string) => void;
  uninstall: (id: string) => void;
  /** Restore every catalog app (factory reset). */
  installAll: () => void;
}

/** By default every catalog app is pre-installed. */
const DEFAULT_INSTALLED = OS_APPS.map((a) => a.routeId);

export const useOsPlugins = create<PluginStore>()(
  persist(
    (set) => ({
      installed: DEFAULT_INSTALLED,
      install: (id) =>
        set((s) =>
          s.installed.includes(id) ? s : { installed: [...s.installed, id] },
        ),
      uninstall: (id) =>
        set((s) => ({ installed: s.installed.filter((x) => x !== id) })),
      installAll: () => set({ installed: OS_APPS.map((a) => a.routeId) }),
    }),
    {
      name: "qwenpaw-os-installed",
      version: 1,
      migrate: (persisted) => {
        const prev = (persisted ?? {}) as Partial<PluginStore>;
        const existing = prev.installed ?? [];
        const merged = Array.from(new Set([...existing, ...DEFAULT_INSTALLED]));
        return { ...prev, installed: merged } as PluginStore;
      },
    },
  ),
);
