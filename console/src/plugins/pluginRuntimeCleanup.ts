import { pluginSystem } from "./hostExternals";
import { chatExtensions } from "./registry/chatExtensions";
import { menuRegistry, routeRegistry, slotRegistry } from "./registry/store";

/** Remove every host-managed registration owned by one frontend plugin. */
export function removePluginRuntime(pluginId: string): void {
  menuRegistry.removeBySource(pluginId);
  routeRegistry.removeBySource(pluginId);
  slotRegistry.removeBySource(pluginId);
  pluginSystem.removePlugin(pluginId);
  chatExtensions.disposeAll(pluginId);
}
