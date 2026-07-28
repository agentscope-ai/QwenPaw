/**
 * dynamicModuleRegistry.ts
 *
 * Runtime module-factory discovery using Vite's import.meta.glob.
 *
 * Benefits:
 * - No generated files to commit
 * - No merge conflicts on module registry
 * - Automatically discovers new modules
 * - Clean git history
 */

import { moduleRegistry } from "./moduleRegistry";

export function pagePathToModuleKey(path: string): string {
  return path.replace(/^\.\.\/pages\//, "").replace(/\.(ts|tsx)$/, "");
}

/**
 * Register import factories for every page module without executing them.
 * Routes and plugins call moduleRegistry.load() only for modules they need.
 */
export function registerHostModuleFactories(): number {
  // Use positive and negative patterns to exclude test files at build time
  const modules = import.meta.glob<Record<string, unknown>>(
    [
      "../pages/**/*.ts",
      "../pages/**/*.tsx",
      "!../pages/**/*.test.ts",
      "!../pages/**/*.test.tsx",
      "!../pages/**/*.spec.ts",
      "!../pages/**/*.spec.tsx",
      "!../pages/**/*.d.ts",
      "!../pages/**/__tests__/**",
    ],
    {
      eager: false,
      import: "*",
    },
  );

  for (const [path, importFn] of Object.entries(modules)) {
    moduleRegistry.registerFactory(pagePathToModuleKey(path), importFn);
  }
  const factoryCount = Object.keys(modules).length;
  console.log(`[patchable] Registered ${factoryCount} module factories`);
  return factoryCount;
}
