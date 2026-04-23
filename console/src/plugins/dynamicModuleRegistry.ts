/**
 * dynamicModuleRegistry.ts
 *
 * Runtime dynamic module discovery using Vite's import.meta.glob
 * Replaces the need for auto-generated registerHostModules.ts
 *
 * Benefits:
 * - No generated files to commit
 * - No merge conflicts on module registry
 * - Automatically discovers new modules
 * - Clean git history
 */

import { moduleRegistry } from "./moduleRegistry";

/**
 * Dynamically discover and register all modules in src/pages
 * Uses Vite's import.meta.glob for efficient lazy loading
 *
 * Note: This uses separate glob calls to properly exclude test files at build time
 */
export async function registerHostModulesDynamic(): Promise<void> {
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

  console.log(
    `[patchable] Discovered ${
      Object.keys(modules).length
    } module(s) for registration`,
  );

  // Register modules
  let registeredCount = 0;
  for (const [path, importFn] of Object.entries(modules)) {
    try {
      // Convert absolute path to module key
      // "../pages/Agent/Config/index.tsx" -> "Agent/Config/index"
      const moduleKey = path
        .replace(/^\.\.\/pages\//, "")
        .replace(/\.(ts|tsx)$/, "");

      // Lazy load the module
      const module = await importFn();

      // Check if module has exports
      if (module && Object.keys(module).length > 0) {
        moduleRegistry.register(moduleKey, module);
        registeredCount++;
      }
    } catch (error) {
      console.warn(`[patchable] Failed to register module: ${path}`, error);
    }
  }

  console.log(`[patchable] Registered ${registeredCount} module(s)`);
}

/**
 * Alternative: Eager loading (loads all modules immediately)
 * Use this if you need all modules available at startup
 *
 * Excludes test files using negative glob patterns at build time
 */
export function registerHostModulesEager(): void {
  // Eager loading - all modules loaded at build time
  // Use negative patterns to exclude test files at glob level
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
      eager: true,
      import: "*",
    },
  );

  let registeredCount = 0;
  for (const [path, module] of Object.entries(modules)) {
    try {
      const moduleKey = path
        .replace(/^\.\.\/pages\//, "")
        .replace(/\.(ts|tsx)$/, "");

      if (module && Object.keys(module).length > 0) {
        moduleRegistry.register(moduleKey, module);
        registeredCount++;
      }
    } catch (error) {
      console.warn(`[patchable] Failed to register module: ${path}`, error);
    }
  }

  console.log(`[patchable] Registered ${registeredCount} module(s)`);
}
