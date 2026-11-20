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

/** Compare dotted numeric versions; `1.10.0` outranks `1.9.0`, suffixes drop. */
export function meetsMinVersion(version: string, minimum: string): boolean {
  // The backend parses the same string with PEP 440, which accepts a leading
  // `v`/`V` and surrounding whitespace. Stripping them here keeps a plugin
  // that declares `v1.2.0` from being rejected as "0.x" on this side.
  const parse = (value: string): number[] =>
    value
      .trim()
      .replace(/^[vV]/, "")
      .split("-")[0]
      .split(".")
      .map((part) => Number.parseInt(part, 10) || 0);
  const left = parse(version);
  const right = parse(minimum);
  const length = Math.max(left.length, right.length);
  for (let index = 0; index < length; index += 1) {
    const a = left[index] ?? 0;
    const b = right[index] ?? 0;
    if (a !== b) return a > b;
  }
  return true;
}
