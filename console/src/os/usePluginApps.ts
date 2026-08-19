/**
 * usePluginApps.ts — Live desktop apps derived from installed plugins.
 *
 * Bridges the route + menu registries into OsAppDef entries so PawApps (plugin
 * pages under "/apps/") appear on the desktop, Dock and launcher automatically
 * as they are installed/uninstalled — no hard-coded catalog entry needed.
 */
import { useMemo } from "react";
import { useRoutes, useAllMenuItems } from "../plugins/registry/hooks";
import { buildPluginApps, type OsAppDef } from "./osApps";

export function usePluginApps(): OsAppDef[] {
  const routes = useRoutes();
  const menuItems = useAllMenuItems();
  return useMemo(() => buildPluginApps(routes, menuItems), [routes, menuItems]);
}
