import { pluginSystem } from "./hostExternals";
import { chatExtensions } from "./registry/chatExtensions";
import {
  menuRegistry,
  routeRegistry,
  slotRegistry,
  type SourceRegistrationSnapshot,
} from "./registry/store";

/** Detach every host-managed registration owned by one frontend plugin. */
export function detachPluginRuntime(
  pluginId: string,
): SourceRegistrationSnapshot {
  const snapshots = [
    menuRegistry.detachBySource(pluginId),
    routeRegistry.detachBySource(pluginId),
    slotRegistry.detachBySource(pluginId),
    pluginSystem.detachPlugin(pluginId),
    chatExtensions.detachAll(pluginId),
  ];
  return {
    restore: () => {
      for (const snapshot of snapshots) snapshot.restore();
    },
  };
}

/** Permanently remove every host-managed registration owned by a plugin. */
export function removePluginRuntime(pluginId: string): void {
  detachPluginRuntime(pluginId);
}
