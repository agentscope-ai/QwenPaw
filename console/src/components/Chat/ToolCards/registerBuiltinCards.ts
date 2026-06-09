/**
 * registerBuiltinCards — registers all built-in tool cards into the
 * PluginSystem so they are available to both ChatV2 (via CardRegistry)
 * and ChatV1 (via customToolRenderConfig / usePlugins).
 *
 * Call once at application startup (e.g. in main.tsx or App.tsx).
 */

import { pluginSystem } from "../../../plugins/hostExternals";
import { BUILTIN_CARD_REGISTRY } from "./cards";
import { adaptRegistryForV1 } from "./adapters/v1Adapter";

const PLUGIN_ID = "builtin-tool-cards";

let registered = false;

/**
 * Register all built-in tool cards as a "plugin" so that:
 *
 * 1. ChatV1 picks them up via `usePlugins().toolRenderConfig`
 *    (through `customToolRenderConfig` in @agentscope-ai/chat)
 *
 * 2. ChatV2 can also discover them through the same PluginSystem
 *    (though ChatV2 primarily uses direct registry lookup)
 */
export function registerBuiltinCards(): void {
  if (registered) return;
  registered = true;

  const v1AdaptedCards = adaptRegistryForV1(BUILTIN_CARD_REGISTRY);
  console.info(
    `[builtin-tool-cards] Registering ${
      Object.keys(v1AdaptedCards).length
    } tool cards:`,
    Object.keys(v1AdaptedCards).join(", "),
  );
  pluginSystem.addToolRenderers(PLUGIN_ID, v1AdaptedCards, { isBuiltin: true });
}
