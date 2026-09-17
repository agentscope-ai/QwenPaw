/**
 * osCleanup.ts — Transactional cleanup of persisted desktop state.
 *
 * Persisted OS state (windows, saved Spaces, icon positions, pending
 * deep-links) is only deleted in response to CONFIRMED removal events:
 *
 *   - a plugin uninstall the backend acknowledged
 *   - a local catalog app uninstall (the toggle itself is the event)
 *   - an agent deletion the backend acknowledged
 *
 * Entries missing from a transient registry or agent-list snapshot are
 * NEVER treated as removals — partial plugin load failures, cached agent
 * lists and failed refreshes leave every persisted layout untouched.
 */
import { useOsWindows } from "./osWindowStore";
import { useOsIcons } from "./osIconStore";
import { useOsRoute } from "./osRouteStore";
import { useOsDock } from "./osDockStore";
import { appsBySource } from "./osAppRegistry";

/** Purge desktop state for the given app route ids (confirmed removals). */
export function purgeAppState(routeIds: Iterable<string>): void {
  const ids: ReadonlySet<string> = new Set(routeIds);
  if (ids.size === 0) return;
  useOsWindows.getState().purgeApps(ids);
  useOsIcons.getState().purge(ids);
  useOsRoute.getState().purge(ids);
  useOsDock.getState().purge(ids);
}

/**
 * Purge desktop state for a plugin bundle after a confirmed uninstall.
 * Must run before the registry drops the plugin's routes (i.e. before a
 * reload), while the source -> app mapping is still resolvable.
 */
export function purgePluginAppState(source: string): void {
  purgeAppState(appsBySource(source).map((a) => a.routeId));
}

/** Purge one deleted agent's Space layout after a confirmed deletion. */
export function purgeAgentSpace(agentId: string): void {
  useOsWindows.getState().purgeSpace(agentId);
}
