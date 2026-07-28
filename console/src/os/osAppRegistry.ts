/**
 * osAppRegistry.ts — Single source of truth for desktop app metadata.
 *
 * Merges every app source into one list consumed by the desktop surfaces
 * (Dock, Launcher, desktop icons, window titles):
 *
 *   Route/Menu Registry ──▶ useOsApps() ──▶ Dock / Launcher / DesktopOS
 *                                │
 *                                └─▶ syncDynamicApps ─▶ resolveAppDef
 *                                    (module-level, for non-React code
 *                                     such as osWindowStore.open)
 *
 * Static apps (catalog + system) resolve via findAppDef; dynamic PawApps
 * (plugin routes under "/apps/") are synced into a module-level map so
 * `resolveAppDef` covers them too — every entry point can open an app by
 * route id alone and get manifest-consistent geometry.
 */
import { useEffect, useMemo } from "react";
import { useRoutes } from "../plugins/registry/hooks";
import { useOsPlugins } from "./osPluginStore";
import { usePluginApps } from "./usePluginApps";
import {
  OS_APPS,
  STORE_APP,
  SETTINGS_APP,
  findAppDef,
  type OsAppDef,
} from "./osApps";

export interface OsAppsResult {
  /** Every visible app, in desktop display order. */
  apps: OsAppDef[];
  /** Route id -> app def for O(1) lookup. */
  appById: Map<string, OsAppDef>;
}

/** Dynamic (plugin-derived) app defs, kept in sync by useOsApps(). */
let dynamicApps = new Map<string, OsAppDef>();

/** Replace the dynamic app set (exported for tests). */
export function syncDynamicApps(defs: OsAppDef[]): void {
  dynamicApps = new Map(defs.map((d) => [d.routeId, d]));
}

/**
 * Resolve any app's manifest (catalog, system or dynamic PawApp).
 * Safe to call from non-React code (stores).
 */
export function resolveAppDef(routeId: string): OsAppDef | undefined {
  return findAppDef(routeId) ?? dynamicApps.get(routeId);
}

/**
 * The one registry hook: App Store (system, always present) + installed
 * catalog apps whose route resolves + live plugin apps + System Settings.
 */
export function useOsApps(): OsAppsResult {
  const routes = useRoutes();
  const installed = useOsPlugins((s) => s.installed);
  const pluginApps = usePluginApps();

  // Keep the module-level dynamic registry in sync so stores can resolve
  // plugin app defs. Runs before any user-triggered open() call.
  useEffect(() => {
    syncDynamicApps(pluginApps);
  }, [pluginApps]);

  return useMemo(() => {
    const availableIds = new Set(routes.map((r) => r.id));
    const installedSet = new Set(installed);
    const catalog = OS_APPS.filter(
      (a) => availableIds.has(a.routeId) && installedSet.has(a.routeId),
    );
    const apps = [STORE_APP, ...catalog, ...pluginApps, SETTINGS_APP];
    return { apps, appById: new Map(apps.map((a) => [a.routeId, a])) };
  }, [routes, installed, pluginApps]);
}
