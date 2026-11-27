/**
 * pluginSdk.ts — what SDK each plugin said it was built against.
 *
 * The console cannot infer a plugin's `sdk.version` from its bundle, so the
 * backend forwards the manifest declaration alongside the frontend plugin
 * list. Theme-role checks use it to tell "this plugin may use the semantic
 * colour surface" apart from "it only ever asked for the original six roles".
 *
 * Unknown plugins stay unknown on purpose: a missing declaration is treated as
 * "did not ask for the newer surface", never as "probably new enough".
 */

export interface PluginSdkDeclaration {
  version: string;
  capabilities: readonly string[];
}

const declarations = new Map<string, PluginSdkDeclaration>();

export function setPluginSdkDeclaration(
  pluginId: string,
  declaration: PluginSdkDeclaration,
): void {
  declarations.set(pluginId, {
    version: declaration.version,
    capabilities: [...declaration.capabilities],
  });
}

export function replacePluginSdkDeclarations(
  rows: readonly {
    id: string;
    sdkVersion?: string;
    sdkCapabilities?: readonly string[];
  }[],
): void {
  declarations.clear();
  for (const row of rows) {
    if (!row.sdkVersion) continue;
    declarations.set(row.id, {
      version: row.sdkVersion,
      capabilities: [...(row.sdkCapabilities ?? [])],
    });
  }
}

export function getPluginSdkDeclaration(
  pluginId: string,
): PluginSdkDeclaration | undefined {
  return declarations.get(pluginId);
}

export function clearPluginSdkDeclarations(): void {
  declarations.clear();
}
