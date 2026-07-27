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

/** How many module imports may run concurrently during warm-up. */
const WARMUP_BATCH_SIZE = 4;

/** Wait for an idle slot so warm-up yields to first-paint work. */
function idleSlot(): Promise<void> {
  return new Promise((resolve) => {
    if (typeof requestIdleCallback === "function") {
      requestIdleCallback(() => resolve(), { timeout: 2000 });
    } else {
      setTimeout(resolve, 50);
    }
  });
}

/**
 * Run warm-up tasks in small sequential batches, waiting for an idle
 * slot before each batch. Keeps background module imports from competing
 * with the initial render for network and main-thread time (previously
 * all ~260 imports were fired at once via a single Promise.allSettled).
 */
export async function runWarmupQueue<T>(
  tasks: Array<() => Promise<T>>,
  batchSize: number = WARMUP_BATCH_SIZE,
  waitSlot: () => Promise<void> = idleSlot,
): Promise<PromiseSettledResult<T>[]> {
  const results: PromiseSettledResult<T>[] = [];
  for (let i = 0; i < tasks.length; i += batchSize) {
    await waitSlot();
    const batch = tasks.slice(i, i + batchSize);
    results.push(...(await Promise.allSettled(batch.map((task) => task()))));
  }
  return results;
}

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

  const tasks = Object.entries(modules).map(([path, importFn]) => async () => {
    const moduleKey = path
      .replace(/^\.\.\/pages\//, "")
      .replace(/\.(ts|tsx)$/, "");
    const module = await importFn();
    if (module && Object.keys(module).length > 0) {
      moduleRegistry.register(moduleKey, module);
      return true;
    }
    return false;
  });

  const results = await runWarmupQueue(tasks);

  const registeredCount = results.filter(
    (r) => r.status === "fulfilled" && r.value,
  ).length;
  for (const r of results) {
    if (r.status === "rejected") {
      console.warn("[patchable] Failed to register module:", r.reason);
    }
  }

  console.log(`[patchable] Registered ${registeredCount} module(s)`);
}
