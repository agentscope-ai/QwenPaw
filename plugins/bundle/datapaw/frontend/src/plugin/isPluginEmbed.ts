/**
 * True when this bundle is built/shipped as a QwenPaw host plugin (see
 * `vite.config.ts` define `__DATAPAW_PLUGIN_EMBED__`).
 */
export function isPluginEmbed(): boolean {
  return (
    typeof __DATAPAW_PLUGIN_EMBED__ !== "undefined" && __DATAPAW_PLUGIN_EMBED__
  );
}
