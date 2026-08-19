/**
 * osAppRegistry.ts — Single source of truth for desktop app metadata.
 *
 * Merges every app source into one list consumed by the desktop surfaces
 * (Dock, Launcher, desktop icons, window titles):
 *
 *   Route/Menu Registry ──▶ useOsApps()   ──▶ Dock / Launcher / DesktopOS
 *          (snapshots) ──▶ resolveAppDef ──▶ osWindowStore.open / clamp
 *
 * Static apps (catalog + system) resolve via findAppDef. Dynamic PawApps
 * (plugin routes under "/apps/") are derived directly from the plugin
 * registry's memoized snapshots — the registry is an external store, so
 * React hooks and non-React callers (stores) always read the same
 * snapshot in the same tick, with no effect-driven synchronisation and no
 * dependency on any component being mounted.
 */
import { useMemo } from "react";
import { useRoutes } from "../plugins/registry/hooks";
import { routeRegistry, menuRegistry } from "../plugins/registry/store";
import { useOsPlugins } from "./osPluginStore";
import { usePluginApps } from "./usePluginApps";
import {
  OS_APPS,
  STORE_APP,
  SETTINGS_APP,
  findAppDef,
  buildPluginApps,
  type OsAppDef,
} from "./osApps";

export interface OsAppsResult {
  /** Every visible app, in desktop display order. */
  apps: OsAppDef[];
  /** Route id -> app def for O(1) lookup. */
  appById: Map<string, OsAppDef>;
}

// Dynamic apps memoized on the registries' stable snapshot refs (both
// registries replace their snapshot arrays on every mutation).
let routesKey: unknown = null;
let menuKey: unknown = null;
let dynamicCache = new Map<string, OsAppDef>();

/** Current dynamic (plugin-derived) app defs, straight from the registry. */
function dynamicApps(): Map<string, OsAppDef> {
  const routes = routeRegistry.snapshot();
  const menu = menuRegistry.snapshot();
  if (routes !== routesKey || menu !== menuKey) {
    routesKey = routes;
    menuKey = menu;
    dynamicCache = new Map(
      buildPluginApps(routes, menu).map((d) => [d.routeId, d]),
    );
  }
  return dynamicCache;
}

/**
 * Resolve any app's manifest (catalog, system or dynamic PawApp).
 * Safe to call from non-React code (stores) at any time.
 */
export function resolveAppDef(routeId: string): OsAppDef | undefined {
  return findAppDef(routeId) ?? dynamicApps().get(routeId);
}

/**
 * Every dynamic app contributed by a plugin source. Used by transactional
 * cleanup to map a confirmed plugin uninstall to its desktop app state.
 */
export function appsBySource(source: string): OsAppDef[] {
  return [...dynamicApps().values()].filter((a) => a.source === source);
}

/**
 * The one registry hook: App Store (system, always present) + installed
 * catalog apps whose route resolves + live plugin apps + System Settings.
 */
export function useOsApps(): OsAppsResult {
  const routes = useRoutes();
  const installed = useOsPlugins((s) => s.installed);
  const pluginApps = usePluginApps();

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
