/**
 * useOsLifecycle.ts — Registry-driven cleanup for persisted desktop state.
 *
 * Plugins get uninstalled, routes disappear and agents get deleted, but the
 * OS persists windows, saved Spaces, icon positions and pending deep-links.
 * This hook reconciles that state whenever the app registry changes:
 *
 *   - ghost windows (active + saved Spaces) are closed
 *   - icon positions for missing apps are dropped
 *   - pending route targets for missing apps are dropped
 *   - saved Space layouts for deleted agents are dropped — but ONLY from a
 *     successfully loaded agent list, so a backend outage never wipes
 *     layouts for apps/agents that merely failed to load.
 */
import { useEffect } from "react";
import { useAgentStore } from "../stores/agentStore";
import { useOsWindows } from "./osWindowStore";
import { useOsIcons } from "./osIconStore";
import { useOsRoute } from "./osRouteStore";
import type { OsAppDef } from "./osApps";

/** System apps alone means the registry hasn't finished loading. */
const SYSTEM_APP_COUNT = 2;

export function useOsLifecycle(appById: Map<string, OsAppDef>): void {
  // App-scoped state: run once on mount and again on registry changes.
  useEffect(() => {
    // Defensive: an implausibly small registry (only App Store + Settings)
    // suggests routes aren't registered yet — don't wipe user state.
    if (appById.size <= SYSTEM_APP_COUNT) return;
    const validIds = new Set(appById.keys());
    useOsWindows.getState().reconcile(validIds);
    useOsIcons.getState().prune(validIds);
    useOsRoute.getState().prune(validIds);
  }, [appById]);

  // Space-scoped state: agents are spaces. Prune only from a loaded list
  // (an empty list means "not loaded" or backend offline — keep layouts).
  const agents = useAgentStore((s) => s.agents);
  useEffect(() => {
    if (agents.length === 0) return;
    const valid = new Set(agents.map((a) => a.id));
    // The space being displayed is always kept, whatever the list says.
    valid.add(useOsWindows.getState().spaceId);
    useOsWindows.getState().pruneSpaces(valid);
  }, [agents]);
}
