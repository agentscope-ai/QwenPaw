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
import { useEffect, useMemo } from "react";
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
  mergePawAppDefinitions,
  type OsAppDef,
} from "./osApps";
import { usePawAppManifestStore } from "./pawAppManifestStore";

export interface OsAppsResult {
  /** Every visible app, in desktop display order. */
  apps: OsAppDef[];
  /** Route id -> app def for O(1) lookup. */
  appById: Map<string, OsAppDef>;
  manifestError: string | null;
}

// Dynamic apps memoized on the registries' stable snapshot refs (both
// registries replace their snapshot arrays on every mutation).
let routesKey: unknown = null;
let menuKey: unknown = null;
let dynamicCache = new Map<string, OsAppDef>();
let manifestsKey: unknown = null;

/** Current dynamic (plugin-derived) app defs, straight from the registry. */
function dynamicApps(): Map<string, OsAppDef> {
  const routes = routeRegistry.snapshot();
  const menu = menuRegistry.snapshot();
  const manifests = usePawAppManifestStore.getState().apps;
  if (routes !== routesKey || menu !== menuKey || manifests !== manifestsKey) {
    routesKey = routes;
    menuKey = menu;
    manifestsKey = manifests;
    const pawApps = mergePawAppDefinitions(
      manifests,
      buildPluginApps(routes, menu),
    );
    dynamicCache = new Map(pawApps.map((app) => [app.routeId, app]));
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
  const pawApps = usePawAppManifestStore((state) => state.apps);
  const manifestsLoaded = usePawAppManifestStore((state) => state.loaded);
  const manifestsLoading = usePawAppManifestStore((state) => state.loading);
  const manifestsError = usePawAppManifestStore((state) => state.error);
  const refreshManifests = usePawAppManifestStore((state) => state.refresh);

  useEffect(() => {
    if (!manifestsLoaded && !manifestsLoading && !manifestsError) {
      void refreshManifests().catch(() => {});
    }
  }, [manifestsError, manifestsLoaded, manifestsLoading, refreshManifests]);

  return useMemo(() => {
    const availableIds = new Set(routes.map((r) => r.id));
    const installedSet = new Set(installed);
    const catalog = OS_APPS.filter(
      (a) => availableIds.has(a.routeId) && installedSet.has(a.routeId),
    );
    const dynamicApps = mergePawAppDefinitions(pawApps, pluginApps);
    const apps = [STORE_APP, ...catalog, ...dynamicApps, SETTINGS_APP];
    return {
      apps,
      appById: new Map(apps.map((a) => [a.routeId, a])),
      manifestError: manifestsError,
    };
  }, [routes, installed, pawApps, pluginApps, manifestsError]);
}
